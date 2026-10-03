"""Ports for durable bootstrap state and provider-neutral code evidence."""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from flow_of_work_mcp.core.domain.bootstrap import (
    BootstrapBehaviorSnapshot,
    BootstrapBehaviorSnapshotRequest,
)


class BootstrapBehaviorProvider(Protocol):
    def snapshot(
        self, request: BootstrapBehaviorSnapshotRequest
    ) -> BootstrapBehaviorSnapshot:
        """Return a bounded, revisioned observed-behavior evidence snapshot."""


class BootstrapRepository(Protocol):
    def start_bootstrap(
        self,
        project_id: str,
        *,
        project_name: str,
        path: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def bootstrap_state(self, project_id: str, bootstrap_id: str) -> Mapping[str, Any]: ...

    def resume_bootstrap(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def record_bootstrap_intake(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        intake: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def record_bootstrap_contradiction(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        contradiction: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def confirm_bootstrap_intake(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        confirmation_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def record_bootstrap_behavior_draft(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        draft: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def complete_bootstrap(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        completion_reference: str,
        handoff: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def cancel_bootstrap(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def mark_bootstrap_blocked(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def latest_guided_bootstrap(self, project_id: str) -> Mapping[str, Any] | None: ...

    def guided_bootstrap_replay(self, project_id: str, bootstrap_id: str, *,
        operation: str, mutation: Mapping[str, object], actor: str,
        request_id: str) -> Mapping[str, Any] | None: ...

    def record_guided_bootstrap(self, project_id: str, bootstrap_id: str, *,
        operation: str, mutation: Mapping[str, object], guided: Mapping[str, object],
        actor: str, request_id: str, stage: str = "intake",
        handoff: Mapping[str, object] | None = None,
        completion_reference: str = "") -> Mapping[str, Any]: ...
