"""Ports for implementation-run continuity and handover projections."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain import (
    HandoverDraft,
    RunCompletionDraft,
    RunDraft,
    RunStepDraft,
    RunStepTransition,
)


class ExecutionRunRepository(Protocol):
    def create_run(
        self, project_id: str, draft: RunDraft, *, actor: str, request_id: str = ""
    ) -> Mapping[str, object]: ...

    def run_state(self, project_id: str, run_id: str) -> Mapping[str, object]: ...

    def runs_for_change(self, project_id: str, change_id: str) -> list[Mapping[str, object]]: ...

    def add_run_step(
        self, project_id: str, draft: RunStepDraft, *, actor: str, request_id: str = ""
    ) -> Mapping[str, object]: ...

    def link_run_step_dependency(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        depends_on_step_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def transition_run_step(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        transition: RunStepTransition,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def complete_run(
        self,
        project_id: str,
        run_id: str,
        draft: RunCompletionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def cancel_run(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def task_view(self, project_id: str, run_id: str) -> Mapping[str, object]: ...

    def create_handover(
        self, project_id: str, draft: HandoverDraft, *, actor: str, request_id: str = ""
    ) -> Mapping[str, object]: ...

    def handover_state(self, project_id: str, handover_id: str) -> Mapping[str, object]: ...

    def resume_context(
        self, project_id: str, *, change_id: str = "", packet_id: str = "", run_id: str = ""
    ) -> Mapping[str, object]: ...

    def ledger_projection(
        self, project_id: str, *, projection_kind: str = "lifecycle"
    ) -> Mapping[str, object]: ...

    def recover_interrupted_runs(self) -> None: ...
