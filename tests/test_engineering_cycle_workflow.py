"""Review is a handoff dimension, never an erasure of implemented facts."""
import sqlite3

import pytest

from flow_of_work_mcp.application.engineering_cycle import RepositoryReviewService
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from tests.engineering_cycle_support import record_test_repository_review
from tests.test_external_work import fixture, report
from tests.test_external_packet_dependencies import dependent_fixture


def finish_units(service, ids, revs):
    receipt = None
    for key in ("producer", "consumer"):
        receipt = service.call(*ids, "report_outcome", actor="agent", request_id="finish-" + key,
                               payload=report(service, ids, revs, key, report_key="finished-" + key))
    return receipt


def test_reported_work_stays_complete_while_review_closes_handoff(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    receipt = finish_units(service, ids, revs)
    assert receipt["status"] == "success"
    assert receipt["repository_review"]["required"] is True
    assert receipt["next_gate"]["tool"] == "fow_audit_phase"
    closure = service.implementation_closure(*ids)
    assert closure["implementation_complete"] is True
    assert closure["local_verification_complete"] is True
    assert closure["complete"] is False
    assert closure["reason"] == "repository_review_required"
    before = ledger.external_work_state(*ids)["reports"]
    fingerprint = service.todo(*ids)["authority_fingerprint"]
    record_test_repository_review(ledger, ids)
    current = service.todo(*ids)
    assert current["repository_review"]["complete"] is True
    assert current["authority_fingerprint"] == fingerprint
    assert current["next_gate"]["external_operation"] == "obtain_deferred_verification"
    assert service.implementation_closure(*ids)["complete"] is True
    assert ledger.external_work_state(*ids)["reports"] == before
    assert current["acceptance"] == "not_inferred"


def test_historical_coverage_records_observation_without_current_closure(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    finish_units(service, ids, revs)
    record_test_repository_review(ledger, ids, state="historical_on_pin")
    context = RepositoryReviewService(ledger).context(*ids)
    assert context["retrospective_recorded"] is True
    assert context["complete"] is False
    assert service.implementation_closure(*ids)["implementation_complete"] is True
    assert service.todo(*ids)["next_gate"]["tool"] == "fow_audit_phase"


def test_dependent_packet_requires_review_without_rewriting_producer_reports(tmp_path):
    ledger, service, producer, revs, consumer, _ = dependent_fixture(tmp_path)
    finish_units(service, producer, revs)
    assert service.todo(*consumer)["reason"] == "packet_dependencies_unresolved"
    row = service.implementation_closure(*consumer)["packet_dependencies"]["predecessors"][0]
    assert row["implementation_complete"] is True
    assert row["reconciliation_complete"] is False
    before = ledger.external_work_state(*producer)["reports"]
    record_test_repository_review(ledger, producer)
    assert service.todo(*consumer)["current_unit"]["unit_key"] == "facade"
    assert ledger.external_work_state(*producer)["reports"] == before


def test_history_read_survives_execution_guard_and_authority_resolution_failure(tmp_path, monkeypatch):
    ledger, service, ids, revs = fixture(tmp_path)
    finish_units(service, ids, revs)
    with sqlite3.connect(ledger.database_path) as connection:
        before = tuple(connection.iterdump())
    def outside(*_):
        raise ChangeControlBlockedError("packet_outside_confirmed_guided_scope")
    service._execution_guard = outside
    assert service.todo(*ids)["execution_allowed"] is False
    history = service.validation(*ids, detail="full")
    assert history["report_history_page"]["total"] == 2
    assert history["report_history"][0]["source_revision"] == "host-revision-1"
    assert history["report_history"][0]["actor"] == "agent"
    assert history["report_history"][0]["occurred_at"]
    assert history["report_history"][0]["compatibility"] == "not_assessed_by_history_read"
    def broken_authority(*_):
        raise ValueError("selected architecture reference cannot be resolved")
    monkeypatch.setattr(ledger, "resolve_architecture_refs", broken_authority)
    blocked = service.validation(*ids, detail="full")
    assert blocked["execution_readiness"] == "not_evaluated"
    assert blocked["repository_review"]["state"] == "authority_blocked"
    assert blocked["report_history_page"]["total"] == 2
    assert all(row["currentness"] == "not_evaluated" for row in blocked["report_history"])
    with sqlite3.connect(ledger.database_path) as connection:
        assert tuple(connection.iterdump()) == before


def test_all_blocked_todo_paths_keep_read_only_history_route(tmp_path):
    _ledger, service, producer, _revs, consumer, _ = dependent_fixture(tmp_path)
    blocked = service.todo(*consumer)
    assert blocked["reason"] == "packet_dependencies_unresolved"
    route = blocked["history_route"]
    assert route["operation"] == "validation"
    assert route["arguments"]["payload"]["detail"] == "full"
    assert service.validation(*consumer, detail="full")["report_history"] == []


def test_review_reads_reuse_only_the_current_coherent_read_scope(tmp_path, monkeypatch):
    ledger, service, ids, revs = fixture(tmp_path)
    finish_units(service, ids, revs)
    original = ledger.all_phase_audits
    reads = []
    def observed(project):
        reads.append(project)
        return original(project)
    monkeypatch.setattr(ledger, "all_phase_audits", observed)
    with ledger.consistent_read():
        service.validation(*ids)
        service.todo(*ids)
        assert RepositoryReviewService(ledger).context(*ids)["complete"] is False
    assert reads == [ids[0]]
    record_test_repository_review(ledger, ids)
    before = len(reads)
    with ledger.consistent_read():
        assert service.todo(*ids)["repository_review"]["complete"] is True
        service.validation(*ids)
    assert len(reads) == before + 1


@pytest.mark.parametrize("offset", [True, -1, "0", 1.2])
def test_history_paging_is_strict(tmp_path, offset):
    _ledger, service, ids, _revs = fixture(tmp_path)
    with pytest.raises(ValueError):
        service.validation(*ids, detail="full", history_offset=offset)
