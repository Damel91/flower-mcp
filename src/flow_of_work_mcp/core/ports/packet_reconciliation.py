"""Persistence boundary for packet evidence reconciliation."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.packet_reconciliation import (
    PacketEvidenceClaimDraft,
    PacketEvidenceSnapshotDraft,
    PacketEvidenceSnapshotRequest,
    PacketReconciliationScopeDraft,
    ReconciliationItemDispositionDraft,
    ReconciliationItemDraft,
)


class PacketEvidenceProvider(Protocol):
    """Optional fact-provider boundary; Flow retains reconciliation authority."""

    def snapshot(self, request: PacketEvidenceSnapshotRequest) -> PacketEvidenceSnapshotDraft: ...


class PacketReconciliationRepository(Protocol):
    def accepted_packet_work_plan(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object] | None: ...

    def set_packet_reconciliation_applicability(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        *,
        applicability: str,
        reason: str,
        plan_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def open_packet_reconciliation_scope(
        self,
        project_id: str,
        draft: PacketReconciliationScopeDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def packet_reconciliation_state(
        self, project_id: str, reconciliation_scope_id: str
    ) -> Mapping[str, object]: ...

    def packet_reconciliation_for_packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object] | None: ...

    def list_packet_reconciliations(self, project_id: str) -> list[Mapping[str, object]]: ...

    def append_packet_evidence_claim(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        draft: PacketEvidenceClaimDraft,
        *,
        origin: str,
        snapshot_id: str = "",
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def supersede_packet_evidence_claim(
        self,
        project_id: str,
        claim_id: str,
        *,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def import_packet_evidence_snapshot(
        self,
        project_id: str,
        draft: PacketEvidenceSnapshotDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def record_packet_reconciliation_run(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        snapshot_id: str,
        *,
        packet_fingerprint: str,
        items: tuple[ReconciliationItemDraft, ...],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def disposition_packet_reconciliation_item(
        self,
        project_id: str,
        draft: ReconciliationItemDispositionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def packet_reconciliation_fingerprint(
        self, project_id: str, change_id: str, packet_id: str
    ) -> str: ...

    def packet_reconciliation_expected_source_revisions(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[str, ...]: ...

    def packet_reconciliation_expected_evidence_context(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object]: ...

    def packet_reconciliation_run(
        self, project_id: str, run_id: str
    ) -> Mapping[str, object]: ...

    def packet_reconciliation_target_claims(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[PacketEvidenceClaimDraft, ...]: ...

    def packet_reconciliation_readiness_blockers(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[str, ...]: ...
