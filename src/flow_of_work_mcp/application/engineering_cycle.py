"""Revision-bound host repository review; no repository inspection or execution."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import fingerprint
from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.jobs import JobRecord
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, ChangeNotFoundError, InputValidationError


REVIEW_CONTRACT = "flow.repository-review.v1"
PROJECTION_CONTRACT = "flow.repository-review-projection.v1"
DIMENSIONS = ("requirements", "architecture", "grounding", "verification", "outcomes")
REVIEW_STATES = frozenset({"aligned", "reconciled", "historical_on_pin", "authority_missing",
                           "compatibility_review", "current_obligation", "unknown", "not_applicable"})
_CURRENT_STATES = frozenset({"aligned", "reconciled"})
_RETROSPECTIVE_STATES = _CURRENT_STATES | {"historical_on_pin", "not_applicable"}


def _bounded_text(value, field, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be nonempty text of at most {limit} characters")
    return value.strip()


def normalize_repository_review(value: object) -> dict[str, object]:
    """Validate the exact public declaration, independently of mutable authority."""
    keys = {"contract_version", "change_id", "packet_id", "expected_basis_fingerprint",
            "source_identity", "source_revision", "coverage"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError("repository_review must contain exactly the declared contract fields")
    if value["contract_version"] != REVIEW_CONTRACT:
        raise ValueError("repository_review contract_version is unsupported")
    change = _bounded_text(value["change_id"], "change_id", 64)
    packet = _bounded_text(value["packet_id"], "packet_id", 64)
    validate_change_id(change)
    validate_packet_id(packet)
    basis = value["expected_basis_fingerprint"]
    if not isinstance(basis, str) or len(basis) != 64 or any(c not in "0123456789abcdef" for c in basis):
        raise ValueError("expected_basis_fingerprint must be a SHA256 fingerprint")
    rows = value["coverage"]
    if not isinstance(rows, list) or len(rows) != len(DIMENSIONS):
        raise ValueError("repository_review coverage must contain exactly five dimensions")
    coverage = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"dimension", "state", "rationale", "evidence_refs"}:
            raise ValueError("coverage rows must contain exactly dimension, state, rationale and evidence_refs")
        dimension, state = row["dimension"], row["state"]
        if not isinstance(dimension, str) or dimension not in DIMENSIONS or dimension in coverage:
            raise ValueError("coverage dimensions must be unique known dimensions")
        if not isinstance(state, str) or state not in REVIEW_STATES:
            raise ValueError("coverage state is unsupported")
        refs = row["evidence_refs"]
        if not isinstance(refs, list) or len(refs) > 16:
            raise ValueError("evidence_refs must be a list of at most sixteen locators")
        refs = [_bounded_text(ref, "evidence_ref", 512) for ref in refs]
        if len(set(refs)) != len(refs):
            raise ValueError("evidence_refs must be unique")
        if state in _CURRENT_STATES | {"historical_on_pin"} and not refs:
            raise ValueError("aligned, reconciled and historical_on_pin require evidence references")
        coverage[dimension] = {"dimension": dimension, "state": state,
                               "rationale": _bounded_text(row["rationale"], "rationale", 4096),
                               "evidence_refs": refs}
    result = {"contract_version": REVIEW_CONTRACT, "change_id": change, "packet_id": packet,
              "expected_basis_fingerprint": basis,
              "source_identity": _bounded_text(value["source_identity"], "source_identity", 512),
              "source_revision": _bounded_text(value["source_revision"], "source_revision", 512),
              "coverage": [coverage[key] for key in DIMENSIONS]}
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")) > 65536:
        raise ValueError("repository_review exceeds 64KiB")
    return result


def engineering_cycle_version(plan: Mapping[str, object] | None) -> int | None:
    """Only an original accepted-plan event enrolls issued authority in the cycle."""
    for event in (plan or {}).get("events", ()):
        version = (event.get("payload") or {}).get("engineering_cycle_version")
        if (event.get("event_type") == "work_plan_accepted"
                and type(version) is int and version == 1):
            return 1
    return None


def _absence(snapshot):
    plan = snapshot.get("plan") or {}
    units = plan.get("units") or []
    verification = any(unit.get("verifies") for unit in units)
    verification = verification or bool(snapshot.get("campaigns")) or any(
        str(key).startswith(("campaign:", "oracle:")) for key in snapshot.get("resolved_authorities", {}))
    return {"requirements": not bool(snapshot.get("requirements")),
            "architecture": not bool((snapshot.get("packet") or {}).get("architecture_refs")),
            "grounding": not bool(snapshot.get("goals")),
            "verification": not verification,
            "outcomes": not units and not (snapshot.get("external") or {}).get("reports")}


def _review_basis(snapshot):
    # Include selections and report dispositions: resolving a conflict is relevant,
    # but jobs, event clocks and review records never invalidate their own audit.
    report_scopes = {}
    def collect(value):
        key = value["packet_id"]
        if key in report_scopes:
            return
        external = value.get("external") or {}
        report_scopes[key] = {"packet_id": key,
            "reports": sorted((dict(row) for row in external.get("reports", [])), key=lambda row: str(row["report_key"])),
            "selections": external.get("selections", [])}
        for predecessor in value.get("predecessor_packets", []):
            collect(predecessor)
        if value.get("contextual_predecessor") is not None:
            collect(value["contextual_predecessor"])
    collect(snapshot)
    return fingerprint({"policy": REVIEW_CONTRACT, "authority": snapshot["authority_basis"],
                        "report_scopes": [report_scopes[key] for key in sorted(report_scopes)]})


def repository_review_projection(snapshot: Mapping[str, object], audits) -> dict[str, object]:
    version = engineering_cycle_version(snapshot.get("plan"))
    required = version == 1 and (snapshot.get("external") or {}).get("consumption_mode") == "external_agent"
    requirement_ids = sorted(str(row["requirement_id"]) for row in snapshot.get("requirements", []))
    scope_id = "repository:" + snapshot["packet_id"] + ":" + fingerprint(requirement_ids)[:16]
    basis = _review_basis(snapshot)
    relevant = [audit for audit in audits if audit.get("scope_id") == scope_id
                and (audit.get("repository_review") or {}).get("packet_id") == snapshot["packet_id"]
                and (audit.get("repository_review") or {}).get("change_id") == snapshot["change_id"]]
    latest = max(relevant, key=lambda audit: int(audit["phase_audit_id"]), default=None)
    review = (latest or {}).get("repository_review")
    current = bool(review and review["expected_basis_fingerprint"] == basis)
    absence = _absence(snapshot)
    coverage = deepcopy(review["coverage"]) if review else []
    complete = current and all(row["state"] in _CURRENT_STATES or
                               (row["state"] == "not_applicable" and absence[row["dimension"]])
                               for row in coverage)
    retrospective = current and all(row["state"] in _RETROSPECTIVE_STATES
        and (row["state"] != "not_applicable" or absence[row["dimension"]]) for row in coverage)
    gaps = [*snapshot.get("missing_requirement_ids", []), *snapshot.get("missing_goal_ids", []),
            *snapshot.get("missing_milestone_ids", [])]
    architecture_gaps = (snapshot.get("architecture") or {}).get("gaps", [])
    if gaps or architecture_gaps:
        state = "authority_blocked"
        complete = retrospective = False
    elif review and not current:
        state = "stale"
    elif review:
        state = "current" if complete else "open"
    elif version is None:
        state = ("historical_authority" if (snapshot.get("plan") or {}).get("status")
                 in {"accepted", "superseded"} else "not_required")
    else:
        state = "pending" if required else "not_required"
    template = {"contract_version": REVIEW_CONTRACT, "change_id": snapshot["change_id"],
                "packet_id": snapshot["packet_id"], "expected_basis_fingerprint": basis}
    route = None if complete else {"tool": "fow_audit_phase", "operation": "call",
        "arguments": {"project_id": snapshot["project_id"], "scope_id": scope_id,
                      "requirement_ids": requirement_ids},
        "required_inputs": ["actor", "request_id", "repository_review.source_identity",
                            "repository_review.source_revision", "repository_review.coverage"],
        "repository_review_template": template}
    result = {"contract_version": PROJECTION_CONTRACT, "engineering_cycle_version": version,
              "required": required, "state": state, "scope_id": scope_id,
              "requirement_ids": requirement_ids, "basis_fingerprint": basis,
              "latest_audit_id": int(latest["phase_audit_id"]) if latest else None,
              "source": {"identity": review["source_identity"], "revision": review["source_revision"],
                         "provenance": "host_declared"} if review else None,
              "coverage": coverage, "complete": bool(complete), "retrospective_recorded": bool(retrospective),
              "semantic_truth_verified": False, "human_acceptance": False, "next_gate": route}
    if state == "authority_blocked":
        result["basis_fingerprint"] = None
        result["diagnostic"] = {"reason": "repository_review_authority_blocked", "missing_authority": gaps,
                                "architecture_gaps": deepcopy(architecture_gaps)}
        result["next_gate"] = {"tool": "fow_external_work", "operation": "validation",
            "arguments": {"project_id": snapshot["project_id"], "change_id": snapshot["change_id"],
                          "packet_id": snapshot["packet_id"], "operation": "validation", "payload": {"detail": "full"}},
            "required_inputs": []}
    return result


class RepositoryReviewService:
    def __init__(self, ledger):
        self._ledger = ledger

    def context(self, project_id, change_id, packet_id):
        from flow_of_work_mcp.application.external_work import ExternalWorkService
        from flow_of_work_mcp.application.engineer_gate import EngineerGateService
        with self._ledger.consistent_read():
            snapshot = ExternalWorkService(self._ledger,
                engineer_projection=EngineerGateService(self._ledger).projection)._snapshot(project_id, change_id, packet_id)
            return deepcopy(snapshot['repository_review'])

    def validate(self, project_id, scope, review):
        review = normalize_repository_review(review)
        try:
            context = self.context(project_id, review["change_id"], review["packet_id"])
        except (ChangeControlBlockedError, ChangeNotFoundError) as exc:
            if isinstance(exc, ChangeControlBlockedError) and exc.reason != "packet_not_found":
                raise
            raise InputValidationError("Review identities must name an existing packet in this project/change.",
                field="repository_review.packet_id", received_value=review["packet_id"], details={
                    "scope_id": scope.scope_id, "cause": getattr(exc, "reason", "change_not_found"),
                    "resolution": "Inspect this project's lifecycle state and select the exact existing change/packet; do not copy foreign IDs.",
                    "next_tool_call": {"tool": "fow_handover", "arguments": {
                        "project_id": project_id, "operation": "project_state_snapshot"}}}) from exc
        if context["state"] == "authority_blocked":
            raise ChangeControlBlockedError("repository_review_authority_blocked", details=context)
        if scope.scope_id != context["scope_id"] or list(scope.requirement_ids) != context["requirement_ids"]:
            raise ValueError("repository review scope must match the current exact derived scope")
        if review["expected_basis_fingerprint"] != context["basis_fingerprint"]:
            raise ChangeControlBlockedError("repository_review_basis_stale", details={"repository_review": context})
        from flow_of_work_mcp.application.external_work import ExternalWorkService
        snapshot = ExternalWorkService(self._ledger)._snapshot(project_id, review["change_id"], review["packet_id"])
        absence = _absence(snapshot)
        if any(row["state"] == "not_applicable" and not absence[row["dimension"]] for row in review["coverage"]):
            raise ValueError("not_applicable requires genuine absence in the selected canonical scope")
        return review

    @staticmethod
    def read_call(project_id, change_id, packet_id):
        return {"tool": "fow_external_work", "arguments": {"project_id": project_id,
            "change_id": change_id, "packet_id": packet_id, "operation": "validation",
            "payload": {"detail": "full"}}}

    def submit(self, project_id, scope, value, *, actor, request_id, jobs, lifecycle):
        """Reserve the exact job atomically, then revalidate in the queued worker."""
        from flow_of_work_mcp.application.jobs import JobBlockedError
        try:
            review = normalize_repository_review(value)
        except ValueError as exc:
            raise InputValidationError(str(exc), field="repository_review", received_value=None,
                details={"resolution": "Read the current packet validation and supply the exact review template, five coverage rows and real host evidence."}) from exc
        for name, item in (("actor", actor), ("request_id", request_id)):
            if not isinstance(item, str) or not item.strip():
                raise InputValidationError(f"{name} is required for repository review", field=name,
                    received_value=item, details={"resolution": "Supply the recording actor and one stable caller-owned request identity."})
        actor, request_id = actor.strip(), request_id.strip()
        request_fp = fingerprint({"operation": "fow_audit_phase", "actor": actor,
            "scope_id": scope.scope_id, "requirement_ids": list(scope.requirement_ids), "repository_review": review})

        def operation():
            try:
                with self._ledger.atomic():
                    audit = lifecycle.audit_phase(project_id, scope, actor=actor,
                        request_id=request_id + ":phase", repository_review=review,
                        request_fingerprint=request_fp)
                    projection = self.context(project_id, review["change_id"], review["packet_id"])
                    return {"phase_audit_id": audit.audit_id, "scope_id": scope.scope_id,
                            "delta_count": len(audit.deltas), "repository_review": projection,
                            "next_tool_call": self.read_call(project_id, review["change_id"], review["packet_id"])}
            except ChangeControlBlockedError as exc:
                raise JobBlockedError(exc.reason) from exc
            except ValueError as exc:
                raise JobBlockedError("repository_review_scope_rejected") from exc

        with self._ledger.atomic():
            replay = self._ledger.phase_audit_request_replay(project_id, request_id, request_fp)
            if replay is None:
                try:
                    self.validate(project_id, scope, review)
                except InputValidationError:
                    raise
                except ValueError as exc:
                    raise InputValidationError(str(exc), field="repository_review", received_value=None,
                        details={"scope_id": scope.scope_id, "resolution": "Use the current derived scope, basis and structural applicability from full packet validation.",
                                 "next_tool_call": self.read_call(project_id, review["change_id"], review["packet_id"])}) from exc
                job = self._ledger.create_job(JobRecord(project_id=project_id, kind="audit_phase",
                                                        created_by=actor, request_id=request_id))
                self._ledger.reserve_phase_audit_request(project_id, request_id=request_id, actor=actor,
                    request_fingerprint=request_fp, job_id=job.job_id, repository_review=review)
            else:
                job = replay
        # Queue dispatch happens only after the job and reservation are committed.
        # A retry can dispatch the same still-queued job; the worker cannot repeat
        # an already committed audit and the durable job service deduplicates it.
        if job.status.value == "queued":
            return jobs.submit(project_id=project_id, kind="audit_phase", actor=actor,
                               request_id=request_id, operation=operation)
        return job

    def job_recovery(self, project_id, job):
        """Read current audit even if job completion failed after its audit commit."""
        reservation = self._ledger.phase_audit_request_context(project_id, job.request_id)
        if reservation is None or reservation.get("job_id") != job.job_id:
            return None
        call = self.read_call(project_id, reservation["change_id"], reservation["packet_id"])
        audit = self._ledger.phase_audit_record_replay(project_id,
            request_id=reservation["request_id"] + ":phase", actor=reservation["actor"],
            request_fingerprint=reservation["request_fingerprint"])
        original = {"phase_audit_id": audit.audit_id, "scope_id": audit.scope.scope_id,
                    "repository_review": deepcopy(audit.repository_review)} if audit is not None else None
        try:
            context = self.context(project_id, reservation["change_id"], reservation["packet_id"])
        except (ValueError, ChangeControlBlockedError) as exc:
            return {"original_audit": original, "next_tool_call": call, "diagnostics": [{"code": getattr(exc, "reason", "repository_review_authority_blocked"),
                "field": "repository_review.expected_basis_fingerprint", "message": str(exc),
                "resolution": "Inspect original reports and resolve the selected canonical authority before a new review."}]}
        return {"original_audit": original, "repository_review": context, "next_tool_call": call,
                "diagnostics": [{"code": job.terminal_reason or "repository_review_recorded",
                    "field": "repository_review.expected_basis_fingerprint", "scope_id": context["scope_id"],
                    "message": "Inspect the original audit and current scoped basis; a job error does not erase a committed audit.",
                    "resolution": "Retain the original request result. Use a new request only for a new grounded review against current authority."}]}
