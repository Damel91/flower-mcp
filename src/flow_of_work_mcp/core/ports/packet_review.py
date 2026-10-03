"""Persistence boundary for provider workspace review receipts."""
from __future__ import annotations

from typing import Mapping, Protocol


class PacketReviewRepository(Protocol):
    def record_workspace_review(
        self,
        project_id: str,
        *,
        change_id: str,
        packet_id: str,
        spec_revision: int,
        provider_kind: str,
        provider_packet_ref: str,
        provider_packet_revision: int,
        binding_epoch: int,
        event_seq: int,
        provider_job_ref: str,
        provider_revision: str,
        workspace_candidate_id: str,
        candidate_revision: str,
        provider_review_ref: str,
        completeness: str,
        disposition: str,
        reviewed_target_refs: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        provider_findings: tuple[Mapping[str, object], ...],
        existing_finding_ids: tuple[str, ...],
        normalized_finding_ids: tuple[str, ...],
        fingerprint: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def latest_workspace_review(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        spec_revision: int,
        *,
        provider_kind: str,
        provider_packet_ref: str,
        provider_packet_revision: int,
        binding_epoch: int,
        event_seq: int,
        provider_job_ref: str,
    ) -> Mapping[str, object] | None: ...
