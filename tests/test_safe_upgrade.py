"""Upgrade preservation with an isolated synthetic installation and real OS leases.

Published old/new package and public MCP qualification is performed separately
by tools/smoke_upgrade.py. No fixture adopts an operator's actual environment.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import venv

import pytest
import yaml


SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("flower_safe_upgrade", SOURCE / "tools/install_flower.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
ownership_spec = importlib.util.spec_from_file_location(
    "flower_upgrade_test_ownership", SOURCE / "src/flow_of_work_mcp/runtime_ownership.py")
ownership = importlib.util.module_from_spec(ownership_spec)
ownership_spec.loader.exec_module(ownership)


@pytest.fixture
def installation(tmp_path):
    root = tmp_path.resolve()
    target = root / "environment with spaces"
    venv.EnvBuilder(with_pip=False, system_site_packages=True).create(target)
    python = installer.interpreter_in(target)
    site = subprocess.run([str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                          check=True, capture_output=True, text=True).stdout.strip()
    package = Path(site) / "flow_of_work_mcp"
    for relative in ("config.py", "profiles.py", "runtime_ownership.py", "core/domain/provider_surfaces.py", "resources/standalone.yaml"):
        destination = package / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / "src/flow_of_work_mcp" / relative, destination)
    # Only canonical configuration/profile/lease services are exercised here.
    # The published complete package is used by the separate public qualifier.
    for directory in (package, package / "core", package / "core/domain"):
        (directory / "__init__.py").write_text("")
    shutil.copytree(Path(yaml.__file__).parent, Path(site) / "yaml", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    metadata = Path(site) / "flow_of_work_mcp-0.3.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.4\nName: flow-of-work-mcp\nVersion: 0.3.0\n")
    record = {"contract": installer.OWNER_CONTRACT, "repository": installer.REPOSITORY,
              "version": "0.3.0", "wheel": "flow_of_work_mcp-0.3.0-py3-none-any.whl", "sha256": "a" * 64}
    installer.write_receipt(target, record)
    profile_root = root / "persistent state"
    profile = profile_root / "profiles/default/flower.yaml"
    profile.parent.mkdir(parents=True)
    database = profile.parent / "ledger.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE retained (identity TEXT, evidence TEXT)")
        connection.execute("INSERT INTO retained VALUES (?, ?)", ("project-one", "Original evidence\nSecond line: è"))
    payload = yaml.safe_load((SOURCE / "src/flow_of_work_mcp/resources/standalone.yaml").read_text())
    payload["runtime"].update(database_path=str(database), import_root=str(profile.parent / "imports"))
    payload["logging"]["logs_path"] = str(profile.parent / "logs")
    profile.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    client = root / "client settings.json"
    client.write_text('{"mcpServers":{"flower":{"command":"retained"}},"other":42}\n')
    args = installer.build_parser().parse_args([
        "--upgrade", "--version", "0.3.1", "--venv", str(target), "--profile-root", str(profile_root)])
    return args, target, profile, database, client


def state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


def plan(fixture, *, dry_run=True):
    args, *_ = fixture
    args.dry_run = dry_run
    return installer.installation(args)


def test_dry_run_discovers_exact_existing_data_without_any_write_or_download(installation, monkeypatch):
    args, target, profile, database, client = installation
    before = state(target.parent)
    monkeypatch.setattr(installer, "download_asset", lambda *a, **k: pytest.fail("dry-run downloaded an asset"))
    result = plan(installation)
    assert result["contract"] == "flower.release-upgrade-plan.v1"
    assert result["previous_version"] == "0.3.0" and result["requested_version"] == "0.3.1"
    assert result["profile_config"] == str(profile) and result["database_path"] == str(database)
    assert result["registration_changed"] is False and args.no_register
    assert result["backup_root"] == str(profile.parents[2] / "upgrade-backups")
    assert state(target.parent) == before
    assert not database.with_name(database.name + ".runtime.lock").exists()


@pytest.mark.parametrize("arguments", [
    ["--upgrade", "--platform", "codex"], ["--upgrade", "--client-config", "client.json"],
    ["--dry-run", "--no-register"], ["--backup-root", "backups", "--no-register"], [],
])
def test_invalid_selection_never_reaches_download_or_install(arguments, monkeypatch, capsys):
    monkeypatch.setattr(installer, "installation", lambda _: pytest.fail("invalid selection reached installation"))
    with pytest.raises(SystemExit) as caught:
        installer.main(arguments)
    assert caught.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_missing_owned_environment_is_not_silently_created(tmp_path):
    target = tmp_path / "absent"
    args = installer.build_parser().parse_args(["--upgrade", "--venv", str(target), "--dry-run"])
    with pytest.raises(installer.InstallationError, match="existing owned"):
        installer.installation(args)
    assert not target.exists()


@pytest.mark.parametrize("invalid", ["foreign", "malformed", "divergent-version", "downgrade", "missing-profile", "missing-ledger"])
def test_upgrade_preflight_refuses_ambiguous_state_without_modifying_it(installation, invalid):
    args, target, profile, database, _ = installation
    if invalid == "foreign":
        (target / installer.OWNER_FILE).unlink()
    elif invalid == "malformed":
        (target / installer.OWNER_FILE).write_text("{broken")
    elif invalid == "divergent-version":
        record = json.loads((target / installer.OWNER_FILE).read_text())
        record.update(version="0.2.0", wheel="flow_of_work_mcp-0.2.0-py3-none-any.whl")
        installer.write_receipt(target, record)
    elif invalid == "downgrade":
        args.version = "0.2.9"
    elif invalid == "missing-profile":
        profile.unlink()
    else:
        database.unlink()
    before = state(target.parent)
    with pytest.raises(installer.InstallationError):
        plan(installation)
    assert state(target.parent) == before


@pytest.mark.parametrize("location", ["environment", "profile", "imports", "logs", "profile-root", "database"])
def test_unsafe_backup_location_is_refused_before_writes(installation, location):
    args, target, profile, database, _ = installation
    args.backup_root = {"environment": target / "backups", "profile": profile.parent / "backups",
                        "imports": profile.parent / "imports/backups", "logs": profile.parent / "logs/backups",
                        "profile-root": profile.parents[2], "database": database}[location]
    before = state(target.parent)
    with pytest.raises(installer.InstallationError, match="backup root"):
        plan(installation)
    assert state(target.parent) == before


def test_profile_inside_environment_is_refused(installation):
    args, target, profile, _, _ = installation
    nested = target / "persistent state"
    shutil.copytree(profile.parents[2], nested)
    args.profile_root = nested
    with pytest.raises(installer.InstallationError, match="must be separate"):
        plan(installation)


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink fixture; Windows native paths are qualified in CI")
def test_environment_alias_is_refused(installation):
    args, target, *_ = installation
    alias = target.parent / "alias"
    alias.symlink_to(target, target_is_directory=True)
    args.venv = alias
    with pytest.raises(installer.InstallationError, match="symlink"):
        plan(installation)


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink fixture; Windows native paths are qualified in CI")
@pytest.mark.parametrize("field", ["database_path", "import_root", "logs_path"])
def test_raw_yaml_data_alias_is_refused_before_canonicalization(installation, field):
    args, target, profile, database, _ = installation
    outside = target.parent / "outside data"
    outside.mkdir()
    alias = target.parent / "data alias"
    alias.symlink_to(outside, target_is_directory=True)
    payload = yaml.safe_load(profile.read_text())
    if field == "database_path":
        shutil.copyfile(database, outside / "ledger.sqlite3")
        payload["runtime"][field] = str(alias / "ledger.sqlite3")
    else:
        payload["logging" if field == "logs_path" else "runtime"][field] = str(alias)
    profile.write_text(yaml.safe_dump(payload), encoding="utf-8")
    before = state(target.parent)
    with pytest.raises(installer.InstallationError, match="profile inspection failed"):
        plan(installation)
    assert state(target.parent) == before


def test_real_old_interpreter_lease_refuses_busy_ledger_and_releases_after_failure(installation):
    args, target, _, database, _ = installation
    result = plan(installation)
    _, discovered = installer.upgrade_plan(args, target, args.version, cwd=target.parent)
    selection = {**installer._selection(args), "expected": discovered,
                 "backup_root": result["backup_root"], "requested_version": args.version}
    with ownership.acquire_runtime_ownership(database):
        with pytest.raises(installer.InstallationError, match="ledger_runtime_in_use"):
            installer.UpgradeLease(installer.interpreter_in(target), selection, cwd=target.parent)
    assert not Path(result["backup_root"]).exists()
    lease = installer.UpgradeLease(installer.interpreter_in(target), selection, cwd=target.parent)
    try:
        with pytest.raises(ownership.RuntimeOwnershipError, match="already owns"):
            ownership.acquire_runtime_ownership(database)
        with sqlite3.connect(lease.receipt["database_backup"]) as connection:
            assert connection.execute("SELECT * FROM retained").fetchall() == [("project-one", "Original evidence\nSecond line: è")]
    finally:
        lease.close()
    with ownership.acquire_runtime_ownership(database):
        pass


@pytest.mark.parametrize("program, reason", [
    ("raise SystemExit(7)", "without a valid backup result"),
    ("import time; time.sleep(30)", "timed out preparing"),
])
def test_ownership_child_exit_and_timeout_are_bounded_and_reaped(tmp_path, monkeypatch, program, reason):
    processes = []
    original_popen = installer.subprocess.Popen
    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(installer.subprocess, "Popen", popen)
    monkeypatch.setattr(installer, "BACKUP_PROGRAM", program)
    monkeypatch.setattr(installer, "UPGRADE_READY_TIMEOUT", 0.2)
    monkeypatch.setattr(installer, "UPGRADE_RELEASE_TIMEOUT", 0.2)
    monkeypatch.setattr(installer, "UPGRADE_STOP_TIMEOUT", 1)
    with pytest.raises(installer.InstallationError, match=reason):
        installer.UpgradeLease(Path(sys.executable), {}, cwd=tmp_path)
    assert len(processes) == 1 and processes[0].poll() is not None
    assert all(stream.closed for stream in (processes[0].stdin, processes[0].stdout, processes[0].stderr))


@pytest.mark.parametrize("failure", [False, True])
def test_backup_precedes_package_mutation_and_data_survives_success_or_failure(installation, monkeypatch, failure):
    args, target, profile, database, client = installation
    before = {path: path.read_bytes() for path in (profile, database, client)}
    original_run = installer.run
    calls = []
    def download(url, destination, *, max_bytes):
        payload = b"synthetic wheel for isolated package-command fixture"
        if url.endswith("SHA256SUMS"):
            payload = f"{hashlib.sha256(payload).hexdigest()}  flow_of_work_mcp-0.3.1-py3-none-any.whl\n".encode()
        destination.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()
    def run(command, **kwargs):
        if DISCOVERY_MARKER in command:
            return original_run(command, **kwargs)
        calls.append(command)
        if "install" in command:
            with pytest.raises(ownership.RuntimeOwnershipError, match="already owns"):
                ownership.acquire_runtime_ownership(database)
            backups = list((profile.parents[2] / "upgrade-backups").glob("flower-upgrade-*"))
            assert len(backups) == 1
            assert (backups[0] / "flower.yaml").read_bytes() == before[profile]
            if failure:
                raise subprocess.CalledProcessError(7, command)
        return subprocess.CompletedProcess(command, 0, stdout="0.3.1\n" if "-c" in command else "")
    monkeypatch.setattr(installer, "download_asset", download)
    monkeypatch.setattr(installer, "run", run)
    args.dry_run = False
    if failure:
        with pytest.raises(installer.InstallationError, match="package installation.*Backup retained.*partly changed"):
            installer.installation(args)
    else:
        result = installer.installation(args)
        assert result["contract"] == "flower.release-upgrade-result.v1"
        assert result["data_preserved"] and not result["registration_changed"]
        assert result["backup"]["contract"] == "flower.release-upgrade-backup.v1"
    assert all(path.read_bytes() == value for path, value in before.items())
    assert not any("install" in command and "--platform" in command for command in calls)
    with ownership.acquire_runtime_ownership(database):
        pass
    record = json.loads((target / installer.OWNER_FILE).read_text())
    assert record["version"] == ("0.3.0" if failure else "0.3.1")


DISCOVERY_MARKER = installer.DISCOVERY_PROGRAM


@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="Bash frontend requires POSIX")
def test_bash_upgrade_skips_agent_menu_and_forwards_literal_plan_options(tmp_path, monkeypatch):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    backend = tmp_path / "install_flower.py"
    backend.write_bytes(b"# verified synthetic forwarding fixture\n")
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(hashlib.sha256(backend.read_bytes()).hexdigest() + "  install_flower.py\n")
    capture = tmp_path / "arguments.txt"
    scripts = {
        "curl": '''#!/bin/sh
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) output="$2"; shift 2 ;;
        https://*) url="$1"; shift ;;
        *) shift ;;
    esac
done
case "$url" in
    */SHA256SUMS) cp "$FLOWER_TEST_MANIFEST" "$output" ;;
    */install_flower.py) cp "$FLOWER_TEST_BACKEND" "$output" ;;
    *) exit 97 ;;
esac
''',
        "python3": '''#!/bin/sh
if [ "$2" = "-c" ]; then exit 0; fi
printf '%s\\n' "$@" > "$FLOWER_TEST_CAPTURE"
''',
    }
    for name, content in scripts.items():
        path = binaries / name
        path.write_text(content)
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FLOWER_TEST_MANIFEST", str(manifest))
    monkeypatch.setenv("FLOWER_TEST_BACKEND", str(backend))
    monkeypatch.setenv("FLOWER_TEST_CAPTURE", str(capture))
    backup = tmp_path / 'private backups "$literal"'
    result = subprocess.run(["bash", str(SOURCE / "tools/install.sh"), "--upgrade", "--dry-run",
                             "--backup-root", str(backup)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    arguments = capture.read_text().splitlines()[2:]
    assert arguments == ["--upgrade", "--dry-run", "--backup-root", str(backup), "--no-register", "--version", "0.3.1"]
    assert "Select an agent" not in result.stderr and not backup.exists()


@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="Bash frontend requires POSIX")
@pytest.mark.parametrize("arguments", [
    ["--upgrade", "--platform", "codex"], ["--upgrade", "--client-config", "client.json"],
    ["--dry-run", "--no-register"], ["--backup-root", "backups", "--no-register"],
])
def test_bash_invalid_upgrade_selection_fails_before_download(arguments):
    result = subprocess.run(["bash", str(SOURCE / "tools/install.sh"), *arguments],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
    assert result.returncode == 1 and "Flower installation failed:" in result.stderr
    assert "Select an agent" not in result.stderr
