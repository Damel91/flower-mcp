#!/usr/bin/env python3
"""Download, verify and install a pinned Flower MCP release with Python 3.11+."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import venv


REPOSITORY = "https://github.com/Damel91/flower-mcp"
DEFAULT_VERSION = "0.2.0"
OWNER_FILE = ".flower-release-install.json"
OWNER_CONTRACT = "flower.release-installation.v1"
DOWNLOAD_TIMEOUT = 30


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
        return False
    if not upgrade:
        raise InstallationError("the installation directory already exists; use --upgrade for an existing Flower installation")
    owner = target / OWNER_FILE
    if not target.is_dir() or owner.is_symlink() or not owner.is_file():
        raise InstallationError("--upgrade requires an environment created by this Flower release installer")
    try:
        record = json.loads(owner.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallationError("the existing installation receipt is invalid") from exc
    if (not isinstance(record, dict) or record.get("contract") != OWNER_CONTRACT
            or record.get("repository") != REPOSITORY
            or not (target / "pyvenv.cfg").is_file() or not interpreter_in(target).is_file()):
        raise InstallationError("--upgrade requires an environment created by this Flower release installer")
    return True


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
    version = release_version(args.version)
    target = (args.venv or default_venv()).expanduser().absolute()
    existing = existing_installation(target, upgrade=args.upgrade)
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
        stage = "environment creation"
        try:
            if not existing:
                target.mkdir(parents=True, exist_ok=False)
                created = True
                venv.EnvBuilder(with_pip=True).create(target)
            python = interpreter_in(target)
            stage = "package installation"
            pip = [str(python), "-I", "-m", "pip", "--isolated", "install", "--no-input",
                   "--disable-pip-version-check", "--no-user"]
            if existing:
                pip.append("--upgrade")
            run([*pip, str(wheel)], cwd=scratch, timeout=600)
            run([str(python), "-I", "-m", "pip", "--isolated", "check"], cwd=scratch)
            identity = run([str(python), "-I", "-c",
                            "from importlib.metadata import version; print(version('flow-of-work-mcp'))"],
                           cwd=scratch, capture_output=True)
            if identity.stdout.strip() != version:
                raise InstallationError("installed package version differs from the requested release")
            record = {"contract": OWNER_CONTRACT, "repository": REPOSITORY,
                      "version": version, "wheel": filename, "sha256": actual}
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
            run([command, "doctor", *options], cwd=scratch)
        except BaseException as exc:
            retained = existing or registration_started
            if created and not registration_started:
                shutil.rmtree(target)
            if isinstance(exc, KeyboardInterrupt):
                raise
            detail = f" Installation environment retained at {target}." if retained else " The new installation environment was removed."
            raise InstallationError(f"Failed during {stage}.{detail}") from exc
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
    parser.add_argument("--upgrade", action="store_true", help="upgrade an existing environment created by this installer")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--platform", choices=("codex", "claude-code", "cursor"), help="install and register this coding client")
    choice.add_argument("--no-register", action="store_true", help="install and diagnose without changing client registration or profiles")
    parser.add_argument("--client-config", type=Path, help="explicit client configuration file")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--profile-root", type=Path, help="persistent Flower lifecycle data location, separate from the installation environment")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
