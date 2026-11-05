"""Exercise CLI recovery boundaries with independent SQLite fixtures."""
from pathlib import Path
import json
import os

import pytest

from flow_of_work_mcp.cli import main
from flow_of_work_mcp.config import load_config
from flow_of_work_mcp.ledger_archive import ArchiveError
from flow_of_work_mcp.ledger_recovery import backup_profile, inspect_or_restore
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_runtime_ownership
from tests.test_native_project_purge import _fixture, _rows


def test_restore_to_new_profile_without_replacing_the_origin(tmp_path, capsys):
    config, database = _fixture(tmp_path / "source")
    source_config = config.read_bytes()
    archive = tmp_path / "backup.flower.zip"
    result = backup_profile(config, archive)
    assert result["kind"] == "backup"
    main(["data", "inspect", "--archive", str(archive)])
    assert json.loads(capsys.readouterr().out)["verified"] is True
    target = tmp_path / "recovered"
    main(["data", "restore", "--archive", str(archive), "--restore-dir", str(target)])
    restored = json.loads(capsys.readouterr().out)
    loaded = load_config(Path(restored["profile_config"]))
    assert loaded.runtime.database_path == target / "ledger.sqlite3"
    assert loaded.runtime.import_root == target / "imports"
    assert loaded.packet_provider.mode == loaded.test_provider.mode == "agnostic"
    assert not loaded.model.enabled and not restored["server_started"]
    assert _rows(loaded.runtime.database_path) == _rows(database)
    assert config.read_bytes() == source_config
    previous = (target / "ledger.sqlite3").read_bytes()
    with pytest.raises(ArchiveError, match="new destination"):
        inspect_or_restore(archive, restore_dir=target)
    assert (target / "ledger.sqlite3").read_bytes() == previous


def test_active_owner_and_bad_input_never_publish(tmp_path):
    config, database = _fixture(tmp_path / "source")
    archive = tmp_path / "backup.flower.zip"
    with acquire_runtime_ownership(database), pytest.raises(RuntimeOwnershipError) as exc:
        backup_profile(config, archive)
    assert exc.value.code == "ledger_runtime_in_use"
    assert not archive.exists()
    archive.write_bytes(b"invalid archive")
    target = tmp_path / "recovered"
    with pytest.raises(ArchiveError):
        inspect_or_restore(archive, restore_dir=target)
    assert not os.path.lexists(target)
