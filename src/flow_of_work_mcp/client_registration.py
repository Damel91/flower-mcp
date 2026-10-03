"""Selected-file client registration, with host-local ownership and recovery.

This module never launches a client or server and never changes client trust,
tool approvals, profiles, or lifecycle evidence. Atomicity is per file. Native
client writers do not necessarily honor Flower's advisory ownership lease.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any
from uuid import uuid4

import tomlkit

from flow_of_work_mcp.runtime_ownership import acquire_file_ownership


PLATFORMS = ("codex", "claude-code", "cursor")
_RECEIPT_CONTRACT = "flower.client-registration.v1"
_RESULT_CONTRACT = "flower.client-registration-result.v1"
_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_MAX_RECEIPT_BYTES = 64 * 1024
_ABSENT = object()
_SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_KEYS = frozenset({
    "contract", "platform", "client_config_path", "profile_config_path",
    "python_executable", "server_name", "managed_entry", "managed_entry_sha256",
    "state", "config_before_sha256", "config_after_sha256", "backup_path",
})


class ClientRegistrationError(ValueError):
    """Safe diagnostic: no foreign settings or parser excerpts are included."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _validate_platform(platform: str) -> None:
    if platform not in PLATFORMS:
        raise ClientRegistrationError("client_platform_invalid", "Select codex, claude-code or cursor.")


def _validate_name(server_name: str) -> None:
    if not isinstance(server_name, str) or not _SERVER_NAME.fullmatch(server_name):
        raise ClientRegistrationError("client_server_name_invalid", "Server name must contain 1..64 letters, digits, underscores or hyphens.")


def _regular_file(path: Path, *, allow_hardlinks: bool = False) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or not allow_hardlinks and info.st_nlink != 1:
        raise ClientRegistrationError("client_file_unsafe", "Selected installation file must be a regular, unlinked file; symlinks are refused.")
    return info


def _path(value: str | Path, *, allow_hardlinks: bool = False) -> Path:
    selected = Path(os.path.abspath(Path(value).expanduser()))
    # Reject the selected final symlink before resolving parent aliases.
    _regular_file(selected, allow_hardlinks=allow_hardlinks)
    return selected.parent.resolve() / selected.name


def default_client_config(platform: str, home: Path | None = None) -> Path:
    """Compute one documented location; do not inspect other client settings."""
    _validate_platform(platform)
    user_home = Path.home() if home is None else Path(home)
    if platform == "codex":
        codex_home = os.environ.get("CODEX_HOME") if home is None else None
        return (Path(codex_home).expanduser() if codex_home else user_home / ".codex") / "config.toml"
    return user_home / (".claude.json" if platform == "claude-code" else ".cursor/mcp.json")


def registration_receipt_path(root: Path, platform: str, client_config: Path, server_name: str = "flower") -> Path:
    _validate_platform(platform)
    _validate_name(server_name)
    selected = _path(client_config)
    identity = hashlib.sha256((str(selected) + "\0" + server_name).encode("utf-8")).hexdigest()
    return Path(root).expanduser().absolute() / "registrations" / f"{platform}-{identity}.json"


