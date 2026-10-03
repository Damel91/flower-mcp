"""Persistence port for navigation-audit lifecycle blocks."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.navigation_audit import (
    CandidateRejectionDraft,
    CandidateTargetSetDraft,
    ContextSnapshotRefDraft,
    NavigationAuditBlockDraft,
    NavigationAuditState,
    ProviderAuditWindowDraft,
    ProviderAuditWindowState,
    ProviderNavigationAuditSnapshotDraft,
    TargetBindingDraft,
)


class NavigationAuditRepository(Protocol):
    def open_navigation_audit(
        self,
        project_id: str,
        draft: NavigationAuditBlockDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...
    def navigation_audit_state(
        self, project_id: str, navigation_audit_id: str
    ) -> Mapping[str, object]: ...

    def list_navigation_audits(self, project_id: str) -> list[Mapping[str, object]]: ...

    def append_candidate_set(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: CandidateTargetSetDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def accept_candidate(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: TargetBindingDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def reject_candidate(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: CandidateRejectionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def attach_context_snapshot(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ContextSnapshotRefDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def transition_navigation_audit(
        self,
        project_id: str,
        navigation_audit_id: str,
        state: NavigationAuditState,
        *,
        actor: str,
        rationale: str = "",
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def start_provider_audit_window(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ProviderAuditWindowDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def import_provider_navigation_snapshot(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ProviderNavigationAuditSnapshotDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def transition_provider_audit_window(
        self,
        project_id: str,
        navigation_audit_id: str,
        state: ProviderAuditWindowState,
        *,
        actor: str,
        rationale: str = "",
        request_id: str = "",
    ) -> Mapping[str, object]: ...
