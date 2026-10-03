"""Durable job value objects for asynchronous MCP operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class JobRecord:
    project_id: str
    kind: str
    created_by: str
    request_id: str = ""
    job_id: str = ""
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    terminal_reason: str = ""
    result: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", validate_project_id(self.project_id))
        object.__setattr__(self, "kind", required_text(self.kind, "kind"))
        object.__setattr__(self, "created_by", required_text(self.created_by, "created_by"))
        if self.job_id and not self.job_id.startswith("JOB-"):
            raise ValueError("job_id must be server-assigned JOB-* identity")
        if not 0 <= self.progress <= 100:
            raise ValueError("job progress must be within [0, 100]")
        if self.status == JobStatus.COMPLETED and self.progress != 100:
            raise ValueError("completed jobs must have 100% progress")
        if self.status in {JobStatus.BLOCKED, JobStatus.FAILED} and not self.terminal_reason:
            raise ValueError("blocked and failed jobs require a terminal reason")