def _sha(payload: bytes | None) -> str | None:
    return None if payload is None else hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _entry_sha(entry: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _entry(platform: str, python_executable: Path, profile_config: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"command": str(python_executable), "args": [
        "-m", "flow_of_work_mcp.cli", "serve", "--config", str(profile_config), "--transport", "stdio",
    ]}
    if platform != "codex":
        entry = {"type": "stdio", **entry}
    return entry


def _read(path: Path, limit: int) -> tuple[bytes | None, int]:
    info = _regular_file(path)
    if info is None:
        return None, 0o600
    if info.st_size > limit:
        raise ClientRegistrationError("client_file_too_large", "Selected installation file exceeds its bounded size limit.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise ClientRegistrationError("client_config_changed", "Selected file changed during inspection; retry after reconciling the writer.")
            payload = source.read(limit + 1)
            finished = os.fstat(source.fileno())
            if (opened.st_size, opened.st_mtime_ns) != (finished.st_size, finished.st_mtime_ns):
                raise ClientRegistrationError("client_config_changed", "Selected file changed during inspection; retry after reconciling the writer.")
        current = _regular_file(path)
    except OSError as exc:
        raise ClientRegistrationError("client_file_unreadable", "Selected installation file could not be read.") from exc
    if current is None or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise ClientRegistrationError("client_config_changed", "Selected file changed during inspection; retry after reconciling the writer.")
    if len(payload) > limit:
        raise ClientRegistrationError("client_file_too_large", "Selected installation file exceeds its bounded size limit.")
    return payload, stat.S_IMODE(info.st_mode)


def _strict_json(payload: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("non-finite number")

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ClientRegistrationError("client_json_invalid", "Selected file must be strict UTF-8 JSON with unique keys; comments are unsupported.") from exc


@dataclass
class _Config:
    raw: bytes | None
    mode: int
    document: Any
    servers: Any
    entry: Any


def _config(platform: str, path: Path, server_name: str) -> _Config:
    raw, mode = _read(path, _MAX_CONFIG_BYTES)
    if platform == "codex":
        try:
            document = tomlkit.document() if raw is None else tomlkit.parse(raw.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ClientRegistrationError("client_toml_invalid", "Selected file must be valid UTF-8 TOML.") from exc
        key = "mcp_servers"
    else:
        document = {} if raw is None else _strict_json(raw)
        key = "mcpServers"
    if not isinstance(document, Mapping):
        raise ClientRegistrationError("client_config_invalid", "Client configuration must be an object or TOML document.")
    servers = document.get(key) if key in document else None
    if key in document and not isinstance(servers, Mapping):
        raise ClientRegistrationError("client_config_invalid", "Client server definitions must be an object or TOML table.")
    actual = _ABSENT if servers is None else servers.get(server_name, _ABSENT)
    if hasattr(actual, "unwrap"):
        actual = actual.unwrap()
    return _Config(raw, mode, document, servers, actual)


def _render(platform: str, config: _Config, server_name: str, entry: dict[str, Any] | None) -> bytes:
    key = "mcp_servers" if platform == "codex" else "mcpServers"
    if config.servers is None:
        config.document[key] = tomlkit.table() if platform == "codex" else {}
        config.servers = config.document[key]
    if entry is None:
        config.servers.pop(server_name, None)
    else:
        config.servers[server_name] = entry
    try:
        payload = tomlkit.dumps(config.document).encode("utf-8") if platform == "codex" else _json_bytes(config.document)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ClientRegistrationError("client_config_invalid", "Client configuration cannot be safely serialized.") from exc
    if len(payload) > _MAX_CONFIG_BYTES:
        raise ClientRegistrationError("client_file_too_large", "Resulting client configuration exceeds its bounded size limit.")
    return payload


def _receipt(path: Path, platform: str, client_config: Path, server_name: str) -> dict[str, Any] | None:
    payload, _ = _read(path, _MAX_RECEIPT_BYTES)
    if payload is None:
        return None
    try:
        receipt = _strict_json(payload)
        if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS:
            raise ValueError("schema")
        if receipt["contract"] != _RECEIPT_CONTRACT or receipt["platform"] != platform or receipt["client_config_path"] != str(client_config) or receipt["server_name"] != server_name:
            raise ValueError("identity")
        if receipt["state"] not in {"prepared", "installed", "removing", "removed"}:
            raise ValueError("state")
        for key in ("profile_config_path", "python_executable"):
            if not isinstance(receipt[key], str) or not Path(receipt[key]).is_absolute():
                raise ValueError("path")
        expected = _entry(platform, Path(receipt["python_executable"]), Path(receipt["profile_config_path"]))
        if receipt["managed_entry"] != expected or receipt["managed_entry_sha256"] != _entry_sha(expected):
            raise ValueError("entry")
        for key in ("config_before_sha256", "config_after_sha256"):
            value = receipt[key]
            if value is not None and (not isinstance(value, str) or not _HASH.fullmatch(value)):
                raise ValueError("hash")
        if receipt["config_after_sha256"] is None:
            raise ValueError("after hash")
        backup = receipt["backup_path"]
        if backup is not None and (not isinstance(backup, str) or not Path(backup).is_absolute()):
            raise ValueError("backup")
        return receipt
    except (ValueError, TypeError) as exc:
        raise ClientRegistrationError("client_receipt_invalid", "Registration receipt is invalid or belongs to another selected configuration.") from exc


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":
        return  # Windows has no portable directory-fsync primitive.
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, payload: bytes, mode: int = 0o600, *, expected: bytes | None | object = _ABSENT) -> None:
    _regular_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging = tempfile.mkstemp(prefix=f".{path.name}.flower-", dir=path.parent)
    staged_path = Path(staging)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(payload)
            destination.flush()
            if hasattr(os, "fchmod"):
                os.fchmod(destination.fileno(), mode)
            else:
                os.chmod(staged_path, mode)
            os.fsync(destination.fileno())
        _regular_file(path)
        if expected is not _ABSENT:
            current, _ = _read(path, _MAX_CONFIG_BYTES)
            if current != expected:
                raise ClientRegistrationError("client_config_changed", "Client configuration changed before replacement; reconcile the writer before retrying.")
        os.replace(staged_path, path)
        _fsync_parent(path)
    finally:
        staged_path.unlink(missing_ok=True)


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    _atomic_write(path, _json_bytes(receipt))


def _backup(receipt_path: Path, payload: bytes | None) -> str | None:
    if payload is None:
        return None
    destination = receipt_path.parent / "backups" / f"{receipt_path.stem}-{uuid4().hex}.bak"
    _atomic_write(destination, payload)
    return str(destination)


def _replace_config(path: Path, expected: bytes | None, payload: bytes, mode: int) -> None:
    _atomic_write(path, payload, mode, expected=expected)


def _result(platform: str, client_config: Path, receipt_path: Path, server_name: str, state: str, *, changed: bool = False, dry_run: bool = False, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "contract": _RESULT_CONTRACT, "platform": platform, "client_config": str(client_config),
        "receipt_path": str(receipt_path), "server_name": server_name, "state": state,
        "changed": changed, "dry_run": dry_run,
        "profile_config": None if receipt is None else receipt["profile_config_path"],
        "message": "Selected-file registration is installation metadata; client trust, precedence and connection are checked separately.",
        "next_action": "repeat the interrupted operation" if state == "needs_recovery" else "check the selected client for trust and connection" if state == "registered" else "inspect the selected registration before changing it" if state in {"unowned", "diverged"} else "none",
    }


def _selected(platform: str, client_config: Path, receipt_path: Path, server_name: str) -> tuple[Path, Path]:
    _validate_platform(platform)
    _validate_name(server_name)
    config_path, metadata_path = _path(client_config), _path(receipt_path)
    if config_path == metadata_path:
        raise ClientRegistrationError("client_paths_invalid", "Client configuration and ownership receipt must be distinct files.")
    return config_path, metadata_path


def inspect_client_registration(*, platform: str, client_config: Path, receipt_path: Path, server_name: str = "flower") -> dict[str, Any]:
    """Read only the selected config and receipt; no lock, process or probing."""
    client_config, receipt_path = _selected(platform, client_config, receipt_path, server_name)
    config = _config(platform, client_config, server_name)
    receipt = _receipt(receipt_path, platform, client_config, server_name)
    if receipt is None:
        state = "absent" if config.entry is _ABSENT else "unowned"
    elif receipt["state"] == "prepared":
        state = "needs_recovery" if config.entry == receipt["managed_entry"] or _sha(config.raw) == receipt["config_before_sha256"] else "diverged"
    elif receipt["state"] == "removing":
        unchanged_before = config.entry == receipt["managed_entry"] and _sha(config.raw) == receipt["config_before_sha256"]
        recorded_after = config.entry is _ABSENT and _sha(config.raw) == receipt["config_after_sha256"]
        state = "needs_recovery" if unchanged_before or recorded_after else "diverged"
    elif receipt["state"] == "installed":
        state = "absent" if config.entry is _ABSENT else "registered" if config.entry == receipt["managed_entry"] else "diverged"
    else:
        state = "absent" if config.entry is _ABSENT else "unowned"
    return _result(platform, client_config, receipt_path, server_name, state, receipt=receipt)


def register_client(*, platform: str, client_config: Path, profile_config: Path, receipt_path: Path, python_executable: Path, server_name: str = "flower", replace: bool = False, dry_run: bool = False) -> dict[str, Any]:
    client_config, receipt_path = _selected(platform, client_config, receipt_path, server_name)
    # Python may legitimately be a virtualenv symlink; preserve its installed
    # absolute spelling, rather than resolving it to a different interpreter.
    python_executable = Path(os.path.abspath(Path(python_executable).expanduser()))
    # The profile is only referenced, never read or mutated here. Atomic
    # no-replace profile initialization can leave a valid hardlinked YAML
    # after process interruption, so that reference need not be unlinked.
    profile_config = _path(profile_config, allow_hardlinks=True)
    if profile_config in {client_config, receipt_path}:
        raise ClientRegistrationError("client_paths_invalid", "Profile, client configuration and ownership receipt must be distinct files.")
    desired = _entry(platform, python_executable, profile_config)

    def perform() -> dict[str, Any]:
        config = _config(platform, client_config, server_name)
        receipt = _receipt(receipt_path, platform, client_config, server_name)
        if receipt is not None and receipt["state"] == "removing":
            raise ClientRegistrationError("client_recovery_required", "Finish the recorded uninstall before registering a client.")
        if receipt is not None and receipt["state"] == "prepared":
            if receipt["managed_entry"] != desired:
                raise ClientRegistrationError("client_recovery_required", "Finish the recorded registration before switching profiles or interpreters.")
            if config.entry == desired:
                if not dry_run:
                    _write_receipt(receipt_path, {**receipt, "state": "installed"})
                return _result(platform, client_config, receipt_path, server_name, "registered", changed=not dry_run, dry_run=dry_run, receipt=receipt)
            if _sha(config.raw) != receipt["config_before_sha256"]:
                raise ClientRegistrationError("client_config_changed", "Interrupted registration cannot prove its unchanged before state or recorded effect.")
            payload = _render(platform, config, server_name, desired)
            if _sha(payload) != receipt["config_after_sha256"]:
                raise ClientRegistrationError("client_receipt_invalid", "Interrupted registration does not reproduce its recorded after state.")
            if not dry_run:
                _replace_config(client_config, config.raw, payload, config.mode)
                _write_receipt(receipt_path, {**receipt, "state": "installed"})
            return _result(platform, client_config, receipt_path, server_name, "registered", changed=not dry_run, dry_run=dry_run, receipt=receipt)
        if receipt is not None and receipt["state"] == "installed" and receipt["managed_entry"] == desired and config.entry == desired:
            return _result(platform, client_config, receipt_path, server_name, "registered", dry_run=dry_run, receipt=receipt)
        if config.entry is not _ABSENT and not replace:
            raise ClientRegistrationError("client_registration_conflict", "The selected server name is already defined; use explicit replacement after reviewing this conflict.")
        payload = _render(platform, config, server_name, desired)
        new_receipt = {
            "contract": _RECEIPT_CONTRACT, "platform": platform,
            "client_config_path": str(client_config), "profile_config_path": str(profile_config),
            "python_executable": str(python_executable), "server_name": server_name,
            "managed_entry": desired, "managed_entry_sha256": _entry_sha(desired), "state": "prepared",
            "config_before_sha256": _sha(config.raw), "config_after_sha256": _sha(payload), "backup_path": None,
        }
        if not dry_run:
            new_receipt["backup_path"] = _backup(receipt_path, config.raw)
            _write_receipt(receipt_path, new_receipt)
            _replace_config(client_config, config.raw, payload, config.mode)
            _write_receipt(receipt_path, {**new_receipt, "state": "installed"})
        return _result(platform, client_config, receipt_path, server_name, "registered", changed=not dry_run, dry_run=dry_run, receipt=new_receipt)

    if dry_run:
        return perform()
    with acquire_file_ownership(client_config, suffix=".flower-registration.lock"):
        return perform()


def unregister_client(*, platform: str, client_config: Path, receipt_path: Path, server_name: str = "flower", dry_run: bool = False) -> dict[str, Any]:
    client_config, receipt_path = _selected(platform, client_config, receipt_path, server_name)
    # An observed absence needs no mutation lease or directory creation. This
    # reports the read boundary only; it does not remove an entry that might
    # appear afterward. Existing state is always reread under the lease below.
    preliminary = _config(platform, client_config, server_name)
    metadata = _receipt(receipt_path, platform, client_config, server_name)
    if metadata is None and preliminary.entry is _ABSENT:
        return _result(platform, client_config, receipt_path, server_name, "absent", dry_run=dry_run)

    def perform() -> dict[str, Any]:
        config = _config(platform, client_config, server_name)
        receipt = _receipt(receipt_path, platform, client_config, server_name)
        if receipt is None:
            if config.entry is _ABSENT:
                return _result(platform, client_config, receipt_path, server_name, "absent", dry_run=dry_run)
            raise ClientRegistrationError("client_registration_unowned", "No valid ownership receipt permits removal of the selected entry.")
        if receipt["state"] == "prepared":
            raise ClientRegistrationError("client_recovery_required", "Finish the recorded registration before uninstalling it.")
        if receipt["state"] == "removed":
            if config.entry is not _ABSENT:
                raise ClientRegistrationError("client_registration_unowned", "The removed registration name has been defined again and is not owned by this receipt.")
            return _result(platform, client_config, receipt_path, server_name, "absent", dry_run=dry_run, receipt=receipt)
        if receipt["state"] == "removing" and config.entry is _ABSENT:
            if _sha(config.raw) != receipt["config_after_sha256"]:
                raise ClientRegistrationError("client_config_changed", "Interrupted uninstall cannot prove its recorded after state.")
            if not dry_run:
                _write_receipt(receipt_path, {**receipt, "state": "removed"})
            return _result(platform, client_config, receipt_path, server_name, "absent", changed=not dry_run, dry_run=dry_run, receipt=receipt)
        if config.entry != receipt["managed_entry"]:
            raise ClientRegistrationError("client_registration_diverged", "Owned client entry changed or disappeared; removal is refused until ownership is reconciled.")
        payload = _render(platform, config, server_name, None)
        if receipt["state"] == "removing":
            if _sha(config.raw) != receipt["config_before_sha256"] or _sha(payload) != receipt["config_after_sha256"]:
                raise ClientRegistrationError("client_config_changed", "Interrupted uninstall cannot prove its unchanged before state.")
            removing = receipt
        else:
            removing = {**receipt, "state": "removing", "config_before_sha256": _sha(config.raw),
                        "config_after_sha256": _sha(payload), "backup_path": None}
            if not dry_run:
                removing["backup_path"] = _backup(receipt_path, config.raw)
                _write_receipt(receipt_path, removing)
        if not dry_run:
            _replace_config(client_config, config.raw, payload, config.mode)
            _write_receipt(receipt_path, {**removing, "state": "removed"})
        return _result(platform, client_config, receipt_path, server_name, "absent", changed=not dry_run, dry_run=dry_run, receipt=removing)

    if dry_run:
        return perform()
    with acquire_file_ownership(client_config, suffix=".flower-registration.lock"):
        return perform()
