"""Application owner for explicit Flow Project Context selection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping

from flow_of_work_mcp.core.domain.project_context import ProjectContextBinding


class ProjectContextService:
    def __init__(
        self,
        repository: Any,
        *,
        provider_context_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self._repository = repository
        self._provider_context_resolver = provider_context_resolver

    def execute(
        self,
        operation: str,
        *,
        interaction_session_ref: str,
        project_id: str = "",
        selection: int = 0,
        actor: str = "orchestrator",
        request_id: str = "",
    ) -> Mapping[str, object]:
        op = str(operation or "status").strip().lower()
        if op in {"status", "discover"}:
            return self.discover(interaction_session_ref)
        if op == "open":
            current = self._repository.get_interaction_project_context(
                interaction_session_ref
            )
            if current is not None:
                return self.discover(interaction_session_ref)
            projects = self._repository.list_projects_for_interaction()
            if len(projects) != 1:
                return {
                    **self.discover(interaction_session_ref),
                    "decision_required": "select_project",
                }
            project_id = str(projects[0]["project_id"])
        if op in {"open", "select_project", "switch_project"}:
            selected = self._resolve_project(project_id, selection)
            provider_context = self._provider_context(selected)
            self._repository.set_interaction_project_context(
                interaction_session_ref,
                selected,
                provider_context_id=provider_context,
                transition="switch" if op == "switch_project" else "select",
                actor=actor,
                request_id=request_id,
            )
            return self.discover(interaction_session_ref)
        if op == "clear_project":
            cleared = self._repository.clear_interaction_project_context(
                interaction_session_ref, actor=actor, request_id=request_id
            )
            return {
                **self.discover(interaction_session_ref),
                "transition": dict(cleared),
            }
        raise ValueError("project_context_operation_invalid")

    def discover(self, interaction_session_ref: str) -> Mapping[str, object]:
        projects = list(self._repository.list_projects_for_interaction())
        current: ProjectContextBinding | None = (
            self._repository.get_interaction_project_context(interaction_session_ref)
        )
        choices = [
            {
                "number": index,
                "project_id": str(item["project_id"]),
                "name": str(item["name"]),
                "selected": bool(current and current.project_id == item["project_id"]),
            }
            for index, item in enumerate(projects, 1)
        ]
        return {
            "contract": "flow.project-context.v1",
            "selected": (
                {
                    "project_id": current.project_id,
                    "provider_configured": bool(current.provider_context_id),
                    "revision": current.revision,
                }
                if current
                else None
            ),
            "choices": choices,
            "decision_required": "select_project"
            if not current and len(choices) != 1
            else None,
        }

    def current(self, interaction_session_ref: str) -> ProjectContextBinding | None:
        return self._repository.get_interaction_project_context(interaction_session_ref)

    def _resolve_project(self, project_id: str, selection: int) -> str:
        projects = list(self._repository.list_projects_for_interaction())
        if project_id:
            matches = [item for item in projects if item["project_id"] == project_id]
            if len(matches) == 1:
                return str(matches[0]["project_id"])
            raise ValueError("project_context_project_unknown")
        if (
            isinstance(selection, int)
            and not isinstance(selection, bool)
            and 1 <= selection <= len(projects)
        ):
            return str(projects[selection - 1]["project_id"])
        raise ValueError("project_context_selection_required")

    def _provider_context(self, project_id: str) -> str:
        bindings = [
            item
            for item in self._repository.list_provider_bindings(project_id) or ()
            if str(item.get("status") or "active") == "active"
        ]
        if not bindings:
            return ""
        if self._provider_context_resolver is not None:
            try:
                return str(self._provider_context_resolver(project_id) or "").strip()
            except Exception as exc:
                terminal_reason = str(
                    getattr(
                        exc, "terminal_reason", "project_context_provider_unavailable"
                    )
                )
                raise ValueError(terminal_reason) from exc
        values = {
            str(item.get("provider_context_id") or "").strip()
            for item in bindings
            if str(item.get("provider_context_id") or "").strip()
        }
        if len(values) > 1:
            raise ValueError("project_context_provider_binding_ambiguous")
        return next(iter(values), "")


__all__ = ["ProjectContextService"]
