"""Durable execution history for bounded semantic roles, not semantic authority."""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Mapping, Protocol


class SemanticAssignmentRepository(Protocol):
    def ensure_semantic_project(self, project_id: str) -> None: ...

    def atomic(self) -> AbstractContextManager:
        """Compose result adoption with the canonical lifecycle mutation."""

    def prepare_semantic_assignment(
        self, project_id: str, *, role: str, execution_mode: str,
        preparation: Mapping[str, object], actor: str, request_id: str = "",
    ) -> Mapping[str, object]: ...

    def semantic_assignment(
        self, project_id: str, assignment_id: str,
    ) -> Mapping[str, object]: ...

    def record_semantic_submission(
        self, project_id: str, assignment_id: str, *,
        result: Mapping[str, object], usable: bool, actor: str,
        request_id: str = "", internal: bool = False,
    ) -> Mapping[str, object]: ...

    def begin_semantic_internal(
        self, project_id: str, assignment_id: str, *, actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def adopt_semantic_assignment(
        self, project_id: str, assignment_id: str, *,
        adoption: Mapping[str, object], actor: str, request_id: str = "",
    ) -> Mapping[str, object]: ...
