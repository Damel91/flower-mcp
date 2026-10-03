"""Application service for current packet-provider workspace reviews."""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Mapping

from flow_of_work_mcp.core.domain.assurance import ReviewFindingDraft
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_review import WorkspaceReviewReceiptDraft
from flow_of_work_mcp.core.errors import ChangeControlBlockedError


_REVIEWABLE_STATES = frozenset({"completed", "partial"})


class PacketReviewService:
    def __init__(self, *, ledger, assurance, provider_kind: str) -> None:
        self._ledger = ledger
        self._assurance = assurance
        self._provider_kind = str(provider_kind or "").strip()

    def record(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        draft: WorkspaceReviewReceiptDraft,
        *,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        if not self._provider_kind:
            raise ChangeControlBlockedError("workspace_review_provider_unavailable")
        packet = self._current_packet(project_id, change_id, packet_id)
        spec_revision = _spec_revision(packet)
        binding = self._current_binding(project_id, change_id, packet_id)
        self._assert_reviewable(binding, spec_revision)
        identity = _provider_identity(binding)
        context = {
            "project_id": project_id,
            "change_id": change_id,
            "packet_id": packet_id,
            "spec_revision": spec_revision,
            **identity,
            "provider_revision": draft.provider_revision,
            "workspace_candidate_id": draft.workspace_candidate_id,
            "candidate_revision": draft.candidate_revision,
            "provider_review_ref": draft.provider_review_ref,
            "completeness": draft.completeness.value,
            "disposition": draft.disposition.value,
            "reviewed_target_refs": list(draft.reviewed_target_refs),
            "evidence_refs": list(draft.evidence_refs),
            "findings": [item.as_payload() for item in draft.findings],
            "existing_finding_ids": list(draft.existing_finding_ids),
        }
        fingerprint = sha256(
            json.dumps(context, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        with self._ledger.atomic():
            current_packet = self._current_packet(project_id, change_id, packet_id)
            current_binding = self._current_binding(project_id, change_id, packet_id)
            if _spec_revision(current_packet) != spec_revision:
                raise ChangeControlBlockedError("workspace_review_stale_packet")
            self._assert_reviewable(current_binding, spec_revision)
            if _provider_identity(current_binding) != identity:
                raise ChangeControlBlockedError("workspace_review_stale_provider_event")
            existing = self._ledger.workspace_review_for_provider_event(
                project_id,
                provider_kind=self._provider_kind,
                provider_packet_ref=str(binding["provider_packet_ref"]),
                binding_epoch=int(binding["binding_epoch"]),
                event_seq=int(binding["event_seq"]),
            )
            if existing is not None:
                if str(existing.get("fingerprint") or "") != fingerprint:
                    raise ChangeControlBlockedError(
                        "workspace_review_conflicting_replay",
                        details={"provider_packet_ref": binding["provider_packet_ref"]},
                    )
                return existing
            finding_ids: list[str] = list(draft.existing_finding_ids)
            for index, finding in enumerate(draft.findings, start=1):
                recorded = self._assurance.record_finding(
                    project_id,
                    ReviewFindingDraft(
                        change_id=change_id,
                        packet_id=packet_id,
                        severity=finding.severity,
                        title=finding.title,
                        rationale=finding.rationale,
                        expected_correction=finding.expected_correction,
                        scope_kind=finding.scope_kind,
                        scope_ref=finding.scope_ref,
                        source_anchor=finding.source_anchor,
                        implementation_ref=finding.provider_finding_ref,
                    ),
                    actor=actor,
                    request_id=f"{request_id}:finding:{index}",
                )
                finding_ids.append(str(recorded["finding_id"]))
            return self._ledger.record_workspace_review(
                project_id,
                change_id=change_id,
                packet_id=packet_id,
                spec_revision=spec_revision,
                provider_kind=self._provider_kind,
                provider_packet_ref=str(binding["provider_packet_ref"]),
                provider_packet_revision=int(binding["provider_packet_revision"]),
                binding_epoch=int(binding["binding_epoch"]),
                event_seq=int(binding["event_seq"]),
                provider_job_ref=str(binding.get("provider_job_ref") or ""),
                provider_revision=draft.provider_revision,
                workspace_candidate_id=draft.workspace_candidate_id,
                candidate_revision=draft.candidate_revision,
                provider_review_ref=draft.provider_review_ref,
                completeness=draft.completeness.value,
                disposition=draft.disposition.value,
                reviewed_target_refs=draft.reviewed_target_refs,
                evidence_refs=draft.evidence_refs,
                provider_findings=tuple(item.as_payload() for item in draft.findings),
                existing_finding_ids=draft.existing_finding_ids,
                normalized_finding_ids=tuple(finding_ids),
                fingerprint=fingerprint,
                actor=actor,
                request_id=request_id,
            )

    def _current_packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object]:
        change = self._ledger.change_state(project_id, change_id)
        packet = next(
            (
                item
                for item in change.get("packets", [])
                if isinstance(item, Mapping)
                and str(item.get("packet_id") or "") == packet_id
            ),
            None,
        )
        if packet is None:
            raise ValueError(f"unknown packet in change: {packet_id}")
        return packet

    def _current_binding(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object]:
        binding = self._ledger.packet_provider_binding(
            project_id,
            change_id,
            packet_id,
            provider_kind=self._provider_kind,
        )
        if binding is None:
            raise ChangeControlBlockedError("workspace_review_provider_binding_missing")
        return binding

    @staticmethod
    def _assert_reviewable(
        binding: Mapping[str, object], spec_revision: int
    ) -> None:
        if int(binding.get("flow_spec_revision") or 0) != spec_revision:
            raise ChangeControlBlockedError("workspace_review_stale_provider_binding")
        run_phase = str(binding.get("run_phase") or "")
        provider_state = str(binding.get("provider_state") or "")
        if run_phase not in _REVIEWABLE_STATES and provider_state not in _REVIEWABLE_STATES:
            raise ChangeControlBlockedError(
                "workspace_review_provider_not_reviewable",
                details={
                    "run_phase": run_phase,
                    "provider_state": provider_state,
                },
            )


def _spec_revision(packet: Mapping[str, object]) -> int:
    return int(packet.get("spec_revision") or packet.get("current_revision") or 0)


def _provider_identity(binding: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "provider_kind": str(binding.get("provider_kind") or ""),
        "provider_packet_ref": str(binding.get("provider_packet_ref") or ""),
        "provider_packet_revision": int(
            binding.get("provider_packet_revision") or 0
        ),
        "binding_epoch": int(binding.get("binding_epoch") or 0),
        "event_seq": int(binding.get("event_seq") or 0),
        "provider_job_ref": str(binding.get("provider_job_ref") or ""),
    }


__all__ = ["PacketReviewService"]
