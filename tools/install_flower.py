#!/usr/bin/env python3
"""Download, verify and install a pinned Flower MCP release with Python 3.11+."""
from __future__ import annotations

import argparse
import errno
import hashlib
import hmac
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import venv


REPOSITORY = "https://github.com/Damel91/flower-mcp"
DEFAULT_VERSION = "0.7.0"
OWNER_FILE = ".flower-release-install.json"
OWNER_CONTRACT = "flower.release-installation.v1"
DOWNLOAD_TIMEOUT = 30
UPGRADE_READY_TIMEOUT = 120
UPGRADE_RELEASE_TIMEOUT = 10
UPGRADE_STOP_TIMEOUT = 5

# These helpers run in the OLD isolated installation. They reuse its canonical
# profile/configuration and OS ownership services without composing a runtime,
# opening a mutable store or importing the source checkout.
DISCOVER_UPGRADE = r'''
import hashlib, json, os, stat, sys
import yaml
from importlib.metadata import version
from pathlib import Path
from flow_of_work_mcp.config import load_config
from flow_of_work_mcp.profiles import profile_config_path, profile_root

def discover(selection):
    root = profile_root(None if selection['profile_root'] is None else Path(selection['profile_root']))
    path = profile_config_path(root, selection['profile'])
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
        raise ValueError('Selected profile must be an existing regular bounded YAML file')
    payload = path.read_bytes()
    config = load_config(path)
    raw = yaml.safe_load(payload)
    for value in (raw['runtime']['database_path'], raw['runtime']['import_root'], raw['logging']['logs_path']):
        selected = Path(value).expanduser()
        if not selected.is_absolute():
            selected = path.parent / selected
        selected = Path(os.path.abspath(selected))
        if selected.resolve() != selected:
            raise ValueError('Selected persistent data paths must not contain symlink aliases')
    ledger = config.runtime.database_path
    metadata = ledger.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError('Selected ledger must be an existing regular unlinked SQLite file')
    return dict(installed_version=version('flow-of-work-mcp'), profile_root=str(root),
        profile_config=str(path), profile_sha256=hashlib.sha256(payload).hexdigest(),
        database_path=str(ledger), import_root=str(config.runtime.import_root),
        logs_path=str(config.logging.logs_path))

selection = json.loads(sys.argv[1])
'''

DISCOVERY_PROGRAM = DISCOVER_UPGRADE + r'''
try:
    print(json.dumps({'status': 'ok', **discover(selection)}), flush=True)
except Exception:
    print(json.dumps({'status': 'error', 'message': 'Cannot inspect the existing selected profile and ledger; no files were changed.'}), flush=True)
    raise SystemExit(1)
'''

