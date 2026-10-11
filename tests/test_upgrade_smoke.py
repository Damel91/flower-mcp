"""Upgrade qualifier boundaries; no network, package install or domain services."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import smoke_upgrade as smoke


class UpgradeSmokeTests(unittest.TestCase):
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
