"""Deterministic packet evidence reconciliation policy."""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_reconciliation import (
    EvidenceCompleteness,
    PacketEvidenceClaimDraft,
    PacketEvidenceClaimOrigin,
    PacketEvidenceClaimType,
    PacketEvidenceSnapshotDraft,
    PacketEvidenceSnapshotRequest,
    PacketReconciliationScopeDraft,
    ReconciliationClassification,
    ReconciliationItemDispositionDraft,
    ReconciliationItemDraft,
)
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.core.ports.packet_reconciliation import (
    PacketEvidenceProvider,
    PacketReconciliationRepository,
)


_PROFILE_REQUIRED_TYPES = {
    "target-impact-v1": {
        PacketEvidenceClaimType.TARGET.value,
        PacketEvidenceClaimType.IMPACT.value,
    }
}


class PacketReconciliationService:
    """Own claim, evidence, residual and readiness reconciliation state."""

    def __init__(
        self,
        repository: PacketReconciliationRepository,
        provider: PacketEvidenceProvider | None = None,
    ) -> None:
        self._repository = repository
        self._provider = provider

    def initialize(
        self,
        project_id: str,
        *,
        change_id: str,
        packet_id: str,
        profile: str = "target-impact-v1",
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.open_packet_reconciliation_scope(
            project_id,
            PacketReconciliationScopeDraft(
                change_id=change_id,
                packet_id=packet_id,
                profile=profile,
            ),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def derive_applicability(
        self,
        project_id: str,
        *,
        change_id: str,
        packet_id: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object] | None:
        """Persist evidence applicability from accepted unit semantics."""

        scope = self._repository.packet_reconciliation_for_packet(
            project_id, change_id, packet_id
        )
        if scope is None:
            return None
        plan = self._repository.accepted_packet_work_plan(
            project_id, change_id, packet_id
        )
        if plan is None:
            applicability = "deferred"
            reason = "work_plan_not_accepted"
            plan_revision = 0
        else:
            units = [
                item
                for item in plan.get("units", [])
                if isinstance(item, Mapping)
            ]
            plan_revision = int(plan.get("plan_revision") or 0)
            if units and all(
                str(item.get("operation_kind") or "") == "new_file"
                for item in units
            ):
                applicability = "deferred"
                reason = "future_targets_not_provider_observable"
            elif units:
                applicability = "applicable"
                reason = "accepted_plan_contains_existing_code_targets"
            else:
                applicability = "not_applicable"
                reason = "accepted_plan_has_no_executable_units"
        return self._repository.set_packet_reconciliation_applicability(
            project_id,
            str(scope["reconciliation_scope_id"]),
            applicability=applicability,
            reason=reason,
            plan_revision=plan_revision,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def answer_gate(
        self,
        project_id: str,
        *,
        change_id: str,
        packet_id: str,
        gate_kind: str,
        subject_ref: str,
        predicate: str,
        object_ref: str = "",
        assertion: Mapping[str, object] | None = None,
        evidence_refs: tuple[str, ...] = (),
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        """Translate one ordinary target/impact answer into v1.3 claims."""

        scope = self._repository.packet_reconciliation_for_packet(
            project_id, change_id, packet_id
        )
        if scope is None:
            raise ChangeControlBlockedError(
                "packet_reconciliation_scope_missing"
            )
        kind = str(gate_kind or "").strip().lower()
        actor = required_text(actor, "actor")
        if kind == PacketEvidenceClaimType.TARGET.value:
            self._sync_target_claims(
                project_id,
                scope,
                actor=actor,
                request_id=str(request_id or ""),
            )
            current = self._repository.packet_reconciliation_state(
                project_id, str(scope["reconciliation_scope_id"])
            )
            matching = [
                item
                for item in current.get("claims", [])
                if isinstance(item, Mapping)
                and str(item.get("claim_type") or "") == "target"
                and str(item.get("subject_ref") or "") == subject_ref
                and str(item.get("status") or "") == "active"
            ]
            if not matching:
                raise ChangeControlBlockedError(
                    "target_gate_subject_not_bound",
                    details={"subject_ref": subject_ref},
                )
            return {
                "gate_kind": kind,
                "subject_ref": subject_ref,
                "translated_claim_count": len(matching),
            }
        if kind != PacketEvidenceClaimType.IMPACT.value:
            raise ValueError("gate_kind must be target or impact")
        subject_ref = required_text(subject_ref, "subject_ref")
        predicate = required_text(predicate, "predicate")
        claim_key = f"impact:{subject_ref}:{predicate}:{object_ref}"
        claim_draft = PacketEvidenceClaimDraft(
            claim_type=PacketEvidenceClaimType.IMPACT,
            claim_key=claim_key,
            subject_ref=subject_ref,
            predicate=predicate,
            object_ref=str(object_ref or ""),
            assertion=dict(assertion or {}),
            evidence_refs=tuple(str(item) for item in evidence_refs),
            required=True,
        )
        state = self._repository.packet_reconciliation_state(
            project_id, str(scope["reconciliation_scope_id"])
        )
        result: Mapping[str, object] | None = None
        for current in state.get("claims", []):
            if (
                not isinstance(current, Mapping)
                or str(current.get("origin") or "") != "declared"
                or str(current.get("claim_type") or "") != "impact"
                or str(current.get("subject_ref") or "") != subject_ref
                or str(current.get("predicate") or "") != predicate
                or str(current.get("status") or "") != "active"
            ):
                continue
            if _stored_claim_matches_draft(current, claim_draft):
                result = current
                continue
            self.supersede_claim(
                project_id,
                str(current["claim_id"]),
                rationale="engineering gate answer superseded",
                actor=actor,
                request_id=(
                    f"{request_id}:supersede:{current['claim_id']}"
                    if request_id
                    else ""
                ),
            )
        if result is None:
            result = self.declare_claim(
                project_id,
                str(scope["reconciliation_scope_id"]),
                claim_draft,
                actor=actor,
                request_id=str(request_id or ""),
            )
        return {
            "gate_kind": kind,
            "subject_ref": subject_ref,
            "predicate": predicate,
            "object_ref": str(object_ref or ""),
            "translated_claim": {
                "claim_type": str(result.get("claim_type") or "impact"),
                "claim_key": str(result.get("claim_key") or claim_key),
            },
        }

    def get(
        self,
        project_id: str,
        *,
        reconciliation_scope_id: str = "",
        change_id: str = "",
        packet_id: str = "",
    ) -> Mapping[str, object] | None:
        if reconciliation_scope_id:
            return self._repository.packet_reconciliation_state(
                project_id, reconciliation_scope_id
            )
        return self._repository.packet_reconciliation_for_packet(
            project_id, change_id, packet_id
        )

    def collect_provider_snapshot(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        *,
        actor: str,
        request_id: str = "",
        max_claims: int = 512,
        max_depth: int = 4,
    ) -> Mapping[str, object]:
        """Collect and import one provider snapshot from packet-bound context."""

        if self._provider is None:
            raise ChangeControlBlockedError("packet_evidence_provider_unconfigured")
        scope = self._repository.packet_reconciliation_state(
            project_id, reconciliation_scope_id
        )
        expected = self._repository.packet_reconciliation_expected_evidence_context(
            project_id, str(scope["change_id"]), str(scope["packet_id"])
        )
        contexts = [
            dict(value)
            for value in expected.get("contexts", [])
            if isinstance(value, Mapping)
        ]
        if not contexts:
            raise ChangeControlBlockedError("packet_evidence_provider_context_missing")
        context = self._covering_provider_context(contexts)
        request = PacketEvidenceSnapshotRequest(
            reconciliation_scope_id=reconciliation_scope_id,
            project_id=project_id,
            packet_id=str(scope["packet_id"]),
            provider_id=str(context.get("provider_id") or ""),
            provider_scope_id=str(context.get("provider_scope_id") or ""),
            selection_ref=str(context.get("selection_ref") or ""),
            source_revision=str(context.get("source_revision") or ""),
            surfaces=(str(context.get("provider_surface_id") or ""),),
            selection_refs=tuple(
                str(value) for value in context.get("selection_refs", [])
            ),
            target_handles=tuple(
                str(value) for value in context.get("target_handles", [])
            ),
            workspace_revision=str(context.get("workspace_revision") or ""),
            claim_types=_profile_claim_types(str(scope.get("profile") or "")),
            max_claims=max_claims,
            max_depth=max_depth,
        )
        draft = self._provider.snapshot(request)
        return self.import_snapshot(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
            collection_request=request,
        )

    @staticmethod
    def _covering_provider_context(
        contexts: list[dict[str, object]],
    ) -> dict[str, object]:
        if any(
            context.get("authoritative_snapshot_found") is False
            for context in contexts
        ):
            raise ChangeControlBlockedError(
                "packet_evidence_provider_context_ambiguous",
                details={
                    "context_count": len(contexts),
                    "reason": "authoritative_provider_snapshot_missing",
                },
            )
        required_fields = (
            "provider_id",
            "provider_scope_id",
            "selection_ref",
            "source_revision",
            "provider_surface_id",
        )
        missing_fields = sorted({
            field
            for context in contexts
            for field in required_fields
            if not str(context.get(field) or "").strip()
        })
        if missing_fields:
            raise ChangeControlBlockedError(
                "packet_evidence_provider_context_ambiguous",
                details={
                    "context_count": len(contexts),
                    "reason": "provider_context_identity_incomplete",
                    "missing_fields": missing_fields,
                },
            )
        if len(contexts) == 1:
            return contexts[0]

        target_sets = [
            {
                str(value)
                for value in context.get("target_handles", [])
                if str(value)
            }
            for context in contexts
        ]
        if any(not values for values in target_sets):
            raise ChangeControlBlockedError(
                "packet_evidence_provider_context_ambiguous",
                details={
                    "context_count": len(contexts),
                    "reason": "context_targets_missing",
                },
            )

        packet_targets = set().union(*target_sets)
        full_identity_fields = (
            "provider_id",
            "provider_scope_id",
            "source_revision",
            "workspace_revision",
            "provider_surface_id",
        )
        full_identities = {
            tuple(str(context.get(field) or "") for field in full_identity_fields)
            for context in contexts
        }
        base_identity_fields = (
            "provider_id",
            "provider_scope_id",
            "provider_surface_id",
        )
        base_identities = {
            tuple(str(context.get(field) or "") for field in base_identity_fields)
            for context in contexts
        }
        if len(base_identities) != 1:
            raise ChangeControlBlockedError(
                "packet_evidence_provider_context_ambiguous",
                details={
                    "context_count": len(contexts),
                    "reason": "provider_contexts_differ",
                },
            )
        covering = [
            context
            for context, targets in zip(contexts, target_sets, strict=True)
            if packet_targets.issubset(targets)
        ]
        if len(full_identities) == 1 and covering:
            return max(
                covering,
                key=lambda context: (
                    str(context.get("latest_binding_id") or ""),
                    str(context.get("selection_ref") or ""),
                ),
            )

        ordered_contexts = sorted(
            contexts,
            key=lambda context: (
                str(context.get("latest_binding_id") or ""),
                str(context.get("selection_ref") or ""),
            ),
        )
        selection_refs = tuple(dict.fromkeys(
            str(context.get("selection_ref") or "")
            for context in ordered_contexts
        ))
        target_handles = tuple(dict.fromkeys(
            str(value)
            for context in ordered_contexts
            for value in context.get("target_handles", [])
            if str(value)
        ))
        latest = ordered_contexts[-1]
        return {
            "provider_id": str(latest.get("provider_id") or ""),
            "provider_scope_id": str(latest.get("provider_scope_id") or ""),
            "provider_surface_id": str(
                latest.get("provider_surface_id") or ""
            ),
            "selection_ref": "",
            "selection_refs": list(selection_refs),
            "source_revision": "",
            "workspace_revision": "",
            "target_handles": list(target_handles),
            "rehydration_required": True,
        }

    def declare_claim(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        draft: PacketEvidenceClaimDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.append_packet_evidence_claim(
            project_id,
            reconciliation_scope_id,
            draft,
            origin=PacketEvidenceClaimOrigin.DECLARED.value,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def supersede_claim(
        self,
        project_id: str,
        claim_id: str,
        *,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.supersede_packet_evidence_claim(
            project_id,
            claim_id,
            rationale=required_text(rationale, "rationale"),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def import_snapshot(
        self,
        project_id: str,
        draft: PacketEvidenceSnapshotDraft,
        *,
        actor: str,
        request_id: str = "",
        collection_request: PacketEvidenceSnapshotRequest | None = None,
    ) -> Mapping[str, object]:
        scope = self._repository.packet_reconciliation_state(
            project_id, draft.reconciliation_scope_id
        )
        if str(scope["packet_id"]) != draft.packet_id:
            raise ChangeControlBlockedError("packet_evidence_scope_mismatch")
        expected = self._repository.packet_reconciliation_expected_evidence_context(
            project_id,
            str(scope["change_id"]),
            str(scope["packet_id"]),
        )
        self._require_expected_snapshot_value(
            "provider_id", draft.provider_id, expected.get("provider_ids", [])
        )
        self._require_expected_snapshot_value(
            "provider_scope_id",
            draft.provider_scope_id,
            expected.get("provider_scope_ids", []),
        )
        rehydrated = bool(
            collection_request is not None and collection_request.selection_refs
        )
        if rehydrated:
            if not draft.selection_ref or not draft.source_revision:
                raise ChangeControlBlockedError(
                    "packet_evidence_rehydrated_identity_missing"
                )
        else:
            self._require_expected_snapshot_value(
                "selection_ref", draft.selection_ref, expected.get("selection_refs", [])
            )
            self._require_expected_snapshot_value(
                "source_revision",
                draft.source_revision,
                expected.get("source_revisions", []),
            )
            self._require_expected_snapshot_value(
                "workspace_revision",
                draft.workspace_revision,
                expected.get("workspace_revisions", []),
            )
        expected_surfaces = tuple(str(value) for value in expected.get("surface_ids", []))
        if expected_surfaces and set(draft.surfaces) != set(expected_surfaces):
            raise ChangeControlBlockedError(
                "packet_evidence_surfaces_mismatch",
                details={
                    "surfaces": list(draft.surfaces),
                    "expected_surfaces": list(expected_surfaces),
                },
            )
        contexts = [
            dict(value)
            for value in expected.get("contexts", [])
            if isinstance(value, Mapping)
        ]
        if not rehydrated and contexts and not any(
            _snapshot_matches_expected_context(draft, context)
            for context in contexts
        ):
            raise ChangeControlBlockedError(
                "packet_evidence_provider_context_mismatch",
                details={"expected_contexts": contexts},
            )
        allowed_targets = {
            claim.claim_key: claim.subject_ref
            for claim in self._repository.packet_reconciliation_target_claims(
                project_id, str(scope["change_id"]), str(scope["packet_id"])
            )
        }
        unknown_targets = sorted(
            claim.claim_key
            for claim in draft.claims
            if claim.claim_type == PacketEvidenceClaimType.TARGET
            and allowed_targets.get(claim.claim_key) != claim.subject_ref
        )
        if unknown_targets:
            raise ChangeControlBlockedError(
                "packet_evidence_target_handle_unbound",
                details={"unknown_target_claim_keys": unknown_targets},
            )
        if rehydrated and collection_request is not None:
            observed_targets = {
                claim.subject_ref
                for claim in draft.claims
                if claim.claim_type == PacketEvidenceClaimType.TARGET
            }
            if observed_targets != set(collection_request.target_handles):
                raise ChangeControlBlockedError(
                    "packet_evidence_rehydrated_target_closure_mismatch",
                    details={
                        "expected_target_count": len(
                            collection_request.target_handles
                        ),
                        "observed_target_count": len(observed_targets),
                    },
                )
        return self._repository.import_packet_evidence_snapshot(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    @staticmethod
    def _require_expected_snapshot_value(
        field: str, actual: str, expected: object
    ) -> None:
        values = tuple(str(value) for value in expected or ())
        if values and actual not in values:
            raise ChangeControlBlockedError(
                f"packet_evidence_{field}_mismatch",
                details={
                    field: actual,
                    f"expected_{field}s": list(values),
                },
            )

    def get_run(self, project_id: str, run_id: str) -> Mapping[str, object]:
        return self._repository.packet_reconciliation_run(project_id, run_id)

    def reconcile(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        *,
        snapshot_id: str = "",
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        scope = self._repository.packet_reconciliation_state(
            project_id, reconciliation_scope_id
        )
        self._sync_target_claims(project_id, scope, actor=actor, request_id=request_id)
        scope = self._repository.packet_reconciliation_state(
            project_id, reconciliation_scope_id
        )
        snapshots = [dict(item) for item in scope.get("snapshots", [])]
        if snapshot_id:
            snapshots = [item for item in snapshots if item.get("snapshot_id") == snapshot_id]
        if not snapshots:
            raise ChangeControlBlockedError("packet_evidence_snapshot_missing")
        snapshot = snapshots[-1]
        snapshot_id = str(snapshot["snapshot_id"])
        claims = [dict(item) for item in scope.get("claims", [])]
        declared = [
            item
            for item in claims
            if item.get("origin") == PacketEvidenceClaimOrigin.DECLARED.value
            and item.get("status") == "active"
        ]
        observed = [
            item
            for item in claims
            if item.get("origin") == PacketEvidenceClaimOrigin.OBSERVED.value
            and item.get("snapshot_id") == snapshot_id
            and item.get("status") == "active"
        ]
        items = self._classify(scope, snapshot, declared, observed)
        fingerprint = self._repository.packet_reconciliation_fingerprint(
            project_id,
            str(scope["change_id"]),
            str(scope["packet_id"]),
        )
        return self._repository.record_packet_reconciliation_run(
            project_id,
            reconciliation_scope_id,
            snapshot_id,
            packet_fingerprint=fingerprint,
            items=tuple(items),
            actor=actor,
            request_id=str(request_id or ""),
        )

    def disposition_item(
        self,
        project_id: str,
        draft: ReconciliationItemDispositionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.disposition_packet_reconciliation_item(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def accept_current_proposal(
        self,
        project_id: str,
        *,
        change_id: str,
        packet_id: str,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        """Declare one current provider proposal and reconcile it canonically."""

        actor = required_text(actor, "actor")
        required_text(rationale, "rationale")
        scope = self._repository.packet_reconciliation_for_packet(
            project_id, change_id, packet_id
        )
        if scope is None or not isinstance(scope.get("latest_run"), Mapping):
            raise ChangeControlBlockedError("packet_reconciliation_residual_missing")
        item = _current_blocking_item(scope["latest_run"])
        if item is None:
            raise ChangeControlBlockedError("packet_reconciliation_residual_missing")
        if (
            str(item.get("classification") or "")
            != ReconciliationClassification.PROPOSED.value
        ):
            raise ChangeControlBlockedError(
                "packet_reconciliation_proposal_not_acceptable",
                details={"classification": str(item.get("classification") or "")},
            )
        observed_ids = tuple(
            str(value) for value in item.get("observed_claim_ids", [])
        )
        if len(observed_ids) != 1:
            raise ChangeControlBlockedError(
                "packet_reconciliation_proposal_ambiguous",
                details={"observed_claim_count": len(observed_ids)},
            )
        snapshot_id = str(scope["latest_run"].get("snapshot_id") or "")
        observed = next(
            (
                value
                for value in scope.get("claims", [])
                if isinstance(value, Mapping)
                and str(value.get("claim_id") or "") == observed_ids[0]
                and str(value.get("origin") or "")
                == PacketEvidenceClaimOrigin.OBSERVED.value
                and str(value.get("snapshot_id") or "") == snapshot_id
                and str(value.get("status") or "") == "active"
            ),
            None,
        )
        if (
            observed is None
            or bool(observed.get("dynamic"))
            or bool(observed.get("contradicted"))
        ):
            raise ChangeControlBlockedError(
                "packet_reconciliation_proposal_not_current"
            )
        draft = PacketEvidenceClaimDraft(
            claim_type=PacketEvidenceClaimType(str(observed["claim_type"])),
            claim_key=str(observed["claim_key"]),
            subject_ref=str(observed["subject_ref"]),
            predicate=str(observed["predicate"]),
            object_ref=str(observed.get("object_ref") or ""),
            assertion=dict(observed.get("assertion") or {}),
            evidence_refs=tuple(
                str(value) for value in observed.get("evidence_refs", [])
            ),
            required=bool(observed.get("required")),
        )
        active_declared = [
            value
            for value in scope.get("claims", [])
            if isinstance(value, Mapping)
            and str(value.get("origin") or "")
            == PacketEvidenceClaimOrigin.DECLARED.value
            and str(value.get("status") or "") == "active"
            and str(value.get("claim_key") or "") == draft.claim_key
        ]
        if not any(
            _stored_claim_matches_draft(value, draft) for value in active_declared
        ):
            if active_declared:
                raise ChangeControlBlockedError(
                    "packet_reconciliation_declared_claim_conflict",
                    details={"claim_key": draft.claim_key},
                )
            self.declare_claim(
                project_id,
                str(scope["reconciliation_scope_id"]),
                draft,
                actor=actor,
                request_id=(
                    f"{request_id}:accept-proposal" if request_id else ""
                ),
            )
        return self.reconcile(
            project_id,
            str(scope["reconciliation_scope_id"]),
            snapshot_id=snapshot_id,
            actor=actor,
            request_id=(
                f"{request_id}:reconcile-accepted" if request_id else ""
            ),
        )

    def readiness_blockers(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[str, ...]:
        return self._repository.packet_reconciliation_readiness_blockers(
            project_id, change_id, packet_id
        )

    def current_residual_action(
        self,
        project_id: str,
        *,
        change_id: str,
        packet_id: str,
    ) -> Mapping[str, object]:
        """Resolve the first blocking residual to one callable public action."""

        scope = self._repository.packet_reconciliation_for_packet(
            project_id, change_id, packet_id
        )
        if scope is None:
            raise ChangeControlBlockedError("packet_reconciliation_scope_missing")
        run = scope.get("latest_run")
        if not isinstance(run, Mapping):
            raise ChangeControlBlockedError("packet_reconciliation_run_missing")
        item = next(
            (
                value
                for value in run.get("items", [])
                if isinstance(value, Mapping)
                and bool(value.get("blocking"))
                and str(value.get("disposition") or "")
                in {"open", "rejected", "escalated"}
            ),
            None,
        )
        if item is None:
            raise ChangeControlBlockedError("packet_reconciliation_residual_missing")
        claims = [
            value
            for value in scope.get("claims", [])
            if isinstance(value, Mapping)
            and str(value.get("claim_key") or "") == str(item.get("claim_key") or "")
        ]
        readable = {
            "claim_type": str(item.get("claim_type") or ""),
            "claim_key": str(item.get("claim_key") or ""),
            "classification": str(item.get("classification") or ""),
            "closure_condition": str(item.get("closure_condition") or ""),
            "subject_ref": str(claims[0].get("subject_ref") or "") if claims else "",
            "next_action": dict(item.get("next_action") or {}),
        }
        resolver = getattr(self._provider, "residual_action", None)
        if callable(resolver):
            action = resolver(project_id=project_id, residual=readable)
            if isinstance(action, Mapping) and str(action.get("tool") or ""):
                return dict(action)
        capability = str(readable["next_action"].get("capability") or "")
        if capability == "graph.collect_packet_evidence":
            return {
                "tool": "fow_packet_advance",
                "operation": "advance",
                "arguments": {"project_id": project_id, "packet_id": packet_id},
                "required_inputs": ["actor", "request_id"],
            }
        return {
            "tool": "fow_packet_advance",
            "operation": "advance",
            "arguments": {"project_id": project_id, "packet_id": packet_id},
            "required_inputs": [
                "decision.operation",
                "decision.disposition",
                "decision.rationale",
                "actor",
                "request_id",
            ],
        }

    def next_actions(self, project_id: str) -> list[Mapping[str, object]]:
        actions: list[Mapping[str, object]] = []
        for scope in self._repository.list_packet_reconciliations(project_id):
            scope_id = str(scope["reconciliation_scope_id"])
            change_id = str(scope["change_id"])
            packet_id = str(scope["packet_id"])
            blockers = set(str(item) for item in scope.get("readiness_blockers", []))
            if "packet_evidence_snapshot_missing" in blockers:
                actions.append(
                    {
                        "action_id": f"collect-packet-evidence:{packet_id}",
                        "kind": "collect_packet_evidence_snapshot",
                        "priority": 11,
                        "change_id": change_id,
                        "packet_id": packet_id,
                        "reconciliation_scope_id": scope_id,
                        "rationale": "packet reconciliation has no provider evidence snapshot",
                    }
                )
                continue
            if "packet_evidence_reconciliation_missing" in blockers:
                actions.append(
                    {
                        "action_id": f"reconcile-packet-evidence:{packet_id}",
                        "kind": "reconcile_packet_evidence",
                        "priority": 12,
                        "change_id": change_id,
                        "packet_id": packet_id,
                        "reconciliation_scope_id": scope_id,
                        "rationale": "packet evidence has not been reconciled",
                    }
                )
                continue
            run = dict(scope.get("latest_run") or {})
            for item in run.get("items", []):
                if not isinstance(item, Mapping):
                    continue
                if not item.get("blocking") or item.get("disposition") not in {
                    "open",
                    "rejected",
                    "escalated",
                }:
                    continue
                actions.append(
                    {
                        "action_id": f"resolve-evidence-residual:{item['item_id']}",
                        "kind": "resolve_packet_evidence_residual",
                        "priority": _residual_priority(str(item.get("severity") or "medium")),
                        "change_id": change_id,
                        "packet_id": packet_id,
                        "reconciliation_scope_id": scope_id,
                        "item_id": str(item["item_id"]),
                        "claim_type": str(item["claim_type"]),
                        "claim_key": str(item["claim_key"]),
                        "classification": str(item["classification"]),
                        "closure_condition": str(item["closure_condition"]),
                        "next_action": dict(item.get("next_action") or {}),
                        "rationale": "blocking packet evidence residual requires disposition",
                    }
                )
        return sorted(actions, key=lambda item: (int(item["priority"]), str(item["action_id"])))

    def _sync_target_claims(
        self,
        project_id: str,
        scope: Mapping[str, object],
        *,
        actor: str,
        request_id: str,
    ) -> None:
        active_claims = [
            item
            for item in scope.get("claims", [])
            if isinstance(item, Mapping)
            and item.get("origin") == PacketEvidenceClaimOrigin.DECLARED.value
            and item.get("status") == "active"
        ]
        expected_claims = {
            claim.claim_key: claim
            for claim in self._repository.packet_reconciliation_target_claims(
                project_id, str(scope["change_id"]), str(scope["packet_id"])
            )
        }
        existing_keys = {str(item["claim_key"]) for item in active_claims}
        for item in active_claims:
            assertion = dict(item.get("assertion") or {})
            if assertion.get("derived_from") != "accepted_target_binding":
                continue
            claim_key = str(item["claim_key"])
            expected = expected_claims.get(claim_key)
            if expected is not None and _stored_claim_matches_draft(item, expected):
                continue
            self._repository.supersede_packet_evidence_claim(
                project_id,
                str(item["claim_id"]),
                rationale="accepted target binding set changed",
                actor=actor,
                request_id=(
                    f"{request_id}:supersede-target:{item['claim_id']}"
                    if request_id
                    else ""
                ),
            )
            existing_keys.discard(claim_key)
        for index, claim in enumerate(expected_claims.values(), start=1):
            if claim.claim_key in existing_keys:
                continue
            self._repository.append_packet_evidence_claim(
                project_id,
                str(scope["reconciliation_scope_id"]),
                claim,
                origin=PacketEvidenceClaimOrigin.DECLARED.value,
                actor=actor,
                request_id=f"{request_id}:target:{index}" if request_id else "",
            )
            existing_keys.add(claim.claim_key)

    @staticmethod
    def _classify(
        scope: Mapping[str, object],
        snapshot: Mapping[str, object],
        declared: list[Mapping[str, object]],
        observed: list[Mapping[str, object]],
    ) -> list[ReconciliationItemDraft]:
        by_declared: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        by_observed: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for claim in declared:
            by_declared[str(claim["claim_key"])].append(claim)
        for claim in observed:
            by_observed[str(claim["claim_key"])].append(claim)
        completeness = {
            str(key): str(value)
            for key, value in dict(snapshot.get("completeness") or {}).items()
        }
        required_types = _PROFILE_REQUIRED_TYPES[str(scope["profile"])]
        items: list[ReconciliationItemDraft] = []
        represented_types: set[str] = set()
        for key in sorted(set(by_declared).union(by_observed)):
            declared_claims = by_declared[key]
            observed_claims = by_observed[key]
            sample = (declared_claims or observed_claims)[0]
            claim_type = str(sample["claim_type"])
            represented_types.add(claim_type)
            required = claim_type in required_types or any(
                bool(item.get("required")) for item in declared_claims
            )
            classification = _classification_for_claim(
                claim_type,
                declared_claims,
                observed_claims,
                completeness,
                truncated=bool(snapshot.get("truncated")),
            )
            blocking = required and classification != ReconciliationClassification.CONFIRMED
            items.append(
                _item_for_classification(
                    PacketEvidenceClaimType(claim_type),
                    key,
                    classification,
                    declared_claims,
                    observed_claims,
                    blocking=blocking,
                )
            )
        for claim_type in sorted(required_types.difference(represented_types)):
            items.append(
                ReconciliationItemDraft(
                    claim_type=PacketEvidenceClaimType(claim_type),
                    claim_key=f"required-family:{claim_type}",
                    classification=ReconciliationClassification.INCOMPLETE_EVIDENCE,
                    blocking=True,
                    severity="high",
                    closure_condition=(
                        f"declare and observe at least one material {claim_type} claim"
                    ),
                    next_action={
                        "capability": "packet.declare_or_collect_evidence",
                        "claim_type": claim_type,
                        "packet_id": str(scope["packet_id"]),
                    },
                )
            )
        return items


def _classification_for_claim(
    claim_type: str,
    declared: list[Mapping[str, object]],
    observed: list[Mapping[str, object]],
    completeness: Mapping[str, str],
    *,
    truncated: bool,
) -> ReconciliationClassification:
    if observed and any(bool(item.get("contradicted")) for item in observed):
        return ReconciliationClassification.CONTRADICTED
    if observed and any(bool(item.get("dynamic")) for item in observed):
        return ReconciliationClassification.UNRESOLVED_DYNAMIC
    if declared and observed:
        declared_identities = {_claim_identity(item) for item in declared}
        observed_identities = {_claim_identity(item) for item in observed}
        if declared_identities != observed_identities:
            return ReconciliationClassification.CONTRADICTED
        return ReconciliationClassification.CONFIRMED
    if observed:
        return ReconciliationClassification.PROPOSED
    if declared:
        if (
            completeness.get(claim_type) == EvidenceCompleteness.COMPLETE.value
            and not truncated
        ):
            return ReconciliationClassification.CONTRADICTED
        return ReconciliationClassification.INCOMPLETE_EVIDENCE
    raise AssertionError("reconciliation key has no claims")


def _item_for_classification(
    claim_type: PacketEvidenceClaimType,
    claim_key: str,
    classification: ReconciliationClassification,
    declared: list[Mapping[str, object]],
    observed: list[Mapping[str, object]],
    *,
    blocking: bool,
) -> ReconciliationItemDraft:
    closure, action = _closure_and_action(classification, claim_type.value, claim_key)
    return ReconciliationItemDraft(
        claim_type=claim_type,
        claim_key=claim_key,
        classification=classification,
        declared_claim_ids=tuple(str(item["claim_id"]) for item in declared),
        observed_claim_ids=tuple(str(item["claim_id"]) for item in observed),
        blocking=blocking,
        severity="high" if blocking else "low",
        closure_condition=closure,
        next_action=action,
    )


def _claim_identity(claim: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        str(claim.get("claim_type") or ""),
        str(claim.get("subject_ref") or ""),
        str(claim.get("predicate") or ""),
        str(claim.get("object_ref") or ""),
    )


def _closure_and_action(
    classification: ReconciliationClassification,
    claim_type: str,
    claim_key: str,
) -> tuple[str, Mapping[str, object]]:
    if classification == ReconciliationClassification.CONFIRMED:
        return "claim is confirmed by the active provider snapshot", {}
    if classification == ReconciliationClassification.PROPOSED:
        return (
            "accept, reject or waive the provider-only material claim",
            {
                "capability": "packet.review_provider_claim",
                "claim_type": claim_type,
                "claim_key": claim_key,
            },
        )
    if classification == ReconciliationClassification.CONTRADICTED:
        return (
            "revise the declared claim or provide superseding provider evidence",
            {
                "capability": "graph.investigate_claim",
                "claim_type": claim_type,
                "claim_key": claim_key,
            },
        )
    if classification == ReconciliationClassification.UNRESOLVED_DYNAMIC:
        return (
            "resolve the dynamic relation through bounded runtime evidence or authority waiver",
            {
                "capability": "runtime.investigate_dynamic_claim",
                "claim_type": claim_type,
                "claim_key": claim_key,
            },
        )
    return (
        "collect a non-truncated provider snapshot with sufficient claim-family coverage",
        {
            "capability": "graph.collect_packet_evidence",
            "claim_type": claim_type,
            "claim_key": claim_key,
        },
    )


def _residual_priority(severity: str) -> int:
    return {"critical": 5, "high": 8, "medium": 12, "low": 20}.get(severity, 12)


def _profile_claim_types(profile: str) -> tuple[PacketEvidenceClaimType, ...]:
    required = _PROFILE_REQUIRED_TYPES.get(profile)
    if required is None:
        raise ChangeControlBlockedError(
            "packet_reconciliation_profile_unsupported",
            details={"profile": profile},
        )
    return tuple(item for item in PacketEvidenceClaimType if item.value in required)


def _current_blocking_item(run: Mapping[str, object]) -> Mapping[str, object] | None:
    return next(
        (
            value
            for value in run.get("items", [])
            if isinstance(value, Mapping)
            and bool(value.get("blocking"))
            and str(value.get("disposition") or "")
            in {"open", "rejected", "escalated"}
        ),
        None,
    )


def _stored_claim_matches_draft(
    stored: Mapping[str, object], draft: PacketEvidenceClaimDraft
) -> bool:
    return {
        "claim_type": str(stored.get("claim_type") or ""),
        "subject_ref": str(stored.get("subject_ref") or ""),
        "predicate": str(stored.get("predicate") or ""),
        "object_ref": str(stored.get("object_ref") or ""),
        "assertion": dict(stored.get("assertion") or {}),
        "evidence_refs": list(stored.get("evidence_refs") or []),
        "required": bool(stored.get("required")),
        "dynamic": bool(stored.get("dynamic")),
        "contradicted": bool(stored.get("contradicted")),
    } == {
        "claim_type": draft.claim_type.value,
        "subject_ref": draft.subject_ref,
        "predicate": draft.predicate,
        "object_ref": draft.object_ref,
        "assertion": dict(draft.assertion),
        "evidence_refs": list(draft.evidence_refs),
        "required": draft.required,
        "dynamic": draft.dynamic,
        "contradicted": draft.contradicted,
    }


def _snapshot_matches_expected_context(
    draft: PacketEvidenceSnapshotDraft, expected: Mapping[str, object]
) -> bool:
    actual = {
        "provider_id": draft.provider_id,
        "provider_scope_id": draft.provider_scope_id,
        "selection_ref": draft.selection_ref,
        "source_revision": draft.source_revision,
        "workspace_revision": draft.workspace_revision,
    }
    return all(
        not str(value or "") or actual[field] == str(value)
        for field, value in expected.items()
        if field in actual
    )
