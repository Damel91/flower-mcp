"""Bounded packet-provider fixtures shared by installed sync-only qualification."""
from __future__ import annotations

from typing import Mapping
from dataclasses import replace
import json
import sqlite3

from flow_of_work_mcp import GovernedChangeDraft, RequirementDraft, RequirementService
from flow_of_work_mcp.application import ChangeControlService
from flow_of_work_mcp.core.domain.packet_provider import PacketProviderCommand, PacketProviderReceipt, PacketProviderUnitReceipt
from flow_of_work_mcp.core.domain.provider_binding import ImplementationProviderKind, ProviderProjectBindingDraft
from flow_of_work_mcp.core.domain.provider_validation import ACK_VERSION, RECEIPT_VERSION
from flow_of_work_mcp.core.errors import ImplementationProviderUnavailableError, PacketProviderRejectedError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import handle_packet_author
from tests.engineering_cycle_support import adopt_minimal_architecture
from tests.test_packet_executor import CapabilityProvider


class _PacketProvider:
    kind = "codingcastle"

    def __init__(self, *, bound: bool = True, offer_choices: bool = False) -> None:
        self.bound = bound
        self.offer_choices = offer_choices
        self.packet_ref = "cc-packet-1"
        self.binding_epoch = 1
        self.revision = 0
        self.event_seq = 0
        self.packet_state = "draft"
        self.run_phase = "idle"
        self.job_ref = ""
        self.units: dict[str, str] = {}
        self.commands: list[PacketProviderCommand] = []
        self._replays: dict[str, PacketProviderReceipt] = {}

    def session_for_project(self, project_id: str) -> str:
        if not self.bound or project_id != "alpha":
            raise ImplementationProviderUnavailableError(
                "packet_provider_project_unbound"
            )
        return "cc-session"

    def binding_identity(self, project_id):
        self.session_for_project(project_id)
        return self._capability_provider.binding_identity(project_id)

    def validation_capabilities(self, project_id):
        self.session_for_project(project_id)
        return self._capability_provider.validation_capabilities(project_id)

    def execute_bound(self, command, *, binding_identity):
        # Preserve this provider's state/choice/retry mechanics while conforming
        # to the already-qualified v3 exact-ACK pattern.
        receipt = self.execute(command)
        context = command.validation_context
        ack = {"contract_version": ACK_VERSION, "context_sha256": context["context_sha256"],
               "authority_fingerprint": context["authority_fingerprint"], "unit_key": context["unit_key"],
               "compiled_context_sha256": "a" * 64}
        return replace(receipt, provider_contract_version="codingcastle.packet.receipt.v3",
                       contract_version=RECEIPT_VERSION, validation_ack=ack)

    def execute(self, command: PacketProviderCommand) -> PacketProviderReceipt:
        self.session_for_project(command.flow_session_ref)
        if command.operation.value == "status":
            if self.run_phase == "running":
                self.event_seq += 1
                self.run_phase = "completed"
                self.packet_state = "completed"
            return self._receipt(changed=False, include_all_units=True)
        cached = self._replays.get(command.delivery_fingerprint)
        if cached is not None:
            return cached
        self.commands.append(command)
        receipt = self._execute(command)
        self._replays[command.delivery_fingerprint] = receipt
        return receipt

    def _execute(self, command: PacketProviderCommand) -> PacketProviderReceipt:
        operation = command.operation.value
        semantic = dict(command.semantic_input)
        if operation == "add" and not semantic:
            self.event_seq += 1
            return self._receipt(
                changed=True,
                choices=(
                    (
                        {
                            "ordinal": 1,
                            "label": "Service.run",
                            "relative_path": "src/service.py",
                            "kind": "method",
                        },
                        {
                            "ordinal": 2,
                            "label": "Service.helper",
                            "relative_path": "src/service.py",
                            "kind": "method",
                        },
                    )
                    if self.offer_choices
                    else ()
                ),
            )
        if operation in {"add", "edit"}:
            unit = semantic.get("unit")
            changes = semantic.get("changes")
            authored = unit if isinstance(unit, Mapping) else changes
            if not isinstance(authored, Mapping):
                raise AssertionError("provider unit payload is missing")
            key = command.flow_unit_ref
            self.units.setdefault(key, f"cc-unit-{key}")
            self.revision += 1
            self.event_seq += 1
            self.packet_state = "ready"
            return self._receipt(changed=True, unit_key=key, unit_state="ready")
        if operation == "remove":
            key = command.flow_unit_ref
            unit_ref = self.units.pop(key)
            self.revision += 1
            self.event_seq += 1
            self.packet_state = "ready" if self.units else "draft"
            return self._receipt(
                changed=True,
                unit_key=key,
                unit_ref=unit_ref,
                unit_state="removed",
            )
        if operation == "start":
            self.event_seq += 1
            self.packet_state = "running"
            self.run_phase = "running"
            self.job_ref = self.job_ref or "cc-job-1"
            return self._receipt(changed=True, include_all_units=True)
        if operation == "stop":
            self.event_seq += 1
            self.packet_state = "stopped"
            self.run_phase = "stopped"
            return self._receipt(changed=True, include_all_units=True)
        raise AssertionError(f"unexpected provider operation: {operation}")

    def _receipt(
        self,
        *,
        changed: bool,
        unit_key: str = "",
        unit_ref: str = "",
        unit_state: str = "",
        include_all_units: bool = False,
        choices: tuple[Mapping[str, object], ...] = (),
    ) -> PacketProviderReceipt:
        if include_all_units:
            units = tuple(
                PacketProviderUnitReceipt(
                    flow_unit_ref=key,
                    provider_unit_ref=provider_ref,
                    state="ready",
                    unit_number=ordinal,
                )
                for ordinal, (key, provider_ref) in enumerate(
                    self.units.items(), start=1
                )
            )
        elif unit_key:
            units = (
                PacketProviderUnitReceipt(
                    flow_unit_ref=unit_key,
                    provider_unit_ref=unit_ref or self.units[unit_key],
                    state=unit_state,
                    unit_number=tuple(self.units).index(unit_key) + 1,
                ),
            )
        else:
            units = ()
        return PacketProviderReceipt(
            provider_kind=self.kind,
            provider_contract_version="codingcastle.packet.receipt.v2",
            provider_packet_ref=self.packet_ref,
            provider_packet_revision=self.revision,
            provider_state=self.packet_state,
            binding_epoch=self.binding_epoch,
            event_seq=self.event_seq,
            changed=changed,
            unit_receipts=units,
            run_phase=self.run_phase,
            provider_job_ref=(self.job_ref if self.run_phase != "idle" else ""),
            current_step="choose_target" if choices else "add",
            question="Which visited symbol should this unit modify?" if choices else "",
            choices=choices,
            required_input={"target": {"mutation": None, "context": []}}
            if choices
            else {},
            available_actions=("add", "status"),
        )


