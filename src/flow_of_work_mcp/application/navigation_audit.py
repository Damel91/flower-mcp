"""Deterministic navigation-audit lifecycle policy."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.application.provider_context import (
    provider_baseline_snapshot_closes,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
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
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.core.ports import (
    NavigationAuditRepository,
    PacketWorkPlanRepository,
)


_TERMINAL_STATES = {
    NavigationAuditState.SUPERSEDED.value,
    NavigationAuditState.CLOSED.value,
}


class NavigationAuditService:
    """Owns lifecycle rules for graph-backed repository navigation audit."""

    def __init__(
        self,
        repository: NavigationAuditRepository,
        *,
        work_plans: PacketWorkPlanRepository | None = None,
    ) -> None:
        self._repository = repository
        self._work_plans = work_plans

    def packet_local_candidates(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> list[Mapping[str, object]]:
        """Return readable packet bindings while keeping identities internal."""

        result: list[Mapping[str, object]] = []
        seen: set[str] = set()
        for block in self.list_blocks(project_id):
            if (
                str(block.get("change_id") or "") != change_id
                or str(block.get("packet_id") or "") != packet_id
            ):
                continue
            candidates = {
                (
                    str(candidate_set.get("candidate_set_id") or ""),
                    str(candidate.get("candidate_id") or ""),
                ): candidate
                for candidate_set in block.get("candidate_sets", [])
                if isinstance(candidate_set, Mapping)
                for candidate in candidate_set.get("candidates", [])
                if isinstance(candidate, Mapping)
            }
            for binding in block.get("target_bindings", []):
                if not isinstance(binding, Mapping):
                    continue
                binding_id = str(binding.get("binding_id") or "")
                if not binding_id or binding_id in seen:
                    continue
                seen.add(binding_id)
                candidate = candidates.get(
                    (
                        str(binding.get("candidate_set_id") or ""),
                        str(binding.get("candidate_id") or ""),
                    ),
                    {},
                )
                result.append(
                    {
                        "binding_id": binding_id,
                        "label": str(
                            candidate.get("target_handle")
                            or binding.get("target_handle")
                            or ""
                        ),
                        "kind": str(candidate.get("target_kind") or ""),
                        "display_path": str(candidate.get("file_path") or ""),
                        "path_visibility": "relative",
                    }
                )
        return result

    def open_block(
        self,
        project_id: str,
        draft: NavigationAuditBlockDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.open_navigation_audit(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def get_block(self, project_id: str, navigation_audit_id: str) -> Mapping[str, object]:
        return self._repository.navigation_audit_state(project_id, navigation_audit_id)

    def list_blocks(self, project_id: str) -> list[Mapping[str, object]]:
        return self._repository.list_navigation_audits(project_id)

    def append_candidate_set(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: CandidateTargetSetDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        self._assert_mutable(project_id, navigation_audit_id)
        return self._repository.append_candidate_set(
            project_id,
            navigation_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def accept_candidate(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: TargetBindingDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        self._assert_mutable(project_id, navigation_audit_id)
        return self._repository.accept_candidate(
            project_id,
            navigation_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def reject_candidate(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: CandidateRejectionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        self._assert_mutable(project_id, navigation_audit_id)
        return self._repository.reject_candidate(
            project_id,
            navigation_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def attach_context_snapshot(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ContextSnapshotRefDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        self._assert_mutable(project_id, navigation_audit_id)
        return self._repository.attach_context_snapshot(
            project_id,
            navigation_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def transition_block(
        self,
        project_id: str,
        navigation_audit_id: str,
        state: NavigationAuditState,
        *,
        actor: str,
        rationale: str = "",
        request_id: str = "",
    ) -> Mapping[str, object]:
        target_state = NavigationAuditState(state)
        current = self._repository.navigation_audit_state(project_id, navigation_audit_id)
        if str(current["state"]) in _TERMINAL_STATES:
            raise ChangeControlBlockedError(
                "navigation_audit_terminal_state",
                details={"navigation_audit_id": navigation_audit_id, "state": current["state"]},
            )
        if (
            target_state == NavigationAuditState.ACCEPTED_FOR_PACKET
            and not current.get("target_bindings")
        ):
            self._assert_baseline_only_new_file_audit(
                project_id,
                navigation_audit_id,
                current,
            )
        if target_state in {NavigationAuditState.BLOCKED, NavigationAuditState.SUPERSEDED}:
            required_text(rationale, "rationale")
        return self._repository.transition_navigation_audit(
            project_id,
            navigation_audit_id,
            target_state,
            actor=required_text(actor, "actor"),
            rationale=str(rationale or ""),
            request_id=str(request_id or ""),
        )

    def _assert_baseline_only_new_file_audit(
        self,
        project_id: str,
        navigation_audit_id: str,
        current: Mapping[str, object],
    ) -> None:
        """Permit target-free acceptance only for evidenced greenfield plans."""
        if self._work_plans is None:
            raise ChangeControlBlockedError(
                "navigation_audit_requires_target_binding",
                details={"navigation_audit_id": navigation_audit_id},
            )

        change_id = str(current.get("change_id") or "")
        packet_id = str(current.get("packet_id") or "")
        plan = self._work_plans.packet_work_plan_state(
            project_id,
            change_id,
            packet_id,
        )
        units = [
            unit
            for unit in (plan or {}).get("units", [])
            if isinstance(unit, Mapping)
        ]
        if (
            not plan
            or str(plan.get("status") or "") not in {"proposed", "accepted"}
            or not units
            or any(str(unit.get("operation_kind") or "") != "new_file" for unit in units)
        ):
            raise ChangeControlBlockedError(
                "navigation_audit_requires_target_binding",
                details={"navigation_audit_id": navigation_audit_id},
            )

        expected_surfaces = tuple(
            dict.fromkeys(str(unit.get("surface") or "repo") for unit in units)
        )
        provider_baselines = [
            snapshot
            for snapshot in current.get("context_snapshots", [])
            if isinstance(snapshot, Mapping)
            and provider_baseline_snapshot_closes(
                snapshot, expected_surfaces=expected_surfaces
            )
        ]
        if provider_baselines:
            return

        source_revision = str(current.get("source_revision") or "").strip()
        if not source_revision:
            raise ChangeControlBlockedError(
                "navigation_audit_source_revision_missing",
                details={"navigation_audit_id": navigation_audit_id},
            )

        candidate_sets = [
            candidate_set
            for candidate_set in current.get("candidate_sets", [])
            if isinstance(candidate_set, Mapping)
        ]
        candidate_ids = {
            (
                str(candidate_set.get("candidate_set_id") or ""),
                str(candidate.get("candidate_id") or ""),
            )
            for candidate_set in candidate_sets
            for candidate in candidate_set.get("candidates", [])
            if isinstance(candidate, Mapping)
        }
        rejected_ids = {
            (
                str(rejection.get("candidate_set_id") or ""),
                str(rejection.get("candidate_id") or ""),
            )
            for rejection in current.get("rejected_candidates", [])
            if isinstance(rejection, Mapping)
        }
        candidate_revisions = {
            str(candidate_set.get("source_revision") or "").strip()
            for candidate_set in candidate_sets
        }
        if (
            not candidate_ids
            or not candidate_ids.issubset(rejected_ids)
            or candidate_revisions != {source_revision}
        ):
            raise ChangeControlBlockedError(
                "navigation_audit_baseline_evidence_incomplete",
                details={"navigation_audit_id": navigation_audit_id},
            )

    def start_provider_window(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ProviderAuditWindowDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        self._assert_mutable(project_id, navigation_audit_id)
        current = self._repository.navigation_audit_state(project_id, navigation_audit_id)
        window = dict(current.get("provider_audit_window") or {})
        if str(window.get("state") or "") in {
            ProviderAuditWindowState.RECORDING.value,
            ProviderAuditWindowState.SNAPSHOT_READY.value,
            ProviderAuditWindowState.IMPORTED_BY_FLOW.value,
        }:
            raise ChangeControlBlockedError(
                "provider_navigation_audit_window_active",
                details={"navigation_audit_id": navigation_audit_id, "state": window.get("state")},
            )
        return self._repository.start_provider_audit_window(
            project_id,
            navigation_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def import_provider_snapshot(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ProviderNavigationAuditSnapshotDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        self._assert_mutable(project_id, navigation_audit_id)
        current = self._repository.navigation_audit_state(project_id, navigation_audit_id)
        window = dict(current.get("provider_audit_window") or {})
        if str(window.get("state") or "") not in {
            ProviderAuditWindowState.RECORDING.value,
            ProviderAuditWindowState.SNAPSHOT_READY.value,
            ProviderAuditWindowState.IMPORTED_BY_FLOW.value,
        }:
            raise ChangeControlBlockedError(
                "provider_navigation_audit_window_not_active",
                details={"navigation_audit_id": navigation_audit_id, "state": window.get("state")},
            )
        self._assert_provider_snapshot_matches_window(navigation_audit_id, draft, window)
        self._assert_provider_snapshot_handles(current, draft)
        return self._repository.import_provider_navigation_snapshot(
            project_id,
            navigation_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def transition_provider_window(
        self,
        project_id: str,
        navigation_audit_id: str,
        state: ProviderAuditWindowState,
        *,
        actor: str,
        rationale: str = "",
        request_id: str = "",
    ) -> Mapping[str, object]:
        self._assert_mutable(project_id, navigation_audit_id)
        return self._repository.transition_provider_audit_window(
            project_id,
            navigation_audit_id,
            ProviderAuditWindowState(state),
            actor=required_text(actor, "actor"),
            rationale=str(rationale or ""),
            request_id=str(request_id or ""),
        )

    def _assert_mutable(self, project_id: str, navigation_audit_id: str) -> None:
        state = str(self._repository.navigation_audit_state(project_id, navigation_audit_id)["state"])
        if state in _TERMINAL_STATES:
            raise ChangeControlBlockedError(
                "navigation_audit_terminal_state",
                details={"navigation_audit_id": navigation_audit_id, "state": state},
            )

    @staticmethod
    def _assert_provider_snapshot_matches_window(
        navigation_audit_id: str,
        snapshot: ProviderNavigationAuditSnapshotDraft,
        window: Mapping[str, object],
    ) -> None:
        mismatches: dict[str, object] = {}
        if str(window.get("provider") or "") != snapshot.provider:
            mismatches["provider"] = {
                "window": str(window.get("provider") or ""),
                "snapshot": snapshot.provider,
            }
        if str(window.get("provider_capability_version") or "") != snapshot.provider_capability_version:
            mismatches["provider_capability_version"] = {
                "window": str(window.get("provider_capability_version") or ""),
                "snapshot": snapshot.provider_capability_version,
            }
        window_scope = dict(window.get("target_scope") or {})
        snapshot_scope = dict(snapshot.target_scope or {})
        for key in ("project_id", "scope_id", "packet_id", "milestone_id", "source_revision", "target_set_id", "target_kind"):
            if key in window_scope or key in snapshot_scope:
                if str(window_scope.get(key) or "") != str(snapshot_scope.get(key) or ""):
                    mismatches[f"target_scope.{key}"] = {
                        "window": str(window_scope.get(key) or ""),
                        "snapshot": str(snapshot_scope.get(key) or ""),
                    }
        window_revision = str(
            window.get("source_revision") or window_scope.get("source_revision") or ""
        ).strip()
        if window_revision and window_revision != snapshot.source_revision:
            mismatches["source_revision"] = {
                "window": window_revision,
                "snapshot": snapshot.source_revision,
            }
        if mismatches:
            raise ChangeControlBlockedError(
                "provider_navigation_snapshot_scope_mismatch",
                details={"navigation_audit_id": navigation_audit_id, "mismatches": mismatches},
            )

    @staticmethod
    def _assert_provider_snapshot_handles(
        current: Mapping[str, object],
        snapshot: ProviderNavigationAuditSnapshotDraft,
    ) -> None:
        allowed: set[str] = set()
        for candidate_set in current.get("candidate_sets") or []:
            if not isinstance(candidate_set, Mapping):
                continue
            metadata = candidate_set.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            handles = metadata.get("provider_target_handles")
            if isinstance(handles, list):
                allowed.update(str(value) for value in handles)
        unknown = set(snapshot.selected_target_handles).difference(allowed)
        if allowed and unknown:
            raise ChangeControlBlockedError(
                "provider_navigation_snapshot_target_handle_unbound",
                details={"unknown_target_handles": sorted(unknown)},
            )
