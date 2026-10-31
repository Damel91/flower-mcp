"""OpenCode V2 selected-file registration; no native client or user state."""
import json
from pathlib import Path
import sys

import pytest

from flow_of_work_mcp import cli
from flow_of_work_mcp import client_registration as clients


def registration(tmp_path):
    config = tmp_path / "client settings" / "opencode.json"
    return dict(platform="opencode", client_config=config,
                profile_config=tmp_path / "profile with spaces" / "config.yaml",
                receipt_path=clients.registration_receipt_path(tmp_path / "owned", "opencode", config),
                python_executable=Path(sys.executable))


def inspection(args):
    return {key: args[key] for key in ("platform", "client_config", "receipt_path")}


def test_opencode_default_paths_are_pure_and_explicit_home_ignores_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert clients.default_client_config("opencode") == tmp_path / "custom/opencode.json"
    assert clients.default_client_config("opencode", home=tmp_path / "home") == tmp_path / "home/.config/opencode/opencode.json"
    monkeypatch.delenv("OPENCODE_CONFIG_DIR")
    assert clients.default_client_config("opencode") == tmp_path / "xdg/opencode/opencode.json"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert clients.default_client_config("opencode") == tmp_path / "home/.config/opencode/opencode.json"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("variable", ["OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME"])
def test_relative_directory_override_is_refused_without_writes(tmp_path, monkeypatch, variable):
    monkeypatch.delenv("OPENCODE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv(variable, "relative-directory")
    with pytest.raises(clients.ClientRegistrationError) as error:
        clients.default_client_config("opencode")
    assert error.value.code == "client_path_invalid"
    assert list(tmp_path.iterdir()) == []


def test_opencode_nested_settings_receipts_replay_drift_and_removal(tmp_path):
    args = registration(tmp_path)
    config, receipt = args["client_config"], args["receipt_path"]
    config.parent.mkdir()
    original = {"mcp": {"timeout": {"startup": 12345}, "servers": {
        "other": {"type": "remote", "url": "https://example.invalid/mcp", "headers": {"secret": "SECRET_NEVER_REPORT_OPENCODE"}}}},
        "providers": {"local": {"settings": {"apiKey": "SECRET_NEVER_REPORT_OPENCODE"}}},
        "permissions": [{"action": "*", "resource": "*", "effect": "ask"}], "instructions": ["custom.md"]}
    config.write_text(json.dumps(original))
    before = config.read_bytes()
    dry = clients.register_client(**args, dry_run=True)
    assert not dry["changed"] and config.read_bytes() == before and not receipt.exists()
    clients.register_client(**args)
    document = json.loads(config.read_bytes())
    entry = document["mcp"]["servers"].pop("flower")
    assert document == original
    assert entry == {"type": "local", "command": [str(Path(sys.executable).absolute()), "-m", "flow_of_work_mcp.cli", "serve", "--config", str(args["profile_config"]), "--transport", "stdio"], "disabled": False, "codemode": False}
    persisted = json.loads(receipt.read_bytes())
    assert persisted["managed_entry"] == entry and persisted["contract"] == "flower.client-registration.v1"
    assert "SECRET_NEVER_REPORT_OPENCODE" not in json.dumps(persisted)
    assert Path(persisted["backup_path"]).read_bytes() == before
    stable = config.read_bytes(), receipt.read_bytes(), config.stat().st_mtime_ns, receipt.stat().st_mtime_ns
    assert not clients.register_client(**args)["changed"]
    assert (config.read_bytes(), receipt.read_bytes(), config.stat().st_mtime_ns, receipt.stat().st_mtime_ns) == stable
    changed = json.loads(config.read_bytes())
    changed["mcp"]["servers"]["flower"]["codemode"] = True
    config.write_text(json.dumps(changed))
    assert clients.inspect_client_registration(**inspection(args))["state"] == "diverged"
    with pytest.raises(clients.ClientRegistrationError):
        clients.unregister_client(**inspection(args))
    clients.register_client(**args, replace=True)
    clients.unregister_client(**inspection(args))
    assert json.loads(config.read_bytes()) == original
    assert not args["profile_config"].exists()


@pytest.mark.parametrize("raw", [
    '{"mcp":null}', '{"mcp":[]}', '{"mcp":{"servers":null}}', '{"mcp":{"servers":[]}}',
    '{"mcp":{"servers":{},"servers":{}}}', '{/* private-comment */ "mcp":{}}',
])
def test_invalid_opencode_config_is_preserved_without_receipt(tmp_path, raw):
    args = registration(tmp_path)
    args["client_config"].parent.mkdir()
    args["client_config"].write_text(raw)
    with pytest.raises(clients.ClientRegistrationError) as error:
        clients.register_client(**args)
    assert error.value.code in {"client_json_invalid", "client_config_invalid"}
    assert "private-comment" not in str(error.value)
    assert args["client_config"].read_text() == raw and not args["receipt_path"].exists()


@pytest.mark.parametrize("kind", ["local", "remote"])
def test_v1_direct_server_requires_explicit_native_migration(tmp_path, kind):
    args = registration(tmp_path)
    args["client_config"].parent.mkdir()
    original = json.dumps({"mcp": {"old": {"type": kind, "command": ["private"]}}})
    args["client_config"].write_text(original)
    with pytest.raises(clients.ClientRegistrationError) as error:
        clients.register_client(**args)
    assert error.value.code == "client_opencode_v1_config"
    assert args["client_config"].read_text() == original and not args["receipt_path"].exists()


@pytest.mark.parametrize("name", ["servers", "timeout"])
def test_v1_server_named_reserved_key_cannot_be_misread_as_v2_container(tmp_path, name):
    args = registration(tmp_path)
    args["client_config"].parent.mkdir()
    original = json.dumps({"mcp": {name: {"type": "local", "command": ["old-server"]}}})
    args["client_config"].write_text(original)
    with pytest.raises(clients.ClientRegistrationError) as error:
        clients.register_client(**args)
    assert error.value.code == "client_opencode_v1_config"
    assert args["client_config"].read_text() == original and not args["receipt_path"].exists()


@pytest.mark.parametrize("field", ["disabled", "codemode"])
@pytest.mark.parametrize("value", [0, 0.0])
@pytest.mark.parametrize("target", ["config", "receipt"])
def test_numeric_false_is_not_a_boolean_owned_entry(tmp_path, field, value, target):
    args = registration(tmp_path)
    clients.register_client(**args)
    path = args["client_config"] if target == "config" else args["receipt_path"]
    document = json.loads(path.read_bytes())
    entry = document["mcp"]["servers"]["flower"] if target == "config" else document["managed_entry"]
    entry[field] = value
    path.write_text(json.dumps(document))
    before = args["client_config"].read_bytes(), args["receipt_path"].read_bytes()
    if target == "config":
        assert clients.inspect_client_registration(**inspection(args))["state"] == "diverged"
    else:
        with pytest.raises(clients.ClientRegistrationError, match="invalid"):
            clients.inspect_client_registration(**inspection(args))
    for action in (lambda: clients.register_client(**args), lambda: clients.unregister_client(**inspection(args))):
        with pytest.raises(clients.ClientRegistrationError):
            action()
    assert (args["client_config"].read_bytes(), args["receipt_path"].read_bytes()) == before


@pytest.mark.parametrize("kind", ["file", "directory", "dangling-symlink"])
def test_implicit_jsonc_guard_precedes_all_profile_writes(tmp_path, monkeypatch, kind):
    directory = tmp_path / "config"
    directory.mkdir()
    sibling = directory / "opencode.jsonc"
    if kind == "file":
        sibling.write_text("// private-comment\n{}")
    elif kind == "directory":
        sibling.mkdir()
    else:
        try:
            sibling.symlink_to(tmp_path / "absent")
        except OSError:
            pytest.skip("Symlinks unavailable")
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(directory))
    with pytest.raises(SystemExit) as error:
        cli.main(["install", "--platform", "opencode", "--profile-root", str(tmp_path / "profiles")])
    assert error.value.code == 2
    assert not (tmp_path / "profiles").exists() and not (directory / "opencode.json").exists()