class _RejectUnitOnceProvider(_PacketProvider):
    def __init__(
        self,
        *,
        reason: str = "packet_revision_conflict",
        offer_choices: bool = False,
    ) -> None:
        super().__init__(offer_choices=offer_choices)
        self._reject_unit_once = True
        self._rejection_reason = reason

    def execute(self, command: PacketProviderCommand) -> PacketProviderReceipt:
        if command.flow_unit_ref and self._reject_unit_once:
            self._reject_unit_once = False
            raise PacketProviderRejectedError(self._rejection_reason)
        return super().execute(command)


def _seed_packet(tmp_path, *, mode: str, provider=None, test_provider=None, legacy_wire=False):
    """Current v3 setup; legacy_wire explicitly models pre-policy v2 state."""
    runtime = build_runtime(
        database_path=tmp_path / f"{mode}.sqlite3",
        import_root=tmp_path,
        packet_provider_mode=mode,
        packet_provider=provider,
        test_provider=test_provider,
    )
    requirements = RequirementService(runtime.ledger)
    requirements.create_project("alpha", "Alpha", actor="operator")
    architecture_refs = adopt_minimal_architecture(runtime.ledger)
    requirement = requirements.register(
        "alpha",
        RequirementDraft(
            title="Provider packet overlay",
            statement="The server shall author and execute one bounded packet.",
            category="functional",
            rationale="Cross-server packet qualification.",
        ),
        actor="operator",
    )
    change = ChangeControlService(runtime.ledger).create_change(
        "alpha",
        GovernedChangeDraft(
            title="Provider packet overlay",
            rationale="Qualify the stable packet socket.",
            requirement_ids=(str(requirement["requirement_id"]),),
        ),
        actor="operator",
    )
    started = handle_packet_author(
        runtime,
        project_id="alpha",
        change_id=str(change["change_id"]),
        operation="start_packet",
        title="Provider packet",
        intent="Implement the bounded provider packet.",
        rationale="Keep semantic and technical authority separate.",
        completion_criteria=["The provider reports technical completion."],
        requirement_ids=[str(requirement["requirement_id"])],
        in_scope=["provider packet authoring"],
        out_of_scope=["semantic acceptance"],
        invariants=["provider completion does not accept the requirement"],
        target_policy="code_targets_required",
        architecture_refs=[] if legacy_wire else list(architecture_refs),
        actor="operator",
        request_id=f"start-{mode}",
    )
    packet_id = str(started["result"]["packet"]["packet_id"])
    runtime._sync_legacy_wire = legacy_wire
    runtime._sync_architecture_refs = architecture_refs
    if not legacy_wire:
        packet = next(row for row in runtime.ledger.change_state("alpha", change["change_id"])["packets"]
                      if row["packet_id"] == packet_id)
        runtime.external_work.call("alpha", change["change_id"], packet_id, "upgrade_validation",
            payload={"expected_spec_revision": packet["spec_revision"], "expected_plan_revision": 0},
            actor="operator", request_id="upgrade-provider-validation")
        if provider is not None:
            runtime.ledger.bind_provider_project("alpha", ProviderProjectBindingDraft(
                ImplementationProviderKind.PACKET_EXECUTION, "fixture-provider", "", (),
                provider_context_id="cc-session"), actor="operator")
            provider._capability_provider = CapabilityProvider(runtime.ledger)
            packet = next(row for row in runtime.ledger.change_state("alpha", change["change_id"])["packets"]
                          if row["packet_id"] == packet_id)
            runtime.external_work.call("alpha", change["change_id"], packet_id, "select_executor",
                payload={"executor": "provider", "provider_kind": "codingcastle",
                         "expected_spec_revision": packet["spec_revision"], "expected_plan_revision": 0},
                actor="operator", request_id="select-provider-executor")
    return (
        runtime,
        str(change["change_id"]),
        str(started["result"]["packet"]["packet_id"]),
        started,
    )


