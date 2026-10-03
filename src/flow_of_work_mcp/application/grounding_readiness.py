"""Grounding-backed live readiness projection helpers."""
from __future__ import annotations

from typing import Mapping, Sequence

from flow_of_work_mcp.core.domain.grounding import (
    GroundingDisposition,
    GroundingDivergence,
)


_BLOCKING_DIVERGENCES = {
    GroundingDivergence.GOAL_UNIMPLEMENTED.value,
    GroundingDivergence.BEHAVIOR_CONFLICT.value,
}
_PARTIAL_DIVERGENCES = {
    GroundingDivergence.GOAL_PARTIALLY_REALIZED.value,
    GroundingDivergence.REQUIREMENT_STALE_CANDIDATE.value,
}
_EVIDENCE_ONLY_DIVERGENCES = {
    GroundingDivergence.EVIDENCE_MISSING.value,
}


def goal_scope_from_case(case: Mapping[str, object]) -> tuple[str, ...]:
    """Return the closed use-case/sequence Goal Graph scope for a campaign case."""

    ids: list[str] = []
    for key in ("covered_use_case_goal_node_ids", "covered_sequence_goal_node_ids"):
        for value in case.get(key, []):
            goal_id = str(value or "").strip()
            if goal_id and goal_id not in ids:
                ids.append(goal_id)
    return tuple(ids)


