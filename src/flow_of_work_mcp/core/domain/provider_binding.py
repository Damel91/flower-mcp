"""Durable Flow-project bindings to authorized implementation providers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id


class ImplementationProviderKind(StrEnum):
    IMPLEMENTATION_GRAPH = "implementation_graph"
    BOOTSTRAP_BEHAVIOR = "bootstrap_behavior"
    PACKET_EVIDENCE = "packet_evidence"
    PACKET_EXECUTION = "packet_execution"
    TEST_EXECUTION = "test_execution"


_EXECUTION_KINDS = frozenset(
    {ImplementationProviderKind.PACKET_EXECUTION, ImplementationProviderKind.TEST_EXECUTION}
)


@dataclass(frozen=True)
class ProviderProjectBindingDraft:
    provider_kind: ImplementationProviderKind
    provider_id: str
    scope_id: str
    surfaces: tuple[str, ...]
    provider_context_id: str = ""
    replacement_reason: str = ""
    repository: str | int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_kind", ImplementationProviderKind(self.provider_kind))
        object.__setattr__(self, "provider_id", required_text(self.provider_id, "provider_id"))
        object.__setattr__(self, "scope_id", _scope_id(self.scope_id, self.provider_kind))
        surfaces = tuple(required_text(value, "surfaces") for value in self.surfaces)
        if not surfaces and self.provider_kind not in _EXECUTION_KINDS:
            raise ValueError("provider binding requires at least one surface")
        if len(surfaces) != len(set(surfaces)):
            raise ValueError("provider binding surfaces must be unique")
        if len(surfaces) > 16:
            raise ValueError("provider binding surfaces exceed the supported bound")
        object.__setattr__(self, "surfaces", surfaces)
        object.__setattr__(
            self,
            "provider_context_id",
            _provider_context_id(self.provider_context_id),
        )
        object.__setattr__(self, "replacement_reason", str(self.replacement_reason or "").strip())
        object.__setattr__(self, "repository", _repository(self.repository, self.provider_kind))
        if self.provider_kind in _EXECUTION_KINDS and not self.provider_context_id:
            raise ValueError("execution provider binding requires provider_context_id")


@dataclass(frozen=True)
class ProviderProjectBinding:
    project_id: str
    provider_kind: ImplementationProviderKind
    provider_id: str
    scope_id: str
    surfaces: tuple[str, ...]
    provider_context_id: str = ""
    revision: int = 1
    repository: str | int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", validate_project_id(self.project_id))
        object.__setattr__(self, "provider_kind", ImplementationProviderKind(self.provider_kind))
        object.__setattr__(self, "provider_id", required_text(self.provider_id, "provider_id"))
        object.__setattr__(self, "scope_id", _scope_id(self.scope_id, self.provider_kind))
        surfaces = tuple(required_text(value, "surfaces") for value in self.surfaces)
        if (not surfaces and self.provider_kind not in _EXECUTION_KINDS) or len(surfaces) != len(set(surfaces)):
            raise ValueError("provider binding surfaces must be non-empty and unique")
        if self.revision <= 0:
            raise ValueError("provider binding revision must be positive")
        object.__setattr__(self, "surfaces", surfaces)
        object.__setattr__(
            self,
            "provider_context_id",
            _provider_context_id(self.provider_context_id),
        )
        object.__setattr__(self, "repository", _repository(self.repository, self.provider_kind))
        if self.provider_kind in _EXECUTION_KINDS and not self.provider_context_id:
            raise ValueError("execution provider binding requires provider_context_id")


def _scope_id(value: str, kind: ImplementationProviderKind) -> str:
    if kind in _EXECUTION_KINDS:
        return str(value or "").strip()
    return required_text(value, "scope_id")


def _repository(value: str | int | None, kind: ImplementationProviderKind):
    if value is None:
        return None
    if kind != ImplementationProviderKind.TEST_EXECUTION:
        raise ValueError("repository selector is supported only for test_execution")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("repository must be a string, integer or null")
    if isinstance(value, int):
        if value < 1:
            raise ValueError("repository number must be positive")
        return value
    return required_text(value, "repository")


def _provider_context_id(value: str) -> str:
    context_id = str(value or "").strip()
    if len(context_id) > 256:
        raise ValueError("provider_context_id exceeds the supported bound")
    if any(ord(character) < 32 or ord(character) == 127 for character in context_id):
        raise ValueError("provider_context_id contains control characters")
    return context_id
