"""Canonical provider context-target projections."""
from __future__ import annotations

from typing import Iterable, Mapping

from flow_of_work_mcp.core.errors import ChangeControlBlockedError


def stable_unique_target_handles(
    bindings: Iterable[Mapping[str, object]],
) -> tuple[str, ...]:
    """Return non-empty target handles once, preserving first-seen order."""

    handles: list[str] = []
    seen: set[str] = set()
    for binding in bindings:
        handle = str(binding.get("target_handle") or "").strip()
        if not handle or handle in seen:
            continue
        seen.add(handle)
        handles.append(handle)
    return tuple(handles)


def canonical_context_bindings(
    bindings: Iterable[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Collapse equal semantic targets without collapsing packet unit roles."""

    canonical: list[Mapping[str, object]] = []
    identities: dict[str, tuple[object, ...]] = {}
    binding_ids: dict[str, str] = {}
    for raw in bindings:
        binding = dict(raw)
        handle = str(binding.get("target_handle") or "").strip()
        if not handle:
            raise ChangeControlBlockedError(
                "packet_context_target_handle_missing",
                details={"binding_id": str(binding.get("binding_id") or "")},
            )
        provider_identity_status = str(
            binding.get("provider_identity_status") or ""
        ).strip()
        if provider_identity_status and provider_identity_status != "resolved":
            raise ChangeControlBlockedError(
                "packet_context_target_identity_unresolved",
                details={
                    "binding_id": str(binding.get("binding_id") or ""),
                    "target_handle": handle,
                    "reason": provider_identity_status,
                },
            )
        identity = _context_identity(binding)
        if handle in identities:
            if identities[handle] != identity:
                raise ChangeControlBlockedError(
                    "packet_context_target_identity_conflict",
                    details={
                        "target_handle": handle,
                        "binding_ids": [
                            binding_ids[handle],
                            str(binding.get("binding_id") or ""),
                        ],
                    },
                )
            continue
        identities[handle] = identity
        binding_ids[handle] = str(binding.get("binding_id") or "")
        canonical.append(binding)
    return canonical


def provider_baseline_snapshot_closes(
    snapshot: Mapping[str, object],
    *,
    expected_surfaces: tuple[str, ...] = (),
) -> bool:
    """Validate one source-text-free, target-free provider revision baseline."""

    metadata = _mapping(snapshot.get("metadata"))
    observed_surfaces = tuple(str(item) for item in metadata.get("surfaces", []))
    return bool(
        metadata.get("baseline_only")
        and str(metadata.get("revision_authority") or "") == "provider"
        and not tuple(metadata.get("target_handles", []))
        and str(snapshot.get("source_revision") or "").strip()
        and (not expected_surfaces or observed_surfaces == expected_surfaces)
        and not bool(metadata.get("contains_full_source_text"))
    )


def _context_identity(binding: Mapping[str, object]) -> tuple[object, ...]:
    graph = _mapping(binding.get("graph_evidence"))
    return (
        str(binding.get("surface_id") or "").strip(),
        str(binding.get("repo_or_workspace_id") or "").strip(),
        str(binding.get("target_kind") or "").strip(),
        str(binding.get("file_path") or graph.get("file_path") or "").strip(),
        str(binding.get("provider_source_revision") or "").strip(),
        str(binding.get("provider_identity_status") or "").strip(),
        tuple(
            str(graph.get(key) or binding.get(key) or "").strip()
            for key in (
                "chunk_id",
                "symbol_id",
                "node_id",
                "graph_node_id",
                "kuzu_node_id",
            )
        ),
    )


def _mapping(value: object) -> Mapping[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}
