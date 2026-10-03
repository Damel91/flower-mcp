"""Policy for binding projects to pre-authorized implementation providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.provider_binding import (
    ImplementationProviderKind,
    ProviderProjectBindingDraft,
)
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, ProjectNotFoundError
from flow_of_work_mcp.core.ports.provider_binding import ProviderProjectBindingRepository


@dataclass(frozen=True)
class ProviderBindingAuthorization:
    provider_kind: ImplementationProviderKind
    provider_id: str
    surfaces: tuple[str, ...]
    supports_context_binding: bool = False
    default_provider_context_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_kind", ImplementationProviderKind(self.provider_kind))
        object.__setattr__(self, "provider_id", required_text(self.provider_id, "provider_id"))
        surfaces = tuple(required_text(value, "surfaces") for value in self.surfaces)
        execution_kind = self.provider_kind in {
            ImplementationProviderKind.PACKET_EXECUTION,
            ImplementationProviderKind.TEST_EXECUTION,
        }
        if (not surfaces and not execution_kind) or len(surfaces) != len(set(surfaces)):
            raise ValueError("provider authorization surfaces must be non-empty and unique")
        object.__setattr__(self, "surfaces", surfaces)
        default_context = str(self.default_provider_context_id or "").strip()
        if default_context and not self.supports_context_binding:
            raise ValueError(
                "provider authorization without context support cannot have a default context"
            )
        object.__setattr__(self, "default_provider_context_id", default_context)


class ProviderBindingService:
    """Own dynamic scope binding without granting transport configuration authority."""

    def __init__(
        self,
        repository: ProviderProjectBindingRepository,
        authorizations: tuple[ProviderBindingAuthorization, ...] = (),
    ) -> None:
        self._repository = repository
        self._authorizations = {item.provider_kind: item for item in authorizations}
        if len(self._authorizations) != len(authorizations):
            raise ValueError("provider binding authorizations must be unique")

    def bind(
        self,
        project_id: str,
        *,
        provider_kind: ImplementationProviderKind | str,
        scope_id: str,
        surfaces: tuple[str, ...] = (),
        provider_context_id: str = "",
        actor: str,
        replacement_reason: str = "",
        request_id: str = "",
        repository: str | int | None = None,
    ) -> Mapping[str, object]:
        kind = ImplementationProviderKind(provider_kind)
        authorization = self._authorizations.get(kind)
        if authorization is None:
            raise ChangeControlBlockedError(
                "implementation_provider_kind_disabled",
                details={"provider_kind": kind.value},
            )
        selected_surfaces = tuple(surfaces or authorization.surfaces)
        execution_kind = kind in {
            ImplementationProviderKind.PACKET_EXECUTION,
            ImplementationProviderKind.TEST_EXECUTION,
        }
        if (not selected_surfaces and not execution_kind) or not set(selected_surfaces).issubset(authorization.surfaces):
            raise ChangeControlBlockedError(
                "implementation_provider_surfaces_unauthorized",
                details={"provider_kind": kind.value},
            )
        requested_context = str(provider_context_id or "").strip()
        if requested_context and not authorization.supports_context_binding:
            raise ChangeControlBlockedError(
                "implementation_provider_context_unsupported",
                details={"provider_kind": kind.value},
            )
        selected_context = requested_context or authorization.default_provider_context_id
        return self._repository.bind_provider_project(
            project_id,
            ProviderProjectBindingDraft(
                provider_kind=kind,
                provider_id=authorization.provider_id,
                scope_id=scope_id,
                surfaces=selected_surfaces,
                provider_context_id=selected_context,
                replacement_reason=replacement_reason,
                repository=repository,
            ),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def import_default(
        self,
        project_id: str,
        *,
        provider_kind: ImplementationProviderKind | str,
        scope_id: str,
        surfaces: tuple[str, ...],
        provider_context_id: str = "",
        repository: str | int | None = None,
    ) -> None:
        try:
            self.bind(
                project_id,
                provider_kind=provider_kind,
                scope_id=scope_id,
                surfaces=surfaces,
                provider_context_id=provider_context_id,
                actor="runtime-config",
                request_id=f"provider-default:{provider_kind}:{project_id}",
                repository=repository,
            )
        except (ProjectNotFoundError, ChangeControlBlockedError):
            # A future project is still served by the adapter's static fallback;
            # an existing explicit ledger binding always wins over config defaults.
            return

    def get(
        self, project_id: str, provider_kind: ImplementationProviderKind | str
    ) -> Mapping[str, object]:
        binding = self._repository.resolve_provider_binding(project_id, provider_kind)
        if binding is None:
            raise ChangeControlBlockedError(
                "implementation_provider_project_unbound",
                details={"provider_kind": str(provider_kind)},
            )
        return {
            "project_id": binding.project_id,
            "provider_kind": binding.provider_kind.value,
            "provider_id": binding.provider_id,
            "scope_id": binding.scope_id,
            "surfaces": list(binding.surfaces),
            "provider_context_id": binding.provider_context_id,
            "repository": binding.repository,
            "revision": binding.revision,
            "status": "active",
        }

    def list(self, project_id: str) -> list[Mapping[str, object]]:
        return self._repository.list_provider_bindings(project_id)

    def available_provider_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(kind.value for kind in self._authorizations))

    def authorized_routes(self) -> list[Mapping[str, object]]:
        return [
            {
                "provider_kind": kind.value,
                "route_id": authorization.provider_id,
                "surfaces": list(authorization.surfaces),
                "supports_context_binding": authorization.supports_context_binding,
            }
            for kind, authorization in sorted(self._authorizations.items())
        ]