def _packet_and_plan(runtime, change_id: str, packet_id: str):
    change = runtime.changes.get_change("alpha", change_id)
    packet = next(item for item in change["packets"] if item["packet_id"] == packet_id)
    plan = runtime.ledger.packet_work_plan_state("alpha", change_id, packet_id)
    assert plan is not None
    return packet, plan


def _close_semantic_gates(runtime, change_id: str, packet_id: str) -> None:
    packet, plan = _packet_and_plan(runtime, change_id, packet_id)
    if runtime._sync_legacy_wire:
        # Construct the old issued state through real current prerequisites,
        # then remove only post-policy fields in the explicit fixture below.
        # Unissued legacy target-choice cases retain their original v2 shape.
        revised = handle_packet_author(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            operation="revise_packet", architecture_refs=list(runtime._sync_architecture_refs),
            expected_spec_revision=packet["spec_revision"], expected_plan_revision=plan["plan_revision"],
            actor="operator", request_id="legacy-fixture-architecture")
        assert revised["status"] == "success"
        packet, _ = _packet_and_plan(runtime, change_id, packet_id)
        replaced = handle_packet_author(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            operation="replace_plan", work_plan={"units": plan["units"]},
            expected_spec_revision=packet["spec_revision"], expected_plan_revision=plan["plan_revision"],
            actor="operator", request_id="legacy-fixture-plan")
        assert replaced["status"] == "success"
        packet, plan = _packet_and_plan(runtime, change_id, packet_id)
    runtime.packet_work_plan.accept(
        "alpha",
        change_id,
        packet_id,
        plan_revision=int(plan["plan_revision"]),
        expected_packet_revision=int(plan["packet_revision"]),
        expected_current_plan_revision=int(plan["plan_revision"]),
        rationale="The bounded work plan is approved for provider delivery.",
        actor="operator",
        request_id="accept-provider-plan",
    )
    audit = runtime.packet_construction.audit_for_packet("alpha", change_id, packet_id)
    assert audit is not None
    answers = [
        {
            "question_id": str(item["question_id"]),
            "answer_summary": "The packet metadata and bounded unit are authoritative.",
            "evidence_refs": ["test:semantic-authority"],
        }
        for item in audit.get("questions", [])
        if item.get("required") and item.get("status") in {"open", "blocked"}
    ]
    if answers:
        handle_packet_author(
            runtime,
            project_id="alpha",
            packet_id=packet_id,
            operation="resolve_questions",
            answers=answers,
            actor="operator",
            request_id="answer-provider-questions",
        )
    pressure = runtime.packet_pressure.derive(
        "alpha",
        change_id,
        packet_id,
        actor="operator",
        request_id="derive-provider-pressure",
    )
    if pressure.get("residual_risks"):
        runtime.packet_pressure.accept_risk(
            "alpha",
            str(pressure["pressure_id"]),
            accepted_risk_ref="test:accepted-provider-risk",
            actor="operator",
            request_id="accept-provider-pressure",
        )
    if runtime._sync_legacy_wire:
        # Explicit synthetic pre-policy v2 issued state for the one historical
        # compatibility case. This is not a current admission or a runtime bypass.
        with sqlite3.connect(runtime.ledger.database_path) as connection:
            for table in ("implementation_packets", "implementation_packet_revisions"):
                connection.execute(f"UPDATE {table} SET architecture_refs_json='[]' WHERE project_id=? AND packet_id=?",
                                   ("alpha", packet_id))
            events = connection.execute("SELECT event_id,payload_json FROM packet_work_plan_events WHERE project_id=? AND work_plan_id=?",
                                        ("alpha", plan["work_plan_id"])).fetchall()
            for event_id, payload in events:
                value = json.loads(payload)
                value.pop("engineering_cycle_version", None)
                connection.execute("UPDATE packet_work_plan_events SET payload_json=? WHERE event_id=?",
                                   (json.dumps(value), event_id))
        assert runtime.ledger.packet_work_plan_state("alpha", change_id, packet_id)["engineering_cycle_version"] is None
    else:
        packet, plan = _packet_and_plan(runtime, change_id, packet_id)
        negotiated = runtime.external_work.call("alpha", change_id, packet_id, "negotiate_provider",
            payload={"expected_spec_revision": packet["spec_revision"], "expected_plan_revision": plan["plan_revision"]},
            actor="operator", request_id="negotiate-provider-executor")
        assert negotiated["status"] == "success"


def _author_unit(runtime, packet_id: str, unit: Mapping[str, object], request: str):
    unit = dict(unit)
    if not runtime._sync_legacy_wire:
        unit.setdefault("implements", [1])
        unit.setdefault("verifies", [{"criterion": 1, "kind": "unit_check", "statement": check}
                                     for check in unit["unit_checks"]])
    return handle_packet_author(
        runtime,
        project_id="alpha",
        packet_id=packet_id,
        operation="add_unit",
        unit=unit,
        actor="operator",
        request_id=request,
    )
