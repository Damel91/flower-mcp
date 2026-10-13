"""Deterministic portability boundaries; installed qualification is separate."""
import builtins
from pathlib import Path
import socket
import tomllib

import pytest

from flow_of_work_mcp.config import FlowConfigError, ModelConfig
from flow_of_work_mcp.runtime_factory import build_model_gateway
from flow_of_work_mcp.adapters.documents.markdown_srs import markdown_parser_status


PUBLIC_RUNTIME_REQUIREMENT = (
    "runtime-llama @ https://github.com/Damel91/llama-runtime/releases/download/v0.4.1/"
    "runtime_llama-0.4.1-py3-none-any.whl"
    "#sha256=8c512eb79b00ac3fdf761036fa0c8d74c24c3581651332736f6a95e6e38ae0aa"
)


def block_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("optional inference composition attempted network access")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_disabled_inference_does_not_import_adapter(monkeypatch):
    original = builtins.__import__
    forbidden = {"lmstudio_agent_runtime", "lmstudio", "openai", "runtime_llama", "flow_of_work_mcp.adapters.model_runtime"}

    def guarded(name, *args, **kwargs):
        if any(name == module or name.startswith(module + ".") for module in forbidden):
            pytest.fail("core attempted an optional inference import")
        return original(name, *args, **kwargs)

    block_network(monkeypatch)
    monkeypatch.setattr(builtins, "__import__", guarded)
    assert build_model_gateway(ModelConfig(enabled=False)) is None


def test_selected_absent_inference_explains_missing_extra(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "flow_of_work_mcp.adapters.model_runtime":
            raise ModuleNotFoundError("optional inference absent", name="runtime_llama")
        return original(name, *args, **kwargs)

    block_network(monkeypatch)
    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(FlowConfigError, match=r"flow-of-work-mcp\[inference\]") as caught:
        build_model_gateway(ModelConfig(enabled=True, model="authorized-model"))
    message = str(caught.value)
    for required in ("selected current Flower source or wheel", "python -m pip install '.[inference]'",
                     "hash-pinned public runtime-llama", "authorized model endpoint", "model.enabled=false"):
        assert required in message
    assert "--find-links" not in message
    assert "supplied in the Flower release" not in message
    assert "pip install flow-of-work-mcp[inference]" not in message


def test_source_dependency_pin_and_core_grammars_are_reachable():
    # This is a source contract check. Installed wheel metadata/markers are
    # qualified separately in a fresh environment, never from iaEnv's editable install.
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())["project"]
    assert project["optional-dependencies"]["inference"] == [PUBLIC_RUNTIME_REQUIREMENT]
    dependencies = project["dependencies"]
    assert all("runtime-llama" not in item.lower().replace("_", "-") for item in dependencies)
    assert "mcp>=1.23,<2" in dependencies
    assert all("tree-sitter-language-pack" not in item for item in dependencies)
    assert markdown_parser_status()["available"] is True


def test_unrelated_missing_import_is_not_mislabeled_as_optional_runtime_absence(monkeypatch):
    original = builtins.__import__
    failure = ModuleNotFoundError("another dependency is unavailable", name="other_adapter_dependency")

    def guarded(name, *args, **kwargs):
        if name == "flow_of_work_mcp.adapters.model_runtime":
            raise failure
        return original(name, *args, **kwargs)

    block_network(monkeypatch)
    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(ModuleNotFoundError) as caught:
        build_model_gateway(ModelConfig(enabled=True, model="authorized-model"))
    assert caught.value is failure
