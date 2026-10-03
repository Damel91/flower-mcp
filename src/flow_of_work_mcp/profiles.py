"""Host-owned core profiles, independent of source checkout and working directory."""
from __future__ import annotations

from importlib.resources import files
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

import yaml

from flow_of_work_mcp.config import FlowConfigError, load_config


class ProfileError(ValueError):
    """A profile cannot be selected or initialized safely."""


def default_profile_root() -> Path:
    if "FLOWER_HOME" in os.environ:
        if not os.environ["FLOWER_HOME"].strip():
            raise ProfileError("FLOWER_HOME must be a nonempty absolute path")
        return _absolute_root(Path(os.environ["FLOWER_HOME"]))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Flower MCP"
    if sys.platform == "win32":
        location = os.environ.get("LOCALAPPDATA")
        if not location:
            raise ProfileError("LOCALAPPDATA is required; select --profile-root explicitly")
        return _absolute_root(Path(location)) / "Flower MCP"
    location = os.environ.get("XDG_DATA_HOME")
    return (_absolute_root(Path(location)) if location else Path.home() / ".local" / "share") / "flower-mcp"


def _absolute_root(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise ProfileError("profile root must be absolute")
    return path.resolve()


def profile_root(root: Path | None = None) -> Path:
    return _absolute_root(root) if root is not None else _absolute_root(default_profile_root())


def profile_config_path(root: Path | None = None, name: str = "default") -> Path:
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name) or name.endswith(".") or name.split(".")[0].upper() in reserved:
        raise ProfileError("profile name must be a portable name of 1..64 letters, digits, _, - or .")
    root_path = profile_root(root)
    parent = root_path / "profiles" / name
    if not parent.resolve().is_relative_to(root_path):
        raise ProfileError("profile directory resolves outside the selected root")
    return parent / "flower.yaml"


def _existing(path: Path, import_root: Path | None) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise ProfileError("profile configuration must be a regular file, not a symlink")
    try:
        config = load_config(path)
    except FlowConfigError as exc:
        raise ProfileError(str(exc)) from exc
    if import_root is not None and config.runtime.import_root != import_root.expanduser().resolve():
        raise ProfileError("existing profile has a different import root; inspect and edit its YAML explicitly")
    if config.runtime.import_root.exists() and not config.runtime.import_root.is_dir():
        raise ProfileError("profile import root must be a directory; existing data was preserved")
    return True


def prepare_profile(root: Path | None = None, name: str = "default", *, import_root: Path | None = None, dry_run: bool = False) -> Path:
    path = profile_config_path(root, name)
    if _existing(path, import_root):
        return path
    parent = path.parent
    destination = import_root.expanduser().resolve() if import_root is not None else parent / "imports"
    if import_root is None and destination.is_symlink():
        raise ProfileError("implicit profile imports must not be a symlink; select an explicit --import-root")
    if destination.exists() and not destination.is_dir():
        raise ProfileError("profile import root must be a directory; existing data was preserved")
    payload = yaml.safe_load(files("flow_of_work_mcp").joinpath("resources/standalone.yaml").read_text(encoding="utf-8"))
    payload["runtime"].update(database_path=str(parent / "ledger.sqlite3"), import_root=str(destination))
    payload["logging"]["logs_path"] = str(parent / "logs")
    if dry_run:
        return path
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not parent.resolve().is_relative_to(profile_root(root)):
        raise ProfileError("profile directory changed outside the selected root")
    if import_root is None:
        # Close this prerequisite before publishing usable configuration. An
        # existing file/symlink must never become a false-success retry.
        if destination.is_symlink():
            raise ProfileError("implicit profile imports changed to a symlink")
        destination.mkdir(mode=0o700, exist_ok=True)
    # Create a complete private file before exposing it. Link is an atomic
    # no-replace operation: concurrent initialization never overwrites a profile.
    fd, temporary = tempfile.mkstemp(prefix=".flower-profile-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yaml.safe_dump(payload, stream, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not _existing(path, import_root):
                raise ProfileError("concurrent profile initialization did not produce a valid file")
    finally:
        Path(temporary).unlink(missing_ok=True)
        if os.name == "posix":
            directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    _existing(path, import_root)
    return path
