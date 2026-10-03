"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

import json
import sqlite3
from typing import Mapping

from flow_of_work_mcp.core.domain import (
    JobRecord,
    JobStatus,
)
from flow_of_work_mcp.core.domain.identifiers import (
    required_text,
)
from flow_of_work_mcp.core.errors import (
    JobNotFoundError,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now



class JobStoreMixin:
    def create_job(self, job: JobRecord) -> JobRecord:
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, job.project_id)
            if job.request_id:
                existing = connection.execute(
                    """
                    SELECT job_id FROM jobs
                    WHERE project_id = ? AND request_id = ?
                    """,
                    (job.project_id, job.request_id),
                ).fetchone()
                if existing is not None:
                    return self._job_row(connection, job.project_id, str(existing["job_id"]))
            connection.execute(
                """
                INSERT OR IGNORE INTO job_sequences(project_id, next_job_ordinal)
                VALUES (?, 1)
                """,
                (job.project_id,),
            )
            ordinal = int(
                connection.execute(
                    "SELECT next_job_ordinal FROM job_sequences WHERE project_id = ?",
                    (job.project_id,),
                ).fetchone()["next_job_ordinal"]
            )
            job_id = f"JOB-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO jobs(
                    project_id, job_id, ordinal, kind, status, progress, terminal_reason,
                    result_json, created_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, '', '{}', ?, ?, ?)
                """,
                (
                    job.project_id,
                    job_id,
                    ordinal,
                    job.kind,
                    JobStatus.QUEUED.value,
                    0,
                    occurred_at,
                    job.created_by,
                    job.request_id,
                ),
            )
            connection.execute(
                """
                UPDATE job_sequences SET next_job_ordinal = ?
                WHERE project_id = ?
                """,
                (ordinal + 1, job.project_id),
            )
            self._append_event(
                connection,
                project_id=job.project_id,
                requirement_id=None,
                event_type="job_created",
                actor=job.created_by,
                request_id=job.request_id,
                payload={"job_id": job_id, "kind": job.kind, "status": JobStatus.QUEUED.value},
                occurred_at=occurred_at,
            )
            return self._job_row(connection, job.project_id, job_id)

    def mark_job_running(self, project_id: str, job_id: str) -> JobRecord:
        occurred_at = _utc_now()
        with self._transaction() as connection:
            current = self._job_row(connection, project_id, job_id)
            if current.status != JobStatus.QUEUED:
                return current
            connection.execute(
                """
                UPDATE jobs SET status = ?, progress = ?, started_at = ?
                WHERE project_id = ? AND job_id = ?
                """,
                (JobStatus.RUNNING.value, 10, occurred_at, project_id, job_id),
            )
            self._append_event(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="job_started",
                actor=current.created_by,
                request_id=current.request_id,
                payload={"job_id": job_id, "kind": current.kind},
                occurred_at=occurred_at,
            )
            return self._job_row(connection, project_id, job_id)

    def complete_job(
        self, project_id: str, job_id: str, *, result: Mapping[str, object]
    ) -> JobRecord:
        return self._finish_job(
            project_id,
            job_id,
            status=JobStatus.COMPLETED,
            terminal_reason="completed",
            result=result,
        )

    def block_job(self, project_id: str, job_id: str, *, terminal_reason: str) -> JobRecord:
        return self._finish_job(
            project_id,
            job_id,
            status=JobStatus.BLOCKED,
            terminal_reason=required_text(terminal_reason, "terminal_reason"),
            result={},
        )

    def fail_job(self, project_id: str, job_id: str, *, terminal_reason: str) -> JobRecord:
        return self._finish_job(
            project_id,
            job_id,
            status=JobStatus.FAILED,
            terminal_reason=required_text(terminal_reason, "terminal_reason"),
            result={},
        )

    def get_job(self, project_id: str, job_id: str) -> JobRecord:
        with self._read_connection() as connection:
            return self._job_row(connection, project_id, job_id)

    def jobs(self, project_id: str) -> list[JobRecord]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            rows = connection.execute(
                """
                SELECT project_id, job_id, kind, status, progress, terminal_reason,
                       result_json, created_by, request_id
                FROM jobs WHERE project_id = ? ORDER BY ordinal
                """,
                (project_id,),
            ).fetchall()
            return [self._job_from_row(row) for row in rows]

    def recover_interrupted_jobs(self) -> int:
        """Fail closed after restart: interrupted work is never silently resumed."""

        occurred_at = _utc_now()
        count = 0
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT project_id, job_id, kind, created_by, request_id
                FROM jobs
                WHERE status IN (?, ?)
                ORDER BY project_id, ordinal
                """,
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = ?, terminal_reason = ?, completed_at = ?
                    WHERE project_id = ? AND job_id = ?
                    """,
                    (
                        JobStatus.BLOCKED.value,
                        "process_interrupted",
                        occurred_at,
                        row["project_id"],
                        row["job_id"],
                    ),
                )
                self._append_event(
                    connection,
                    project_id=str(row["project_id"]),
                    requirement_id=None,
                    event_type="job_interrupted",
                    actor="system",
                    request_id=str(row["request_id"]),
                    payload={"job_id": row["job_id"], "kind": row["kind"]},
                    occurred_at=occurred_at,
                )
                count += 1
        return count

    def _finish_job(
        self,
        project_id: str,
        job_id: str,
        *,
        status: JobStatus,
        terminal_reason: str,
        result: Mapping[str, object],
    ) -> JobRecord:
        occurred_at = _utc_now()
        with self._transaction() as connection:
            current = self._job_row(connection, project_id, job_id)
            if current.status in {JobStatus.COMPLETED, JobStatus.BLOCKED, JobStatus.FAILED}:
                return current
            progress = 100 if status == JobStatus.COMPLETED else current.progress
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, progress = ?, terminal_reason = ?, result_json = ?, completed_at = ?
                WHERE project_id = ? AND job_id = ?
                """,
                (
                    status.value,
                    progress,
                    terminal_reason,
                    json.dumps(dict(result), sort_keys=True, separators=(",", ":")),
                    occurred_at,
                    project_id,
                    job_id,
                ),
            )
            self._append_event(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type=f"job_{status.value}",
                actor=current.created_by,
                request_id=current.request_id,
                payload={
                    "job_id": job_id,
                    "kind": current.kind,
                    "terminal_reason": terminal_reason,
                },
                occurred_at=occurred_at,
            )
            return self._job_row(connection, project_id, job_id)

    def _job_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        job_id: str,
    ) -> JobRecord:
        self._ensure_project(connection, project_id)
        row = connection.execute(
            """
            SELECT project_id, job_id, kind, status, progress, terminal_reason,
                   result_json, created_by, request_id
            FROM jobs WHERE project_id = ? AND job_id = ?
            """,
            (project_id, required_text(job_id, "job_id")),
        ).fetchone()
        if row is None:
            raise JobNotFoundError(f"unknown job in project {project_id}: {job_id}")
        return self._job_from_row(row)

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            project_id=str(row["project_id"]),
            job_id=str(row["job_id"]),
            kind=str(row["kind"]),
            status=JobStatus(str(row["status"])),
            progress=int(row["progress"]),
            terminal_reason=str(row["terminal_reason"]),
            result=json.loads(str(row["result_json"])),
            created_by=str(row["created_by"]),
            request_id=str(row["request_id"]),
        )
