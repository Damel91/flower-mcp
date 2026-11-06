"""Optional second HTTPS listener with an explicit owner-controlled lifetime."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
from pathlib import Path
import socket
import sys
from threading import Event, Thread
import time

from flow_of_work_mcp.dashboard_network import DEFAULT_LAN_PORT


class DashboardHTTPSListenerError(ValueError):
    """A dashboard HTTPS endpoint could not be started or safely stopped."""


_OPTION_NAMES = ("bind", "name", "port", "cert", "key")
_START_TIMEOUT = 10
_DRAIN_TIMEOUT = 30
_LAN_REFRESH_INTERVAL = 5
_LOG = logging.getLogger(__name__)


def add_dashboard_https_arguments(parser):
    parser.add_argument("--dashboard-bind", help="HTTPS dashboard IP, or 0.0.0.0 for automatic IPv4 LAN access")
    parser.add_argument("--dashboard-name", help="DNS name or IP that browsers use to reach the HTTPS dashboard")
    parser.add_argument("--dashboard-port", type=int, help=f"HTTPS dashboard port (default {DEFAULT_LAN_PORT} when enabled)")
    parser.add_argument("--dashboard-cert", type=Path, help="optional HTTPS dashboard PEM certificate")
    parser.add_argument("--dashboard-key", type=Path, help="optional HTTPS dashboard PEM private key")
    parser.add_argument("--dashboard-local", action="store_true", help="disable HTTPS dashboard access for this start")


def dashboard_https_arguments(args):
    """Forward only supplied options from the installed CLI to the server."""
    if args.dashboard_local:
        yield "--dashboard-local"
    for name in _OPTION_NAMES:
        value = getattr(args, f"dashboard_{name}")
        if value is not None:
            yield f"--dashboard-{name}"
            yield str(value)


def _ip_address(value):
    try:
        if "%" in value:
            raise ValueError
        address = ipaddress.ip_address(value)
        if address.version == 6 and address.ipv4_mapped is not None:
            raise ValueError
        return address
    except ValueError:
        raise DashboardHTTPSListenerError("Use an explicit IPv4 or IPv6 address without a scope or mapped address.") from None


def dashboard_https_options(args, *, saved_port=None):
    """Reject invalid opt-in arguments before selecting or creating a profile."""
    options = {name: getattr(args, f"dashboard_{name}") for name in _OPTION_NAMES}
    if args.dashboard_local:
        if any(value is not None for value in options.values()):
            raise DashboardHTTPSListenerError("--dashboard-local cannot be combined with HTTPS dashboard options.")
        return None
    if all(value is None for value in options.values()):
        if saved_port is None:
            return None
        options.update(bind="0.0.0.0", port=saved_port)
    if args.transport != "streamable-http":
        raise DashboardHTTPSListenerError("The HTTPS dashboard requires the streamable-http transport.")
    if not options["bind"]:
        raise DashboardHTTPSListenerError("Set both --dashboard-bind and --dashboard-name to enable the HTTPS dashboard.")
    if (options["cert"] is None) != (options["key"] is None):
        raise DashboardHTTPSListenerError("Supply --dashboard-cert and --dashboard-key together.")
    local_address = _ip_address(args.host)
    if not local_address.is_loopback:
        raise DashboardHTTPSListenerError("Use a loopback IP for --host when enabling the HTTPS dashboard.")
    dashboard_address = _ip_address(options["bind"])
    lan = dashboard_address == ipaddress.IPv4Address("0.0.0.0")
    if not lan and (dashboard_address.is_unspecified or dashboard_address.is_multicast):
        raise DashboardHTTPSListenerError("Choose a concrete unicast IP or IPv4 0.0.0.0 for --dashboard-bind.")
    if lan and any(options[key] is not None for key in ("name", "cert", "key")):
        raise DashboardHTTPSListenerError("IPv4 0.0.0.0 discovers its addresses and certificate automatically. Omit --dashboard-name, --dashboard-cert and --dashboard-key.")
    if not lan and not options["name"]:
        raise DashboardHTTPSListenerError("Set both --dashboard-bind and --dashboard-name to enable the HTTPS dashboard.")
    options["bind"] = str(dashboard_address)
    port = options["port"] if options["port"] is not None else DEFAULT_LAN_PORT
    if not 1 <= port <= 65535:
        raise DashboardHTTPSListenerError("--dashboard-port must be in the range 1..65535.")
    if port == args.port and (dashboard_address == local_address or lan and local_address.version == 4):
        raise DashboardHTTPSListenerError("Choose distinct sockets for local MCP and the HTTPS dashboard.")
    options["port"] = port
    return options


def dashboard_https_urls(tls):
    if getattr(tls, "bind", None) == "0.0.0.0":
        port = "" if tls.port == 443 else f":{tls.port}"
        addresses = (name for name in tls.names if not ipaddress.IPv4Address(name).is_loopback)
        return tuple(f"https://{name}{port}/" for name in (*tls.hostnames, *addresses))
    return (f"https://{tls.authority}/dashboard",)


class DashboardHTTPSListener:
    def __init__(self, app, tls):
        self._app = app
        self._tls = tls
        self._server = None
        self._socket = None
        self._thread = None
        self._finished = Event()

    def _bind(self):
        address = _ip_address(self._tls.bind)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind((str(address), self._tls.port))
            sock.listen()
        except OSError:
            sock.close()
            raise
        return sock

    def _run(self):
        try:
            asyncio.run(self._serve())
        except (Exception, SystemExit):
            _LOG.error("HTTPS dashboard listener stopped with an error.")
        finally:
            self._socket.close()
            self._finished.set()

    async def _serve(self):
        refresh = None
        if self._tls.bind == "0.0.0.0":
            refresh = asyncio.create_task(self._refresh_lan())
        try:
            await self._server.serve(sockets=[self._socket])
        finally:
            if refresh is not None:
                refresh.cancel()
                await asyncio.gather(refresh, return_exceptions=True)

    async def _refresh_lan(self):
        failed = False
        while True:
            await asyncio.sleep(_LAN_REFRESH_INTERVAL)
            previous = dashboard_https_urls(self._tls)
            try:
                self._tls.refresh()
            except (OSError, ValueError):
                if not failed:
                    _LOG.warning("Could not refresh the HTTPS dashboard LAN certificate.")
                failed = True
                continue
            failed = False
            urls = dashboard_https_urls(self._tls)
            if previous != urls:
                for url in urls:
                    print(f"Flower HTTPS dashboard: {url}", file=sys.stderr)

    def start(self):
        import uvicorn

        try:
            config = uvicorn.Config(
                self._app,
                host=self._tls.bind,
                port=self._tls.port,
                proxy_headers=False,
                access_log=False,
            )
            config.load()
            # Uvicorn passes this context to asyncio's listener. Build it
            # ourselves so the certificate loader cannot prompt for a key.
            config.ssl = self._tls.context()
        except (OSError, ValueError):
            raise DashboardHTTPSListenerError("The HTTPS dashboard TLS material could not be loaded.") from None
        try:
            self._socket = self._bind()
        except OSError:
            raise DashboardHTTPSListenerError("Could not bind the HTTPS dashboard to the selected IP and port.") from None
        self._server = uvicorn.Server(config)
        self._thread = Thread(target=self._run, name="flower-dashboard-https", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + _START_TIMEOUT
        while not self._server.started:
            if self._finished.wait(0.025) or time.monotonic() >= deadline:
                raise DashboardHTTPSListenerError("The HTTPS dashboard did not become ready.")
        if self._finished.is_set():
            raise DashboardHTTPSListenerError("The HTTPS dashboard stopped before startup completed.")

    def close(self):
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=_DRAIN_TIMEOUT)
            if self._thread.is_alive():
                raise DashboardHTTPSListenerError(
                    "The HTTPS dashboard did not drain. Runtime ownership is retained until process exit."
                )
        if self._socket is not None:
            self._socket.close()
