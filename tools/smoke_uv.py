"""Qualify a fresh uv core project and its environment-aware public MCP command."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys


def copy_source(source: Path, destination: Path) -> dict[str, str]:
    """Copy only package build inputs; never copy an existing environment/state."""
    inputs = [source / name for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE")]
    package = source / "src/flow_of_work_mcp"
    if not package.is_dir() or package.is_symlink():
        raise ValueError("source must contain a regular Flower package directory")
    inputs.extend(package.rglob("*"))
    manifest = {}
    for path in sorted(inputs):
        if path.is_symlink():
            raise ValueError("source build inputs must not be symlinks")
        if path.is_dir() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"} or path.name == ".DS_Store":
            continue
        if not path.is_file():
            raise ValueError("source build inputs must be regular files")
        if path.is_relative_to(package) and path.suffix not in {".py", ".yaml", ".md"}:
            raise ValueError("unapproved package input; only Python/YAML/Markdown are selected")
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        manifest[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    return manifest


def core_environment(parent: dict[str, str], root: Path, python: str) -> dict[str, str]:
    environment = {key: value for key, value in parent.items()
                   if not key.startswith("UV_")
                   and key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "FLOWER_HOME"}}
    environment.update(UV_PYTHON=python, UV_PYTHON_DOWNLOADS="never",
                       UV_CACHE_DIR=str(root / "cache"), UV_NO_CONFIG="1",
                       UV_PROJECT=str(root / "project"), UV_WORKING_DIR=str(root / "project"),
                       UV_PROJECT_ENVIRONMENT=str(root / "project/.venv"),
                       FLOWER_HOME=str(root / "state"))
    return environment


def server_arguments(profile_root: Path) -> list[str]:
    return ["run", "--no-sync", "flower-mcp", "serve", "--profile", "uv-smoke",
            "--profile-root", str(profile_root), "--transport", "stdio"]


def ledger_snapshot(state: Path) -> dict:
    databases = list(state.rglob("ledger.sqlite3"))
    if len(databases) != 1:
        raise ValueError("expected exactly one owned synthetic ledger")
    result = {}
    with sqlite3.connect(databases[0].as_uri() + "?mode=ro", uri=True) as connection:
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for name in sorted(names):
            quoted = '"' + name.replace('"', '""') + '"'
            rows = sorted(connection.execute("SELECT * FROM " + quoted).fetchall(), key=repr)
            result[name] = {"rows": len(rows), "sha256": hashlib.sha256(repr(rows).encode()).hexdigest()}
    return result


async def client(uv: Path, project: Path, root: Path) -> dict:
    # These are real public MCP clients, imported only in the uv-created environment.
    from mcp import StdioServerParameters
    from smoke_mcp import public_session, qualify_sessions

    snapshots = []
    yaml_hashes = []
    environment = core_environment(dict(os.environ), root, sys.executable)
    parameters = StdioServerParameters(command=str(uv), args=server_arguments(root / "state"),
                                       cwd=str(project), env=environment)

    @asynccontextmanager
    async def session():
        async with public_session(parameters, strict=True) as value:
            yield value
        snapshots.append(ledger_snapshot(root / "state"))
        profiles = list((root / "state").rglob("flower.yaml"))
        if len(profiles) != 1:
            raise ValueError("expected exactly one owned profile YAML")
        yaml_hashes.append({str(p.relative_to(root / "state")): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in profiles})

    result = await asyncio.wait_for(qualify_sessions(session), timeout=120)
    if len(snapshots) != 2 or snapshots[0] != snapshots[1] or yaml_hashes[0] != yaml_hashes[1]:
        raise RuntimeError("uv restart changed synthetic ledger/profile authority")
    result.update(uv_stdio_command=[str(uv), *parameters.args],
                  all_table_restart_purity=True, table_count=len(snapshots[0]),
                  profile_yaml_unchanged=True, profile_snapshots=yaml_hashes, ledger_snapshots=snapshots)
    return result


def qualify(source: Path, root: Path, uv: Path, python: str, revision: str) -> dict:
    if root.exists():
        raise ValueError("qualification root must be fresh; existing state is never overwritten")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("source revision must be a complete commit SHA")
    root.mkdir(parents=True)
    project = root / "project"
    manifest = copy_source(source, project)
    environment = core_environment(dict(os.environ), root, python)
    commands = []

    def run(name, arguments):
        command = [str(item) for item in arguments]
        commands.append({"name": name, "argv": command, "cwd": str(project)})
        (root / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        completed = subprocess.run(command, cwd=project, env=environment, capture_output=True,
                                   text=True, timeout=240)
        (root / (name + ".stdout")).write_text(completed.stdout)
        (root / (name + ".stderr")).write_text(completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"{name} failed with exit {completed.returncode}; retained stdout/stderr")
        return completed.stdout

    (root / "source-manifest.json").write_text(json.dumps({"declared_source_revision": revision,
                                                          "sha256": manifest}, indent=2) + "\n")
    version = run("uv-version", [uv, "--version"]).strip()
    run("uv-sync-original", [uv, "sync"])
    run("uv-sync-core", [uv, "sync", "--no-dev", "--no-editable"])
    executable = project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    identity = json.loads(run("installed-identity", [executable, "-I", "-c", """
import json,sys
from pathlib import Path
from importlib.util import find_spec
from importlib.metadata import version
import flow_of_work_mcp
assert Path(flow_of_work_mcp.__file__).is_relative_to(Path(sys.prefix))
assert find_spec('runtime_llama') is None and find_spec('lmstudio_agent_runtime') is None
print(json.dumps({'prefix':sys.prefix,'module':flow_of_work_mcp.__file__,
                  'version':version('flow-of-work-mcp'),'inference_installed':False}))
"""]))
    output = root / "public-mcp.json"
    run("public-stdio", [executable, Path(__file__).resolve(), "--client-only", "--uv", uv,
                          "--source", project, "--root", root, "--output", output])
    public = json.loads(output.read_text())
    return {"status": "passed", "declared_source_revision": revision, "uv_version": version,
            "installed": identity, "public": public,
            "scope": "Owned uv core resolver/stdio/restart mechanics; Glama proxy/hosting and human acceptance separate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--uv", required=True, type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--source-revision")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--client-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.client_only:
        result = asyncio.run(client(args.uv.absolute(), args.source.absolute(), args.root.absolute()))
    else:
        result = qualify(args.source.absolute(), args.root.absolute(), args.uv.absolute(),
                         args.python, args.source_revision or "")
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"public", "receipts", "ledger_snapshots"}}))


if __name__ == "__main__":
    main()
