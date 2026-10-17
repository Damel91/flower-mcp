"""Owned deterministic native fixtures; not MCP or host/provider acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest
import yaml

from flow_of_work_mcp.adapters.sqlite import SQLiteRequirementLedger
from flow_of_work_mcp.cli import build_cli_parser
from flow_of_work_mcp import native_project_purge as purge
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership


def _fixture(root: Path, *, rich: bool = False) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    database = root / "ledger.sqlite3"
    ledger = SQLiteRequirementLedger(database)
    config = root / "flower.yaml"
    from importlib.resources import files
    payload = yaml.safe_load(files("flow_of_work_mcp").joinpath("resources/standalone.yaml").read_text())
    payload["runtime"].update(database_path=str(database), import_root=str(root / "imports"))
    payload["logging"]["logs_path"] = str(root / "logs")
    config.write_text(yaml.safe_dump(payload))
    if rich:
        _seed_all_tables(database)
    else:
        ledger.create_project("project-a", "PRIVATE PROJECT A", actor="native-test")
        ledger.create_project("project-b", "PRIVATE PROJECT B", actor="native-test")
    return config, database


def _call(config: Path, operation: str, deletion: str, *, project: str = "project-a", fingerprint: str = "", stopped: tuple[str, ...] = (), ack: bool = False) -> tuple[dict, int]:
    values = ["project-purge", operation, "--config", str(config), "--project-id", project, "--deletion-id", deletion]
    if fingerprint:
        values += ["--expected-fingerprint", fingerprint]
    if operation == "delete":
        values += ["--confirm-project-id", project, "--host-quiescence-ref", "owned-test:workers-stopped"]
    for run in stopped:
        values += ["--host-stopped-run-id", run]
    if ack:
        values += ["--acknowledge-host-cleanup"]
    return purge.run_project_purge(build_cli_parser().parse_args(values))


def _rows(database: Path) -> dict[str, list]:
    with sqlite3.connect(database) as connection:
        return {name: list(connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid'))
                for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}


def _seed_all_tables(database: Path) -> None:
    """Seed every ownership class, including otherwise inaccessible history.

    Synthetic semantic payloads bypass application services, not SQL integrity;
    table/FK/index structure is unchanged and full integrity is proved below.
    This fixture is intentionally separate from the public-MCP campaign.
    """
    with sqlite3.connect(database) as connection:
        names = set(purge.SCHEMA55_TABLE_HASHES) - {"schema_migrations"}
        parent_names = {name: {row[2] for row in connection.execute(f"PRAGMA foreign_key_list({name})") if row[2] != name} for name in names}
        order = []
        while names:
            ready = sorted(name for name in names if not (parent_names[name] & names))
            assert ready
            order.extend(ready)
            names -= set(ready)
        for number, project in enumerate(("project-a", "project-b"), 1):
            data = {}
            for name in order:
                columns = list(connection.execute(f"PRAGMA table_xinfo({name})"))
                row = {}
                integer_primary = [item for item in columns if item[5] and item[2] == "INTEGER"]
                for item in columns:
                    column, kind, not_null = item[1:4]
                    if column == "project_id":
                        value = project
                    elif not not_null and not item[5]:
                        value = None
                    elif kind in {"INTEGER", "REAL"}:
                        value = number if len(integer_primary) == 1 and item[5] else 1
                    elif column.endswith("_json"):
                        value = json.dumps({"synthetic_private": project})
                    else:
                        value = f"{column}-{project}"
                    row[column] = value
                for foreign in connection.execute(f"PRAGMA foreign_key_list({name})"):
                    if foreign[2] != name:
                        row[foreign[3]] = data[foreign[2]][foreign[4]]
                if name == "phase_audits":
                    row["previous_phase_audit_id"] = None
                if "provider_kind" in row:
                    row["provider_kind"] = "fixture"
                if name == "packet_provider_bindings":
                    row.update(provider_state="ready", run_phase="idle")
                if name in {"packet_provider_outbox", "test_provider_outbox"}:
                    row.update(state="pending", attempts=0, operation="add" if name.startswith("packet") else "report")
                if name == "implementation_runs":
                    row.update(external_ref="", orchestrator_ref="", status="blocked", completion_reference="", run_id="RUN-000001")
                if name == "interaction_project_context_events":
                    row["previous_project_id"] = "project-a" if project == "project-b" else ""
                overrides = {
                    "behavioral_oracle_revisions": {"status": "draft"},
                    "behavioral_oracles": {"status": "current"},
                    "campaign_plan_heads": {"qualification": "current"},
                    "oracle_questions": {"question_scope": "source"},
                    "packet_executor_selections": {"executor": "external_agent"},
                    "packet_provider_receipts": {"observation_kind": "status"},
                    "packet_provider_workspace_reviews": {"completeness": "complete", "disposition": "approved"},
                    "packet_reconciliation_scopes": {"applicability": "deferred"},
                    "packet_unit_authoring_intents": {"state": "pending"},
                    "semantic_assignments": {"execution_mode": "internal", "state": "internal_running"},
                    "campaign_attestation_intents": {"materialization_mode": "orchestrator_source",
                        "oracle_ir_contract_version": "", "oracle_ir_operator_profile": "",
                        "oracle_ir_fingerprint": "", "oracle_ir_json": "{}", "requested_capability_json": "{}",
                        "requested_capability_fingerprint": ""},
                }
                row.update(overrides.get(name, {}))
                # The provider kind participates in some composite FKs; keep
                # the referenced synthetic parent identity in agreement.
                for foreign in connection.execute(f"PRAGMA foreign_key_list({name})"):
                    if foreign[2] != name:
                        row[foreign[3]] = data[foreign[2]][foreign[4]]
                values = tuple(row[column[1]] for column in columns)
                connection.execute(f"INSERT INTO {name} ({','.join(item[1] for item in columns)}) VALUES ({','.join('?' for _ in columns)})", values)
                data[name] = row
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_full_schema55_ownership_purge_and_private_journal(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    before = _rows(database)
    config_bytes = config.read_bytes()
    sentinel = tmp_path / "source-and-import-sentinel.txt"
    sentinel.write_text("external source preserved")
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0, prepared
    assert prepared["deletion_state"] == "prepared"
    assert len(prepared["counts"]) == 128
    assert all(count >= 1 for count in prepared["counts"].values())
    journal_path = database.with_name(database.name + ".project-purge") / (deletion + ".json")
    journal = json.loads(journal_path.read_text())
    assert "PRIVATE PROJECT" not in journal_path.read_text()
    assert "synthetic_private" not in journal_path.read_text()
    assert set(journal) == purge._JOURNAL_KEYS
    result, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 0, result
    assert result["deletion_state"] == "scrubbed"
    assert result["project_effect_state"] == "applied"
    assert not result["project_present"] and not any(result["counts"].values())
    after = _rows(database)
    assert after["sqlite_sequence"] == before["sqlite_sequence"]
    assert after["schema_migrations"] == before["schema_migrations"]
    for name in set(purge.SCHEMA55_TABLE_HASHES) - {"schema_migrations"}:
        assert len(after[name]) == (0 if name == "interaction_project_context_events" else 1), name
        if after[name]:
            assert after[name] == [before[name][1]], name
    assert config.read_bytes() == config_bytes
    assert sentinel.read_text() == "external source preserved"
    assert b"project-a" not in database.read_bytes()
    ack, code = _call(config, "reconcile", deletion, ack=True)
    assert code == 0 and ack["deletion_state"] == "acknowledged"
    assert not journal_path.exists()
    repeated, code = _call(config, "reconcile", deletion, ack=True)
    assert code == 0 and repeated["deletion_state"] == "absent"
    assert repeated["project_effect_state"] == "unknown"


def test_source_stdout_exact_json_and_exit_codes(tmp_path):
    config, _ = _fixture(tmp_path)
    environment = dict(os.environ, PYTHONPATH=str(Path(purge.__file__).parents[1]))
    child = subprocess.run([sys.executable, "-m", "flow_of_work_mcp.cli", "project-purge", "delete",
        "--config", str(config), "--project-id", "project-a", "--deletion-id", str(uuid4())],
        env=environment, capture_output=True, text=True, check=False)
    assert child.returncode == 2 and child.stderr == ""
    assert child.stdout.count("\n") == 1
    result = json.loads(child.stdout)
    assert result["contract"] == purge.CONTRACT
    assert result["diagnostics"][0]["code"] == "purge_confirmation_required"


def test_replay_stale_conflict_and_other_project_changes(tmp_path):
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0
    journal = database.with_name(database.name + ".project-purge") / (deletion + ".json")
    original = journal.read_bytes()
    replay, code = _call(config, "prepare", deletion)
    assert code == 0 and not replay["journal_changed"] and journal.read_bytes() == original
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE projects SET name='new B' WHERE project_id='project-b'")
    assert _call(config, "inspect", deletion)[1] == 0
    conflict, code = _call(config, "prepare", deletion, project="project-b")
    assert code == 3 and conflict["diagnostics"][0]["code"] == "purge_intent_conflict"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE projects SET name='changed A' WHERE project_id='project-a'")
    stale, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 2 and stale["project_effect_state"] == "none"
    assert journal.read_bytes() == original
    assert stale["prepared_fingerprint"] != stale["current_fingerprint"]


def test_active_lease_and_unsafe_paths_do_not_initialize_or_delete(tmp_path):
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    with acquire_runtime_ownership(database):
        blocked, code = _call(config, "prepare", deletion)
    assert code == 3 and blocked["diagnostics"][0]["code"] == "ledger_runtime_in_use"
    assert not database.with_name(database.name + ".project-purge").exists()
    alias = tmp_path / "alias.yaml"
    alias.symlink_to(config)
    result, code = _call(alias, "prepare", deletion)
    assert code == 2 and result["diagnostics"][0]["code"] == "path_unsafe"
    os.link(config, tmp_path / "hardlink.yaml")
    result, code = _call(config, "prepare", deletion)
    assert code == 2 and result["diagnostics"][0]["code"] == "path_unsafe"
    assert len(_rows(database)["projects"]) == 2


@pytest.mark.parametrize("drift", ["table", "trigger", "schema", "column"])
def test_schema_drift_fails_closed(tmp_path, drift):
    config, database = _fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        if drift == "table":
            connection.execute("CREATE TABLE unknown_project_data(project_id TEXT)")
        elif drift == "trigger":
            connection.execute("CREATE TRIGGER unexpected AFTER DELETE ON projects BEGIN DELETE FROM project_sequences; END")
        elif drift == "schema":
            connection.execute("INSERT INTO schema_migrations VALUES(56,'test')")
        else:
            connection.execute("ALTER TABLE projects ADD COLUMN hidden_data TEXT")
    result, code = _call(config, "prepare", str(uuid4()))
    assert code == 3 and result["diagnostics"][0]["code"] == "purge_schema_unsupported"
    assert len(_rows(database)["projects"]) == 2


def test_two_owned_historical_generations_use_current_cli_without_boot(tmp_path):
    deletion = str(uuid4())
    selected = [_fixture(tmp_path / name) for name in ("old-generation", "current-generation")]
    preparations = [_call(config, "prepare", deletion)[0] for config, _ in selected]
    assert all(value["deletion_state"] == "prepared" for value in preparations)
    for (config, database), prepared in zip(selected, preparations):
        value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
        assert code == 0 and value["deletion_state"] == "scrubbed", value
        assert [row[0] for row in _rows(database)["projects"]] == ["project-b"]


def test_partial_scrub_resume_and_cumulative_applied_on_bad_argument(tmp_path, monkeypatch):
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    original = purge._Gateway._checkpoint_wal
    def fail_scrub(self, connection):
        raise OSError("SENSITIVE TEST EXCEPTION NEVER RETURNED")
    monkeypatch.setattr(purge._Gateway, "_checkpoint_wal", fail_scrub)
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 4 and value["project_effect_state"] == "applied" and value["deletion_state"] == "ledger_deleted"
    assert "SENSITIVE" not in json.dumps(value)
    assert len(_rows(database)["projects"]) == 1
    bad, code = _call(config, "delete", deletion, fingerprint="bad")
    assert code == 2 and bad["project_effect_state"] == "applied" and bad["deletion_state"] == "ledger_deleted"
    monkeypatch.setattr(purge._Gateway, "_checkpoint_wal", original)
    resumed, code = _call(config, "reconcile", deletion)
    assert code == 0 and resumed["deletion_state"] == "scrubbed"
    replay, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 0 and replay["deletion_state"] == "scrubbed" and not replay["journal_changed"]


def test_after_intent_before_commit_rolls_back_and_reconcile_never_deletes_present(tmp_path, monkeypatch):
    config, database = _fixture(tmp_path)
    before = _rows(database)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    original = purge._delete_rows
    def fail_after_partial(connection, columns, project):
        connection.execute("DELETE FROM project_sequences WHERE project_id = ?", (project,))
        raise RuntimeError("crash before commit")
    monkeypatch.setattr(purge, "_delete_rows", fail_after_partial)
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 4 and value["project_effect_state"] == "unknown" and value["project_present"] is None
    assert _rows(database) == before
    reconciled, code = _call(config, "reconcile", deletion)
    assert code == 0 and reconciled["deletion_state"] == "deleting" and reconciled["project_present"]
    assert _rows(database) == before
    monkeypatch.setattr(purge, "_delete_rows", original)
    retried, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 0 and retried["deletion_state"] == "scrubbed"


def test_lost_commit_journal_response_recovers_from_actual_absence(tmp_path, monkeypatch):
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    original = purge._Gateway._stage
    def lost_after_commit(self, stage, **extra):
        if stage == "ledger_deleted":
            raise OSError("lost journal acknowledgement")
        return original(self, stage, **extra)
    monkeypatch.setattr(purge._Gateway, "_stage", lost_after_commit)
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 4 and value["project_effect_state"] == "applied"
    journal = database.with_name(database.name + ".project-purge") / (deletion + ".json")
    assert json.loads(journal.read_text())["stage"] == "deleting"
    monkeypatch.setattr(purge._Gateway, "_stage", original)
    value, code = _call(config, "reconcile", deletion)
    assert code == 0 and value["deletion_state"] == "scrubbed"


def test_recreated_target_is_not_deleted_or_scrubbed(tmp_path):
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    assert _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])[1] == 0
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO projects VALUES('project-a','RECREATED','different-created','different-owner')")
    value, code = _call(config, "reconcile", deletion)
    assert code == 3 and value["diagnostics"][0]["code"] == "purge_project_recreated"
    assert value["project_effect_state"] == "applied"
    assert len(_rows(database)["projects"]) == 2


def test_directory_durability_is_a_pre_effect_gate(tmp_path, monkeypatch):
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    before = _rows(database)
    def unavailable(path):
        raise purge._Problem("native_purge_durability_unavailable", "No durability", "Use a qualified filesystem", status="blocked")
    monkeypatch.setattr(purge, "_fsync_directory", unavailable)
    result, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 3 and result["project_effect_state"] == "none"
    assert _rows(database) == before


def test_foreign_key_corruption_is_not_hidden_by_purge(tmp_path):
    config, database = _fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO project_sequences VALUES('missing-project',1)")
    value, code = _call(config, "prepare", str(uuid4()))
    assert code == 3 and value["diagnostics"][0]["code"] == "purge_foreign_key_corruption"


@pytest.mark.parametrize("table,state,attempts", [
    ("packet_provider_outbox", "unknown", 1),
    ("packet_provider_outbox", "delivering", 1),
    ("packet_provider_outbox", "pending", 1),
    ("test_provider_outbox", "unknown", 1),
    ("test_provider_outbox", "delivering", 1),
])
def test_genuine_uncertain_external_command_blocks_without_rewriting_it(tmp_path, table, state, attempts):
    config, database = _fixture(tmp_path, rich=True)
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE {table} SET state=?, attempts=? WHERE project_id='project-a'", (state, attempts))
    before = _rows(database)
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0 and prepared["blockers"]
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 3 and value["project_effect_state"] == "none"
    assert any(item["code"] == "external_command_unresolved" for item in value["blockers"])
    assert _rows(database) == before


@pytest.mark.parametrize("state,phase", [("running", "execution"), ("blocked", "technical_remediation"), ("not-understood", "idle")])
def test_bound_active_or_unknown_packet_writer_blocks_even_delivered_outbox(tmp_path, state, phase):
    config, database = _fixture(tmp_path, rich=True)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE packet_provider_outbox SET state='delivered',operation='start',attempts=1 WHERE project_id='project-a'")
        connection.execute("UPDATE packet_provider_bindings SET provider_state=?, run_phase=? WHERE project_id='project-a'", (state, phase))
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 3 and any(item["code"] == "external_packet_writer_unresolved" for item in value["blockers"])
    # A host-declared stopped implementation run cannot waive a packet provider.
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"], stopped=("RUN-000001",))
    assert code == 3


def _test_receipt(command: str, *, complete: bool, state: str = "completed", sequence: int = 2) -> dict:
    from flow_of_work_mcp.core.domain.campaign_authority import TestProviderReceipt
    return TestProviderReceipt(command_id=command, provider_event_seq=sequence, technical_state=state,
        evidence_disposition="passed", attestation_state="attested_current", oracle_id="ORACLE-000001",
        oracle_revision=1, oracle_fingerprint="oracle-fingerprint", source_manifest_digest="source-fingerprint",
        materialization_ref="materialization-1", materialization_revision=1,
        representation_fingerprint="representation-fingerprint", evidence_reference="owned-test:evidence",
        current=True, complete=complete, integrity_preserved=True, next_action="none",
        authority_input_fingerprint="source-fingerprint").as_payload()


def _delivered_test_run(database: Path, *, complete: bool = False, state: str = "completed") -> None:
    from flow_of_work_mcp.core.domain.campaign_authority import TestProviderReceipt
    receipt = _test_receipt("TCMD-000001", complete=complete, state=state)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE test_provider_outbox SET operation='run', state='delivered', attempts=1, command_id='TCMD-000001' WHERE project_id='project-a'")
        connection.execute("UPDATE test_provider_receipts SET command_id='TCMD-000001', provider_event_seq=2, receipt_json=?, receipt_fingerprint=? WHERE project_id='project-a'",
            (json.dumps(receipt), TestProviderReceipt.from_payload(receipt).fingerprint))


@pytest.mark.parametrize("complete,state", [(False, "completed"), (True, "running"), (True, "unrecognized")])
def test_delivered_test_run_requires_supported_terminal_same_command_receipt(tmp_path, complete, state):
    config, database = _fixture(tmp_path, rich=True)
    _delivered_test_run(database, complete=complete, state=state)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 3 and any(item["code"] == "external_test_writer_unresolved" for item in value["blockers"])
    assert _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"], stopped=("RUN-000001",))[1] == 3


def test_later_terminal_same_run_receipt_resolves_but_distinct_report_does_not(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    _delivered_test_run(database)
    with sqlite3.connect(database) as connection:
        source = connection.execute("SELECT * FROM test_provider_outbox WHERE project_id='project-a'").fetchone()
        names = [row[1] for row in connection.execute("PRAGMA table_info(test_provider_outbox)")]
        values = dict(zip(names, source))
        values.update(command_id="TCMD-000003", ordinal=3, operation="report", delivery_fingerprint="distinct-report",
                      command_fingerprint="distinct-report", state="delivered")
        connection.execute(f"INSERT INTO test_provider_outbox ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(values[name] for name in names))
        names = [row[1] for row in connection.execute("PRAGMA table_info(test_provider_receipts)")]
        values = dict(zip(names, connection.execute("SELECT * FROM test_provider_receipts WHERE project_id='project-a'").fetchone()))
        values.update(receipt_id="TRCPT-000003", ordinal=3, command_id="TCMD-000003", receipt_json=json.dumps(_test_receipt("TCMD-000003", complete=True)))
        connection.execute(f"INSERT INTO test_provider_receipts ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(values[name] for name in names))
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    assert any(item["code"] == "external_test_writer_unresolved" for item in prepared["blockers"])
    assert _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])[1] == 3
    # The original RUN's new receipt, not the REPORT, supplies supported proof.
    from flow_of_work_mcp.core.domain.campaign_authority import TestProviderReceipt
    receipt = _test_receipt("TCMD-000001", complete=True, sequence=4)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE test_provider_receipts SET provider_event_seq=4,receipt_json=?,receipt_fingerprint=? WHERE project_id='project-a' AND command_id='TCMD-000001'",
            (json.dumps(receipt), TestProviderReceipt.from_payload(receipt).fingerprint))
    # This is changed authority: prepare a new native intent, do not rebase.
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0 and not prepared["blockers"]
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 0 and value["deletion_state"] == "scrubbed", value


def test_recovered_external_run_needs_actual_host_declaration_or_terminal_reconciliation(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE implementation_runs SET external_ref='native-host:run', status='blocked' WHERE project_id='project-a'")
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    assert _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])[1] == 3
    wrong, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"], stopped=("RUN-999999",))
    assert code == 2 and wrong["diagnostics"][0]["code"] == "host_run_declaration_stale"
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"], stopped=("RUN-000001",))
    assert code == 0 and value["deletion_state"] == "scrubbed", value
    journal = database.with_name(database.name + ".project-purge") / (deletion + ".json")
    assert json.loads(journal.read_text())["provenance"] == "host_declared"


def test_wal_reader_blocks_scrub_after_commit_then_reconcile_completes(tmp_path):
    config, database = _fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    reader = sqlite3.connect(database)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM projects").fetchall()
    try:
        deletion = str(uuid4())
        prepared, _ = _call(config, "prepare", deletion)
        value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
        assert code == 3 and value["project_effect_state"] == "applied"
        assert value["deletion_state"] == "ledger_deleted"
    finally:
        reader.close()
    value, code = _call(config, "reconcile", deletion)
    assert code == 0 and value["deletion_state"] == "scrubbed", value
    wal = database.with_name(database.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0


def test_profile_selection_missing_files_and_unsafe_journal_preserve_state(tmp_path):
    profile_root = tmp_path / "owned-root"
    config, database = _fixture(profile_root / "profiles" / "native")
    deletion = str(uuid4())
    args = build_cli_parser().parse_args(["project-purge", "prepare", "--profile", "native", "--profile-root", str(profile_root),
        "--project-id", "project-a", "--deletion-id", deletion])
    assert purge.run_project_purge(args)[1] == 0
    directory = database.with_name(database.name + ".project-purge")
    journal = directory / (deletion + ".json")
    original = journal.read_bytes()
    target = tmp_path / "external-journal-sentinel"
    target.write_bytes(original)
    journal.unlink()
    journal.symlink_to(target)
    result, code = _call(config, "inspect", deletion)
    assert code == 2 and result["diagnostics"][0]["code"] == "path_unsafe"
    assert target.read_bytes() == original
    missing = tmp_path / "missing" / "flower.yaml"
    result, code = _call(missing, "prepare", str(uuid4()))
    assert code == 2 and not missing.parent.exists()


@pytest.mark.parametrize("crash_stage", ["before_commit", "after_commit", "during_scrub"])
def test_actual_process_exit_recovers_without_job_or_model_boot(tmp_path, crash_stage):
    config, database = _fixture(tmp_path)
    before = _rows(database)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    script = r'''
import os, sys
from flow_of_work_mcp import native_project_purge as p
from flow_of_work_mcp.cli import build_cli_parser
stage = sys.argv[1]
if stage == 'before_commit':
    original = p._delete_rows
    def interrupted(*args):
        original(*args)
        os._exit(88)
    p._delete_rows = interrupted
elif stage == 'after_commit':
    original = p._Gateway._stage
    def interrupted(self, name, **extra):
        if name == 'ledger_deleted':
            os._exit(88)
        return original(self, name, **extra)
    p._Gateway._stage = interrupted
else:
    original = p._Gateway._checkpoint_wal
    calls = 0
    def interrupted(self, connection):
        global calls
        calls += 1
        if calls == 2:
            os._exit(88)
        return original(self, connection)
    p._Gateway._checkpoint_wal = interrupted
args = build_cli_parser().parse_args(sys.argv[2:])
p.run_project_purge(args)
raise SystemExit('crash hook was not reached')
'''
    environment = dict(os.environ, PYTHONPATH=str(Path(purge.__file__).parents[1]))
    child = subprocess.run([sys.executable, "-c", script, crash_stage, "project-purge", "delete",
        "--config", str(config), "--project-id", "project-a", "--deletion-id", deletion,
        "--expected-fingerprint", prepared["prepared_fingerprint"], "--confirm-project-id", "project-a",
        "--host-quiescence-ref", "owned-test:stopped"], capture_output=True, text=True, env=environment, timeout=15)
    assert child.returncode == 88 and child.stdout == "" and child.stderr == "", child
    result, code = _call(config, "reconcile", deletion)
    assert code == 0, result
    if crash_stage == "before_commit":
        assert _rows(database) == before
        assert result["project_present"] and result["deletion_state"] == "deleting"
        result, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
        assert code == 0 and result["deletion_state"] == "scrubbed"
    else:
        assert result["deletion_state"] == "scrubbed" and result["project_effect_state"] == "applied"
        assert len(_rows(database)["projects"]) == 1


@pytest.mark.parametrize("tamper", ["sequence", "fingerprint", "provider", "command"])
def test_test_terminal_receipt_must_match_durable_correlation(tmp_path, tamper):
    config, database = _fixture(tmp_path, rich=True)
    _delivered_test_run(database, complete=True)
    with sqlite3.connect(database) as connection:
        if tamper == "sequence":
            connection.execute("UPDATE test_provider_receipts SET provider_event_seq=99 WHERE project_id='project-a'")
        elif tamper == "fingerprint":
            connection.execute("UPDATE test_provider_receipts SET receipt_fingerprint='wrong' WHERE project_id='project-a'")
        elif tamper == "provider":
            connection.execute("UPDATE test_provider_receipts SET provider_kind='different' WHERE project_id='project-a'")
        else:
            receipt = _test_receipt("TCMD-000099", complete=True)
            connection.execute("UPDATE test_provider_receipts SET receipt_json=? WHERE project_id='project-a'", (json.dumps(receipt),))
    value, code = _call(config, "prepare", str(uuid4()))
    assert code == 0 and any(item["code"] == "external_test_writer_unresolved" for item in value["blockers"])


def test_self_referencing_phase_chain_is_deleted_child_first(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    with sqlite3.connect(database) as connection:
        names = [row[1] for row in connection.execute("PRAGMA table_info(phase_audits)")]
        row = dict(zip(names, connection.execute("SELECT * FROM phase_audits WHERE project_id='project-a'").fetchone()))
        row.update(phase_audit_id=3, previous_phase_audit_id=1)
        connection.execute(f"INSERT INTO phase_audits ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(row[name] for name in names))
        row.update(phase_audit_id=4, previous_phase_audit_id=3)
        connection.execute(f"INSERT INTO phase_audits ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(row[name] for name in names))
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    assert prepared["counts"]["phase_audits"] == 3
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 0 and value["deletion_state"] == "scrubbed", value
    assert len(_rows(database)["phase_audits"]) == 1


def test_cross_project_phase_reference_blocks_without_deleting_other_project(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE phase_audits SET previous_phase_audit_id=1 WHERE project_id='project-b'")
    before = _rows(database)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 3 and value["diagnostics"][0]["code"] == "purge_cross_project_or_cycle"
    assert _rows(database) == before


def test_intent_name_publication_failure_reports_changed_unknown_and_preserves_rows(tmp_path, monkeypatch):
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    before = _rows(database)
    journal = database.with_name(database.name + ".project-purge") / (deletion + ".json")
    original = purge._fsync_directory
    def fail_after_intent_publish(path):
        if path == journal.parent and journal.exists() and json.loads(journal.read_text())["stage"] == "deleting":
            raise OSError("directory durability acknowledgement lost")
        return original(path)
    monkeypatch.setattr(purge, "_fsync_directory", fail_after_intent_publish)
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 4 and value["journal_changed"] and value["deletion_state"] == "deleting"
    assert value["project_effect_state"] == "unknown" and _rows(database) == before
    monkeypatch.setattr(purge, "_fsync_directory", original)
    value, code = _call(config, "reconcile", deletion)
    assert code == 0 and value["project_present"] and _rows(database) == before


def test_ack_name_removal_failure_reports_actual_journal_change(tmp_path, monkeypatch):
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    assert _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])[1] == 0
    journal = database.with_name(database.name + ".project-purge") / (deletion + ".json")
    original = purge._fsync_directory
    def fail_after_unlink(path):
        if path == journal.parent and not journal.exists():
            raise OSError("ack directory synchronization unavailable")
        return original(path)
    monkeypatch.setattr(purge, "_fsync_directory", fail_after_unlink)
    value, code = _call(config, "reconcile", deletion, ack=True)
    assert code == 4 and value["journal_changed"] and value["project_effect_state"] == "applied"
    assert not journal.exists()
    monkeypatch.setattr(purge, "_fsync_directory", original)
    value, code = _call(config, "reconcile", deletion, ack=True)
    assert code == 0 and value["deletion_state"] == "absent" and value["project_effect_state"] == "unknown"


def test_unsafe_private_journal_permissions_do_not_change_project(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX journal mode contract")
    config, database = _fixture(tmp_path)
    deletion = str(uuid4())
    _call(config, "prepare", deletion)
    journal = database.with_name(database.name + ".project-purge") / (deletion + ".json")
    journal.chmod(0o644)
    value, code = _call(config, "inspect", deletion)
    assert code == 3 and value["diagnostics"][0]["code"] == "journal_not_private"
    assert len(_rows(database)["projects"]) == 2


def _packet_start_history(database, *, terminal=True, missing_binding=False):
    from flow_of_work_mcp.core.domain.packet_provider import PacketProviderCommand, PacketProviderReceipt
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        start = connection.execute("SELECT * FROM packet_provider_outbox WHERE project_id='project-a'").fetchone()
        command = PacketProviderCommand(flow_session_ref="project-a", flow_packet_ref=start["packet_id"],
            flow_spec_revision=start["flow_spec_revision"], operation="start", delivery_fingerprint="owned-start").as_payload()
        receipt = PacketProviderReceipt(provider_kind="fixture", provider_contract_version="fixture.packet.v2",
            provider_packet_ref="original-packet", provider_packet_revision=1, provider_state="completed" if terminal else "running",
            binding_epoch=1, event_seq=1, changed=True, run_phase="completed" if terminal else "execution").persisted_payload()
        receipt_id = connection.execute("SELECT receipt_id FROM packet_provider_receipts WHERE project_id='project-a'").fetchone()[0]
        connection.execute("""UPDATE packet_provider_outbox SET operation='start',state='delivered', attempts=1,
            flow_binding_generation=1,flow_unit_ref='',delivery_fingerprint='owned-start',command_json=?,command_fingerprint=?,receipt_id=?
            WHERE project_id='project-a'""", (json.dumps(command), purge._packet_payload_digest(command), receipt_id))
        connection.execute("""UPDATE packet_provider_receipts SET outbox_id=?,observation_kind='command',
            provider_contract_version='fixture.packet.v2',provider_packet_ref='original-packet',provider_packet_revision=1,
            provider_state=?,binding_epoch=1,event_seq=1,receipt_json=?,receipt_fingerprint=? WHERE project_id='project-a'""",
            (start["outbox_id"], receipt["provider_state"], json.dumps(receipt), purge._packet_payload_digest(receipt)))
        connection.execute("""UPDATE packet_provider_bindings SET flow_binding_generation=1,provider_packet_ref='original-packet',
            provider_packet_revision=1,provider_state=?,run_phase=?,provider_job_ref='',binding_epoch=1,event_seq=1,last_receipt_id=? WHERE project_id='project-a'""",
            (receipt["provider_state"], receipt["technical"]["phase"], receipt_id))
        if missing_binding:
            connection.execute("DELETE FROM packet_provider_unit_correlations WHERE project_id='project-a'")
            connection.execute("DELETE FROM packet_provider_bindings WHERE project_id='project-a'")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_delivered_start_missing_binding_is_a_real_blocker_not_absent_local_work(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    _packet_start_history(database, terminal=False, missing_binding=True)
    before = _rows(database)
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0 and any(item["code"] == "external_packet_start_unresolved" for item in prepared["blockers"])
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 3 and value["project_effect_state"] == "none" and _rows(database) == before


def test_delivered_start_with_exact_current_generation_terminal_proof_can_purge(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    _packet_start_history(database)
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0 and not prepared["blockers"], prepared
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 0 and value["deletion_state"] == "scrubbed", value


@pytest.mark.parametrize("mismatch", ["generation", "reference", "receipt_hash", "receipt_outbox", "last_receipt", "binding_job"])
def test_delivered_start_mismatched_binding_or_receipt_cannot_waive_writer(tmp_path, mismatch):
    config, database = _fixture(tmp_path, rich=True)
    _packet_start_history(database)
    with sqlite3.connect(database) as connection:
        if mismatch == "generation":
            connection.execute("UPDATE packet_provider_bindings SET flow_binding_generation=1 WHERE project_id='project-a'")
            connection.execute("UPDATE packet_provider_outbox SET flow_binding_generation=2 WHERE project_id='project-a'")
        elif mismatch == "reference":
            connection.execute("UPDATE packet_provider_bindings SET provider_packet_ref='unrelated-new-packet' WHERE project_id='project-a'")
        elif mismatch == "receipt_hash":
            connection.execute("UPDATE packet_provider_receipts SET receipt_fingerprint='invalid' WHERE project_id='project-a'")
        elif mismatch == "receipt_outbox":
            connection.execute("UPDATE packet_provider_receipts SET outbox_id='another-command' WHERE project_id='project-a'")
        elif mismatch == "last_receipt":
            connection.execute("UPDATE packet_provider_bindings SET last_receipt_id='missing' WHERE project_id='project-a'")
        else:
            connection.execute("UPDATE packet_provider_bindings SET provider_job_ref='unobserved-job' WHERE project_id='project-a'")
    value, code = _call(config, "prepare", str(uuid4()))
    assert code == 0 and any(item["code"] == "external_packet_start_unresolved" for item in value["blockers"])


def test_old_generation_running_start_is_not_closed_by_new_binding_terminal_state(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    _packet_start_history(database, terminal=False)
    from flow_of_work_mcp.core.domain.packet_provider import PacketProviderReceipt
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        old = dict(connection.execute("SELECT * FROM packet_provider_receipts WHERE project_id='project-a'").fetchone())
        receipt = PacketProviderReceipt(provider_kind="fixture", provider_contract_version="fixture.packet.v2",
            provider_packet_ref="new-packet", provider_packet_revision=1, provider_state="ready",
            binding_epoch=0, event_seq=1, changed=True, run_phase="idle").persisted_payload()
        old.update(receipt_id="PREC-000003", ordinal=3, outbox_id="", observation_kind="status", provider_packet_ref="new-packet",
            provider_state="ready", binding_epoch=0, event_seq=1, receipt_json=json.dumps(receipt), receipt_fingerprint=purge._packet_payload_digest(receipt))
        connection.execute(f"INSERT INTO packet_provider_receipts ({','.join(old)}) VALUES ({','.join('?' for _ in old)})", tuple(old.values()))
        connection.execute("""UPDATE packet_provider_bindings SET flow_binding_generation=2,provider_packet_ref='new-packet',provider_state='ready',
            run_phase='idle',binding_epoch=0,event_seq=1,last_receipt_id='PREC-000003' WHERE project_id='project-a'""")
    deletion = str(uuid4())
    prepared, _ = _call(config, "prepare", deletion)
    assert any(item["code"] == "external_packet_start_unresolved" for item in prepared["blockers"])
    assert _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])[1] == 3
    # An exact same-old-generation STOP receipt supplies supported closure;
    # the newer binding alone did not establish this.
    from flow_of_work_mcp.core.domain.packet_provider import PacketProviderCommand
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        stop = dict(connection.execute("SELECT * FROM packet_provider_outbox WHERE project_id='project-a'").fetchone())
        command = PacketProviderCommand(flow_session_ref="project-a", flow_packet_ref=stop["packet_id"],
            flow_spec_revision=stop["flow_spec_revision"], operation="stop", delivery_fingerprint="old-generation-stop").as_payload()
        stop.update(outbox_id="POUT-000002", ordinal=2, operation="stop", delivery_fingerprint="old-generation-stop",
            command_json=json.dumps(command), command_fingerprint=purge._packet_payload_digest(command), receipt_id="PREC-000002")
        connection.execute(f"INSERT INTO packet_provider_outbox ({','.join(stop)}) VALUES ({','.join('?' for _ in stop)})", tuple(stop.values()))
        terminal = PacketProviderReceipt(provider_kind="fixture", provider_contract_version="fixture.packet.v2",
            provider_packet_ref="original-packet", provider_packet_revision=2, provider_state="stopped",
            binding_epoch=1, event_seq=2, changed=True, run_phase="stopped").persisted_payload()
        row = dict(connection.execute("SELECT * FROM packet_provider_receipts WHERE project_id='project-a' ORDER BY ordinal LIMIT 1").fetchone())
        row.update(receipt_id="PREC-000002", ordinal=2, outbox_id="POUT-000002", provider_packet_revision=2,
            provider_state="stopped", event_seq=2, receipt_json=json.dumps(terminal), receipt_fingerprint=purge._packet_payload_digest(terminal))
        connection.execute(f"INSERT INTO packet_provider_receipts ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0 and not prepared["blockers"], prepared
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 0 and value["deletion_state"] == "scrubbed", value


@pytest.mark.parametrize("operation", ["prepare", "inspect", "reconcile"])
def test_missing_project_with_no_fk_owned_rows_is_not_successful_absence(tmp_path, operation):
    config, database = _fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO external_work_requests VALUES('never-created','req','fp','{}')")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    before = _rows(database)
    value, code = _call(config, operation, str(uuid4()), project="never-created", ack=operation == "reconcile")
    assert code == 3 and value["diagnostics"][0]["code"] == "purge_remaining_records"
    assert value["project_present"] is False and value["counts"]["external_work_requests"] == 1
    assert value["deletion_state"] == "unknown" and value["project_effect_state"] == "unknown"
    assert _rows(database) == before


@pytest.mark.parametrize("project", [" project-a ", "project-a ", " project-a"])
def test_native_project_identity_requires_exact_canonical_input_before_sql(tmp_path, project, monkeypatch):
    config, database = _fixture(tmp_path)
    before = _rows(database)
    def no_sql(*args, **kwargs):
        raise AssertionError("noncanonical project IDs must be rejected before SQL")
    monkeypatch.setattr(purge.sqlite3, "connect", no_sql)
    value, code = _call(config, "prepare", str(uuid4()), project=project)
    assert code == 2 and value["diagnostics"][0]["code"] == "purge_identity_invalid"
    monkeypatch.undo()
    assert _rows(database) == before


@pytest.mark.parametrize("variation", ["running", "new-job", "unknown", "revision", "newer-running", "metadata", "stale-running", "terminal-disposition"])
def test_retained_packet_clock_execution_conflicts_block_but_harmless_observations_do_not(tmp_path, variation):
    config, database = _fixture(tmp_path, rich=True)
    _packet_start_history(database)
    from flow_of_work_mcp.core.domain.packet_provider import PacketProviderReceipt
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        old = dict(connection.execute("SELECT * FROM packet_provider_receipts WHERE project_id='project-a'").fetchone())
        state, phase = ("running", "execution") if variation in {"running", "newer-running", "stale-running"} else ("completed", "completed")
        if variation == "unknown":
            state, phase = "unknown", "idle"
        if variation == "terminal-disposition":
            state, phase = "stopped", "stopped"
        revision = 2 if variation == "revision" else 1
        sequence = 2 if variation == "newer-running" else 0 if variation == "stale-running" else 1
        receipt = PacketProviderReceipt(provider_kind="fixture", provider_contract_version="fixture.packet.v2",
            provider_packet_ref="original-packet", provider_packet_revision=revision, provider_state=state,
            binding_epoch=1, event_seq=sequence, changed=False, run_phase=phase,
            provider_job_ref="new-execution-job" if variation == "new-job" else "",
            current_step="harmless status presentation").persisted_payload()
        old.update(receipt_id="PREC-000099", ordinal=99, outbox_id="", observation_kind="status", provider_state=state,
            event_seq=sequence, provider_packet_revision=revision, receipt_json=json.dumps(receipt),
            receipt_fingerprint=purge._packet_payload_digest(receipt))
        connection.execute(f"INSERT INTO packet_provider_receipts ({','.join(old)}) VALUES ({','.join('?' for _ in old)})", tuple(old.values()))
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    before = _rows(database)
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0
    if variation in {"metadata", "stale-running", "terminal-disposition"}:
        assert not prepared["blockers"], prepared
        value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
        assert code == 0 and value["deletion_state"] == "scrubbed", value
    else:
        assert any(item["code"] == "external_packet_start_unresolved" for item in prepared["blockers"])
        value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
        assert code == 3 and value["project_effect_state"] == "none"
        assert _rows(database) == before


def test_newer_terminal_proof_recovers_older_clock_fork_without_rewriting_history(tmp_path):
    config, database = _fixture(tmp_path, rich=True)
    _packet_start_history(database)
    from flow_of_work_mcp.core.domain.packet_provider import PacketProviderReceipt
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        old = dict(connection.execute("SELECT * FROM packet_provider_receipts WHERE project_id='project-a'").fetchone())
        active = PacketProviderReceipt(provider_kind="fixture", provider_contract_version="fixture.packet.v2",
            provider_packet_ref="original-packet", provider_packet_revision=1, provider_state="running",
            binding_epoch=1, event_seq=1, changed=True, run_phase="execution", provider_job_ref="retry-job").persisted_payload()
        old.update(receipt_id="PREC-000099", ordinal=99, outbox_id="", observation_kind="status", provider_state="running",
            receipt_json=json.dumps(active), receipt_fingerprint=purge._packet_payload_digest(active))
        connection.execute(f"INSERT INTO packet_provider_receipts ({','.join(old)}) VALUES ({','.join('?' for _ in old)})", tuple(old.values()))
    blocked, code = _call(config, "prepare", str(uuid4()))
    assert code == 0 and any(item["code"] == "external_packet_start_unresolved" for item in blocked["blockers"])
    retained_before = _rows(database)["packet_provider_receipts"]
    with sqlite3.connect(database) as connection:
        terminal = PacketProviderReceipt(provider_kind="fixture", provider_contract_version="fixture.packet.v2",
            provider_packet_ref="original-packet", provider_packet_revision=2, provider_state="completed",
            binding_epoch=1, event_seq=2, changed=True, run_phase="completed", provider_job_ref="retry-job").persisted_payload()
        old.update(receipt_id="PREC-000100", ordinal=100, provider_packet_revision=2, provider_state="completed", event_seq=2,
            receipt_json=json.dumps(terminal), receipt_fingerprint=purge._packet_payload_digest(terminal))
        connection.execute(f"INSERT INTO packet_provider_receipts ({','.join(old)}) VALUES ({','.join('?' for _ in old)})", tuple(old.values()))
        connection.execute("""UPDATE packet_provider_bindings SET provider_packet_revision=2,provider_state='completed',
            run_phase='completed',event_seq=2,provider_job_ref='retry-job',last_receipt_id='PREC-000100' WHERE project_id='project-a'""")
    assert _rows(database)["packet_provider_receipts"][:len(retained_before)] == retained_before
    deletion = str(uuid4())
    prepared, code = _call(config, "prepare", deletion)
    assert code == 0 and not prepared["blockers"], prepared
    value, code = _call(config, "delete", deletion, fingerprint=prepared["prepared_fingerprint"])
    assert code == 0 and value["deletion_state"] == "scrubbed", value
