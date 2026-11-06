"""The opt-in HTTPS dashboard uses a separate socket and leaves stdio alone."""

from pathlib import Path

import pytest

from flow_of_work_mcp import cli, server
from flow_of_work_mcp.dashboard_https_listener import DashboardHTTPSListenerError, dashboard_https_options


def _options(*args):
    return dashboard_https_options(server.build_cli_parser().parse_args(args))


def test_https_dashboard_is_opt_in_with_explicit_bind_and_tls_name():
    assert _options() is None
    assert _options("--transport", "streamable-http") is None
    assert _options("--transport", "streamable-http", "--dashboard-bind", "127.0.0.2",
                    "--dashboard-name", "flower.example") == {
        "bind": "127.0.0.2", "name": "flower.example", "port": 8443, "cert": None, "key": None,
    }


@pytest.mark.parametrize(("extra", "message"), [
    (["--transport", "stdio"], "requires the streamable-http"),
    (["--host", "0.0.0.0"], "loopback IP"),
    (["--host", "localhost"], "explicit IPv4 or IPv6"),
    (["--dashboard-bind", "flower.example"], "explicit IPv4 or IPv6"),
    (["--dashboard-bind", "0.0.0.0"], "concrete unicast IP"),
    (["--dashboard-port", "0"], "range 1..65535"),
    (["--dashboard-port", "8010"], "distinct sockets"),
    (["--dashboard-cert", "/fixture/server.pem"], "together"),
    (["--dashboard-name", ""], "both --dashboard-bind and --dashboard-name"),
])
def test_invalid_https_dashboard_options_are_rejected(extra, message):
    with pytest.raises(DashboardHTTPSListenerError, match=message):
        _options("--transport", "streamable-http", "--dashboard-bind", "127.0.0.1",
                 "--dashboard-name", "flower.example", *extra)


def test_distinct_same_port_ipv6_dashboard_uses_v6_only():
    assert _options("--transport", "streamable-http", "--dashboard-bind", "::1",
                    "--dashboard-name", "flower.example", "--dashboard-port", "8010")["bind"] == "::1"
    with pytest.raises(DashboardHTTPSListenerError, match="distinct sockets"):
        _options("--transport", "streamable-http", "--host", "::1", "--dashboard-bind", "::1",
                 "--dashboard-name", "flower.example", "--dashboard-port", "8010")


def test_installed_cli_forwards_tls_and_profile_options(monkeypatch):
    invocation = []
    monkeypatch.setattr(server, "main", invocation.append)
    cli.main(["serve", "--profile", "fixture", "--transport", "streamable-http",
              "--dashboard-bind", "::1", "--dashboard-name", "flower.example", "--dashboard-port", "9443",
              "--dashboard-cert", "/fixture/server.pem", "--dashboard-key", "/fixture/key.pem"])
    assert len(invocation) == 1
    arguments = server.build_cli_parser().parse_args(invocation[0])
    assert arguments.profile == "fixture"
    assert dashboard_https_options(arguments) == {
        "bind": "::1", "name": "flower.example", "port": 9443,
        "cert": Path("/fixture/server.pem"), "key": Path("/fixture/key.pem"),
    }
