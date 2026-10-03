"""Portable receipts accepted through canonical host/provider ledger services."""
from __future__ import annotations

from collections.abc import Mapping
import re

from flow_of_work_mcp.application.provider_binding import ProviderBindingService
from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.core.domain.provider_binding import ImplementationProviderKind
from flow_of_work_mcp.core.errors import ChangeControlBlockedError


ASSOCIATION_RECEIPT_CONTRACT = "flow.project-association.v1"
_HOST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_EXECUTION_KINDS = {"packet_execution", "test_execution"}


def _text(value: object, field: str, *, empty: bool = False, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if (not text and not empty) or len(text) > limit:
        raise ValueError(f"{field} must be {'a bounded' if empty else 'a non-empty bounded'} string")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field} cannot contain control characters")
    if "://" in text:
        raise ValueError(f"{field} cannot contain an endpoint URL")
    return text


def _closed_mapping(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    unknown = set(value) - keys
    if unknown:
        raise ValueError(f"{field} contains unsupported keys: {', '.join(sorted(map(str, unknown)))}")
    return value


def canonical_association_receipt(value: object) -> dict[str, object]:
    root = _closed_mapping(value, {"contract", "project_id", "association"}, "association_receipt")
    if root.get("contract") != ASSOCIATION_RECEIPT_CONTRACT:
        raise ValueError("unsupported association receipt contract")
    project_id = validate_project_id(_text(root.get("project_id"), "project_id"))
    association = root.get("association")
    if not isinstance(association, Mapping):
        raise ValueError("association must be an object")
    kind = association.get("kind")
    if kind == "host":
        fields = _closed_mapping(association, {"kind", "host_id", "repository_locator"}, "association")
        host_id = _text(fields.get("host_id"), "host_id", limit=128)
        if not _HOST_ID.fullmatch(host_id):
            raise ValueError("host_id must be a stable host name containing letters, digits, '.', '_' or '-'")
        normalized: dict[str, object] = {
            "kind": "host", "host_id": host_id,
            "repository_locator": _text(fields.get("repository_locator"), "repository_locator", limit=2048),
        }
    elif kind == "implementation_provider":
        fields = _closed_mapping(
            association,
            {"kind", "provider_kind", "route_id", "scope_id", "provider_context_id", "surfaces", "repository"},
            "association",
        )
        provider_kind = ImplementationProviderKind(_text(fields.get("provider_kind"), "provider_kind")).value
        surfaces = fields.get("surfaces")
        if not isinstance(surfaces, list) or len(surfaces) > 16:
            raise ValueError("surfaces must be a bounded list")
        surfaces = [_text(item, "surface") for item in surfaces]
        if len(set(surfaces)) != len(surfaces):
            raise ValueError("surfaces must be unique")
        execution = provider_kind in _EXECUTION_KINDS
        if not surfaces and not execution:
            raise ValueError("evidence provider association requires surfaces")
        repository = fields.get("repository")
        if repository is not None:
            if provider_kind != "test_execution":
                raise ValueError("repository selector is supported only for test_execution")
            if isinstance(repository, bool) or not isinstance(repository, (str, int)):
                raise ValueError("repository selector must be a string, integer or null")
            if isinstance(repository, str):
                repository = _text(repository, "repository")
            elif repository < 1:
                raise ValueError("repository number must be positive")
        normalized = {
            "kind": "implementation_provider", "provider_kind": provider_kind,
            "route_id": _text(fields.get("route_id"), "route_id"),
            "scope_id": _text(fields.get("scope_id", ""), "scope_id", empty=execution),
            "provider_context_id": _text(fields.get("provider_context_id", ""), "provider_context_id", empty=not execution),
            "surfaces": surfaces, "repository": repository,
        }
    else:
        raise ValueError("association kind must be host or implementation_provider")
    return {"contract": ASSOCIATION_RECEIPT_CONTRACT, "project_id": project_id, "association": normalized}


class AssociationReceiptService:
    def __init__(self, repository, provider_bindings: ProviderBindingService) -> None:
        self._repository = repository
        self._providers = provider_bindings

    def inspect(self, project_id: str) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        with self._repository.consistent_read():
            hosts = list(self._repository.list_host_associations(project_id))
            providers = list(self._providers.list(project_id))
        return {
            "contract": ASSOCIATION_RECEIPT_CONTRACT,
            "project_id": project_id,
            "state": "current" if hosts or providers else "unbound",
            "host_associations": hosts,
            "provider_bindings": providers,
            "authorized_routes": self._providers.authorized_routes(),
            "continuation": {
                "tool": "fow_bindings", "arguments": {"project_id": project_id, "operation": "import"},
                "required_inputs": ["association_receipt", "actor"],
                "policy": "Select a host association or an already authorized provider route explicitly.",
            },
        }

    def export_association(
        self, project_id: str, *, association_kind: str, host_id: str = "", provider_kind: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        if association_kind == "host":
            if provider_kind or not host_id:
                raise ValueError("host export requires host_id and cannot select provider_kind")
            matches = [item for item in self._repository.list_host_associations(project_id) if item["host_id"] == host_id]
            if not matches:
                raise ChangeControlBlockedError("host_association_unbound", details={"host_id": host_id})
            item = matches[0]
            association = {"kind": "host", "host_id": host_id, "repository_locator": item["repository_locator"]}
        elif association_kind == "implementation_provider":
            if host_id or not provider_kind:
                raise ValueError("provider export requires provider_kind and cannot select host_id")
            item = self._providers.get(project_id, provider_kind)
            association = {
                "kind": "implementation_provider", "provider_kind": item["provider_kind"],
                "route_id": item["provider_id"], "scope_id": item["scope_id"],
                "provider_context_id": item["provider_context_id"], "surfaces": list(item["surfaces"]),
                "repository": item.get("repository"),
            }
        else:
            raise ValueError("association_kind must be host or implementation_provider")
        return {
            "association_receipt": canonical_association_receipt({
                "contract": ASSOCIATION_RECEIPT_CONTRACT, "project_id": project_id, "association": association,
            }),
            "current_revision": item["revision"],
        }

    def import_association(
        self, project_id: str, association_receipt: object, *, actor: str,
        replacement_reason: str = "", request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        receipt = canonical_association_receipt(association_receipt)
        if receipt["project_id"] != project_id:
            raise ValueError("association receipt project does not match the selected lifecycle project")
        association = receipt["association"]
        assert isinstance(association, Mapping)
        is_host = association["kind"] == "host"
        selected_kind = str(association.get("provider_kind") or "")
        if not is_host:
            authorizations = {str(item["provider_kind"]): item for item in self._providers.authorized_routes()}
            authorization = authorizations.get(selected_kind)
            if authorization is None or authorization["route_id"] != association["route_id"]:
                raise ChangeControlBlockedError(
                    "association_route_unauthorized",
                    details={"provider_kind": selected_kind, "continuation": "Configure the route with operator authorization, then import its receipt."},
                )
        with self._repository.atomic():
            before = self._current_revision(project_id, association)
            try:
                if is_host:
                    stored = self._repository.bind_host_project(
                        project_id, host_id=str(association["host_id"]),
                        repository_locator=str(association["repository_locator"]), actor=actor,
                        replacement_reason=replacement_reason, request_id=request_id,
                    )
                else:
                    stored = self._providers.bind(
                        project_id, provider_kind=selected_kind, scope_id=str(association["scope_id"]),
                        provider_context_id=str(association["provider_context_id"]),
                        surfaces=tuple(association["surfaces"]), repository=association["repository"],
                        actor=actor, replacement_reason=replacement_reason, request_id=request_id,
                    )
            except ChangeControlBlockedError as exc:
                if "conflict" not in exc.reason:
                    raise
                current = self.export_association(
                    project_id, association_kind=str(association["kind"]),
                    host_id=str(association.get("host_id") or ""), provider_kind=selected_kind,
                )
                raise ChangeControlBlockedError(exc.reason, details={
                    **exc.details, "state": "conflicting", "current": dict(current), "proposed": receipt,
                    "continuation": {
                        "tool": "fow_bindings",
                        "arguments": {"operation": "import", "project_id": project_id, "association_receipt": receipt},
                        "required_inputs": ["actor", "replacement_reason"],
                    },
                }) from exc
            exported = self.export_association(
                project_id, association_kind=str(association["kind"]),
                host_id=str(association.get("host_id") or ""), provider_kind=selected_kind,
            )
            return {"state": "current", **dict(exported), "revision": stored["revision"], "replayed": before == stored["revision"]}

    def _current_revision(self, project_id: str, association: Mapping[str, object]) -> int:
        if association["kind"] == "host":
            matches = [item for item in self._repository.list_host_associations(project_id) if item["host_id"] == association["host_id"]]
            return int(matches[0]["revision"]) if matches else 0
        binding = self._repository.resolve_provider_binding(project_id, str(association["provider_kind"]))
        return binding.revision if binding is not None else 0


__all__ = ["AssociationReceiptService", "ASSOCIATION_RECEIPT_CONTRACT", "canonical_association_receipt"]
