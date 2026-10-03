"""Persistence boundary for project-scoped implementation-provider bindings."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.provider_binding import (
    ImplementationProviderKind,
    ProviderProjectBinding,
    ProviderProjectBindingDraft,
)


class ProviderProjectBindingRepository(Protocol):
    def bind_provider_project(
        self,
        project_id: str,
        draft: ProviderProjectBindingDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def resolve_provider_binding(
        self,
        project_id: str,
        provider_kind: ImplementationProviderKind | str,
    ) -> ProviderProjectBinding | None: ...

    def list_provider_bindings(self, project_id: str) -> list[Mapping[str, object]]: ...
