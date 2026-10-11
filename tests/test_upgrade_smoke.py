"""Upgrade qualifier boundaries; no network, package install or domain services."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import smoke_upgrade as smoke
import public_inventory


class UpgradeSmokeTests(unittest.TestCase):
    def test_worker_script_starts_in_isolated_python_without_checkout_import_path(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-I", str(Path(smoke.__file__).resolve()), "--help"],
                cwd=directory, env=smoke.clean_environment(),
                text=True, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--baseline-assets", completed.stdout)
        self.assertEqual(completed.stderr, "")

    def migration_fixture(self, directory):
        path = Path(directory) / "ledger.sqlite3"
        with sqlite3.connect(path) as connection:
            connection.executescript('''
                CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                INSERT INTO schema_migrations VALUES(1, 'original-first'), (52, 'original-current');
                CREATE TABLE projects(project_id TEXT PRIMARY KEY, clock INTEGER NOT NULL);
                INSERT INTO projects VALUES('alpha', 17);
                CREATE TABLE implementation_packets(project_id TEXT, change_id TEXT, packet_id TEXT,
                    body TEXT NOT NULL, PRIMARY KEY(project_id,change_id,packet_id));
                INSERT INTO implementation_packets VALUES('alpha', 'change', 'packet', 'Original packet');
                CREATE TABLE implementation_packet_revisions(project_id TEXT, revision INTEGER, body TEXT NOT NULL);
                INSERT INTO implementation_packet_revisions VALUES('alpha', 1, 'Frozen packet revision');
                CREATE TABLE packet_provider_outbox(project_id TEXT, outbox_id TEXT,
                    PRIMARY KEY(project_id,outbox_id));
                CREATE TABLE frozen_handover(id INTEGER PRIMARY KEY AUTOINCREMENT, body BLOB NOT NULL);
                CREATE INDEX handover_id ON frozen_handover(id);
                INSERT INTO frozen_handover(body) VALUES(X'000AFF');
                CREATE TABLE evidence(body TEXT NOT NULL, provenance TEXT NOT NULL);
                INSERT INTO evidence VALUES('Originale\nè evidenza.', 'host-reported');
            ''')
        before = smoke.database_authority(path)
        with sqlite3.connect(path) as connection:
            connection.executescript(smoke.ADDITIVE_SCHEMA_SQL)
            for table in smoke.ARCHITECTURE_TABLES:
                connection.execute('ALTER TABLE "' + table + '" ADD COLUMN ' + smoke.ARCHITECTURE_COLUMN)
            connection.executemany("INSERT INTO schema_migrations VALUES(?,?)", [(53, "new53"), (54, "new54"), (55, "new55")])
        return path, before

    def test_exact_additive_migration_preserves_all_original_fields_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path, before = self.migration_fixture(directory)
            original_bytes = path.read_bytes()
            result = smoke.require_additive_migration(path, before)
            self.assertEqual(path.read_bytes(), original_bytes)
            self.assertEqual((result["previous_schema"], result["current_schema"]), (52, 55))
            self.assertEqual(set(result["new_tables"]), smoke.NEW_TABLES)
            self.assertFalse(result["invented_authority"])

    def test_migration_rejects_changed_original_evidence_clock_or_frozen_handover(self):
        mutations = (
            "UPDATE evidence SET provenance='provider-audited'",
            "UPDATE projects SET clock=18",
            "UPDATE frozen_handover SET body=X'000AFE'",
            "UPDATE implementation_packet_revisions SET body='replacement'",
        )
        for sql in mutations:
            with self.subTest(sql=sql), tempfile.TemporaryDirectory() as directory:
                path, before = self.migration_fixture(directory)
                with sqlite3.connect(path) as connection:
                    connection.execute(sql)
                with self.assertRaisesRegex(RuntimeError, "original rows or clocks"):
                    smoke.require_additive_migration(path, before)

    def test_migration_rejects_missing_constraints_index_or_unexpected_objects(self):
        mutations = (
            "DROP INDEX packet_provider_admissions_context",
            "CREATE TABLE unexpected (value TEXT)",
            "DROP TABLE packet_executor_requests; CREATE TABLE packet_executor_requests(project_id TEXT, request_id TEXT, request_fingerprint TEXT NOT NULL, result_json TEXT NOT NULL, actor TEXT NOT NULL, operation TEXT NOT NULL, occurred_at TEXT NOT NULL, PRIMARY KEY(project_id,request_id))",
            "CREATE INDEX unexpected_old_index ON evidence(body)",
        )
        for sql in mutations:
            with self.subTest(sql=sql), tempfile.TemporaryDirectory() as directory:
                path, before = self.migration_fixture(directory)
                with sqlite3.connect(path) as connection:
                    connection.executescript(sql)
                with self.assertRaisesRegex(RuntimeError, "schema (object|definition)"):
                    smoke.require_additive_migration(path, before)

    def test_migration_rejects_invented_architecture_and_missing_or_rewritten_checkpoints(self):
        mutations = (
            ("UPDATE implementation_packets SET architecture_refs_json='[{\"revision\":1}]'", "historical architecture"),
            ("INSERT INTO architecture_requests VALUES('alpha','invented','propose','hash','{}','model','now')", "invented architecture or executor"),
            ("DELETE FROM schema_migrations WHERE version=55", "Migration versions"),
            ("UPDATE schema_migrations SET applied_at='rewritten' WHERE version=52", "Historical migration timestamps"),
        )
        for sql, expected in mutations:
            with self.subTest(sql=sql), tempfile.TemporaryDirectory() as directory:
                path, before = self.migration_fixture(directory)
                with sqlite3.connect(path) as connection:
                    connection.execute(sql)
                with self.assertRaisesRegex(RuntimeError, expected):
                    smoke.require_additive_migration(path, before)

    def test_exact_catalogs_reject_same_count_substitutions_duplicates_and_wrong_generation(self):
        baseline = [SimpleNamespace(name=name) for name in public_inventory.BASELINE_TOOL_NAMES]
        current = [*baseline, SimpleNamespace(name="fow_architecture")]
        public_inventory.require_tool_inventory(baseline, baseline=True)
        public_inventory.require_tool_inventory(current)
        for catalog, baseline_flag in (
            (baseline, False), (current, True),
            ([*current[:-1], SimpleNamespace(name="fow_unexpected")], False),
            ([*current[:-1], current[0]], False),
        ):
            with self.subTest(baseline=baseline_flag, names=[tool.name for tool in catalog]):
                with self.assertRaisesRegex(RuntimeError, "exact .* contract"):
                    public_inventory.require_tool_inventory(catalog, baseline=baseline_flag)

    def test_existing_qualification_root_is_rejected_before_loading_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / "user-state"
            sentinel.write_bytes(b"do not modify")
            with patch.object(smoke, "load_backend") as loader:
                with self.assertRaisesRegex(RuntimeError, "absent isolated root"):
                    smoke.qualify(argparse.Namespace(root=root, assets=root, baseline_assets=None, output=None))
                loader.assert_not_called()
            self.assertEqual(sentinel.read_bytes(), b"do not modify")

    def test_development_wheel_named_like_baseline_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supplied = root / "supplied"
            supplied.mkdir()
            payloads = {"install_flower.py": b"raise RuntimeError('must not execute')\n",
                        "flow_of_work_mcp-0.3.0-py3-none-any.whl": b"development build"}
            for name, content in payloads.items():
                (supplied / name).write_bytes(content)
            (supplied / "SHA256SUMS").write_text("".join(
                hashlib.sha256(content).hexdigest() + "  " + name + "\n" for name, content in payloads.items()))
            with self.assertRaisesRegex(RuntimeError, "immutable published"):
                smoke.baseline_assets(root / "destination", supplied)

    def test_baseline_installer_tampering_cannot_hide_in_a_rewritten_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supplied = root / "supplied"
            supplied.mkdir()
            wheel = supplied / "flow_of_work_mcp-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"bounded synthetic wheel")
            backend = supplied / "install_flower.py"
            backend.write_bytes(b"raise RuntimeError('must not execute')\n")
            (supplied / "SHA256SUMS").write_text("".join(
                smoke.digest(path) + "  " + path.name + "\n" for path in (wheel, backend)))
            with patch.object(smoke, "BASELINE_WHEEL_SHA256", smoke.digest(wheel)):
                with self.assertRaisesRegex(RuntimeError, "Baseline installer differs"):
                    smoke.baseline_assets(root / "destination", supplied)

    def test_existing_output_is_rejected_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "previous-receipt.json"
            output.write_bytes(b"original evidence")
            with patch.object(smoke, "load_backend") as loader:
                with self.assertRaisesRegex(RuntimeError, "must not replace"):
                    smoke.qualify(argparse.Namespace(root=parent / "new-root", assets=parent,
                                                     baseline_assets=None, output=output))
                loader.assert_not_called()
            self.assertEqual(output.read_bytes(), b"original evidence")

    def backend(self):
        source = Path(__file__).resolve().parents[1] / "tools/install_flower.py"
        return smoke.load_backend(source)

    def test_loading_backend_does_not_mutate_release_asset_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "install_flower.py"
            path.write_bytes((Path(__file__).resolve().parents[1] / "tools/install_flower.py").read_bytes())
            original = smoke.state_snapshot(root)
            smoke.load_backend(path)
            self.assertEqual(smoke.state_snapshot(root), original)

    def test_historical_requirement_retains_authority_while_validating_new_recovery_route(self):
        authority = {"requirement": {"statement": "original intent"}, "revisions": [{"revision": 1}], "events": []}
        current = {**authority, "evidence_recovery": {"description": "Read original evidence.", "next_tool_call": {
            "tool": "fow_traceability", "arguments": {"project_id": smoke.PROJECT, "detail_level": "audit", "offset": 0, "limit": 10}}}}
        self.assertEqual(smoke.historical_requirement(current, smoke.PROJECT), authority)
        self.assertIn("evidence_recovery", current)
        current["evidence_recovery"]["next_tool_call"]["arguments"]["project_id"] = "another-project"
        with self.assertRaisesRegex(RuntimeError, "different evidence recovery route"):
            smoke.historical_requirement(current, smoke.PROJECT)

    def test_historical_requirement_does_not_silently_drop_unknown_fields(self):
        current = {"requirement": {}, "revisions": [], "events": [], "unknown_authority": "changed",
                   "evidence_recovery": {"description": "Read original evidence.", "next_tool_call": {
                       "tool": "fow_traceability", "arguments": {"project_id": smoke.PROJECT,
                           "detail_level": "audit", "offset": 0, "limit": 10}}}}
        with self.assertRaisesRegex(RuntimeError, "Unexpected requirement authority fields"):
            smoke.historical_requirement(current, smoke.PROJECT)

    def assets(self, root, backend, content=b"synthetic wheel bytes"):
        name = f"flow_of_work_mcp-{backend.DEFAULT_VERSION}-py3-none-any.whl"
        (root / name).write_bytes(content)
        (root / "SHA256SUMS").write_text(hashlib.sha256(content).hexdigest() + "  " + name + "\n")
        return name

    def test_local_download_seam_validates_checksum_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = self.backend()
            name = self.assets(root, backend)
            smoke.local_assets(backend, root)
            destination = root / "copied.whl"
            value = backend.download_asset(smoke.REPOSITORY + "/releases/download/v" + backend.DEFAULT_VERSION + "/" + name,
                                           destination, max_bytes=1024)
            self.assertEqual(value, smoke.digest(destination))
            self.assertEqual(destination.read_bytes(), (root / name).read_bytes())

    def test_tampered_local_wheel_does_not_create_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = self.backend()
            name = self.assets(root, backend)
            (root / name).write_bytes(b"tampered")
            smoke.local_assets(backend, root)
            with self.assertRaisesRegex(RuntimeError, "differs from its manifest"):
                backend.download_asset("https://example.test/" + name, root / "copy", max_bytes=1024)
            self.assertFalse((root / "copy").exists())

    def test_unexpected_installer_download_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = self.backend()
            self.assets(root, backend)
            smoke.local_assets(backend, root)
            with self.assertRaisesRegex(RuntimeError, "Unexpected installer download"):
                backend.download_asset("https://example.test/unexpected.py", root / "copy", max_bytes=1024)

    def test_database_fingerprint_is_read_only_and_detects_changed_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE evidence (body TEXT)")
                connection.execute("INSERT INTO evidence VALUES ('original')")
            original_bytes = path.read_bytes()
            before = smoke.database_state(path)
            self.assertEqual(path.read_bytes(), original_bytes)
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE evidence SET body = 'changed'")
            self.assertNotEqual(smoke.database_state(path), before)

    def test_invalid_database_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            path.write_bytes(b"invalid SQLite")
            with self.assertRaises(sqlite3.DatabaseError):
                smoke.database_state(path)

    def test_state_snapshot_detects_rewrite_and_new_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "flower.yaml"
            path.write_bytes(b"configuration")
            before = smoke.state_snapshot(root)
            path.write_bytes(b"changed configuration")
            self.assertNotEqual(smoke.state_snapshot(root), before)
            (root / "unexpected").mkdir()
            self.assertIn("unexpected", smoke.state_snapshot(root))


if __name__ == "__main__":
    unittest.main()
