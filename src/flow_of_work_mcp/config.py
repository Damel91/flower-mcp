"""Strict standalone runtime configuration for Flow of Work MCP."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from flow_of_work_mcp.core.domain.provider_surfaces import (
    CODINGCASTLE_BOOTSTRAP_SURFACES,
    codingcastle_provider_surfaces,
)


class FlowConfigError(ValueError):
    """Raised before runtime side effects when configuration is invalid."""


@dataclass(frozen=True)
class RuntimeConfig:
    database_path: Path
    import_root: Path
    job_workers: int = 1


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    enable_console: bool
    logs_path: Path


@dataclass(frozen=True)
class ModelConfig:
    enabled: bool = False
    backend: str = "llamacpp"
    model: str = ""
    base_url: str = "http://127.0.0.1:8080"
    context_length: int | None = None
    api_key_env: str | None = None
    idle_timeout_sec: float = 30.0
    verify_ssl: bool = True
    temperature: float = 0.1
    reasoning: str = "auto"


@dataclass(frozen=True)
class ProviderBindingConfig:
    project_id: str
    scope_id: str
    provider_context_id: str = ""
    surfaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderConfig:
    enabled: bool
    url: str
    tool: str
    invocation: str
    session_id: str
    domain: str
    operation: str
    surfaces: tuple[str, ...]
    bindings: tuple[ProviderBindingConfig, ...]


@dataclass(frozen=True)
class PacketProviderProjectConfig:
    project_id: str
    provider_session_id: str


@dataclass(frozen=True)
class PacketProviderConfig:
    mode: str = "agnostic"
    kind: str = "codingcastle"
    endpoint: str = ""
    tool: str = "codingcastle_packet"
    timeout_seconds: float = 30.0
    bindings: tuple[PacketProviderProjectConfig, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)


@dataclass(frozen=True)
class TestProviderProjectConfig:
    project_id: str
    provider_session_id: str
    repository: str | int | None = None


@dataclass(frozen=True)
class TestProviderConfig:
    mode: str = "agnostic"
    kind: str = "codingcastle"
    endpoint: str = ""
    tool: str = "codingcastle_tests"
    timeout_seconds: float = 30.0
    bindings: tuple[TestProviderProjectConfig, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)


@dataclass(frozen=True)
class FlowConfig:
    schema_version: int
    source_path: Path
    runtime: RuntimeConfig
    logging: LoggingConfig
    model: ModelConfig
    implementation_graph_provider: ProviderConfig
    bootstrap_behavior_provider: ProviderConfig
    packet_evidence_provider: ProviderConfig
    packet_provider: PacketProviderConfig
    test_provider: TestProviderConfig

    def safe_summary(self) -> Mapping[str, object]:
        """Return non-secret startup metadata suitable for logging."""

        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "config_path": str(self.source_path),
                "database_path": str(self.runtime.database_path),
                "import_root": str(self.runtime.import_root),
                "logs_path": str(self.logging.logs_path),
                "model_enabled": self.model.enabled,
                "model_backend": self.model.backend if self.model.enabled else "disabled",
                "implementation_provider_enabled": self.implementation_graph_provider.enabled,
                "bootstrap_provider_enabled": self.bootstrap_behavior_provider.enabled,
                "packet_evidence_provider_enabled": self.packet_evidence_provider.enabled,
                "packet_provider_mode": self.packet_provider.mode,
                "packet_provider_kind": self.packet_provider.kind,
                "packet_provider_configured": self.packet_provider.configured,
                "test_provider_mode": self.test_provider.mode,
                "test_provider_kind": self.test_provider.kind,
                "test_provider_configured": self.test_provider.configured,
            }
        )


_ROOT_KEYS = {
    "schema_version",
    "runtime",
    "logging",
    "model",
    "providers",
    "packet_provider",
    "test_provider",
}
_RUNTIME_KEYS = {"database_path", "import_root", "job_workers"}
_LOGGING_KEYS = {"level", "enable_console", "logs_path"}
_MODEL_KEYS = {
    "enabled",
    "backend",
    "model",
    "base_url",
    "context_length",
    "auto_load",  # Recognized only to produce an explicit migration error.
    "api_key_env",
    "idle_timeout_sec",
    "verify_ssl",
    "temperature",
    "reasoning",
}
_PROVIDERS_KEYS = {"implementation_graph", "bootstrap_behavior", "packet_evidence"}
_PROVIDER_KEYS = {
    "enabled",
    "url",
    "tool",
    "invocation",
    "session_id",
    "domain",
    "operation",
    "surfaces",
    "bindings",
}
_BINDING_KEYS = {"project_id", "scope_id", "provider_context_id", "surfaces"}
_PACKET_PROVIDER_KEYS = {
    "mode",
    "kind",
    "endpoint",
    "tool",
    "timeout_seconds",
    "bindings",
}
_PACKET_PROVIDER_BINDING_KEYS = {"project_id", "provider_session_id"}
_TEST_PROVIDER_KEYS = {
    "mode",
    "kind",
    "endpoint",
    "tool",
    "timeout_seconds",
    "bindings",
}
_TEST_PROVIDER_BINDING_KEYS = {
    "project_id",
    "provider_session_id",
    "repository",
}


def load_config(path: str | Path) -> FlowConfig:
    """Load and validate a v1 YAML configuration without runtime side effects."""

    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise FlowConfigError(f"configuration file not found: {source_path}")
    try:
        raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FlowConfigError("configuration file is not valid YAML") from exc
    root = _mapping(raw, "configuration")
    _reject_unknown(root, _ROOT_KEYS, "configuration")
    schema_version = _integer(root.get("schema_version"), "schema_version", minimum=1)
    if schema_version != 1:
        raise FlowConfigError(f"unsupported schema_version: {schema_version}")

    base = source_path.parent
    runtime_raw = _mapping(root.get("runtime"), "runtime")
    _reject_unknown(runtime_raw, _RUNTIME_KEYS, "runtime")
    runtime = RuntimeConfig(
        database_path=_path(runtime_raw.get("database_path"), "runtime.database_path", base),
        import_root=_path(runtime_raw.get("import_root"), "runtime.import_root", base),
        job_workers=_integer(runtime_raw.get("job_workers", 1), "runtime.job_workers", minimum=1),
    )

    logging_raw = _mapping(root.get("logging"), "logging")
    _reject_unknown(logging_raw, _LOGGING_KEYS, "logging")
    level = _string(logging_raw.get("level", "INFO"), "logging.level").upper()
    if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
        raise FlowConfigError("logging.level is not supported")
    logging_config = LoggingConfig(
        level=level,
        enable_console=_boolean(
            logging_raw.get("enable_console", True), "logging.enable_console"
        ),
        logs_path=_path(logging_raw.get("logs_path"), "logging.logs_path", base),
    )

    model_raw = _mapping(root.get("model", {}), "model")
    _reject_unknown(model_raw, _MODEL_KEYS, "model")
    model = _model_config(model_raw)

    providers_raw = _mapping(root.get("providers", {}), "providers")
    _reject_unknown(providers_raw, _PROVIDERS_KEYS, "providers")
    implementation = _provider_config(
        _mapping(providers_raw.get("implementation_graph", {}), "providers.implementation_graph"),
        field="providers.implementation_graph",
        default_tool="implementation_graph_snapshot",
        default_surfaces=("repo",),
        reject_default_advanced_tool=True,
    )
    bootstrap = _provider_config(
        _mapping(providers_raw.get("bootstrap_behavior", {}), "providers.bootstrap_behavior"),
        field="providers.bootstrap_behavior",
        default_tool="",
        default_surfaces=CODINGCASTLE_BOOTSTRAP_SURFACES,
        reject_default_advanced_tool=False,
    )
    _validate_codingcastle_provider_config(
        bootstrap,
        field="providers.bootstrap_behavior",
        require_repo=True,
    )
    packet_evidence = _provider_config(
        _mapping(providers_raw.get("packet_evidence", {}), "providers.packet_evidence"),
        field="providers.packet_evidence",
        default_tool="",
        default_surfaces=("repo",),
        reject_default_advanced_tool=False,
    )
    packet_provider = _packet_provider_config(
        _mapping(root.get("packet_provider", {}), "packet_provider")
    )
    test_provider = _test_provider_config(
        _mapping(root.get("test_provider", {}), "test_provider")
    )
    return FlowConfig(
        schema_version=schema_version,
        source_path=source_path,
        runtime=runtime,
        logging=logging_config,
        model=model,
        implementation_graph_provider=implementation,
        bootstrap_behavior_provider=bootstrap,
        packet_evidence_provider=packet_evidence,
        packet_provider=packet_provider,
        test_provider=test_provider,
    )


def _model_config(raw: Mapping[str, Any]) -> ModelConfig:
    if "auto_load" in raw:
        raise FlowConfigError(
            "model.auto_load is no longer supported; remove it. "
            "runtime-llama uses server-owned model loading and never launches models"
        )
    enabled = _boolean(raw.get("enabled", False), "model.enabled")
    backend = _string(raw.get("backend", "llamacpp"), "model.backend").lower()
    if backend != "llamacpp":
        raise FlowConfigError(
            "model.backend must be llamacpp; migrate legacy lmstudio configuration "
            "to a llama.cpp HTTP endpoint and remove auto_load"
        )
    model = _string(raw.get("model", ""), "model.model", allow_empty=True)
    base_url = _string(
        raw.get("base_url", "http://127.0.0.1:8080"),
        "model.base_url",
    )
    if enabled and not model:
        raise FlowConfigError("model.model must be non-empty when model.enabled is true")
    context_value = raw.get("context_length", 0)
    context_length = _integer(context_value, "model.context_length", minimum=0)
    reasoning = _string(raw.get("reasoning", "auto"), "model.reasoning").lower()
    if reasoning not in {"auto", "off", "on", "low", "medium", "high"}:
        raise FlowConfigError("model.reasoning must be auto, off, on, low, medium or high")
    temperature = _number(raw.get("temperature", 0.1), "model.temperature", exclusive_minimum=-1)
    if temperature < 0:
        raise FlowConfigError("model.temperature must be non-negative")
    return ModelConfig(
        enabled=enabled,
        backend=backend,
        model=model,
        base_url=base_url,
        context_length=context_length or None,
        api_key_env=_optional_string(raw.get("api_key_env"), "model.api_key_env"),
        idle_timeout_sec=_number(
            raw.get("idle_timeout_sec", 30.0), "model.idle_timeout_sec", exclusive_minimum=0
        ),
        verify_ssl=_boolean(raw.get("verify_ssl", True), "model.verify_ssl"),
        temperature=temperature,
        reasoning=reasoning,
    )


def _provider_config(
    raw: Mapping[str, Any],
    *,
    field: str,
    default_tool: str,
    default_surfaces: tuple[str, ...],
    reject_default_advanced_tool: bool,
) -> ProviderConfig:
    _reject_unknown(raw, _PROVIDER_KEYS, field)
    enabled = _boolean(raw.get("enabled", False), f"{field}.enabled")
    url = _string(raw.get("url", ""), f"{field}.url", allow_empty=True)
    tool = _string(raw.get("tool", default_tool), f"{field}.tool", allow_empty=True)
    invocation = _string(raw.get("invocation", "direct"), f"{field}.invocation").lower()
    if invocation not in {"direct", "advanced"}:
        raise FlowConfigError(f"{field}.invocation must be direct or advanced")
    session_id = _string(raw.get("session_id", ""), f"{field}.session_id", allow_empty=True)
    domain = _string(raw.get("domain", ""), f"{field}.domain", allow_empty=True)
    operation = _string(raw.get("operation", ""), f"{field}.operation", allow_empty=True)
    surfaces = _string_tuple(raw.get("surfaces", list(default_surfaces)), f"{field}.surfaces")
    bindings_raw = _list(raw.get("bindings", []), f"{field}.bindings")
    bindings: list[ProviderBindingConfig] = []
    for index, item in enumerate(bindings_raw):
        binding_field = f"{field}.bindings[{index}]"
        mapping = _mapping(item, binding_field)
        _reject_unknown(mapping, _BINDING_KEYS, binding_field)
        binding_surfaces = (
            _string_tuple(mapping["surfaces"], f"{binding_field}.surfaces")
            if "surfaces" in mapping
            else ()
        )
        if binding_surfaces and not set(binding_surfaces).issubset(surfaces):
            raise FlowConfigError(
                f"{binding_field}.surfaces must be authorized by {field}.surfaces"
            )
        bindings.append(
            ProviderBindingConfig(
                project_id=_string(mapping.get("project_id"), f"{binding_field}.project_id"),
                scope_id=_string(mapping.get("scope_id"), f"{binding_field}.scope_id"),
                provider_context_id=_string(
                    mapping.get("provider_context_id", ""),
                    f"{binding_field}.provider_context_id",
                    allow_empty=True,
                ),
                surfaces=binding_surfaces,
            )
        )
    project_ids = [binding.project_id for binding in bindings]
    if len(project_ids) != len(set(project_ids)):
        raise FlowConfigError(f"{field}.bindings project_id values must be unique")
    if enabled:
        if not url.startswith(("http://", "https://")):
            raise FlowConfigError(f"{field}.url must be an HTTP(S) URL when enabled")
        if not tool:
            raise FlowConfigError(f"{field}.tool must be non-empty when enabled")
        if invocation == "advanced":
            if reject_default_advanced_tool and tool == default_tool:
                raise FlowConfigError(f"{field}.tool must name an explicit advanced gateway")
            if not all((session_id, domain, operation)):
                raise FlowConfigError(
                    f"{field} advanced invocation requires session_id, domain and operation"
                )
        elif any((session_id, domain, operation)):
            raise FlowConfigError(f"{field} direct invocation cannot include advanced fields")
        if invocation == "direct" and any(binding.provider_context_id for binding in bindings):
            raise FlowConfigError(
                f"{field} direct invocation cannot include binding provider_context_id"
            )
    return ProviderConfig(
        enabled=enabled,
        url=url,
        tool=tool,
        invocation=invocation,
        session_id=session_id,
        domain=domain,
        operation=operation,
        surfaces=surfaces,
        bindings=tuple(bindings),
    )


def _validate_codingcastle_provider_config(
    provider: ProviderConfig,
    *,
    field: str,
    require_repo: bool,
) -> None:
    try:
        codingcastle_provider_surfaces(
            provider.surfaces,
            require_repo=require_repo,
        )
        for index, binding in enumerate(provider.bindings):
            if binding.surfaces:
                codingcastle_provider_surfaces(
                    binding.surfaces,
                    require_repo=require_repo,
                )
    except ValueError as exc:
        raise FlowConfigError(f"{field}.surfaces are invalid: {exc}") from exc


def _packet_provider_config(raw: Mapping[str, Any]) -> PacketProviderConfig:
    field = "packet_provider"
    _reject_unknown(raw, _PACKET_PROVIDER_KEYS, field)
    mode = _string(raw.get("mode", "agnostic"), f"{field}.mode").lower()
    if mode not in {"agnostic", "auto", "required"}:
        raise FlowConfigError(
            "packet_provider.mode must be agnostic, auto or required"
        )
    kind = _string(raw.get("kind", "codingcastle"), f"{field}.kind").lower()
    endpoint = _string(
        raw.get("endpoint", ""), f"{field}.endpoint", allow_empty=True
    )
    tool = _string(
        raw.get("tool", "codingcastle_packet"),
        f"{field}.tool",
        allow_empty=True,
    )
    timeout_seconds = _number(
        raw.get("timeout_seconds", 30.0),
        f"{field}.timeout_seconds",
        exclusive_minimum=0,
    )
    bindings: list[PacketProviderProjectConfig] = []
    for index, raw_binding in enumerate(
        _list(raw.get("bindings", []), f"{field}.bindings")
    ):
        binding_field = f"{field}.bindings[{index}]"
        binding = _mapping(raw_binding, binding_field)
        _reject_unknown(binding, _PACKET_PROVIDER_BINDING_KEYS, binding_field)
        bindings.append(
            PacketProviderProjectConfig(
                project_id=_string(
                    binding.get("project_id"), f"{binding_field}.project_id"
                ),
                provider_session_id=_string(
                    binding.get("provider_session_id"),
                    f"{binding_field}.provider_session_id",
                ),
            )
        )
    project_ids = [item.project_id for item in bindings]
    if len(project_ids) != len(set(project_ids)):
        raise FlowConfigError("packet_provider.bindings project_id values must be unique")
    configured = bool(endpoint or bindings)
    if configured:
        if kind != "codingcastle":
            raise FlowConfigError("packet_provider.kind must be codingcastle")
        if not endpoint.startswith(("http://", "https://")):
            raise FlowConfigError(
                "packet_provider.endpoint must be an HTTP(S) URL when configured"
            )
        if tool != "codingcastle_packet":
            raise FlowConfigError(
                "packet_provider.tool must be codingcastle_packet"
            )
    if mode == "required" and not configured:
        raise FlowConfigError("required packet_provider must be configured")
    return PacketProviderConfig(
        mode=mode,
        kind=kind,
        endpoint=endpoint,
        tool=tool,
        timeout_seconds=timeout_seconds,
        bindings=tuple(bindings),
    )


def _test_provider_config(raw: Mapping[str, Any]) -> TestProviderConfig:
    field = "test_provider"
    _reject_unknown(raw, _TEST_PROVIDER_KEYS, field)
    mode = _string(raw.get("mode", "agnostic"), f"{field}.mode").lower()
    if mode not in {"agnostic", "auto", "required"}:
        raise FlowConfigError(
            "test_provider.mode must be agnostic, auto or required"
        )
    kind = _string(raw.get("kind", "codingcastle"), f"{field}.kind").lower()
    endpoint = _string(
        raw.get("endpoint", ""), f"{field}.endpoint", allow_empty=True
    )
    tool = _string(
        raw.get("tool", "codingcastle_tests"),
        f"{field}.tool",
        allow_empty=True,
    )
    timeout_seconds = _number(
        raw.get("timeout_seconds", 30.0),
        f"{field}.timeout_seconds",
        exclusive_minimum=0,
    )
    bindings: list[TestProviderProjectConfig] = []
    for index, raw_binding in enumerate(
        _list(raw.get("bindings", []), f"{field}.bindings")
    ):
        binding_field = f"{field}.bindings[{index}]"
        binding = _mapping(raw_binding, binding_field)
        _reject_unknown(binding, _TEST_PROVIDER_BINDING_KEYS, binding_field)
        bindings.append(
            TestProviderProjectConfig(
                project_id=_string(
                    binding.get("project_id"), f"{binding_field}.project_id"
                ),
                provider_session_id=_string(
                    binding.get("provider_session_id"),
                    f"{binding_field}.provider_session_id",
                ),
                repository=_repository_selector(
                    binding.get("repository"), f"{binding_field}.repository"
                ),
            )
        )
    project_ids = [item.project_id for item in bindings]
    if len(project_ids) != len(set(project_ids)):
        raise FlowConfigError("test_provider.bindings project_id values must be unique")
    configured = bool(endpoint or bindings)
    if configured:
        if kind != "codingcastle":
            raise FlowConfigError("test_provider.kind must be codingcastle")
        if not endpoint.startswith(("http://", "https://")):
            raise FlowConfigError(
                "test_provider.endpoint must be an HTTP(S) URL when configured"
            )
        if tool != "codingcastle_tests":
            raise FlowConfigError("test_provider.tool must be codingcastle_tests")
    if mode == "required" and not configured:
        raise FlowConfigError("required test_provider must be configured")
    return TestProviderConfig(
        mode=mode,
        kind=kind,
        endpoint=endpoint,
        tool=tool,
        timeout_seconds=timeout_seconds,
        bindings=tuple(bindings),
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FlowConfigError(f"{field} must be a mapping")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise FlowConfigError(f"{field} must be a list")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise FlowConfigError(f"{field} contains unknown keys: {', '.join(unknown)}")


def _string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise FlowConfigError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise FlowConfigError(f"{field} must be non-empty")
    return normalized


def _optional_string(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _string(value, field)


def _repository_selector(value: Any, field: str) -> str | int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise FlowConfigError(f"{field} must be a non-empty string or integer")
    if isinstance(value, str):
        return _string(value, field)
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise FlowConfigError(f"{field} must be boolean")
    return value


def _integer(value: Any, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FlowConfigError(f"{field} must be an integer")
    if value < minimum:
        raise FlowConfigError(f"{field} must be >= {minimum}")
    return value


def _number(value: Any, field: str, *, exclusive_minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FlowConfigError(f"{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= exclusive_minimum:
        raise FlowConfigError(f"{field} must be > {exclusive_minimum}")
    return parsed


def _path(value: Any, field: str, base: Path) -> Path:
    raw = _string(value, field)
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    values = _list(value, field)
    normalized = tuple(_string(item, f"{field}[]") for item in values)
    if not normalized:
        raise FlowConfigError(f"{field} must be non-empty")
    if len(normalized) != len(set(normalized)):
        raise FlowConfigError(f"{field} values must be unique")
    return normalized
