#!/usr/bin/env python3
"""Qualify a published 0.3.1 installation upgrade using isolated public MCP state.

Only release downloads are replaced with checksum-verified local asset copies.
Environment creation, pip, registration, OS ownership, backup and diagnosis are
real. This is package mechanics qualification, not anonymous release delivery.
The requested root must not exist; all generated state is retained there.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request

BASELINE_VERSION = "0.3.1"
BASELINE_WHEEL_SHA256 = "f665570e15f45f57629082faa9547b536fb44db7b61cd042bf2c46629852458c"
BASELINE_INSTALLER_SHA256 = "a0625e31e6f40ae19ad940e3765d037f97a2213fc02fcabcfc8cef901da57889"
REPOSITORY = "https://github.com/Damel91/flower-mcp"
PROJECT = "flower-upgrade-smoke"
PROFILE = "upgrade-smoke"

# Independent qualification oracle for the additive IMPL-63 persistence contract.
# Do not obtain this from the implementation being tested or accept arbitrary DDL.
ADDITIVE_SCHEMA_SQL = '''
CREATE TABLE architecture_revisions (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    base_revision INTEGER NOT NULL CHECK(base_revision >= 0),
    definition_json TEXT NOT NULL, definition_fingerprint TEXT NOT NULL,
    actor TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(project_id, revision));
CREATE TABLE architecture_adoptions (
    adoption_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
    revision INTEGER NOT NULL, previous_revision INTEGER NOT NULL CHECK(previous_revision >= 0),
    rationale TEXT NOT NULL, actor TEXT NOT NULL, adopted_at TEXT NOT NULL,
    UNIQUE(project_id, revision), FOREIGN KEY(project_id, revision)
        REFERENCES architecture_revisions(project_id, revision) ON DELETE RESTRICT);
CREATE TABLE architecture_requests (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
    request_id TEXT NOT NULL, operation TEXT NOT NULL, request_fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, request_id));
CREATE TABLE packet_executor_selections (
    project_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
    selection_revision INTEGER NOT NULL CHECK(selection_revision=1),
    executor TEXT NOT NULL CHECK(executor IN ('external_agent','provider')),
    provider_kind TEXT NOT NULL, spec_revision INTEGER NOT NULL, plan_revision INTEGER NOT NULL,
    authority_fingerprint TEXT NOT NULL, actor TEXT NOT NULL, selected_at TEXT NOT NULL,
    PRIMARY KEY(project_id,change_id,packet_id), FOREIGN KEY(project_id,change_id,packet_id)
        REFERENCES implementation_packets(project_id,change_id,packet_id));
CREATE TABLE packet_provider_capabilities (
    capability_identity INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
    provider_kind TEXT NOT NULL, binding_identity_json TEXT NOT NULL,
    flow_binding_generation INTEGER NOT NULL CHECK(flow_binding_generation>=0),
    selection_revision INTEGER NOT NULL CHECK(selection_revision=1),
    selection_fingerprint TEXT NOT NULL, spec_revision INTEGER NOT NULL,
    plan_revision INTEGER NOT NULL, authority_fingerprint TEXT NOT NULL,
    supported INTEGER NOT NULL CHECK(supported IN (0,1)), reason TEXT NOT NULL,
    capability_json TEXT NOT NULL, actor TEXT NOT NULL, observed_at TEXT NOT NULL,
    FOREIGN KEY(project_id,change_id,packet_id)
        REFERENCES implementation_packets(project_id,change_id,packet_id));
CREATE TABLE packet_executor_requests (
    project_id TEXT NOT NULL, request_id TEXT NOT NULL, request_fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL, actor TEXT NOT NULL, operation TEXT NOT NULL,
    occurred_at TEXT NOT NULL, PRIMARY KEY(project_id,request_id));
CREATE TABLE packet_provider_admissions (
    project_id TEXT NOT NULL, outbox_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
    capability_identity INTEGER NOT NULL, binding_identity_json TEXT NOT NULL,
    context_sha256 TEXT NOT NULL, unit_key TEXT NOT NULL, actor TEXT NOT NULL, admitted_at TEXT NOT NULL,
    PRIMARY KEY(project_id,outbox_id),
    FOREIGN KEY(project_id,outbox_id) REFERENCES packet_provider_outbox(project_id,outbox_id),
    FOREIGN KEY(capability_identity) REFERENCES packet_provider_capabilities(capability_identity),
    FOREIGN KEY(project_id,change_id,packet_id) REFERENCES implementation_packets(project_id,change_id,packet_id));
CREATE INDEX packet_provider_admissions_context
    ON packet_provider_admissions(project_id,change_id,packet_id,unit_key,context_sha256);
'''
NEW_TABLES = frozenset({"architecture_revisions", "architecture_adoptions", "architecture_requests",
    "packet_executor_selections", "packet_provider_capabilities", "packet_executor_requests",
    "packet_provider_admissions"})
ARCHITECTURE_TABLES = ("implementation_packets", "implementation_packet_revisions")
ARCHITECTURE_COLUMN = "architecture_refs_json TEXT NOT NULL DEFAULT '[]'"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "Expected a JSON object: " + str(path))
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_backend(path: Path):
    require(path.is_file() and not path.is_symlink(), "Installer must be a regular file")
    specification = importlib.util.spec_from_file_location("flower_upgrade_installer", path)
    module = importlib.util.module_from_spec(specification)
    bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = bytecode
    return module


def local_assets(backend, assets: Path) -> None:
    """Replace exactly the network boundary; validate every requested copy."""
    manifest = assets / "SHA256SUMS"
    require(manifest.is_file() and not manifest.is_symlink(), "Missing regular release manifest")

    def download(url: str, destination: Path, *, max_bytes: int) -> str:
        backend.require_https(url)
        name = Path(urllib.parse.urlsplit(url).path).name
        require(name in {"SHA256SUMS", f"flow_of_work_mcp-{backend.DEFAULT_VERSION}-py3-none-any.whl"},
                "Unexpected installer download: " + name)
        source = assets / name
        require(source.is_file() and not source.is_symlink(), "Missing regular release asset: " + name)
        require(source.stat().st_size <= max_bytes, "Release asset exceeds installer download limit")
        actual = digest(source)
        if name != "SHA256SUMS":
            require(actual == backend.checksum_for(manifest.read_text(encoding="utf-8"), name),
                    "Local release asset differs from its manifest: " + name)
        with destination.open("xb") as output, source.open("rb") as content:
            shutil.copyfileobj(content, output)
        return actual

    backend.download_asset = download


def baseline_assets(destination: Path, supplied: Path | None) -> Path:
    """Pin the real published baseline, never a development wheel with its name."""
    destination.mkdir()
    names = ("SHA256SUMS", "install_flower.py", f"flow_of_work_mcp-{BASELINE_VERSION}-py3-none-any.whl")
    for name in names:
        target = destination / name
        if supplied is not None:
            source = supplied / name
            require(source.is_file() and not source.is_symlink(), "Missing regular baseline asset: " + name)
            with target.open("xb") as output, source.open("rb") as content:
                shutil.copyfileobj(content, output)
        else:
            request = urllib.request.Request(
                REPOSITORY + "/releases/download/v" + BASELINE_VERSION + "/" + name,
                headers={"User-Agent": "Flower-MCP-Upgrade-Qualification"})
            with urllib.request.urlopen(request, timeout=30) as response:
                require(urllib.parse.urlsplit(response.geturl()).scheme == "https", "Baseline redirected away from HTTPS")
                limit = 128 * 1024 * 1024 if name.endswith(".whl") else 1024 * 1024
                with target.open("xb") as output:
                    total = 0
                    while chunk := response.read(64 * 1024):
                        total += len(chunk)
                        require(total <= limit, "Baseline asset exceeds qualification limit")
                        output.write(chunk)
    wheel = destination / names[-1]
    require(digest(wheel) == BASELINE_WHEEL_SHA256, f"Baseline is not the immutable published {BASELINE_VERSION} wheel")
    require(digest(destination / "install_flower.py") == BASELINE_INSTALLER_SHA256,
            f"Baseline installer differs from the immutable published {BASELINE_VERSION} backend")
    # Verify the executable before importing it, using the pinned release manifest.
    manifest = (destination / "SHA256SUMS").read_text(encoding="utf-8")
    for name in names[1:]:
        entries = [line.split() for line in manifest.splitlines() if line.strip()]
        matches = [parts[0] for parts in entries if len(parts) == 2 and parts[1].lstrip("*") == name]
        require(matches == [digest(destination / name)], "Baseline manifest mismatch: " + name)
    return destination


def clean_environment() -> dict[str, str]:
    result = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "FLOWER_HOME"):
        result.pop(key, None)
    return result


def run_worker(python: Path, root: Path, phase: str, assets: Path | None = None) -> dict:
    options = [] if assets is None else ["--assets", str(assets)]
    completed = subprocess.run(
        [str(python), "-I", str(Path(__file__).resolve()), "--worker", phase, "--root", str(root), *options],
        cwd=root, env=clean_environment(), text=True, encoding="utf-8", capture_output=True, timeout=180)
    require(completed.returncode == 0, f"Public MCP {phase} failed: {completed.stderr}")
    return read_json(root / f"{phase}-mcp.json")


def state_snapshot(root: Path) -> dict:
    """Detect changes to persistent state, including identical-byte rewrites."""
    result = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "Unexpected symlink in qualification state")
        info = path.stat()
        require(path.is_file() or path.is_dir(), "Unexpected special file in qualification state")
        value = {"mtime_ns": info.st_mtime_ns, "mode": info.st_mode}
        if path.is_file():
            value.update(size=info.st_size, sha256=digest(path))
        result[path.relative_to(root).as_posix()] = value
    return result


def database_state(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), "Expected regular existing SQLite database")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        require(connection.execute("PRAGMA integrity_check").fetchone() == ("ok",), "SQLite integrity check failed")
        return hashlib.sha256("\n".join(connection.iterdump()).encode("utf-8")).hexdigest()


def _sql_tokens(sql: str | None):
    if sql is None:
        return None
    # Ignore SQL formatting, preserving quoted values and identifiers exactly.
    tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|[A-Za-z_][A-Za-z0-9_]*|[0-9]+|\S", sql)
    return tuple(token if token[0] in "'\"`[" else token.lower() for token in tokens if token != ';')


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def database_authority(path: Path) -> dict:
    """Read every old field, row and schema object without opening a runtime."""
    require(path.is_file() and not path.is_symlink(), "Expected regular existing SQLite database")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        require(connection.execute("PRAGMA integrity_check").fetchone() == ("ok",), "SQLite integrity check failed")
        require(connection.execute("PRAGMA foreign_key_check").fetchall() == [], "SQLite foreign key check failed")
        objects = {name: (kind, table, sql) for kind, name, table, sql in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")}
        columns, rows = {}, {}
        for name, (kind, unused, sql) in objects.items():
            if kind != "table":
                continue
            columns[name] = connection.execute("PRAGMA table_info(" + _identifier(name) + ")").fetchall()
            rows[name] = sorted(connection.execute("SELECT * FROM " + _identifier(name)).fetchall(), key=repr)
    return {"objects": objects, "columns": columns, "rows": rows}


def require_additive_migration(path: Path, before: dict) -> dict:
    """Qualify exactly52→55, keeping every historical field and clock intact."""
    require(max(row[0] for row in before["rows"]["schema_migrations"]) == 52,
            "Upgrade fixture must begin with the exact schema52 predecessor")
    require(not NEW_TABLES.intersection(before["columns"]), "Predecessor already contains new authority tables")
    after = database_authority(path)
    expected = dict(before["objects"])
    with closing(sqlite3.connect(":memory:")) as oracle:
        # SQLite inserts new column SQL before existing table constraints. Let
        # the same SQLite engine apply only the independently permitted ALTER.
        for table in ARCHITECTURE_TABLES:
            require(table in before["columns"] and all(column[1] != "architecture_refs_json" for column in before["columns"][table]),
                    "Predecessor packet schema differs from schema52")
            kind, owner, sql = expected[table]
            oracle.execute(sql)
            oracle.execute("ALTER TABLE " + _identifier(table) + " ADD COLUMN " + ARCHITECTURE_COLUMN)
            altered = oracle.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            expected[table] = (kind, owner, altered)
        oracle.executescript(ADDITIVE_SCHEMA_SQL)
        expected.update({name: (kind, owner, sql) for kind, name, owner, sql in oracle.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master") if owner in NEW_TABLES})
    require(set(after["objects"]) == set(expected), "Migration added or removed an unexpected schema object")
    for name, (kind, owner, sql) in expected.items():
        actual_kind, actual_owner, actual_sql = after["objects"][name]
        require((actual_kind, actual_owner, _sql_tokens(actual_sql)) == (kind, owner, _sql_tokens(sql)),
                "Migration changed an unexpected schema definition: " + name)
    for table, original_columns in before["columns"].items():
        actual_columns = after["columns"][table]
        if table in ARCHITECTURE_TABLES:
            addition = (len(original_columns), "architecture_refs_json", "TEXT", 1, "'[]'", 0)
            require(actual_columns == [*original_columns, addition], "Migration changed original packet fields: " + table)
            require(all(row[-1] == "[]" for row in after["rows"][table]), "Migration invented historical architecture references")
            actual_rows = sorted((row[:-1] for row in after["rows"][table]), key=repr)
        else:
            require(actual_columns == original_columns, "Migration changed original columns: " + table)
            actual_rows = after["rows"][table]
        if table != "schema_migrations":
            require(actual_rows == before["rows"][table], "Migration changed original rows or clocks: " + table)
    old_migrations = dict(before["rows"]["schema_migrations"])
    new_migrations = dict(after["rows"]["schema_migrations"])
    require(set(new_migrations) == set(old_migrations) | {53, 54, 55}, "Migration versions differ from exact53..55 contract")
    require(all(new_migrations[key] == value for key, value in old_migrations.items()), "Historical migration timestamps changed")
    require(all(isinstance(new_migrations[key], str) and new_migrations[key] for key in (53, 54, 55)), "New migration timestamp is absent")
    require(all(after["rows"][table] == [] for table in NEW_TABLES), "Migration invented architecture or executor authority")
    return {"status": "passed", "previous_schema": 52, "current_schema": 55,
            "historical_tables_preserved": len(before["columns"]), "new_tables": sorted(NEW_TABLES),
            "added_packet_columns": list(ARCHITECTURE_TABLES), "invented_authority": False}


def historical_requirement(current: dict, project: str) -> dict:
    """Validate the evidence recovery route established in published 0.3.1."""
    value = dict(current)
    recovery = value.pop("evidence_recovery", None)
    require(isinstance(recovery, dict) and set(recovery) == {"description", "next_tool_call"},
            "Current requirement omitted its bounded evidence recovery guidance")
    require(isinstance(recovery["description"], str) and bool(recovery["description"]),
            "Current evidence recovery description is empty")
    require(recovery["next_tool_call"] == {"tool": "fow_traceability", "arguments": {
        "project_id": project, "detail_level": "audit", "offset": 0, "limit": 10}},
        "Current requirement returned a different evidence recovery route")
    require(set(value) == {"requirement", "revisions", "events"}, "Unexpected requirement authority fields")
    return value


def require_public_state_preserved(requirement: dict, handover: dict, traceability: dict, before: dict) -> None:
    """Compare the full 0.3.1 public payloads, including established guidance."""
    historical_requirement(before["requirement"], PROJECT)
    historical_requirement(requirement, PROJECT)
    require(requirement == before["requirement"], "Original requirement changed through upgrade")
    require(handover == before["handover"], "Frozen HAND changed through upgrade")
    require(traceability == before["traceability"], "Original verification evidence changed through upgrade")


async def public_fixture(root: Path, phase: str, assets: Path | None = None) -> dict:
    # Import MCP only in the installed interpreter, never a source checkout.
    # The worker uses -I, which omits the script directory from sys.path.
    # Reach sibling qualification helpers explicitly at this boundary.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from public_inventory import require_tool_inventory
    from smoke_mcp import StdioServerParameters, public_session

    command = Path(sys.prefix) / ("Scripts/flower-mcp.exe" if os.name == "nt" else "bin/flower-mcp")
    parameters = StdioServerParameters(
        command=str(command), args=["serve", "--profile", PROFILE, "--profile-root", str(root / "profiles"),
                                   "--transport", "stdio"], cwd=str(root), env=clean_environment())
    receipts = []
    busy = None

    async def call(session, name, arguments):
        response = await session.call_tool(name, arguments)
        require(not response.isError, f"Public MCP transport rejection: {response}")
        value = response.structuredContent["result"]
        markdown = "\n".join(block.text for block in response.content if block.type == "text")
        require(markdown.startswith("#") and "\n" in markdown, "Missing model-facing multiline Markdown")
        require(value["status"] == "success", f"Public operation rejected: {value}")
        receipts.append({"tool": name, "arguments": arguments, "envelope": value, "markdown": markdown})
        return value["result"]

    async with public_session(parameters, strict=True) as session:
        catalog = await session.list_tools()
        require_tool_inventory(catalog.tools, baseline=phase == "before")
        catalog_values = [tool.model_dump(mode="json") for tool in catalog.tools]
        await call(session, "fow_capabilities", {"view": "summary"})
        if phase == "before":
            address = {"project_id": PROJECT, "actor": "synthetic-upgrade-engineer"}
            contract = await call(session, "fow_capabilities", {
                "view": "operation", "operation_tool": "fow_bootstrap", "operation_name": "start"})
            start = contract["operation_contract"]["example"]
            start.update(**address, project_name="Public upgrade fixture", path="guided_engineering", request_id="upgrade-start")
            await call(session, "fow_bootstrap", start)
            requirement = await call(session, "fow_register_requirement", {**address,
                "title": "Retain the integer successor scenario", "statement": "The API shall return the integer successor.",
                "category": "functional", "rationale": "Synthetic upgrade qualification only.", "request_id": "upgrade-requirement"})
            requirement_id = requirement["requirement_id"]
            await call(session, "fow_record_verification", {**address, "requirement_id": requirement_id,
                "verification_kind": "tested_deterministically", "outcome": "passed", "reference": "synthetic:upgrade-fixture",
                "metadata": {"provenance": "declared_host_fixture", "original_detail": "Keep this exact evidence through upgrade."},
                "request_id": "upgrade-evidence"})
            handover = await call(session, "fow_handover", {**address, "operation": "create_handover", "request_id": "upgrade-handover"})
            identity = {"project_id": PROJECT, "requirement_id": requirement_id, "handover_id": handover["handover"]["handover_id"]}
            (root / "fixture.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
        else:
            identity = read_json(root / "fixture.json")
        requirement = await call(session, "fow_get_requirement", {
            "project_id": PROJECT, "requirement_id": identity["requirement_id"]})
        handover = await call(session, "fow_handover", {
            "project_id": PROJECT, "operation": "get_handover", "handover_id": identity["handover_id"]})
        traceability = await call(session, "fow_traceability", {"project_id": PROJECT, "detail_level": "audit"})
        if phase == "before" and assets is not None:
            # Keep the real MCP foreground process alive while an actual upgrade
            # attempts its ownership gate. No service is stopped by the installer.
            backend = load_backend(assets / "install_flower.py")
            local_assets(backend, assets)
            environment = root / "venv"
            receipt = environment / backend.OWNER_FILE
            owner_before = receipt.read_bytes()
            options = backend.build_parser().parse_args([
                "--upgrade", "--venv", str(environment), "--profile", PROFILE, "--profile-root", str(root / "profiles")])
            try:
                await asyncio.to_thread(backend.installation, options)
            except backend.InstallationError as exc:
                require("ledger_runtime_in_use" in str(exc), "Busy runtime failed for a different reason: " + str(exc))
                busy = {"status": "rejected", "reason": "ledger_runtime_in_use", "message": str(exc)}
            else:
                raise RuntimeError("Upgrade proceeded while the public MCP server owned its ledger")
            require(receipt.read_bytes() == owner_before, "Busy upgrade changed installed ownership")
            require(not (root / "profiles" / "upgrade-backups").exists(), "Busy upgrade created a backup before obtaining ownership")
        if phase != "before":
            before = read_json(root / "before-mcp.json")
            require_public_state_preserved(requirement, handover, traceability, before)
            resumed = await call(session, "fow_handover", {
                "project_id": PROJECT, "operation": "resume_context", "handover_id": identity["handover_id"]})
            comparison = resumed["handover"]["historical_comparison"]
            require(comparison["state"] == "legacy_without_recovery" and comparison["historical_payload_unchanged"] is True,
                    "Legacy HAND recovery did not identify unchanged historical authority")
    return {"status": "passed", "phase": phase, "catalog": catalog_values, "receipts": receipts,
            "requirement": requirement, "handover": handover, "traceability": traceability, "busy_upgrade": busy}


def qualify(args) -> dict:
    root = args.root.expanduser().absolute()
    require(not root.exists() and not root.is_symlink(), "Qualification requires an absent isolated root")
    if args.output is not None:
        require(not args.output.exists() and not args.output.is_symlink(), "Qualification output must not replace an existing file")
    assets = args.assets.resolve()
    backend = load_backend(assets / "install_flower.py")
    require(tuple(map(int, backend.DEFAULT_VERSION.split("."))) > tuple(map(int, BASELINE_VERSION.split("."))),
            f"Current assets must be newer than published {BASELINE_VERSION}")
    root.mkdir(parents=True, exist_ok=False)
    result = {"status": "running", "scope": "Real published-baseline package mechanics; local verified current assets, not anonymous delivery",
              "baseline_version": BASELINE_VERSION, "version": backend.DEFAULT_VERSION, "root": str(root)}
    try:
        baseline = baseline_assets(root / "baseline-assets", args.baseline_assets)
        old_backend = load_backend(baseline / "install_flower.py")
        local_assets(old_backend, baseline)
        environment = root / "venv"
        profiles = root / "profiles"
        client = root / "gemini-settings.json"
        client.write_text('{"mcpServers": {}, "ui": {"theme": "synthetic-upgrade"}}\n', encoding="utf-8")
        common = ["--venv", str(environment), "--profile", PROFILE, "--profile-root", str(profiles)]
        original = old_backend.installation(old_backend.build_parser().parse_args([
            *common, "--platform", "gemini-cli", "--client-config", str(client)]))
        python = old_backend.interpreter_in(environment)
        result["baseline_installation"] = original
        result["before"] = run_worker(python, root, "before", assets)
        profile = profiles / "profiles" / PROFILE
        config = profile / "flower.yaml"
        database = profile / "ledger.sqlite3"
        original_database = database_state(database)
        original_authority = database_authority(database)
        original_profile = state_snapshot(profiles)
        original_config = config.read_bytes()
        original_client = client.read_bytes()
        local_assets(backend, assets)
        # A dry run must not download, write, create locks, or refresh ownership.
        def unexpected_download(*unused, **keywords):
            raise RuntimeError("Upgrade dry run attempted a download")
        download = backend.download_asset
        backend.download_asset = unexpected_download
        receipt = environment / backend.OWNER_FILE
        owner_bytes = receipt.read_bytes()
        plan = backend.installation(backend.build_parser().parse_args([*common, "--upgrade", "--dry-run"]))
        require(state_snapshot(profiles) == original_profile and receipt.read_bytes() == owner_bytes,
                "Upgrade dry run changed persistent state or ownership receipt")
        require(client.read_bytes() == original_client, "Upgrade dry run changed coding-client registration")
        backend.download_asset = download
        result["dry_run"] = plan
        updated = backend.installation(backend.build_parser().parse_args([*common, "--upgrade"]))
        require(database_state(database) == original_database, "Upgrade changed the original SQLite authority")
        require(config.read_bytes() == original_config, "Upgrade changed profile YAML")
        require(client.read_bytes() == original_client, "Upgrade changed coding-client registration")
        after_profile = state_snapshot(profiles)
        require(all(key in after_profile for key in original_profile), "Upgrade removed original profile paths")
        require(all(after_profile[key] == value for key, value in original_profile.items()
                    if not key.endswith(".runtime.lock") and not key.endswith("/ledger.sqlite3")),
                "Upgrade rewrote original persistent profile files")
        backups = list(profiles.rglob("*.sqlite3"))
        backup_databases = [path for path in backups if path != database]
        require(len(backup_databases) == 1, "Upgrade did not produce exactly one consistent SQLite backup")
        require(database_state(backup_databases[0]) == original_database, "Backup differs from the original SQLite authority")
        backup_yamls = [path for path in profiles.rglob("*.yaml") if path != config]
        require(len(backup_yamls) == 1 and backup_yamls[0].read_bytes() == config.read_bytes(), "Backup does not retain exact profile YAML")
        require(read_json(receipt)["version"] == backend.DEFAULT_VERSION, "Upgrade did not update owned installation version")
        result["upgrade"] = updated
        result["preservation"] = {"sqlite_logical_sha256": original_database, "database": str(database),
                                  "backup": str(backup_databases[0]), "client_sha256": digest(client), "profile_sha256": digest(config)}
        result["after"] = run_worker(python, root, "after")
        result["migration"] = require_additive_migration(database, original_authority)
        migrated_database = database_state(database)
        result["restart"] = run_worker(python, root, "restart")
        require(database_state(database) == migrated_database, "Read-only restart changed migrated ledger authority")
        require_additive_migration(database, original_authority)
        result["status"] = "passed"
    except BaseException as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        (root / "upgrade-smoke.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if args.output:
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, help="current build_release.py output directory")
    parser.add_argument("--baseline-assets", type=Path, help=f"optional actual published {BASELINE_VERSION} assets; otherwise download anonymously")
    parser.add_argument("--root", type=Path, required=True, help="absent isolated work directory, retained after qualification")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=("before", "after", "restart"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        result = asyncio.run(asyncio.wait_for(public_fixture(args.root, args.worker, args.assets), timeout=120))
        (args.root / f"{args.worker}-mcp.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    else:
        if args.assets is None:
            parser.error("--assets is required")
        result = qualify(args)
    print(json.dumps({key: value for key, value in result.items() if key in {"status", "scope", "baseline_version", "version", "root", "phase"}}))


if __name__ == "__main__":
    main()
