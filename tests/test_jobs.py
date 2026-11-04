from flow_of_work_mcp import (
    DurableJobService,
    JobBlockedError,
    JobRecord,
    JobStatus,
    RequirementService,
    SQLiteRequirementLedger,
)


def _ledger(tmp_path):
    ledger = SQLiteRequirementLedger(tmp_path / "ledger.sqlite3")
    RequirementService(ledger).create_project("alpha", "Alpha", actor="orchestrator")
    return ledger


def test_job_is_durable_idempotent_and_returns_structured_result(tmp_path):
    ledger = _ledger(tmp_path)
    jobs = DurableJobService(ledger)
    calls = []
    try:
        first = jobs.submit(
            project_id="alpha",
            kind="generate_artifacts",
            actor="orchestrator",
            request_id="job-1",
            operation=lambda: calls.append("run") or {"generation_id": 1},
        )
        repeated = jobs.submit(
            project_id="alpha",
            kind="generate_artifacts",
            actor="orchestrator",
            request_id="job-1",
            operation=lambda: calls.append("must-not-run") or {"generation_id": 2},
        )
        completed = jobs.wait("alpha", first.job_id, timeout=5)

        assert repeated.job_id == first.job_id
        assert completed.status == JobStatus.COMPLETED
        assert completed.progress == 100
        assert completed.result == {"generation_id": 1}
        assert calls == ["run"]
    finally:
        jobs.shutdown()


def test_job_failure_and_blockage_do_not_persist_raw_exception(tmp_path):
    ledger = _ledger(tmp_path)
    jobs = DurableJobService(ledger)
    try:
        blocked = jobs.submit(
            project_id="alpha",
            kind="ground_intent",
            actor="orchestrator",
            request_id="job-blocked",
            operation=lambda: (_ for _ in ()).throw(JobBlockedError("provider_unconfigured")),
        )
        failed = jobs.submit(
            project_id="alpha",
            kind="validate_srs",
            actor="orchestrator",
            request_id="job-failed",
            operation=lambda: (_ for _ in ()).throw(RuntimeError("secret diagnostic")),
        )

        assert jobs.wait("alpha", blocked.job_id, timeout=5).terminal_reason == "provider_unconfigured"
        failed_result = jobs.wait("alpha", failed.job_id, timeout=5)
        assert failed_result.status == JobStatus.FAILED
        assert failed_result.terminal_reason == "job_execution_failed"
        assert "secret diagnostic" not in str(ledger.jobs("alpha"))
    finally:
        jobs.shutdown()


def test_startup_recovery_blocks_unfinished_jobs(tmp_path):
    ledger = _ledger(tmp_path)
    queued = ledger.create_job(
        JobRecord(
            project_id="alpha",
            kind="phase_audit",
            created_by="orchestrator",
            request_id="interrupted-1",
        )
    )
    jobs = DurableJobService(ledger)
    try:
        recovered = jobs.get("alpha", queued.job_id)
        assert recovered.status == JobStatus.BLOCKED
        assert recovered.terminal_reason == "process_interrupted"
    finally:
        jobs.shutdown()