BACKUP_PROGRAM = DISCOVER_UPGRADE + r'''
import sqlite3, tempfile, threading
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership

backup_directory = None
try:
    expected = selection['expected']
    if discover(selection) != expected:
        raise ValueError('Selected installation or profile changed after preflight')
    with acquire_runtime_ownership(expected['database_path']):
        if discover(selection) != expected:
            raise ValueError('Selected installation or profile changed before backup')
        root = Path(selection['backup_root'])
        if root.resolve() != root or root.is_symlink():
            raise ValueError('Backup directory changed to an alias')
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.resolve() != root or root.is_symlink():
            raise ValueError('Backup directory changed to an alias')
        backup_directory = Path(tempfile.mkdtemp(prefix='flower-upgrade-', dir=root))
        os.chmod(backup_directory, 0o700)
        profile = Path(expected['profile_config']).read_bytes()
        if hashlib.sha256(profile).hexdigest() != expected['profile_sha256']:
            raise ValueError('Selected profile changed before backup')
        yaml_backup = backup_directory / 'flower.yaml'
        with yaml_backup.open('xb') as output:
            os.chmod(yaml_backup, 0o600)
            output.write(profile)
            output.flush()
            os.fsync(output.fileno())
        database_backup = backup_directory / 'ledger.sqlite3'
        descriptor = os.open(database_backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        uri = Path(expected['database_path']).as_uri() + '?mode=ro'
        source = sqlite3.connect(uri, uri=True, timeout=5)
        destination = sqlite3.connect(database_backup)
        deadline = __import__('time').monotonic() + 90
        def progress(status, remaining, total):
            if __import__('time').monotonic() > deadline:
                raise TimeoutError('SQLite backup exceeded its bounded duration')
        try:
            source.backup(destination, pages=256, progress=progress, sleep=0.05)
            if destination.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite backup integrity check failed')
        finally:
            destination.close()
            source.close()
        receipt = dict(contract='flower.release-upgrade-backup.v1', **expected,
            requested_version=selection['requested_version'], backup_directory=str(backup_directory),
            database_backup=str(database_backup), profile_backup=str(yaml_backup))
        receipt_path = backup_directory / 'upgrade.json'
        with receipt_path.open('x', encoding='utf-8') as output:
            os.chmod(receipt_path, 0o600)
            json.dump(receipt, output, indent=2)
            output.write('\n')
        print(json.dumps({'status': 'ready', **receipt}), flush=True)
        # EOF also releases the lease if the parent is interrupted. The hard
        # bound covers all parent's timed package and diagnosis operations.
        timer = threading.Timer(950, lambda: os._exit(2))
        timer.daemon = True
        timer.start()
        try:
            if sys.stdin.readline().strip() != 'release':
                raise SystemExit(2)
        finally:
            timer.cancel()
except Exception as exc:
    print(json.dumps({'status': 'error', 'code': getattr(exc, 'code', 'upgrade_backup_failed'),
        'message': str(exc) if hasattr(exc, 'code') else 'Selected ledger backup failed; original data was retained.',
        'backup_directory': None if backup_directory is None else str(backup_directory)}), flush=True)
    raise SystemExit(1)
'''


class InstallationError(RuntimeError):
    pass


def release_version(value: str) -> str:
    if re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value) is None:
        raise argparse.ArgumentTypeError("version must be a stable MAJOR.MINOR.PATCH release, for example 0.1.0")
    return value


def default_venv(*, platform=None, environ=None, home=None) -> Path:
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform == "win32":
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return base / "Flower MCP Install" / "venv"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Flower MCP Install" / "venv"
    configured = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    base = configured if configured.is_absolute() else home / ".local" / "share"
    return base / "flower-mcp-install" / "venv"


