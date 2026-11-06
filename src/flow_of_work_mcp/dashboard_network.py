"""Owner-private settings for the profile's optional IPv4 HTTPS listener."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_file_ownership


DEFAULT_LAN_PORT = 8443
_INITIAL_REVISION = '0' * 32
_REVISION = re.compile(r'[0-9a-f]{32}')


class DashboardNetworkError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(message)


def _valid(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {'revision', 'enabled', 'port'}
        and isinstance(value['revision'], str)
        and _REVISION.fullmatch(value['revision']) is not None
        and type(value['enabled']) is bool
        and type(value['port']) is int
        and 1 <= value['port'] <= 65535
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate network setting.')
        result[key] = value
    return result


class DashboardNetworkSettings:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path).expanduser().absolute()
        profile = hashlib.sha256(os.fsencode(self.config_path.name)).hexdigest()[:16]
        self.path = self.config_path.parent / f'.flower-dashboard-network-{profile}' / 'settings.json'

    def snapshot(self) -> dict:
        initial = {'revision': _INITIAL_REVISION, 'enabled': False, 'port': DEFAULT_LAN_PORT}
        try:
            try:
                self.path.parent.lstat()
            except FileNotFoundError:
                return initial
            secure._private(self.path.parent, directory=True)
            # A save can create the private directory before publishing the file.
            try:
                self.path.lstat()
            except FileNotFoundError:
                return initial
            value = json.loads(secure.read_owned(self.path, limit=1024), object_pairs_hook=_unique_object)
            if not _valid(value) or value['revision'] == _INITIAL_REVISION:
                raise ValueError('Invalid network settings.')
            return value
        except (ValueError, OSError, RecursionError):
            raise DashboardNetworkError(
                'dashboard_network_state_invalid', 'The profile network settings cannot be validated.', 409,
            ) from None

    def save(self, value: object, *, mcp_host: str = '127.0.0.1', mcp_port: int = 8010) -> dict:
        if not _valid(value):
            raise DashboardNetworkError(
                'dashboard_network_input_invalid', 'Supply the observed revision, LAN access and an HTTPS port from 1 to 65535.',
            )
        if value['enabled']:
            self._validate_listener(value['port'], mcp_host, mcp_port)
        try:
            secure.check_data_file(self.config_path)
            secure.ensure_directory(self.path.parent)
            with acquire_file_ownership(self.path, suffix='.operation.lock') as lock:
                current = self.snapshot()
                if current['revision'] != value['revision']:
                    raise DashboardNetworkError(
                        'dashboard_network_changed', 'Network settings changed. Reload them before saving.', 409,
                    )
                if current == value:
                    return current
                updated = {**value, 'revision': uuid4().hex}
                lock.assert_resource(self.path)
                secure.write_owned(self.path, (json.dumps(updated) + '\n').encode('utf-8'))
                return updated
        except (secure.ServiceSecurityError, RuntimeOwnershipError, OSError):
            raise DashboardNetworkError(
                'dashboard_network_save_unconfirmed', 'The network settings save could not be confirmed. Reload them before retrying.', 409,
            ) from None

    @staticmethod
    def _validate_listener(port: int, mcp_host: str, mcp_port: int) -> None:
        try:
            address = ipaddress.ip_address(mcp_host)
        except ValueError:
            address = None
        if (address is None or not address.is_loopback or '%' in mcp_host
                or getattr(address, 'ipv4_mapped', None) is not None):
            raise DashboardNetworkError(
                'dashboard_network_mcp_host_invalid', 'The MCP listener must use an explicit loopback IP before enabling LAN access.',
            )
        if address.version == 4 and mcp_port == port:
            raise DashboardNetworkError(
                'dashboard_network_port_conflict', 'Choose an HTTPS port different from the loopback MCP port.',
            )