def live_grounding_readiness(
    *,
    project_id: str,
    goal_node_ids: Sequence[str],
    audits: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """Project whether a live use-case/sequence scope is implementation-grounded.

    The projection is intentionally conservative. It accepts only the latest audit
    whose selected Goal Graph IDs cover the requested scope. A campaign
    declaration alone never proves live readiness. Readiness is a semantic
    precondition for a campaign, never proof of tested behavior. The source
    evidence authority and currentness declaration remain visible in every
    audit-backed projection.
    """

    del project_id  # project scoping is guaranteed by the repository query.
    scope = tuple(dict.fromkeys(str(item or "").strip() for item in goal_node_ids if str(item or "").strip()))
    if not scope:
        return _projection(
            state="needs_campaign_scope",
            ready=False,
            gaps=("live_grounding_scope_missing",),
        )

    audit = _latest_covering_audit(scope, audits)
    if audit is None:
        return _projection(
            state="needs_implementation_projection",
            ready=False,
            gaps=("implementation_grounding_missing",),
            selected_goal_ids=scope,
        )

    base = _audit_base(audit, scope)
    diagnostics = tuple(str(item) for item in audit.get("diagnostics", []))
    if str(audit.get("disposition") or "") != GroundingDisposition.COMPLETED.value:
        return _projection(
            **base,
            state="needs_implementation_projection",
            ready=False,
            gaps=("implementation_grounding_not_completed",),
            diagnostics=diagnostics,
        )
    if bool(audit.get("input_truncated")) or "input_truncated" in diagnostics:
        return _projection(
            **base,
            state="grounding_truncated",
            ready=False,
            gaps=("implementation_grounding_truncated",),
            diagnostics=diagnostics,
        )

    scoped_items = [
        item for item in audit.get("items", [])
        if isinstance(item, Mapping) and str(item.get("goal_node_id") or "") in set(scope)
    ]
    item_goal_ids = {str(item.get("goal_node_id") or "") for item in scoped_items}
    missing_goal_ids = tuple(goal_id for goal_id in scope if goal_id not in item_goal_ids)
    divergences = tuple(
        str(item.get("divergence") or "")
        for item in scoped_items
        if str(item.get("divergence") or "")
    )
    untraced_count = len(
        [
            item for item in audit.get("items", [])
            if isinstance(item, Mapping)
            and str(item.get("divergence") or "") == GroundingDivergence.IMPLEMENTATION_UNTRACED.value
        ]
    )

    if missing_goal_ids:
        return _projection(
            **base,
            state="evidence_building_campaign_only",
            ready=False,
            gaps=("implementation_grounding_goal_missing",),
            missing_goal_ids=missing_goal_ids,
            divergences=divergences,
            implementation_untraced_count=untraced_count,
        )
    if any(divergence in _BLOCKING_DIVERGENCES for divergence in divergences):
        return _projection(
            **base,
            state="blocked_by_grounding",
            ready=False,
            gaps=("implementation_grounding_contradictory",),
            divergences=divergences,
            implementation_untraced_count=untraced_count,
        )
    if any(divergence in _PARTIAL_DIVERGENCES for divergence in divergences):
        return _projection(
            **base,
            state="partial_live_readiness",
            ready=False,
            gaps=("implementation_grounding_partial",),
            divergences=divergences,
            implementation_untraced_count=untraced_count,
        )
    if any(divergence in _EVIDENCE_ONLY_DIVERGENCES for divergence in divergences):
        return _projection(
            **base,
            state="evidence_building_campaign_only",
            ready=False,
            gaps=("implementation_grounding_evidence_missing",),
            divergences=divergences,
            implementation_untraced_count=untraced_count,
        )
    if divergences and all(divergence == GroundingDivergence.CONVERGED.value for divergence in divergences):
        uncited = tuple(str(item.get("goal_node_id")) for item in scoped_items
                        if not item.get("anchor_ids"))
        if base["evidence_authority"] == "host_declared" and uncited:
            return _projection(
                **base,
                state="evidence_building_campaign_only",
                ready=False,
                gaps=("implementation_grounding_goal_evidence_missing",),
                uncited_goal_ids=uncited,
                divergences=divergences,
                implementation_untraced_count=untraced_count,
            )
        return _projection(
            **base,
            state="ready_for_live_campaign",
            ready=True,
            gaps=(),
            divergences=divergences,
            implementation_untraced_count=untraced_count,
        )
    return _projection(
        **base,
        state="evidence_building_campaign_only",
        ready=False,
        gaps=("implementation_grounding_evidence_missing",),
        divergences=divergences,
        implementation_untraced_count=untraced_count,
    )


def _latest_covering_audit(
    scope: tuple[str, ...],
    audits: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    requested = set(scope)
    for audit in reversed(list(audits)):
        selected = {str(item) for item in audit.get("selected_goal_ids", [])}
        if requested.issubset(selected):
            return audit
    return None


def _audit_base(audit: Mapping[str, object], scope: tuple[str, ...]) -> Mapping[str, object]:
    authority = str(audit.get("evidence_authority") or "provider_snapshot")
    provenance = dict(audit.get("provenance") or {})
    return {
        "audit_id": "" if audit.get("audit_id") is None else str(audit.get("audit_id")),
        "provider_id": str(audit.get("provider_id") or ""),
        "source_revision": str(audit.get("source_revision") or ""),
        "contract_version": ("flower-host-grounding-evidence-v1" if authority == "host_declared"
                             else "implementation-graph-snapshot-v1"),
        "evidence_authority": authority,
        "source_currentness": str(provenance.get("source_currentness") or
                                   ("host_declared_as_of_audit" if authority == "host_declared"
                                    else "provider_snapshot_as_of_audit")),
        # A snapshot is not an attestation that its evidence was audited.
        "provider_audited": False,
        "provenance": provenance,
        "selected_goal_ids": [str(item) for item in audit.get("selected_goal_ids", [])],
        "covered_goal_node_ids": list(scope),
    }


def _projection(
    *,
    state: str,
    ready: bool,
    gaps: Sequence[str],
    audit_id: str = "",
    provider_id: str = "",
    source_revision: str = "",
    contract_version: str = "implementation-graph-snapshot-v1",
    evidence_authority: str = "",
    source_currentness: str = "not_independently_verified",
    provider_audited: bool = False,
    provenance: Mapping[str, object] | None = None,
    selected_goal_ids: Sequence[str] = (),
    covered_goal_node_ids: Sequence[str] = (),
    missing_goal_ids: Sequence[str] = (),
    uncited_goal_ids: Sequence[str] = (),
    divergences: Sequence[str] = (),
    diagnostics: Sequence[str] = (),
    implementation_untraced_count: int = 0,
) -> Mapping[str, object]:
    return {
        "ready": bool(ready),
        "state": state,
        "audit_id": str(audit_id or ""),
        "provider_id": str(provider_id or ""),
        "source_revision": str(source_revision or ""),
        "contract_version": str(contract_version or "implementation-graph-snapshot-v1"),
        "evidence_authority": evidence_authority,
        "source_currentness": source_currentness,
        "provider_audited": provider_audited,
        "provenance": dict(provenance or {}),
        "external_source_verified": False,
        "behavior_verified": False,
        "selected_goal_ids": [str(item) for item in selected_goal_ids],
        "covered_goal_node_ids": [str(item) for item in covered_goal_node_ids],
        "missing_goal_ids": [str(item) for item in missing_goal_ids],
        "uncited_goal_ids": [str(item) for item in uncited_goal_ids],
        "divergences": sorted(set(str(item) for item in divergences if str(item))),
        "diagnostics": sorted(set(str(item) for item in diagnostics if str(item))),
        "implementation_untraced_count": int(implementation_untraced_count),
        "gaps": sorted(set(str(item) for item in gaps if str(item))),
    }
