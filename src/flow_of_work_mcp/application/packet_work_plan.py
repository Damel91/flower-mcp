"""Bulk authoring, preview and lifecycle policy for packet work plans."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import normalize_declarations
from flow_of_work_mcp.core.domain.packet_work_plan import (
    PacketWorkPlanDraft,
    PacketWorkPlanStatus,
    WorkPlanUnit,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.core.ports.change_control import ChangeControlRepository
from flow_of_work_mcp.core.ports.navigation_audit import NavigationAuditRepository
from flow_of_work_mcp.core.ports.packet_work_plan import PacketWorkPlanRepository


_IDENTIFIER_ONLY_RE = re.compile(r"^(?:[A-Z][A-Z0-9_-]*-[0-9]+|[A-Za-z_][A-Za-z0-9_.:-]*)$")


class PacketWorkPlanService:
    def __init__(
        self,
        repository: PacketWorkPlanRepository,
        *,
        changes: ChangeControlRepository,
        navigation: NavigationAuditRepository,
    ) -> None:
        self._repository = repository
        self._changes = changes
        self._navigation = navigation

    def set_plan(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        work_plan: Mapping[str, object],
        *,
        expected_packet_revision: int,
        expected_current_plan_revision: int | None,
        actor: str,
        request_id: str = "",
        request_fingerprint: str = "",
    ) -> Mapping[str, object]:
        draft = PacketWorkPlanDraft(
            change_id=change_id,
            packet_id=packet_id,
            packet_revision=int(expected_packet_revision),
            units=tuple(_unit_from_payload(item) for item in _mapping_list(work_plan, "units")),
        )
        return self._repository.create_packet_work_plan(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
            expected_current_plan_revision=expected_current_plan_revision,
            request_fingerprint=str(request_fingerprint or ""),
        )

    def mutate_plan(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        operation: str,
        expected_packet_revision: int,
        expected_current_plan_revision: int | None,
        actor: str,
        request_id: str,
        client_unit_key: str = "",
        unit: Mapping[str, object] | None = None,
        unit_patch: Mapping[str, object] | None = None,
        depends_on: list[str] | None = None,
    ) -> Mapping[str, object]:
        operation = str(operation or "").strip().lower()
        if operation not in {
            "add_unit",
            "revise_unit",
            "remove_unit",
            "rebind_unit",
            "set_dependencies",
        }:
            raise ValueError(f"unsupported work-plan mutation: {operation}")
        request_id = required_text(request_id, "request_id")
        fingerprint = _mutation_fingerprint(
            operation,
            client_unit_key=client_unit_key,
            unit=unit,
            unit_patch=unit_patch,
            depends_on=depends_on,
        )
        replay = self._repository.packet_work_plan_request_replay(
            project_id,
            request_id,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            if (
                str(replay.get("change_id") or "") != change_id
                or str(replay.get("packet_id") or "") != packet_id
            ):
                raise ChangeControlBlockedError("packet_work_plan_request_scope_conflict")
            return replay

        state = self._repository.packet_work_plan_state(
            project_id,
            change_id,
            packet_id,
        )
        plan_missing = state is None or not state.get("work_plan_id")
        if plan_missing and operation != "add_unit":
            raise ChangeControlBlockedError("packet_work_plan_missing")
        current_revision = 0 if plan_missing else int(state.get("plan_revision") or 0)
        if (
            expected_current_plan_revision is not None
            and int(expected_current_plan_revision) != current_revision
        ):
            raise ChangeControlBlockedError(
                "stale_current_work_plan_revision",
                details={
                    "expected_plan_revision": current_revision,
                    "received_plan_revision": int(expected_current_plan_revision),
                },
            )

        units = [] if plan_missing else [
            _unit_payload(item)
            for item in state.get("units", [])
            if isinstance(item, Mapping)
        ]
        key = str(client_unit_key or "").strip()
        if operation == "add_unit":
            if not isinstance(unit, Mapping):
                raise ValueError("add_unit requires unit")
            units.append(_unit_payload(unit))
            affected_key = str(unit.get("client_unit_key") or "")
        else:
            if not key:
                raise ValueError(f"{operation} requires client_unit_key")
            index = _unit_index(units, key)
            affected_key = key
            if operation == "remove_unit":
                dependents = [
                    str(item.get("client_unit_key") or "")
                    for item in units
                    if key in item.get("depends_on", [])
                ]
                if dependents:
                    raise ChangeControlBlockedError(
                        "packet_work_plan_unit_has_dependents",
                        details={
                            "client_unit_key": key,
                            "dependent_unit_keys": dependents,
                        },
                    )
                units.pop(index)
            elif operation == "set_dependencies":
                if depends_on is None:
                    raise ValueError("set_dependencies requires depends_on")
                units[index]["depends_on"] = _string_list(depends_on, "depends_on")
            else:
                if not isinstance(unit_patch, Mapping):
                    raise ValueError(f"{operation} requires unit_patch")
                allowed = (
                    _REBIND_FIELDS if operation == "rebind_unit" else _REVISION_FIELDS
                )
                unknown = sorted(set(unit_patch) - allowed)
                if unknown:
                    raise ValueError(
                        f"{operation} contains unsupported fields: {', '.join(unknown)}"
                    )
                units[index].update(
                    {
                        field: _normalized_patch_value(field, value)
                        for field, value in unit_patch.items()
                    }
                )

        result = self.set_plan(
            project_id,
            change_id,
            packet_id,
            {"units": units},
            expected_packet_revision=expected_packet_revision,
            expected_current_plan_revision=(
                None if plan_missing else expected_current_plan_revision
            ),
            actor=actor,
            request_id=request_id,
            request_fingerprint=fingerprint,
        )
        return {
            **dict(result),
            "mutation_operation": operation,
            "affected_unit_key": affected_key,
        }

    def get_plan(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        plan_revision: int | None = None,
        include_history: bool = False,
        detail_level: str = "standard",
    ) -> Mapping[str, object]:
        detail = _detail_level(detail_level)
        labels = self._binding_labels(project_id)
        if include_history:
            history = self._repository.packet_work_plan_history(
                project_id, change_id, packet_id
            )
            bounded = history[-20:]
            return {
                "history": [self._project_plan(item, labels, detail) for item in bounded],
                "total_revisions": len(history),
                "returned_revisions": len(bounded),
                "truncated": len(history) > len(bounded),
                "detail_level": detail,
            }
        state = self._repository.packet_work_plan_state(
            project_id,
            change_id,
            packet_id,
            plan_revision=plan_revision,
        )
        return {
            "plan": None if state is None else self._project_plan(state, labels, detail),
            "detail_level": detail,
        }

    def preview(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        plan_revision: int | None = None,
        detail_level: str = "standard",
    ) -> Mapping[str, object]:
        detail = _detail_level(detail_level)
        state = self._repository.packet_work_plan_state(
            project_id,
            change_id,
            packet_id,
            plan_revision=plan_revision,
        )
        packet = self._packet(project_id, change_id, packet_id)
        if state is None:
            return {
                "ready_for_acceptance": False,
                "status": "missing",
                "plan_revision": 0,
                "preview": "No explicit packet work plan has been authored.",
                "warnings": [],
                "blockers": ["packet_work_plan_missing"],
                "detail_level": detail,
            }
        labels = self._binding_labels(project_id)
        warnings = _semantic_warnings(state, packet)
        blockers = _preview_blockers(state, packet)
        projected = self._project_plan(state, labels, detail)
        return {
            "ready_for_acceptance": (
                state.get("status") == PacketWorkPlanStatus.PROPOSED.value and not blockers
            ),
            "status": str(state.get("status") or ""),
            "plan_revision": int(state.get("plan_revision") or 0),
            "preview": _render_preview(projected),
            "warnings": warnings,
            "blockers": blockers,
            "detail_level": detail,
            **({"plan": projected} if detail == "verbose" else {}),
        }

    def accept(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        plan_revision: int,
        expected_packet_revision: int,
        expected_current_plan_revision: int,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._transition(
            project_id,
            change_id,
            packet_id,
            plan_revision=plan_revision,
            expected_packet_revision=expected_packet_revision,
            expected_current_plan_revision=expected_current_plan_revision,
            status=PacketWorkPlanStatus.ACCEPTED.value,
            rationale=rationale,
            actor=actor,
            request_id=request_id,
        )

    def reject(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        plan_revision: int,
        expected_packet_revision: int,
        expected_current_plan_revision: int,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._transition(
            project_id,
            change_id,
            packet_id,
            plan_revision=plan_revision,
            expected_packet_revision=expected_packet_revision,
            expected_current_plan_revision=expected_current_plan_revision,
            status=PacketWorkPlanStatus.REJECTED.value,
            rationale=rationale,
            actor=actor,
            request_id=request_id,
        )

    def _transition(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        plan_revision: int,
        expected_packet_revision: int,
        expected_current_plan_revision: int,
        status: str,
        rationale: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        state = self._repository.packet_work_plan_state(
            project_id, change_id, packet_id, plan_revision=plan_revision
        )
        if state is None or not state.get("work_plan_id"):
            raise ChangeControlBlockedError("packet_work_plan_missing")
        if str(state.get("change_id")) != change_id or str(state.get("packet_id")) != packet_id:
            raise ChangeControlBlockedError("packet_work_plan_scope_mismatch")
        return self._repository.transition_packet_work_plan(
            project_id,
            str(state["work_plan_id"]),
            int(plan_revision),
            status=status,
            expected_packet_revision=int(expected_packet_revision),
            expected_current_plan_revision=int(expected_current_plan_revision),
            rationale=rationale,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def _packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object]:
        change = self._changes.change_state(project_id, change_id)
        for packet in change.get("packets", []):
            if isinstance(packet, Mapping) and packet.get("packet_id") == packet_id:
                return packet
        raise ChangeControlBlockedError("packet_not_found")

    def _binding_labels(self, project_id: str) -> Mapping[str, str]:
        labels: dict[str, str] = {}
        for audit in self._navigation.list_navigation_audits(project_id):
            for binding in audit.get("target_bindings", []):
                if not isinstance(binding, Mapping):
                    continue
                binding_id = str(binding.get("binding_id") or "")
                if binding_id:
                    labels[binding_id] = str(binding.get("target_handle") or "accepted target")
        return labels

    @staticmethod
    def _project_plan(
        state: Mapping[str, object], labels: Mapping[str, str], detail: str
    ) -> Mapping[str, object]:
        if detail == "verbose":
            return dict(state)
        units = []
        for raw in state.get("units", []):
            if not isinstance(raw, Mapping):
                continue
            mutation_binding = str(raw.get("mutation_target_binding_id") or "")
            context_bindings = [
                str(item) for item in raw.get("context_target_binding_ids", [])
            ]
            units.append(
                {
                    "client_unit_key": str(raw.get("client_unit_key") or ""),
                    "operation_kind": str(raw.get("operation_kind") or ""),
                    "target": (
                        str(raw.get("file_path") or "")
                        if raw.get("file_path")
                        else str(raw.get("target_description") or "")
                        or labels.get(mutation_binding, "accepted target")
                    ),
                    "member_label": str(raw.get("member_label") or ""),
                    "context_targets": [
                        labels.get(binding_id, "accepted context target")
                        for binding_id in context_bindings
                    ],
                    "instructions": list(raw.get("instructions", [])),
                    "unit_checks": list(raw.get("unit_checks", [])),
                    "constraints": list(raw.get("constraints", [])),
                    "out_of_scope": list(raw.get("out_of_scope", [])),
                    "depends_on": list(raw.get("depends_on", [])),
                    "replaces": list(raw.get("replaces", [])),
                    "surface": str(raw.get("surface") or ""),
                    "unit_number": int(raw.get("unit_number") or raw.get("unit_ordinal") or 0),
                    **normalize_declarations(raw),
                }
            )
        return {
            "change_id": str(state.get("change_id") or ""),
            "packet_id": str(state.get("packet_id") or ""),
            "packet_revision": int(state.get("packet_revision") or 0),
            "plan_revision": int(state.get("plan_revision") or 0),
            "status": str(state.get("status") or ""),
            "transition_rationale": str(state.get("transition_rationale") or ""),
            "units": units,
            "legacy_proposal_count": len(state.get("legacy_proposals", [])),
        }


def _unit_from_payload(payload: Mapping[str, object]) -> WorkPlanUnit:
    value = dict(payload)
    return WorkPlanUnit(
        client_unit_key=str(value.get("client_unit_key") or ""),
        operation_kind=str(value.get("operation_kind") or ""),
        mutation_target_binding_id=str(value.get("mutation_target_binding_id") or ""),
        target_description=str(value.get("target_description") or ""),
        member_label=str(value.get("member_label") or ""),
        file_path=str(value.get("file_path") or ""),
        context_target_binding_ids=_string_tuple(value.get("context_target_binding_ids")),
        instructions=_string_tuple(value.get("instructions")),
        unit_checks=_string_tuple(value.get("unit_checks")),
        constraints=_string_tuple(value.get("constraints")),
        out_of_scope=_string_tuple(value.get("out_of_scope")),
        depends_on=_string_tuple(value.get("depends_on")),
        replaces=_string_tuple(value.get("replaces")),
        surface=str(value.get("surface") or "repo"),
        **{key: tuple(items) for key, items in normalize_declarations(value).items()},
    )


_UNIT_FIELDS = {
    "implements", "provides", "requires", "verifies",
    "client_unit_key",
    "operation_kind",
    "mutation_target_binding_id",
    "target_description",
    "member_label",
    "file_path",
    "context_target_binding_ids",
    "instructions",
    "unit_checks",
    "constraints",
    "out_of_scope",
    "depends_on",
    "replaces",
    "surface",
}
_REVISION_FIELDS = _UNIT_FIELDS - {"client_unit_key"}
_REBIND_FIELDS = {
    "mutation_target_binding_id",
    "target_description",
    "member_label",
    "file_path",
    "context_target_binding_ids",
    "surface",
}
_LIST_FIELDS = {
    "context_target_binding_ids",
    "instructions",
    "unit_checks",
    "constraints",
    "out_of_scope",
    "depends_on",
    "replaces",
}


def _unit_payload(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        field: (
            list(payload.get(field, []))
            if field in _LIST_FIELDS or field in {"implements", "provides", "requires", "verifies"}
            else str(payload.get(field) or "")
        )
        for field in _UNIT_FIELDS
    }


def _unit_index(units: list[dict[str, object]], key: str) -> int:
    matches = [
        index
        for index, item in enumerate(units)
        if str(item.get("client_unit_key") or "") == key
    ]
    if not matches:
        raise ChangeControlBlockedError(
            "packet_work_plan_unit_not_found",
            details={"client_unit_key": key},
        )
    return matches[0]


def _normalized_patch_value(field: str, value: object) -> object:
    if field in {"implements", "provides", "requires", "verifies"}:
        return normalize_declarations({field: value})[field]
    if field in _LIST_FIELDS:
        return _string_list(value, field)
    return str(value or "")


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    return list(value)


def _mutation_fingerprint(
    operation: str,
    *,
    client_unit_key: str,
    unit: Mapping[str, object] | None,
    unit_patch: Mapping[str, object] | None,
    depends_on: list[str] | None,
) -> str:
    payload = {
        "operation": operation,
        "client_unit_key": str(client_unit_key or ""),
        "unit": dict(unit or {}),
        "unit_patch": dict(unit_patch or {}),
        "depends_on": list(depends_on or []),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping_list(value: Mapping[str, object], field_name: str) -> tuple[Mapping[str, object], ...]:
    raw = value.get(field_name)
    if not isinstance(raw, list):
        raise ValueError(f"work_plan.{field_name} must be a list")
    if any(not isinstance(item, Mapping) for item in raw):
        raise ValueError(f"work_plan.{field_name} must contain objects")
    return tuple(item for item in raw if isinstance(item, Mapping))


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("work-plan list fields must be lists")
    return tuple(str(item) for item in value)


def _detail_level(value: str) -> str:
    detail = str(value or "standard").strip().lower()
    if detail not in {"standard", "verbose"}:
        raise ValueError("detail_level must be standard or verbose")
    return detail


def _semantic_warnings(
    state: Mapping[str, object], packet: Mapping[str, object]
) -> list[str]:
    objective = str(packet.get("objective") or "").strip().casefold()
    warnings: list[str] = []
    for unit in state.get("units", []):
        if not isinstance(unit, Mapping):
            continue
        key = str(unit.get("client_unit_key") or "unit")
        instructions = [str(item).strip() for item in unit.get("instructions", [])]
        if instructions and all(_IDENTIFIER_ONLY_RE.fullmatch(item) for item in instructions):
            warnings.append(f"{key}: instructions appear to contain identifiers only")
        if objective and " ".join(instructions).casefold() == objective:
            warnings.append(f"{key}: instructions repeat the packet objective verbatim")
    return warnings


def _preview_blockers(
    state: Mapping[str, object], packet: Mapping[str, object]
) -> list[str]:
    blockers: list[str] = []
    status = str(state.get("status") or "")
    if status == PacketWorkPlanStatus.LEGACY_NON_EXECUTABLE.value:
        blockers.append("legacy_proposals_are_non_executable")
    if int(state.get("packet_revision") or 0) != int(packet.get("spec_revision") or packet.get("current_revision") or 0):
        blockers.append("packet_work_plan_stale")
    if status in {
        PacketWorkPlanStatus.REJECTED.value,
        PacketWorkPlanStatus.SUPERSEDED.value,
    }:
        blockers.append(f"packet_work_plan_{status}")
    return blockers


def _render_preview(plan: Mapping[str, object]) -> str:
    lines = [
        f"Packet work plan revision {plan.get('plan_revision', 0)}",
        f"Status: {plan.get('status', '')}",
    ]
    for index, unit in enumerate(plan.get("units", []), start=1):
        if not isinstance(unit, Mapping):
            continue
        lines.extend(
            [
                "",
                f"{index}. {unit.get('client_unit_key', '')} [{unit.get('operation_kind', '')}]",
                f"   Target: {unit.get('target', '')}",
            ]
        )
        for step_index, instruction in enumerate(unit.get("instructions", []), start=1):
            lines.append(f"   {step_index}) {instruction}")
        dependencies = list(unit.get("depends_on", []))
        if dependencies:
            lines.append(f"   Depends on: {', '.join(str(item) for item in dependencies)}")
    return "\n".join(lines)
