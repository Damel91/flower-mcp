"""Natural, restart-safe authoring of one packet unit at a time."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import normalize_declarations
from flow_of_work_mcp.application.navigation_audit import NavigationAuditService
from flow_of_work_mcp.application.packet_work_plan import PacketWorkPlanService
from flow_of_work_mcp.core.domain.packet_operations import PacketTaskOperationKind
from flow_of_work_mcp.core.domain.paths import repo_relative_file_path
from flow_of_work_mcp.core.domain.provider_targets import candidate_can_be_deleted
from flow_of_work_mcp.core.domain.provider_surfaces import (
    codingcastle_provider_surface,
)
from flow_of_work_mcp.core.errors import (
    ChangeControlBlockedError,
    RequirementConflictError,
)
from flow_of_work_mcp.core.ports.change_control import ChangeControlRepository
from flow_of_work_mcp.core.ports.packet_work_plan import PacketWorkPlanRepository


_LIST_FIELDS = (
    "instructions",
    "unit_checks",
    "constraints",
    "out_of_scope",
    "depends_on",
    "replaces",
)
_PUBLIC_UNIT_FIELDS = {
    "implements", "provides", "requires", "verifies",
    "client_unit_key",
    "operation_kind",
    "target_description",
    "member_label",
    "file_path",
    *_LIST_FIELDS,
    "surface",
}


class PacketUnitAuthoringService:
    """Compile readable per-unit choices into the canonical work-plan writer."""

    def __init__(
        self,
        *,
        ledger,
        repository: PacketWorkPlanRepository,
        changes: ChangeControlRepository,
        navigation: NavigationAuditService,
        work_plans: PacketWorkPlanService,
        provider_managed_targets: bool = False,
    ) -> None:
        self._ledger = ledger
        self._repository = repository
        self._changes = changes
        self._navigation = navigation
        self._work_plans = work_plans
        self._provider_managed_targets = bool(provider_managed_targets)

    def add_unit(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        unit: Mapping[str, object] | None,
        client_unit_key: str = "",
        target_selection: Mapping[str, object] | None = None,
        expected_spec_revision: int | None = None,
        expected_plan_revision: int | None = None,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        request_id = str(request_id or "").strip()
        if not request_id:
            raise ValueError("request_id is required")
        packet = self._packet(project_id, change_id, packet_id)
        current_plan = self._repository.packet_work_plan_state(
            project_id, change_id, packet_id
        )
        current_spec_revision = int(
            packet.get("spec_revision") or packet.get("current_revision") or 0
        )
        current_plan_revision = (
            int(current_plan.get("plan_revision") or 0) if current_plan else 0
        )
        if (
            expected_spec_revision is not None
            and int(expected_spec_revision) not in {0, current_spec_revision}
        ):
            raise ChangeControlBlockedError(
                "stale_packet_revision",
                details={
                    "expected_spec_revision": current_spec_revision,
                    "received_spec_revision": int(expected_spec_revision),
                },
            )
        if (
            expected_plan_revision is not None
            and int(expected_plan_revision) != current_plan_revision
        ):
            raise ChangeControlBlockedError(
                "stale_current_work_plan_revision",
                details={
                    "expected_plan_revision": current_plan_revision,
                    "received_plan_revision": int(expected_plan_revision),
                },
            )

        key = str(client_unit_key or "").strip()
        if unit is not None:
            normalized_unit = _normalize_unit_intent(unit)
            if key and key != normalized_unit["client_unit_key"]:
                raise ValueError(
                    "client_unit_key does not match the unit being resumed"
                )
            key = str(normalized_unit["client_unit_key"])
        elif not key:
            raise ValueError("add_unit requires unit or a pending client_unit_key")

        intent = self._repository.packet_unit_authoring_intent(
            project_id, change_id, packet_id, key
        )
        if unit is None:
            if intent is None:
                raise ValueError("add_unit requires unit or a pending client_unit_key")
            normalized_unit = _normalize_unit_intent(
                _public_authoring_unit(intent["unit"])
            )
        fingerprint = _fingerprint(normalized_unit)
        if intent is not None:
            if str(intent.get("intent_fingerprint") or "") != fingerprint:
                raise RequirementConflictError(
                    "client_unit_key already belongs to another authoring intent"
                )
        else:
            intent = self._repository.save_packet_unit_authoring_intent(
                project_id,
                change_id,
                packet_id,
                key,
                intent_fingerprint=fingerprint,
                unit=normalized_unit,
                candidate_window=[],
                spec_revision=current_spec_revision,
                plan_revision=current_plan_revision,
                actor=actor,
                request_id=f"{request_id}:intent",
            )

        if str(intent.get("state") or "") == "committed":
            committed_revision = int(intent.get("committed_plan_revision") or 0)
            committed_plan = (
                self._repository.packet_work_plan_state(
                    project_id,
                    change_id,
                    packet_id,
                    plan_revision=committed_revision,
                )
                if committed_revision
                else current_plan
            )
            return self._committed_projection(
                intent,
                committed_plan or current_plan,
                replayed=True,
            )

        if int(intent["spec_revision"]) != current_spec_revision or int(
            intent["plan_revision"]
        ) != current_plan_revision:
            intent = self._repository.rebase_packet_unit_authoring_intent(
                project_id,
                change_id,
                packet_id,
                key,
                intent_fingerprint=fingerprint,
                unit=normalized_unit,
                spec_revision=current_spec_revision,
                plan_revision=current_plan_revision,
                actor=actor,
            )

        if str(intent.get("state") or "") == "targets_committed":
            return self._commit_plan(
                project_id,
                change_id,
                packet_id,
                intent,
                actor=actor,
                request_id=request_id,
            )

        operation_kind = PacketTaskOperationKind(
            str(normalized_unit["operation_kind"])
        )
        described_target = str(
            normalized_unit.get("target_description") or ""
        ).strip()
        provider_neutral_target = (
            operation_kind == PacketTaskOperationKind.NEW_FILE
            or bool(described_target)
        )
        if (
            self._provider_managed_targets
            and operation_kind != PacketTaskOperationKind.NEW_FILE
            and not described_target
        ):
            raise ValueError(
                "provider-backed existing-target unit requires target_description"
            )
        if provider_neutral_target:
            if target_selection:
                raise ValueError(
                    "target_selection is provider-owned for a described semantic target"
                )
            resolved_unit = {
                **dict(normalized_unit),
                "mutation_target_binding_id": "",
                "context_target_binding_ids": [],
            }
            intent = self._repository.mark_packet_unit_targets_committed(
                project_id,
                change_id,
                packet_id,
                key,
                unit=resolved_unit,
                candidate_window=[],
                actor=actor,
                request_id=request_id,
            )
            return self._commit_plan(
                project_id,
                change_id,
                packet_id,
                intent,
                actor=actor,
                request_id=request_id,
            )

        selection = dict(target_selection or {})
        candidate_window = [
            dict(item)
            for item in intent.get("candidate_window", [])
            if isinstance(item, Mapping)
        ]
        if not selection:
            selection = _persisted_target_selection(candidate_window)
        needs_mutation = operation_kind != PacketTaskOperationKind.NEW_FILE
        discover_context = bool(selection.get("discover_context"))
        needs_candidates = needs_mutation or discover_context or bool(
            selection.get("context_candidates")
        )
        has_choice = (
            "mutation_candidate" in selection
            or "context_candidates" in selection
        )
        refresh_pending = bool(candidate_window) and not has_choice
        if needs_candidates and (not candidate_window or refresh_pending):
            candidate_window = self._prepare_candidate_window(
                project_id, change_id, packet_id
            )
            intent = self._repository.save_packet_unit_authoring_intent(
                project_id,
                change_id,
                packet_id,
                key,
                intent_fingerprint=str(intent["intent_fingerprint"]),
                unit=normalized_unit,
                candidate_window=candidate_window,
                spec_revision=current_spec_revision,
                plan_revision=current_plan_revision,
                actor=actor,
            )
            if not candidate_window:
                return {
                    "state": "navigation_audit_has_no_candidates",
                    "unit": _unit_summary(normalized_unit),
                    "candidates": [],
                    "next_decision": {
                        "operation": "navigate_implementation_surface",
                        "reason": "navigation_audit_has_no_candidates",
                    },
                }

        if needs_candidates and not has_choice:
            return self._selection_projection(normalized_unit, candidate_window)

        if needs_candidates:
            candidate_window = _annotate_target_selection(
                candidate_window,
                operation_kind=operation_kind,
                selection=selection,
            )
            intent = self._repository.save_packet_unit_authoring_intent(
                project_id,
                change_id,
                packet_id,
                key,
                intent_fingerprint=str(intent["intent_fingerprint"]),
                unit=normalized_unit,
                candidate_window=candidate_window,
                spec_revision=current_spec_revision,
                plan_revision=current_plan_revision,
                actor=actor,
            )

        resolved_unit, resolved_window = self._resolve_targets(
            normalized_unit,
            candidate_window,
            selection,
        )
        intent = self._repository.mark_packet_unit_targets_committed(
            project_id,
            change_id,
            packet_id,
            key,
            unit=resolved_unit,
            candidate_window=resolved_window,
            actor=actor,
            request_id=request_id,
        )
        return self._commit_plan(
            project_id,
            change_id,
            packet_id,
            intent,
            actor=actor,
            request_id=request_id,
        )

    def _prepare_candidate_window(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> list[Mapping[str, object]]:
        window: list[Mapping[str, object]] = []
        for item in self._navigation.packet_local_candidates(
            project_id, change_id, packet_id
        ):
            window.append(
                {
                    "ordinal": len(window) + 1,
                    "origin": "packet",
                    **dict(item),
                }
            )
        return window

    def _resolve_targets(
        self,
        unit: Mapping[str, object],
        window: list[Mapping[str, object]],
        selection: Mapping[str, object],
    ) -> tuple[Mapping[str, object], list[Mapping[str, object]]]:
        operation_kind = PacketTaskOperationKind(str(unit["operation_kind"]))
        mutation_ordinal = selection.get("mutation_candidate")
        if operation_kind == PacketTaskOperationKind.NEW_FILE:
            if mutation_ordinal not in {None, "", 0}:
                raise ValueError("new_file cannot select a mutation candidate")
            mutation_ordinal = None
        elif mutation_ordinal is None:
            raise ValueError("existing-code unit requires mutation_candidate")
        context_ordinals = _positive_ordinals(
            selection.get("context_candidates", []), "context_candidates"
        )
        selected_ordinals = (
            (() if mutation_ordinal is None else (int(mutation_ordinal),))
            + context_ordinals
        )
        if len(set(selected_ordinals)) != len(selected_ordinals):
            raise ValueError("mutation and context candidates must be distinct")
        by_ordinal = {int(item["ordinal"]): dict(item) for item in window}
        unknown = sorted(set(selected_ordinals) - set(by_ordinal))
        if unknown:
            raise ValueError(f"unknown candidate ordinals: {unknown}")
        if (
            operation_kind == PacketTaskOperationKind.DELETE_EXISTING
            and mutation_ordinal is not None
            and not candidate_can_be_deleted(by_ordinal[int(mutation_ordinal)])
        ):
            raise ValueError(
                "delete_existing requires a readable parser symbol candidate"
            )
        resolved_window = [dict(item) for item in window]

        def binding_for(ordinal: int) -> str:
            value = next(
                item for item in resolved_window if int(item["ordinal"]) == ordinal
            )
            binding_id = str(value.get("binding_id") or "")
            if not binding_id:
                raise ChangeControlBlockedError(
                    "unit_target_binding_materialization_missing"
                )
            return binding_id

        resolved = dict(unit)
        resolved["mutation_target_binding_id"] = (
            "" if mutation_ordinal is None else binding_for(int(mutation_ordinal))
        )
        resolved["context_target_binding_ids"] = [
            binding_for(ordinal) for ordinal in context_ordinals
        ]
        return resolved, resolved_window

    def _commit_plan(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        intent: Mapping[str, object],
        *,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        current = self._repository.packet_work_plan_state(
            project_id, change_id, packet_id
        )
        key = str(intent["client_unit_key"])
        if current is not None:
            existing = next(
                (
                    item
                    for item in current.get("units", [])
                    if isinstance(item, Mapping)
                    and str(item.get("client_unit_key") or "") == key
                ),
                None,
            )
            if existing is not None:
                if _execution_unit(existing) != _execution_unit(intent["unit"]):
                    raise ChangeControlBlockedError(
                        "unit_authoring_plan_conflict",
                        details={"client_unit_key": key},
                    )
                committed = self._repository.commit_packet_unit_authoring_intent(
                    project_id,
                    change_id,
                    packet_id,
                    key,
                    committed_plan_revision=int(current["plan_revision"]),
                    actor=actor,
                    request_id=request_id,
                )
                return self._committed_projection(
                    committed, current, replayed=True
                )
        with self._ledger.atomic():
            result = self._work_plans.mutate_plan(
                project_id,
                change_id,
                packet_id,
                operation="add_unit",
                expected_packet_revision=int(intent["spec_revision"]),
                expected_current_plan_revision=int(intent["plan_revision"]),
                actor=actor,
                request_id=f"{request_id}:plan",
                unit=dict(intent["unit"]),
            )
            result = self._repository.finalize_packet_authoring_revision(
                project_id,
                str(result["work_plan_id"]),
                int(result["plan_revision"]),
            )
            committed = self._repository.commit_packet_unit_authoring_intent(
                project_id,
                change_id,
                packet_id,
                key,
                committed_plan_revision=int(result["plan_revision"]),
                actor=actor,
                request_id=request_id,
            )
            self._changes.evaluate_packet_readiness(
                project_id,
                change_id,
                packet_id,
                actor=actor,
                request_id=f"{request_id}:readiness",
            )
        return self._committed_projection(committed, result, replayed=False)

    @staticmethod
    def _selection_projection(
        unit: Mapping[str, object], window: list[Mapping[str, object]]
    ) -> Mapping[str, object]:
        operation_kind = str(unit.get("operation_kind") or "")
        candidates = [_public_candidate(item) for item in window]
        return {
            "state": "needs_target_selection",
            "unit": _unit_summary(unit),
            "candidates": candidates,
            "decision_required": {
                "target_selection": {
                    "mutation_candidate": None,
                    "context_candidates": [],
                },
                "required_fields": (
                    []
                    if operation_kind == "new_file"
                    else ["mutation_candidate"]
                ),
            },
            "next_decision": {
                "operation": "add_unit",
                "client_unit_key": str(unit["client_unit_key"]),
            },
        }

    @staticmethod
    def _committed_projection(
        intent: Mapping[str, object],
        plan: Mapping[str, object] | None,
        *,
        replayed: bool,
    ) -> Mapping[str, object]:
        units = [
            item
            for item in (plan or {}).get("units", [])
            if isinstance(item, Mapping)
        ]
        unit = dict(intent["unit"])
        labels = {
            str(item.get("binding_id") or ""): str(item.get("label") or "")
            for item in intent.get("candidate_window", [])
            if isinstance(item, Mapping)
        }
        selected = [
            labels.get(str(unit.get("mutation_target_binding_id") or ""), "")
        ] + [
            labels.get(str(value), "")
            for value in unit.get("context_target_binding_ids", [])
        ]
        return {
            "state": "unit_added",
            "unit": _unit_summary(unit),
            "target_labels": [item for item in selected if item],
            "plan_revision": int(
                intent.get("committed_plan_revision")
                or (plan or {}).get("plan_revision")
                or 0
            ),
            "unit_count": len(units),
            "replayed": replayed,
            "semantic_delta": {
                "operation": "add_unit",
                "affected_unit_key": str(unit["client_unit_key"]),
            },
            "next_decision": {
                "question": "Add another unit or finish authoring?",
                "allowed_responses": ["add_unit", "finish_authoring"],
            },
        }

    def _packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object]:
        change = self._changes.change_state(project_id, change_id)
        for packet in change.get("packets", []):
            if (
                isinstance(packet, Mapping)
                and str(packet.get("packet_id") or "") == packet_id
            ):
                return packet
        raise ChangeControlBlockedError("packet_not_found")

def _public_authoring_unit(unit: object) -> Mapping[str, object]:
    if not isinstance(unit, Mapping):
        raise RequirementConflictError("stored unit authoring intent is invalid")
    return {
        key: value
        for key, value in unit.items()
        if key in _PUBLIC_UNIT_FIELDS
    }


def _normalize_unit_intent(unit: Mapping[str, object]) -> Mapping[str, object]:
    value = dict(unit)
    forbidden = {
        "mutation_target_binding_id",
        "context_target_binding_ids",
    }.intersection(value)
    if forbidden:
        raise ValueError(
            "unit target identities are server-owned: "
            + ", ".join(sorted(forbidden))
        )
    unknown = sorted(set(value) - _PUBLIC_UNIT_FIELDS)
    if unknown:
        raise ValueError(
            "unit contains unsupported fields: " + ", ".join(unknown)
        )
    key = str(value.get("client_unit_key") or "").strip()
    if not key:
        raise ValueError("unit requires client_unit_key")
    operation = PacketTaskOperationKind(str(value.get("operation_kind") or ""))
    if operation == PacketTaskOperationKind.REVIEW_ONLY:
        raise ValueError("review_only is not executable in a packet work plan")
    file_path = repo_relative_file_path(str(value.get("file_path") or ""))
    target_description = str(value.get("target_description") or "").strip()
    member_label = str(value.get("member_label") or "").strip()
    if len(target_description) > 4096:
        raise ValueError("target_description exceeds 4096 characters")
    if len(member_label) > 4096:
        raise ValueError("member_label exceeds 4096 characters")
    if operation == PacketTaskOperationKind.NEW_FILE and not file_path:
        raise ValueError("new_file unit requires file_path")
    if operation == PacketTaskOperationKind.NEW_FILE and target_description:
        raise ValueError("new_file unit cannot declare target_description")
    if operation == PacketTaskOperationKind.EXTRACT_MOVE and not file_path:
        raise ValueError("extract_move unit requires destination file_path")
    if operation not in {
        PacketTaskOperationKind.NEW_FILE,
        PacketTaskOperationKind.EXTRACT_MOVE,
    } and file_path:
        raise ValueError(
            "file_path is only valid for new_file or extract_move units"
        )
    surface = codingcastle_provider_surface(value.get("surface") or "repo")
    normalized = {
        "client_unit_key": key,
        "operation_kind": operation.value,
        "target_description": target_description,
        "member_label": member_label,
        "file_path": file_path,
        "surface": surface,
    }
    for field in _LIST_FIELDS:
        items = _string_list(value.get(field), field)
        if field in {"instructions", "unit_checks"} and not items:
            raise ValueError(f"unit requires {field}")
        normalized[field] = items
    normalized.update(normalize_declarations(value))
    return normalized


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be a list")
    result = [str(item or "").strip() for item in value]
    if any(not item for item in result):
        raise ValueError(f"{field} cannot contain empty values")
    return result


def _positive_ordinals(value: object, field: str) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be a list")
    result = tuple(int(item) for item in value)
    if any(item <= 0 for item in result) or len(set(result)) != len(result):
        raise ValueError(f"{field} must contain unique positive ordinals")
    return result


def _persisted_target_selection(
    candidate_window: list[Mapping[str, object]],
) -> dict[str, object]:
    mutation: list[int] = []
    context: list[tuple[int, int]] = []
    for item in candidate_window:
        role = str(item.get("_pending_selection_role") or "")
        if not role:
            continue
        ordinal = int(item.get("ordinal") or 0)
        if ordinal <= 0:
            raise RequirementConflictError(
                "persisted unit target selection is invalid"
            )
        if role == "mutation":
            mutation.append(ordinal)
        elif role == "context":
            context.append(
                (int(item.get("_pending_selection_order") or 0), ordinal)
            )
        else:
            raise RequirementConflictError(
                "persisted unit target selection is invalid"
            )
    if not mutation and not context:
        return {}
    if len(mutation) > 1 or any(order <= 0 for order, _ in context):
        raise RequirementConflictError(
            "persisted unit target selection is invalid"
        )
    orders = [order for order, _ in context]
    if len(set(orders)) != len(orders):
        raise RequirementConflictError(
            "persisted unit target selection is invalid"
        )
    selection: dict[str, object] = {
        "context_candidates": [
            ordinal for _, ordinal in sorted(context)
        ]
    }
    if mutation:
        selection["mutation_candidate"] = mutation[0]
    return selection


def _annotate_target_selection(
    candidate_window: list[Mapping[str, object]],
    *,
    operation_kind: PacketTaskOperationKind,
    selection: Mapping[str, object],
) -> list[Mapping[str, object]]:
    mutation = selection.get("mutation_candidate")
    if operation_kind == PacketTaskOperationKind.NEW_FILE:
        if mutation not in {None, "", 0}:
            raise ValueError("new_file cannot select a mutation candidate")
        mutation_ordinal: int | None = None
    else:
        if mutation is None:
            raise ValueError("existing-code unit requires mutation_candidate")
        mutation_ordinal = int(mutation)
    context_ordinals = _positive_ordinals(
        selection.get("context_candidates", []), "context_candidates"
    )
    selected = (
        (() if mutation_ordinal is None else (mutation_ordinal,))
        + context_ordinals
    )
    if len(set(selected)) != len(selected):
        raise ValueError("mutation and context candidates must be distinct")
    known = {int(item.get("ordinal") or 0) for item in candidate_window}
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ValueError(f"unknown candidate ordinals: {unknown}")

    context_order = {
        ordinal: index for index, ordinal in enumerate(context_ordinals, start=1)
    }
    result: list[Mapping[str, object]] = []
    for item in candidate_window:
        value = _without_pending_selection(item)
        ordinal = int(value.get("ordinal") or 0)
        if ordinal == mutation_ordinal:
            value["_pending_selection_role"] = "mutation"
            value["_pending_selection_order"] = 0
        elif ordinal in context_order:
            value["_pending_selection_role"] = "context"
            value["_pending_selection_order"] = context_order[ordinal]
        result.append(value)
    return result


def _without_pending_selection(
    candidate: Mapping[str, object],
) -> dict[str, object]:
    result = dict(candidate)
    result.pop("_pending_selection_role", None)
    result.pop("_pending_selection_order", None)
    return result


def _fingerprint(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _public_candidate(value: Mapping[str, object]) -> Mapping[str, object]:
    return {
        field: value[field]
        for field in (
            "ordinal",
            "origin",
            "label",
            "kind",
            "display_path",
            "path_visibility",
            "symbol_name",
            "qualified_name",
            "owning_type",
            "navigation_anchor",
            "line_start",
            "line_end",
        )
        if field in value
    }


def _unit_summary(value: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "client_unit_key": str(value.get("client_unit_key") or ""),
        "operation_kind": str(value.get("operation_kind") or ""),
        "file_path": str(value.get("file_path") or ""),
        "target_description": str(value.get("target_description") or ""),
        "member_label": str(value.get("member_label") or ""),
        "instruction_count": len(value.get("instructions", [])),
        "check_count": len(value.get("unit_checks", [])),
    }


def _execution_unit(value: Mapping[str, object]) -> Mapping[str, object]:
    return {
        field: value.get(field, [] if field in _LIST_FIELDS else "")
        for field in (
            "client_unit_key",
            "operation_kind",
            "mutation_target_binding_id",
            "target_description",
            "member_label",
            "file_path",
            "context_target_binding_ids",
            *_LIST_FIELDS,
            "surface",
        )
    }