def test_explicit_config_and_doctor_removal_work_with_default_jsonc(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(directory))
    options = ["--platform", "opencode", "--profile-root", str(tmp_path / "profiles")]
    cli.main(["install", *options])
    first = json.loads(capsys.readouterr().out)
    profile = Path(first["profile_config"])
    ledger = profile.with_name("ledger.sqlite3")
    ledger.write_bytes(b"existing-owned-ledger-sentinel")
    sibling = directory / "opencode.jsonc"
    sibling.write_text("// untouched\n{}")
    baseline = profile.read_bytes(), ledger.read_bytes()
    cli.main(["doctor", *options])
    assert json.loads(capsys.readouterr().out)["registration"]["state"] == "registered"
    cli.main(["install", *options, "--client-config", str(directory / "opencode.json")])
    assert not json.loads(capsys.readouterr().out)["changed"]
    cli.main(["uninstall", *options])
    assert json.loads(capsys.readouterr().out)["state"] == "absent"
    assert (profile.read_bytes(), ledger.read_bytes()) == baseline and sibling.read_text() == "// untouched\n{}"


def test_explicit_file_selection_bypasses_invalid_default_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", "relative-invalid")
    config = tmp_path / "selected.json"
    cli.main(["install", "--platform", "opencode", "--client-config", str(config), "--profile-root", str(tmp_path / "profiles"), "--dry-run"])
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert list(tmp_path.iterdir()) == []
