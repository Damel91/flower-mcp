"""Application policy for implementation-run continuity."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain import (
    RunCompletionDraft,
    RunDraft,
    RunStepDraft,
    RunStepStatus,
    RunStepTransition,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.errors import RunControlBlockedError
from flow_of_work_mcp.core.ports import ExecutionRunRepository


class ExecutionRunService:
    """Applies run and step lifecycle rules without closing packets."""

    def __init__(self, repository: ExecutionRunRepository) -> None:
        self._repository = repository

    def create_run(
        self,
        project_id: str,
        draft: RunDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.create_run(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def get_run(self, project_id: str, run_id: str) -> Mapping[str, object]:
        return self._repository.run_state(project_id, run_id)

    def add_step(
        self,
        project_id: str,
        draft: RunStepDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.add_run_step(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def link_step_dependency(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        depends_on_step_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.link_run_step_dependency(
            project_id,
            run_id,
            step_id,
            depends_on_step_id,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def start_step(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.transition_run_step(
            project_id,
            run_id,
            step_id,
            RunStepTransition(RunStepStatus.IN_PROGRESS),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def complete_step(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        *,
        evidence_refs: tuple[str, ...],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.transition_run_step(
            project_id,
            run_id,
            step_id,
            RunStepTransition(RunStepStatus.COMPLETED, evidence_refs=evidence_refs),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def block_step(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        *,
        blocking_reason: str,
        next_expected_action: str = "",
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        if not blocking_reason:
            raise RunControlBlockedError("step_block_requires_reason", details={"step_id": step_id})
        return self._repository.transition_run_step(
            project_id,
            run_id,
            step_id,
            RunStepTransition(
                RunStepStatus.BLOCKED,
                blocking_reason=blocking_reason,
                next_expected_action=next_expected_action,
            ),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def cancel_step(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        if not reason:
            raise RunControlBlockedError("step_cancel_requires_reason", details={"step_id": step_id})
        return self._repository.transition_run_step(
            project_id,
            run_id,
            step_id,
            RunStepTransition(RunStepStatus.CANCELLED, blocking_reason=reason),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def complete_run(
        self,
        project_id: str,
        run_id: str,
        draft: RunCompletionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.complete_run(
            project_id,
            run_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def cancel_run(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.cancel_run(
            project_id,
            run_id,
            reason=required_text(reason, "reason"),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def task_view(self, project_id: str, run_id: str) -> Mapping[str, object]:
        return self._repository.task_view(project_id, run_id)