def require_https(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise InstallationError("release downloads require HTTPS")


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        require_https(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def download_asset(url: str, destination: Path, *, max_bytes: int) -> str:
    require_https(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Flower-MCP-Release-Installer"})
    opener = urllib.request.build_opener(HTTPSRedirects())
    created = False
    digest = hashlib.sha256()
    try:
        with opener.open(request, timeout=DOWNLOAD_TIMEOUT) as response:
            require_https(response.geturl())
            with destination.open("xb") as output:
                created = True
                total = 0
                while chunk := response.read(64 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise InstallationError("release asset exceeds the download limit")
                    output.write(chunk)
                    digest.update(chunk)
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def checksum_for(text: str, filename: str) -> str:
    entries = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([A-Fa-f0-9]{64}) [ *]([A-Za-z0-9_.-]+)", line)
        if match is None or match[2] in {".", ".."}:
            raise InstallationError("SHA256SUMS contains an invalid checksum entry")
        digest, name = match.groups()
        if name in entries:
            raise InstallationError("SHA256SUMS contains a duplicate filename")
        entries[name] = digest.lower()
    if filename not in entries:
        raise InstallationError("SHA256SUMS does not identify the requested wheel")
    return entries[filename]


def interpreter_in(target: Path) -> Path:
    return target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def command_in(target: Path) -> Path:
    return target / ("Scripts/flower-mcp.exe" if os.name == "nt" else "bin/flower-mcp")


def clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PIP_TARGET", "PIP_PREFIX", "PIP_USER"):
        environment.pop(name, None)
    return environment


def run(command: list[str], *, cwd: Path, timeout: int = 60, capture_output=False):
    return subprocess.run(command, cwd=cwd, env=clean_environment(), timeout=timeout,
                          check=True, capture_output=capture_output, text=True)


def existing_installation(target: Path, *, upgrade: bool) -> bool:
    if target.is_symlink():
        raise InstallationError("the installation directory must not be a symlink")
    if not target.exists():
        if upgrade:
            raise InstallationError("--upgrade requires an existing owned installation; it cannot create an environment")
        return False
    if not upgrade:
        raise InstallationError("the installation directory already exists; use --upgrade for an existing Flower installation")
    owner = target / OWNER_FILE
    if not target.is_dir() or owner.is_symlink() or not owner.is_file():
        raise InstallationError("--upgrade requires an environment created by this Flower release installer")
    metadata = owner.stat()
    if metadata.st_nlink != 1 or metadata.st_size > 64 * 1024:
        raise InstallationError("the existing installation receipt is unsafe")
    try:
        record = json.loads(owner.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallationError("the existing installation receipt is invalid") from exc
    if (not isinstance(record, dict) or record.get("contract") != OWNER_CONTRACT
            or record.get("repository") != REPOSITORY
            or not isinstance(record.get("version"), str)
            or re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", record["version"]) is None
            or record.get("wheel") != f"flow_of_work_mcp-{record['version']}-py3-none-any.whl"
            or not isinstance(record.get("sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", record["sha256"]) is None
            or not (target / "pyvenv.cfg").is_file() or not interpreter_in(target).is_file()):
        raise InstallationError("--upgrade requires an environment created by this Flower release installer")
    return True


def _selection(args) -> dict:
    return {"profile": args.profile, "profile_root": None if args.profile_root is None
            else str(args.profile_root.expanduser().absolute())}


def _no_alias(path: Path, label: str) -> Path:
    path = path.expanduser().absolute()
    if path.resolve() != path:
        raise InstallationError(f"{label} must not contain symlink aliases")
    return path


def _overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def upgrade_plan(args, target: Path, version: str, *, cwd: Path) -> tuple[dict, dict]:
    target = _no_alias(target, "installation environment")
    if args.profile_root is not None:
        _no_alias(args.profile_root, "profile root")
    try:
        inspection = run([str(interpreter_in(target)), "-I", "-B", "-c", DISCOVERY_PROGRAM,
                          json.dumps(_selection(args))], cwd=cwd, capture_output=True)
    except (subprocess.SubprocessError, OSError) as exc:
        raise InstallationError("existing installed profile inspection failed; select its existing --profile and --profile-root. No files were changed") from exc
    try:
        discovered = json.loads(inspection.stdout)
        if discovered.pop("status") != "ok":
            raise ValueError("invalid inspection")
        previous = release_version(discovered["installed_version"])
        receipt = json.loads((target / OWNER_FILE).read_text(encoding="utf-8"))
        if previous != receipt["version"]:
            raise InstallationError("installed package version differs from its ownership receipt; inspect the environment before retrying")
        if tuple(map(int, version.split("."))) < tuple(map(int, previous.split("."))):
            raise InstallationError("--upgrade cannot downgrade the installed release")
        root = _no_alias(Path(discovered["profile_root"]), "profile root")
        profile = _no_alias(Path(discovered["profile_config"]), "profile configuration")
        database = _no_alias(Path(discovered["database_path"]), "database")
        imports = _no_alias(Path(discovered["import_root"]), "import root")
        logs = _no_alias(Path(discovered["logs_path"]), "logs directory")
        backup = _no_alias(args.backup_root or root / "upgrade-backups", "backup root")
    except (ValueError, KeyError, TypeError) as exc:
        raise InstallationError("existing installed profile inspection returned an invalid result") from exc
    if (_overlap(target, root) or any(_overlap(target, directory) for directory in (profile.parent, imports, logs))
            or database.is_relative_to(target) or target.is_relative_to(database)):
        raise InstallationError("installation environment and persistent data must be separate; no data was relocated")
    if (_overlap(backup, target) or any(_overlap(backup, directory) for directory in (profile.parent, imports, logs))
            or database.is_relative_to(backup) or backup.is_relative_to(database)):
        raise InstallationError("backup root must be separate from the environment and selected profile, ledger, imports and logs")
    if backup.exists() and not backup.is_dir():
        raise InstallationError("backup root must be a directory")
    plan = {"contract": "flower.release-upgrade-plan.v1", "dry_run": args.dry_run,
            "previous_version": previous, "requested_version": version,
            "environment": str(target), "profile": args.profile, **discovered,
            "backup_root": str(backup), "registration_changed": False,
            "preservation": "Existing profile YAML, SQLite ledger, imports, logs and client registration are retained. No automatic restore or atomic package rollback.",
            "required_actions": ["Stop all Flower clients and servers sharing this installation environment before executing the upgrade.",
                                 "After upgrade, restart the selected Flower connection and recover the existing project using its known project identity and handover. Do not bootstrap a new lifecycle project."]}
    return plan, discovered


class UpgradeLease:
    """An old installed child owns the ledger while the parent changes code."""

    def __init__(self, python: Path, selection: dict, *, cwd: Path):
        self.process = subprocess.Popen([str(python), "-I", "-B", "-c", BACKUP_PROGRAM, json.dumps(selection)],
            cwd=cwd, env=clean_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        self.receipt = None
        responses = queue.Queue()
        self.reader = threading.Thread(target=lambda: responses.put(self.process.stdout.readline(256 * 1024)), daemon=True)
        self.reader.start()
        try:
            try:
                line = responses.get(timeout=UPGRADE_READY_TIMEOUT)
            except queue.Empty as exc:
                raise InstallationError("timed out preparing the selected ledger ownership and backup") from exc
            try:
                result = json.loads(line)
                if not isinstance(result, dict):
                    raise ValueError("invalid child result")
            except ValueError as exc:
                raise InstallationError("the selected ledger ownership process exited without a valid backup result") from exc
            if result.get("status") != "ready":
                retained = result.get("backup_directory")
                detail = "" if retained is None else f" Partial backup retained at {retained}."
                raise InstallationError(f"{result.get('code', 'upgrade_backup_failed')}: {result.get('message', 'Backup could not be prepared.')}{detail}")
            self.receipt = result
            self.assert_active()
        except BaseException:
            self.close()
            raise

    def assert_active(self):
        if self.process.poll() is not None:
            raise InstallationError("the selected ledger ownership process stopped before upgrade finished")

    def close(self):
        process = self.process
        cleanup_error = None
        if process.poll() is None:
            try:
                process.stdin.write("release\n")
                process.stdin.flush()
                process.stdin.close()
                process.wait(timeout=UPGRADE_RELEASE_TIMEOUT)
            except (OSError, subprocess.TimeoutExpired) as exc:
                process.terminate()
                try:
                    process.wait(timeout=UPGRADE_STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=UPGRADE_STOP_TIMEOUT)
                if isinstance(exc, OSError) and not (
                        isinstance(exc, BrokenPipeError) or exc.errno in {errno.EPIPE, errno.EINVAL}):
                    cleanup_error = exc
        self.reader.join(timeout=UPGRADE_STOP_TIMEOUT)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError as exc:
                    # Text stdin may retry a buffered flush during close after
                    # an exited child's pipe is gone. Windows reports EINVAL
                    # for that case. Only this reaped child's stdin qualifies;
                    # unrelated descriptor failures remain visible.
                    broken_stdin = stream is process.stdin and process.poll() is not None and (
                        isinstance(exc, BrokenPipeError) or exc.errno in {errno.EPIPE, errno.EINVAL})
                    if not broken_stdin and cleanup_error is None:
                        cleanup_error = exc
        if cleanup_error is not None:
            raise cleanup_error


def write_receipt(target: Path, record: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".flower-install-",
                                     suffix=".tmp", dir=target, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(record, stream, indent=2)
        stream.write("\n")
    try:
        os.replace(temporary, target / OWNER_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def installation(args) -> dict:
    if sys.version_info < (3, 11):
        raise InstallationError("Flower MCP requires Python 3.11 or newer")
    if args.upgrade:
        if args.platform is not None or args.client_config is not None:
            raise InstallationError("--upgrade cannot be combined with client registration")
        args.no_register = True
    elif args.dry_run or args.backup_root is not None:
        raise InstallationError("--dry-run and --backup-root require --upgrade")
    elif args.platform is None and not args.no_register:
        raise InstallationError("choose --platform or --no-register for a new installation")
    version = release_version(args.version)
    target = (args.venv or default_venv()).expanduser().absolute()
    existing = existing_installation(target, upgrade=args.upgrade)
    plan = discovered = None
    if args.upgrade:
        try:
            plan, discovered = upgrade_plan(args, target, version, cwd=Path.cwd())
        except InstallationError as exc:
            raise InstallationError(f"Failed during upgrade preflight: {exc}") from exc
        if args.dry_run:
            return plan
    filename = f"flow_of_work_mcp-{version}-py3-none-any.whl"
    release_url = f"{REPOSITORY}/releases/download/v{version}"
    with tempfile.TemporaryDirectory(prefix="flower-release-") as folder:
        scratch = Path(folder)
        sums = scratch / "SHA256SUMS"
        wheel = scratch / filename
        download_asset(release_url + "/SHA256SUMS", sums, max_bytes=1024 * 1024)
        expected = checksum_for(sums.read_text(encoding="utf-8"), filename)
        actual = download_asset(release_url + "/" + filename, wheel, max_bytes=128 * 1024 * 1024)
        if not hmac.compare_digest(expected, actual):
            raise InstallationError("wheel SHA-256 differs from the pinned release manifest")
        created = False
        registration_started = False
        lease = None
        backup = None
        stage = "environment creation"
        try:
            if not existing:
                target.mkdir(parents=True, exist_ok=False)
                created = True
                venv.EnvBuilder(with_pip=True).create(target)
            python = interpreter_in(target)
            if args.upgrade:
                stage = "upgrade backup and ownership"
                selection = {**_selection(args), "expected": discovered,
                             "backup_root": plan["backup_root"], "requested_version": version}
                lease = UpgradeLease(python, selection, cwd=scratch)
                backup = {key: value for key, value in lease.receipt.items() if key != "status"}
                lease.assert_active()
            stage = "package installation"
            pip = [str(python), "-I", "-m", "pip", "--isolated", "install", "--no-input",
                   "--disable-pip-version-check", "--no-user"]
            if existing:
                pip.append("--upgrade")
            run([*pip, str(wheel)], cwd=scratch, timeout=600)
            if lease is not None:
                lease.assert_active()
            run([str(python), "-I", "-m", "pip", "--isolated", "check"], cwd=scratch)
            if lease is not None:
                lease.assert_active()
            stage = "installed package identity"
            identity = run([str(python), "-I", "-c",
                            "from importlib.metadata import version; print(version('flow-of-work-mcp'))"],
                           cwd=scratch, capture_output=True)
            if lease is not None:
                lease.assert_active()
            if identity.stdout.strip() != version:
                raise InstallationError("installed package version differs from the requested release")
            record = {"contract": OWNER_CONTRACT, "repository": REPOSITORY,
                      "version": version, "wheel": filename, "sha256": actual}
            if not args.upgrade:
                write_receipt(target, record)
            command = str(command_in(target))
            options = ["--profile", args.profile]
            if args.profile_root is not None:
                options.extend(["--profile-root", str(args.profile_root.expanduser().absolute())])
            if args.platform is not None:
                options.extend(["--platform", args.platform])
            if args.client_config is not None:
                options.extend(["--client-config", str(args.client_config.expanduser().absolute())])
            if not args.no_register:
                stage = "client registration preflight"
                run([command, "install", *options, "--dry-run"], cwd=scratch)
                stage = "client registration"
                registration_started = True
                run([command, "install", *options], cwd=scratch)
            stage = "installation diagnosis"
            if args.upgrade:
                lease.assert_active()
                # Pin the discovered canonical root, including FLOWER_HOME,
                # rather than resolving an implicit selection a second time.
                options = ["--profile", args.profile, "--profile-root", discovered["profile_root"]]
            run([command, "doctor", *options], cwd=scratch)
            if args.upgrade:
                lease.assert_active()
                stage = "installation receipt"
                write_receipt(target, record)
        except BaseException as exc:
            retained = existing or registration_started
            if created and not registration_started:
                shutil.rmtree(target)
            if isinstance(exc, KeyboardInterrupt):
                raise
            detail = f" Installation environment retained at {target}." if retained else " The new installation environment was removed."
            if args.upgrade:
                detail += " Original lifecycle data retained; no automatic restore was performed."
                if backup is not None:
                    detail += f" Backup retained at {backup['backup_directory']}."
                if stage in {"package installation", "installed package identity", "installation diagnosis", "installation receipt"}:
                    detail += " pip may have partly changed the environment; package rollback is not automatic."
                if isinstance(exc, InstallationError):
                    detail += f" {exc}"
            raise InstallationError(f"Failed during {stage}.{detail}") from exc
        finally:
            if lease is not None:
                lease.close()
    if args.upgrade:
        return {**record, "contract": "flower.release-upgrade-result.v1",
                "installation_contract": OWNER_CONTRACT, "previous_version": plan["previous_version"],
                "requested_version": version, "environment": str(target), "command": command,
                "profile": args.profile, "profile_root": discovered["profile_root"],
                "profile_config": discovered["profile_config"], "database_path": discovered["database_path"],
                "backup": backup, "registration_changed": False, "data_preserved": True,
                "preservation": plan["preservation"], "required_actions": plan["required_actions"],
                "next_step": plan["required_actions"][-1]}
    next_step = "In your project, have your agent run bootstrap_command and use its output to update AGENTS.md."
    if args.no_register:
        next_step = "Flower is installed without client registration. " + next_step
    return {**record, "environment": str(target), "command": command,
            "registered_platform": args.platform, "profile": args.profile,
            "bootstrap_command": [command, "bootstrap"], "next_step": next_step}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=release_version, default=DEFAULT_VERSION)
    parser.add_argument("--venv", type=Path, help="dedicated installation environment; defaults to the host user data directory")
    parser.add_argument("--upgrade", action="store_true", help="upgrade an existing owned environment without registering a client; first stop all Flower processes using it")
    parser.add_argument("--dry-run", action="store_true", help="upgrade only: inspect the existing installation and print its plan without downloads, locks or writes")
    parser.add_argument("--backup-root", type=Path, help="upgrade only: private backup parent outside the environment and selected profile data")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--platform", choices=("codex", "claude-code", "cursor", "antigravity", "gemini-cli"), help="install and register this coding client")
    choice.add_argument("--no-register", action="store_true", help="install and diagnose without changing client registration or profiles")
    parser.add_argument("--client-config", type=Path, help="explicit client configuration file")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--profile-root", type=Path, help="persistent Flower lifecycle data location, separate from the installation environment")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.upgrade:
        if args.platform is not None or args.client_config is not None:
            parser.error("--upgrade cannot be combined with client registration; use the separate flower-mcp install command")
        args.no_register = True
    elif args.dry_run or args.backup_root is not None:
        parser.error("--dry-run and --backup-root require --upgrade")
    elif args.platform is None and not args.no_register:
        parser.error("choose --platform or --no-register for a new installation")
    if args.no_register and args.client_config is not None:
        parser.error("--client-config requires --platform")
    try:
        result = installation(args)
    except (InstallationError, OSError, ValueError, argparse.ArgumentTypeError) as exc:
        print(f"Flower installation failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Flower installation interrupted.", file=sys.stderr)
        return 130
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
