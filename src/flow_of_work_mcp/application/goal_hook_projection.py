"""Bounded factual contribution for a host-owned Goal Hook."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Mapping

from flow_of_work_mcp.core.domain.goal_hook_projection import (
    GoalHookDisposition,
    GoalHookEventReceipt,
    GoalHookTrigger,
    normalize_goal_hook_trigger,
)


GOAL_HOOK_CONTRIBUTION_VERSION = "flow.goal-hook-contribution.v1"
_GOAL_LIMIT = 6
_ROLE_LIMIT = 8
_OBLIGATION_LIMIT = 3


class GoalHookProjectionService:
    """Project existing authorities without becoming a Goal or planning store."""

    def project(
        self,
        *,
        trigger: str | GoalHookTrigger,
        snapshot: Mapping[str, object],
        goal_graph: Mapping[str, object],
        interaction_frame: Mapping[str, object],
        previous_anchor_fingerprint: str = "",
        trigger_ref: str = "",
        breath_available: bool = False,
    ) -> Mapping[str, object]:
        selected_trigger = normalize_goal_hook_trigger(trigger)
        previous = str(previous_anchor_fingerprint or "").strip()
        if previous and not _valid_fingerprint(previous, "goal-anchor:"):
            raise ValueError("previous_anchor_fingerprint is invalid")
        bounded_trigger_ref = str(trigger_ref or "").strip()
        if len(bounded_trigger_ref) > 256:
            raise ValueError("trigger_ref must contain at most 256 characters")
        if not isinstance(breath_available, bool):
            raise ValueError("breath_available must be a boolean")

        contribution = self._contribution(
            snapshot=snapshot,
            goal_graph=goal_graph,
            interaction_frame=interaction_frame,
            breath_available=breath_available,
        )
        anchor_fingerprint = _fingerprint("goal-anchor:", contribution)
        append_required = previous != anchor_fingerprint
        receipt = GoalHookEventReceipt(
            trigger=selected_trigger,
            anchor_fingerprint=anchor_fingerprint,
            receipt_fingerprint=_fingerprint(
                "goal-hook-event:",
                {
                    "trigger": selected_trigger.value,
                    "trigger_ref": bounded_trigger_ref,
                    "anchor_fingerprint": anchor_fingerprint,
                    "previous_anchor_fingerprint": previous,
                    "append_required": append_required,
                },
            ),
            append_required=append_required,
            disposition=(
                GoalHookDisposition.REANCHOR
                if append_required
                else GoalHookDisposition.UNCHANGED_ANCHOR
            ),
            trigger_ref=bounded_trigger_ref,
        )
        return {
            "contract": GOAL_HOOK_CONTRIBUTION_VERSION,
            "event_receipt": receipt.as_payload(),
            "contribution": contribution if append_required else None,
            "semantic_boundary": (
                "Factual re-anchoring only; the host owns invocation and this "
                "projection does not select work, mutate lifecycle state, widen "
                "authority or certify completion."
            ),
        }

    @staticmethod
    def _contribution(
        *,
        snapshot: Mapping[str, object],
        goal_graph: Mapping[str, object],
        interaction_frame: Mapping[str, object],
        breath_available: bool,
    ) -> Mapping[str, object]:
        goal_reach = _mapping(snapshot.get("goal_reach"))
        active_work = _mapping(snapshot.get("active_work"))
        next_gate = _mapping(snapshot.get("next_gate"))
        provider_execution = _mapping(active_work.get("provider_execution"))
        provider_availability = _mapping(
            interaction_frame.get("provider_availability")
        )
        repository_roles = [
            _role_summary(item)
            for item in list(provider_availability.get("repository_roles") or ())[
                :_ROLE_LIMIT
            ]
            if isinstance(item, Mapping)
        ]
        goal_nodes = {
            str(item.get("goal_node_id") or ""): item
            for item in list(goal_graph.get("nodes") or ())
            if isinstance(item, Mapping)
        }
        goals = [
            _goal_summary(
                item,
                goal_nodes.get(str(item.get("goal_node_id") or ""), {}),
            )
            for item in list(goal_reach.get("items") or ())[:_GOAL_LIMIT]
            if isinstance(item, Mapping)
        ]
        terminal_receipt = _mapping(provider_execution.get("terminal_receipt"))
        latest_change = _mapping(active_work.get("change"))
        return {
            "goal": {
                "focus": dict(_mapping(snapshot.get("focus"))),
                "summary": dict(_mapping(goal_reach.get("summary"))),
                "items": goals,
                "truncated": bool(goal_reach.get("truncated")),
                "omitted_count": int(goal_reach.get("omitted_count") or 0),
            },
            "project_context": {
                **dict(_mapping(interaction_frame.get("project_context"))),
                "repository_roles": repository_roles,
                "repository_roles_truncated": (
                    len(list(provider_availability.get("repository_roles") or ()))
                    > _ROLE_LIMIT
                ),
            },
            "work_anchor": {
                "focus": dict(_mapping(snapshot.get("focus"))),
                "milestone": dict(_mapping(active_work.get("milestone"))),
                "change": latest_change,
                "packet": dict(_mapping(active_work.get("packet"))),
                "campaign": dict(_mapping(active_work.get("campaign"))),
            },
            "selected_lens": _optional_mapping(
                interaction_frame.get("capability_lens")
            ),
            "latest_authoritative_event": (
                {"kind": "provider_terminal_receipt", **terminal_receipt}
                if terminal_receipt
                else {
                    "kind": "provider_observation",
                    "state": str(provider_execution.get("state") or ""),
                    "provider_status": str(
                        provider_execution.get("provider_status") or ""
                    ),
                    "evidence_ref": str(
                        provider_execution.get("evidence_ref") or ""
                    ),
                    "provider_job_ref": str(
                        provider_execution.get("provider_job_ref") or ""
                    ),
                    "continuation_policy": str(
                        provider_execution.get("continuation_policy") or ""
                    ),
                    "retry": dict(_mapping(provider_execution.get("retry"))),
                }
                if str(provider_execution.get("state") or "")
                not in {"", "not_applicable", "unavailable"}
                else {"kind": "flow_change", **latest_change}
                if latest_change and latest_change.get("state") != "not_active"
                else None
            ),
            "current_authority": {
                "owner": "flow",
                "gate_kind": str(next_gate.get("kind") or "idle"),
                "state": str(next_gate.get("state") or ""),
                "decision_class": str(next_gate.get("decision_class") or ""),
                "continuation_policy": str(
                    next_gate.get("continuation_policy") or "return_to_model"
                ),
                "scope": dict(_mapping(next_gate.get("scope"))),
            },
            "unresolved_obligations": _unresolved_obligations(
                snapshot=snapshot,
                next_gate=next_gate,
            ),
            "availability": {
                "discovery": "available",
                "breath": "available" if breath_available else "unavailable",
                "breath_owner": "host",
            },
        }


def _goal_summary(
    value: Mapping[str, object], node: Mapping[str, object]
) -> Mapping[str, object]:
    payload = _mapping(node.get("payload"))
    result = {
        "goal_node_id": str(value.get("goal_node_id") or ""),
        "node_type": str(value.get("node_type") or ""),
        "title": str(value.get("title") or ""),
        "implementation_state": str(
            _mapping(value.get("implementation_grounding")).get("state") or ""
        ),
        "deterministic_verification": str(
            _mapping(value.get("deterministic_verification")).get("state") or ""
        ),
        "live_verification": str(
            _mapping(value.get("live_verification")).get("state") or ""
        ),
    }
    if result["node_type"] == "use_case":
        result["intent"] = {
            "actor": str(payload.get("actor") or ""),
            "objective": str(payload.get("objective") or ""),
            "observable_outcome": str(payload.get("observable_outcome") or ""),
            "preconditions": _bounded_text_list(payload.get("preconditions"), 4),
            "postconditions": _bounded_text_list(payload.get("postconditions"), 4),
            "invariants": _bounded_text_list(payload.get("invariants"), 4),
        }
    elif result["node_type"] == "sequence":
        result["intent"] = {
            "participants": _bounded_text_list(payload.get("participants"), 6),
            "normal_steps": _bounded_text_list(payload.get("normal_steps"), 6),
            "alternate_steps": _bounded_text_list(payload.get("alternate_steps"), 4),
            "failure_steps": _bounded_text_list(payload.get("failure_steps"), 4),
            "expected_effects": _bounded_text_list(payload.get("expected_effects"), 6),
        }
    return result


def _role_summary(value: Mapping[str, object]) -> Mapping[str, object]:
    return {
        key: value[key]
        for key in (
            "number",
            "name",
            "role",
            "availability",
            "reason",
        )
        if key in value
    }


def _unresolved_obligations(
    *,
    snapshot: Mapping[str, object],
    next_gate: Mapping[str, object],
) -> list[Mapping[str, object]]:
    result: list[Mapping[str, object]] = []
    for item in list(snapshot.get("blockers") or ()):
        if isinstance(item, Mapping):
            result.append(
                {
                    "kind": "blocker",
                    **_selected_fields(
                        item,
                        ("code", "reason", "state", "scope", "reference"),
                    ),
                }
            )
        if len(result) >= _OBLIGATION_LIMIT:
            return result
    for item in list(snapshot.get("open_decisions") or ()):
        if isinstance(item, Mapping):
            result.append(
                {
                    "kind": "open_decision",
                    **_selected_fields(
                        item,
                        ("decision_class", "required_inputs", "reason"),
                    ),
                }
            )
        if len(result) >= _OBLIGATION_LIMIT:
            return result
    if not result and str(next_gate.get("kind") or "idle") != "idle":
        result.append(
            {
                "kind": "current_gate",
                "gate_kind": str(next_gate.get("kind") or ""),
                "state": str(next_gate.get("state") or ""),
                "reason": str(next_gate.get("reason") or ""),
            }
        )
    return result


def _selected_fields(
    value: Mapping[str, object], fields: tuple[str, ...]
) -> dict[str, object]:
    return {field: value[field] for field in fields if field in value}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _bounded_text_list(value: object, limit: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value[:limit]]


def _fingerprint(prefix: str, value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return prefix + sha256(encoded).hexdigest()


def _valid_fingerprint(value: str, prefix: str) -> bool:
    if not value.startswith(prefix):
        return False
    digest = value.removeprefix(prefix)
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


__all__ = ["GOAL_HOOK_CONTRIBUTION_VERSION", "GoalHookProjectionService"]
