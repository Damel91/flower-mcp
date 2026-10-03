"""Single-process execution bridge for durable job records."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable, Mapping

from flow_of_work_mcp.core.domain.jobs import JobRecord, JobStatus
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.ports.jobs import JobRepository


class JobBlockedError(RuntimeError):
    """Expected job-level blockage that can be reported without a traceback."""

    def __init__(self, terminal_reason: str) -> None:
        super().__init__(terminal_reason)
        self.terminal_reason = required_text(terminal_reason, "terminal_reason")


class DurableJobService:
    """Runs bounded operations while SQLite remains the authority for state."""

    def __init__(self, repository: JobRepository, *, max_workers: int = 1) -> None:
        if max_workers <= 0:
            raise ValueError("job worker count must be positive")
        self._repository = repository
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fow-job")
        self._futures: dict[tuple[str, str], Future[None]] = {}
        self._lock = Lock()
        self._repository.recover_interrupted_jobs()

    def submit(
        self,
        *,
        project_id: str,
        kind: str,
        actor: str,
        request_id: str,
        operation: Callable[[], Mapping[str, object]],
    ) -> JobRecord:
        job = self._repository.create_job(
            JobRecord(
                project_id=project_id,
                kind=kind,
                created_by=actor,
                request_id=str(request_id or ""),
            )
        )
        key = (job.project_id, job.job_id)
        if job.status == JobStatus.QUEUED:
            with self._lock:
                if key not in self._futures:
                    self._futures[key] = self._executor.submit(self._run, job, operation)
        return job

    def get(self, project_id: str, job_id: str) -> JobRecord:
        return self._repository.get_job(project_id, job_id)

    def list(self, project_id: str) -> list[JobRecord]:
        return self._repository.jobs(project_id)

    def wait(self, project_id: str, job_id: str, *, timeout: float | None = None) -> JobRecord:
        key = (project_id, job_id)
        with self._lock:
            future = self._futures.get(key)
        if future is not None:
            future.result(timeout=timeout)
        return self.get(project_id, job_id)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def _run(self, job: JobRecord, operation: Callable[[], Mapping[str, object]]) -> None:
        key = (job.project_id, job.job_id)
        try:
            running = self._repository.mark_job_running(job.project_id, job.job_id)
            if running.status != JobStatus.RUNNING:
                return
            result = operation()
            self._repository.complete_job(job.project_id, job.job_id, result=dict(result))
        except JobBlockedError as exc:
            self._repository.block_job(
                job.project_id,
                job.job_id,
                terminal_reason=exc.terminal_reason,
            )
        except Exception:
            self._repository.fail_job(
                job.project_id,
                job.job_id,
                terminal_reason="job_execution_failed",
            )
        finally:
            with self._lock:
                self._futures.pop(key, None)
