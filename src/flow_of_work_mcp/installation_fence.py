"""Protect managed package replacement across all supported macOS server starts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.ledger_archive import ArchiveError, assert_private_archive_directory
from flow_of_work_mcp.runtime_ownership import (
    RuntimeOwnership,
    RuntimeOwnershipError,
    acquire_file_ownership,
)

FENCE_CONTRACT = "flower.dedicated-installation.v1"
UPGRADE_CONTRACT = "flower.managed-upgrade.v1"
_CONTROL = ".flower-installation"
_RECEIPT = ".flower-release-install.json"
_PHASES = {"queued", "stopping", "installing", "restarting", "complete", "failed", "preflight_failed"}
_SETTLED = {"complete", "preflight_failed"}


class InstallationFenceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _unsafe() -> InstallationFenceError:
    return InstallationFenceError("installation_fence_unsafe", "The dedicated Flower installation or its control state cannot be proved.")


def _present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _record(path: Path) -> dict:
    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise _unsafe()
        return value

    try:
        value = json.loads(secure.read_owned(path), object_pairs_hook=unique)
    except (OSError, ValueError, RecursionError) as exc:
        raise _unsafe() from exc
    if not isinstance(value, dict):
        raise _unsafe()
    return value


def _environment() -> Path | None:
    if sys.platform != "darwin" or sys.prefix == sys.base_prefix:
        return None
    try:
        environment = Path(sys.prefix).resolve(strict=True)
        if not (_present(environment / _RECEIPT) or _present(environment / _CONTROL)):
            return None
        secure._metadata(environment, directory=True)
        secure.check_data_file(environment / _RECEIPT)
        return environment
    except (OSError, ValueError, RuntimeError) as exc:
        raise _unsafe() from exc


def _private_control(environment: Path, *, create: bool = False) -> Path:
    control = environment / _CONTROL
    try:
        if create:
            try:
                control.mkdir(mode=0o700)
            except FileExistsError:
                pass
        assert_private_archive_directory(control)
    except (OSError, ArchiveError, secure.ServiceSecurityError) as exc:
        raise _unsafe() from exc
    return control


def _owned_path(path: Path) -> Path:
    try:
        path = Path(path).expanduser().absolute()
        secure.check_data_file(path)
        return path
    except (OSError, ValueError, RuntimeError) as exc:
        raise _unsafe() from exc


def _identity(environment: Path) -> list[int]:
    metadata = secure._metadata(environment, directory=True)
    if not metadata.st_ino:
        raise _unsafe()
    return [metadata.st_dev, metadata.st_ino]


def _service_key(config: Path, host: str, port: int) -> str:
    fingerprint = hashlib.sha256(f"{config}\0{host}\0{port}".encode()).hexdigest()[:20]
    return f"ai.flower-mcp.{fingerprint}"


@dataclass(frozen=True)
class DedicatedInstallation:
    environment: Path
    config: Path
    database: Path
    host: str
    port: int
    service_key: str

    @property
    def journal(self) -> Path:
        return self.environment / _CONTROL / "upgrade.json"

    def assert_selection(self, config: Path, database: Path) -> None:
        _assert_bound_path(config, self.config)
        _assert_bound_path(database, self.database)


def _assert_bound_path(candidate: Path, expected: Path) -> None:
    if Path(candidate).expanduser().absolute() != expected:
        raise InstallationFenceError("installation_profile_mismatch", "This Flower installation is dedicated to a different profile.")
    _owned_path(expected)


def _read_enrollment(environment: Path) -> DedicatedInstallation | None:
    if not _present(environment / _CONTROL):
        return None
    control = _private_control(environment)
    path = control / "enrollment.json"
    if not _present(path):
        if _present(control / "upgrade.json"):
            raise _unsafe()
        return None
    record = _record(path)
    try:
        fields = {"contract", "environment", "environment_identity", "owner", "config", "database", "host", "port", "service_key"}
        if (set(record) != fields or record["contract"] != FENCE_CONTRACT
                or record["environment"] != str(environment)
                or record["environment_identity"] != _identity(environment)
                or record["owner"] != secure._identity()):
            raise _unsafe()
        config, database = Path(record["config"]), Path(record["database"])
        host, port = record["host"], record["port"]
        if (not config.is_absolute() or not database.is_absolute()
                or host not in {"127.0.0.1", "::1"} or type(port) is not int or not 1 <= port <= 65535
                or record["service_key"] != _service_key(config, host, port)):
            raise _unsafe()
    except (OSError, TypeError, ValueError) as exc:
        raise _unsafe() from exc
    return DedicatedInstallation(environment, config, database, host, port, record["service_key"])


def read_enrollment() -> DedicatedInstallation | None:
    environment = _environment()
    return _read_enrollment(environment) if environment is not None else None


def load_installation(config: Path, database: Path) -> DedicatedInstallation:
    binding = read_enrollment()
    if binding is None:
        raise InstallationFenceError("installation_enrollment_required", "Enroll this Flower installation for dedicated managed upgrades first.")
    binding.assert_selection(config, database)
    return binding


def _lease(environment: Path, *, shared: bool) -> RuntimeOwnership:
    try:
        control = _private_control(environment, create=True)
        return acquire_file_ownership(control / "admission", shared=shared)
    except RuntimeOwnershipError as exc:
        if exc.code == "resource_in_use":
            raise InstallationFenceError("installation_in_use", "Another Flower process holds this installation. Inspect the managed upgrade status.") from exc
        raise _unsafe() from exc


def environment_lease(binding: DedicatedInstallation) -> RuntimeOwnership:
    lease = _lease(binding.environment, shared=False)
    try:
        if _read_enrollment(binding.environment) != binding:
            raise _unsafe()
        return lease
    except BaseException:
        lease.close()
        raise


def manual_upgrade_lease() -> RuntimeOwnership | None:
    """Serialize package changes and offline enrollment in an unenrolled environment."""
    environment = _environment()
    if environment is None:
        return None
    lease = _lease(environment, shared=False)
    try:
        if _read_enrollment(environment) is not None:
            raise InstallationFenceError("installation_managed_upgrade_required", "Use the managed upgrade workflow for this dedicated Flower installation.")
        return lease
    except BaseException:
        lease.close()
        raise


def enroll_installation(config: Path, database: Path, *, host: str, port: int, service_key: str) -> DedicatedInstallation:
    """Pin an explicitly selected owned installation while its servers are stopped."""
    from flow_of_work_mcp.release_upgrade import _installation

    environment = _environment()
    if environment is None:
        raise InstallationFenceError("installation_enrollment_unavailable", "Dedicated managed upgrades require an installer-owned Flower environment on macOS.")
    with _lease(environment, shared=False):
        if _installation().target != environment:
            raise _unsafe()
        config, database = _owned_path(config), _owned_path(database)
        if (host not in {"127.0.0.1", "::1"} or type(port) is not int or not 1 <= port <= 65535
                or service_key != _service_key(config, host, port)):
            raise _unsafe()
        binding = DedicatedInstallation(environment, config, database, host, port, service_key)
        existing = _read_enrollment(environment)
        if existing is not None:
            if existing == binding:
                return binding
            raise InstallationFenceError("installation_already_enrolled", "This installation is already dedicated to another Flower service.")
        record = {"contract": FENCE_CONTRACT, "environment": str(environment),
                  "environment_identity": _identity(environment), "owner": secure._identity(),
                  "config": str(config), "database": str(database), "host": host, "port": port,
                  "service_key": service_key}
        try:
            secure.write_owned(environment / _CONTROL / "enrollment.json", (json.dumps(record, sort_keys=True) + "\n").encode())
        except (OSError, secure.ServiceSecurityError) as exc:
            raise _unsafe() from exc
        return binding


def read_upgrade(binding: DedicatedInstallation) -> dict | None:
    if not _present(binding.journal):
        return None
    _private_control(binding.environment)
    record = _record(binding.journal)
    operation = record.get("id")
    phase = record.get("phase")
    if (record.get("contract") != UPGRADE_CONTRACT or record.get("service_key") != binding.service_key
            or not isinstance(operation, str) or not re.fullmatch(r"[a-f0-9]{32}", operation)
            or not isinstance(phase, str) or phase not in _PHASES):
        raise _unsafe()
    return record


@dataclass(frozen=True)
class StartupLease:
    lease: RuntimeOwnership
    binding: DedicatedInstallation | None

    def assert_config(self, config: Path) -> None:
        if self.binding is not None:
            _assert_bound_path(config, self.binding.config)

    def assert_database(self, database: Path) -> None:
        if self.binding is not None:
            _assert_bound_path(database, self.binding.database)

    def assert_admitted(self, *, transport: str, host: str, port: int, managed_restart: str | None) -> None:
        binding = self.binding
        pending = read_upgrade(binding) if binding is not None else None
        if pending is not None and pending["phase"] not in _SETTLED:
            if (pending["phase"] != "restarting" or managed_restart != pending["id"]
                    or transport != "streamable-http" or host != binding.host or port != binding.port):
                raise InstallationFenceError("installation_upgrade_pending", "Flower is fenced by an active or unresolved managed upgrade. Inspect the upgrade status.")
            from flow_of_work_mcp.managed_upgrade import supervised_restart
            if not supervised_restart(binding):
                raise InstallationFenceError("installation_restart_unproved", "Only the selected launchd service may restart during this upgrade.")
        elif managed_restart is not None:
            raise _unsafe()

    def close(self) -> None:
        self.lease.close()


def startup_lease(config: Path | None = None, database: Path | None = None, *, transport: str,
                  host: str = "127.0.0.1", port: int = 8010, managed_restart: str | None = None) -> StartupLease | None:
    """Hold shared installation ownership before selecting or creating a profile."""
    environment = _environment()
    if environment is None:
        if managed_restart is not None:
            raise _unsafe()
        return None
    lease = _lease(environment, shared=True)
    try:
        admission = StartupLease(lease, _read_enrollment(environment))
        admission.assert_admitted(transport=transport, host=host, port=port, managed_restart=managed_restart)
        if config is not None:
            admission.assert_config(config)
        if database is not None:
            admission.assert_database(database)
        return admission
    except BaseException:
        lease.close()
        raise
