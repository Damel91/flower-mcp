"""Deterministic Flower discovery, capability lens and interaction frames."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from flow_of_work_mcp.application.operation_contracts import (
    ContinuationPolicy,
    operation_contract,
    operation_names,
    work_area_catalog,
)
from flow_of_work_mcp.application.goal_hook_projection import (
    GoalHookProjectionService,
)
from flow_of_work_mcp.core.domain.interaction_projection import (
    CapabilityLensBinding,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError,
    ImplementationProviderUnavailableError,
)
from flow_of_work_mcp.core.ports.interaction_provider import InteractionProvider


FRAME_VERSION = "flow.interaction-frame.v1"
DISCOVERY_VERSION = "flow.work-area-discovery.v1"

_GATE_AREAS: Mapping[str, frozenset[str]] = {
    "intent_work": frozenset({"requirements", "goal_graph", "changes"}),
    "packet_construction": frozenset({"packet_lifecycle"}),
    "provider_execution": frozenset({"packet_lifecycle", "changes"}),
    "external_agent_work": frozenset({"packet_lifecycle", "changes", "campaigns"}),
    "workspace_review": frozenset({"packet_lifecycle", "assurance"}),
    "remediation_construction": frozenset({"packet_lifecycle", "assurance"}),
    "deterministic_verification": frozenset({"campaigns", "assurance"}),
    "live_campaign_readiness": frozenset({"campaigns", "assurance"}),
    "campaign_execution": frozenset({"campaigns"}),
    "acceptance": frozenset({"milestones", "assurance"}),
    "lifecycle_audit": frozenset({"assurance"}),
}


class InteractionProjectionError(ValueError):
    pass


class InteractionProjectionService:
    def __init__(
        self,
        *,
        repository: Any,
        project_context: Any,
        project_state_snapshot: Any,
        interaction_provider: InteractionProvider | None = None,
    ) -> None:
        self._repository = repository
        self._project_context = project_context
        self._project_state_snapshot = project_state_snapshot
        self._interaction_provider = interaction_provider
        self._goal_hook_projection = GoalHookProjectionService()

    def execute(
        self,
        operation: str,
        *,
        interaction_session_ref: str,
        project_id: str = "",
        project_selection: int = 0,
        area: int = 0,
        selection: int = 0,
        frame_ref: str = "",
        query: str = "",
        limit: int = 9,
        page_action: str = "refine",
        actor: str = "orchestrator",
        request_id: str = "",
        trigger: str = "",
        previous_anchor_fingerprint: str = "",
        trigger_ref: str = "",
        breath_available: bool = False,
    ) -> Mapping[str, object]:
        op = str(operation or "status").strip().lower()
        interaction = self._required_interaction(interaction_session_ref)
        if op in {"status", "discover"}:
            return self.discover(
                interaction, query=query, limit=limit, page_action=page_action
            )
        if op in {"open", "select_project", "switch_project", "clear_project"}:
            self._project_context.execute(
                op,
                interaction_session_ref=interaction,
                project_id=project_id,
                selection=project_selection,
                actor=actor,
                request_id=request_id,
            )
            return self.discover(interaction, limit=limit)
        if op in {"select", "switch"}:
            context = self._require_context(interaction)
            areas, _provider_state = self._area_inventory(interaction, context)
            selected = self._area_by_number(areas, area)
            self._repository.set_interaction_capability_lens(
                interaction,
                project_id=context.project_id,
                project_context_revision=context.revision,
                producing_provider=str(selected["provider"]),
                selected_area=str(selected["area"]),
                transition=op,
                actor=actor,
                request_id=request_id,
            )
            return self.frame(interaction)
        if op == "clear":
            self._repository.clear_interaction_capability_lens(
                interaction, actor=actor, request_id=request_id
            )
            return self.discover(interaction, limit=limit)
        if op == "frame":
            return self.frame(interaction)
        if op == "goal_hook":
            context = self._require_context(interaction)
            with self._repository.consistent_read():
                snapshot = self._project_state_snapshot.snapshot(
                    context.project_id, limit=6
                )
                goal_graph = self._repository.goal_graph(context.project_id)
            frame = self.frame(interaction)
            current_context = self._require_context(interaction)
            if (
                current_context.project_id != context.project_id
                or current_context.revision != context.revision
            ):
                raise InteractionProjectionError("project_context_changed")
            return self._goal_hook_projection.project(
                trigger=trigger,
                snapshot=snapshot,
                goal_graph=goal_graph,
                interaction_frame=frame,
                previous_anchor_fingerprint=previous_anchor_fingerprint,
                trigger_ref=trigger_ref,
                breath_available=breath_available,
            )
        if op == "resolve":
            return self.resolve(interaction, frame_ref, selection)
        raise InteractionProjectionError("interaction_operation_invalid")

    def discover(
        self,
        interaction_session_ref: str,
        *,
        query: str = "",
        limit: int = 9,
        page_action: str = "refine",
        _persist_continuation: bool = True,
    ) -> Mapping[str, object]:
        interaction = self._required_interaction(interaction_session_ref)
        context = self._project_context.current(interaction)
        if context is None:
            action = str(page_action or "refine").strip().lower()
            if action not in {"more", "refine", "stop"}:
                raise InteractionProjectionError("interaction_page_action_invalid")
            bounded_limit = self._bounded_limit(limit)
            projects = dict(self._project_context.discover(interaction))
            values = list(projects.get("choices") or ())
            fingerprint = self._fingerprint({"projects": values})
            needle = str(query or "").strip().lower()
            offset = 0
            if action == "more":
                continuation = self._repository.get_interaction_continuation(
                    interaction
                )
                if (
                    continuation is None
                    or str(continuation.get("owner") or "") != "project-discovery"
                    or str(continuation.get("source_fingerprint") or "") != fingerprint
                ):
                    if _persist_continuation:
                        self._repository.clear_interaction_continuation(interaction)
                    raise InteractionProjectionError("interaction_continuation_stale")
                needle = str(continuation.get("query") or "")
                offset = int(continuation.get("offset") or 0)
            elif action == "stop" and _persist_continuation:
                self._repository.clear_interaction_continuation(interaction)
            filtered = [
                item
                for item in values
                if not needle
                or needle in f"{item.get('project_id')} {item.get('name')}".lower()
            ]
            visible = (
                [] if action == "stop" else filtered[offset : offset + bounded_limit]
            )
            next_offset = offset + len(visible)
            if (
                _persist_continuation
                and action != "stop"
                and next_offset < len(filtered)
            ):
                self._repository.set_interaction_continuation(
                    interaction,
                    project_id="",
                    project_context_revision=0,
                    owner="project-discovery",
                    query=needle,
                    offset=next_offset,
                    source_fingerprint=fingerprint,
                )
            elif _persist_continuation:
                self._repository.clear_interaction_continuation(interaction)
            return {
                "contract": DISCOVERY_VERSION,
                "mode": "project_selection",
                "project_context": projects.get("selected"),
                "capability_lens": None,
                "projects": visible,
                "areas": [],
                "decision_required": ("select_project" if values else "create_project"),
                "page": self._page(len(filtered), len(visible), offset),
                "details_available": ["fow_capabilities"],
            }

        action = str(page_action or "refine").strip().lower()
        if action not in {"more", "refine", "stop"}:
            raise InteractionProjectionError("interaction_page_action_invalid")
        bounded_limit = self._bounded_limit(limit)
        areas, provider_state = self._area_inventory(interaction, context)
        fingerprint = self._fingerprint(
            {
                "project_id": context.project_id,
                "project_context_revision": context.revision,
                "areas": areas,
            }
        )
        offset = 0
        needle = str(query or "").strip().lower()
        if action == "more":
            continuation = self._repository.get_interaction_continuation(interaction)
            if (
                continuation is None
                or str(continuation.get("owner") or "") != "work-area-discovery"
                or str(continuation.get("project_id") or "") != context.project_id
                or int(continuation.get("project_context_revision") or 0)
                != context.revision
                or str(continuation.get("source_fingerprint") or "") != fingerprint
            ):
                if _persist_continuation:
                    self._repository.clear_interaction_continuation(interaction)
                raise InteractionProjectionError("interaction_continuation_stale")
            needle = str(continuation.get("query") or "")
            offset = int(continuation.get("offset") or 0)
        elif action == "stop" and _persist_continuation:
            self._repository.clear_interaction_continuation(interaction)

        filtered = [
            item
            for item in areas
            if not needle
            or needle
            in " ".join(
                (
                    str(item.get("area") or ""),
                    str(item.get("label") or ""),
                    str(item.get("purpose") or ""),
                )
            ).lower()
        ]
        visible = [] if action == "stop" else filtered[offset : offset + bounded_limit]
        next_offset = offset + len(visible)
        if _persist_continuation and action != "stop" and next_offset < len(filtered):
            self._repository.set_interaction_continuation(
                interaction,
                project_id=context.project_id,
                project_context_revision=context.revision,
                owner="work-area-discovery",
                query=needle,
                offset=next_offset,
                source_fingerprint=fingerprint,
            )
        elif _persist_continuation:
            self._repository.clear_interaction_continuation(interaction)
        lens = self._current_lens(interaction, context)
        return {
            "contract": DISCOVERY_VERSION,
            "mode": provider_state["mode"],
            "project_context": self._context_payload(context),
            "capability_lens": self._lens_payload(lens),
            "areas": visible,
            "page": self._page(len(filtered), len(visible), offset),
            "provider": provider_state,
            "details_available": ["frame", "fow_capabilities"],
        }

    def frame(self, interaction_session_ref: str) -> Mapping[str, object]:
        interaction = self._required_interaction(interaction_session_ref)
        context = self._project_context.current(interaction)
        if context is None:
            return self._orientation_frame(interaction, "select_project")
        lens = self._current_lens(interaction, context)
        if lens is None:
            return self._orientation_frame(interaction, "select_work_area")

        areas, provider_state = self._area_inventory(interaction, context)
        selected = next(
            (
                item
                for item in areas
                if item["provider"] == lens.producing_provider
                and item["area"] == lens.selected_area
            ),
            None,
        )
        if selected is None:
            self._repository.clear_interaction_capability_lens(
                interaction, actor="system", request_id="area-invalidated"
            )
            return self._orientation_frame(interaction, "select_work_area")

        if lens.producing_provider != "flow":
            core = self._technical_frame(context, lens, selected, provider_state)
        else:
            core = self._flow_frame(context, lens, selected, provider_state)
        core["frame_ref"] = self._fingerprint(core)
        return core

    def resolve(
        self,
        interaction_session_ref: str,
        frame_ref: str,
        selection: int,
    ) -> Mapping[str, object]:
        current = dict(self.frame(interaction_session_ref))
        if not frame_ref or str(current.get("frame_ref") or "") != frame_ref:
            return {
                "status": "stale",
                "reason": "interaction_frame_stale",
                "frame": current,
            }
        choices = list(current.get("choices") or ())
        if (
            isinstance(selection, bool)
            or not isinstance(selection, int)
            or not 1 <= selection <= len(choices)
        ):
            raise InteractionProjectionError("interaction_choice_invalid")
        choice = dict(choices[selection - 1])
        return {
            "status": "resolved",
            "frame_ref": frame_ref,
            "selection": selection,
            "next_tool_call": {
                "tool": choice["tool"],
                "arguments": dict(choice.get("arguments") or {}),
            },
            "semantic_inputs": list(choice.get("semantic_inputs") or ()),
            "injected_inputs": list(choice.get("injected_inputs") or ()),
            "continuation_policy": choice["continuation_policy"],
        }

    def _flow_frame(
        self,
        context: Any,
        lens: CapabilityLensBinding,
        selected: Mapping[str, object],
        provider_state: Mapping[str, object],
    ) -> dict[str, object]:
        snapshot = dict(
            self._project_state_snapshot.snapshot(context.project_id, limit=6)
        )
        next_gate = dict(snapshot.get("next_gate") or {})
        actions: list[Mapping[str, object]] = []
        if str(next_gate.get("kind") or "") != "idle" and lens.selected_area in (
            _GATE_AREAS.get(str(next_gate.get("kind") or ""), frozenset())
        ):
            route = next_gate.get("route")
            if isinstance(route, Mapping):
                actions.append(self._action_from_route(route, next_gate))
        if not actions:
            actions.append(self._default_area_action(lens.selected_area, snapshot))
        state = {
            "project_revision": snapshot.get("project_revision"),
            "focus": snapshot.get("focus"),
            "active_work": snapshot.get("active_work"),
            "next_gate": next_gate,
            "blockers": list(snapshot.get("blockers") or ())[:6],
            "open_decisions": list(snapshot.get("open_decisions") or ())[:6],
        }
        return {
            "contract": FRAME_VERSION,
            "provider": "flow",
            "project_context": self._context_payload(context),
            "capability_lens": self._lens_payload(lens),
            "work_anchor": snapshot.get("focus"),
            "state": state,
            "summary": self._summary(lens.selected_area, next_gate),
            "semantic_boundary": (
                "Current lifecycle facts only; resolve returns a call and grants no authority."
            ),
            "continuation_policy": actions[0]["continuation_policy"],
            "actions": actions[:1],
            "choices": actions[:6],
            "page": self._page(len(actions), min(len(actions), 6), 0),
            "provider_availability": dict(provider_state),
            "details_available": [
                "fow_handover",
                "fow_packet_inspect",
                "fow_campaign_inspect",
            ],
        }

    def _technical_frame(
        self,
        context: Any,
        lens: CapabilityLensBinding,
        selected: Mapping[str, object],
        provider_state: Mapping[str, object],
    ) -> dict[str, object]:
        available = str(selected.get("availability") or "blocked") != "blocked"
        return {
            "contract": FRAME_VERSION,
            "provider": lens.producing_provider,
            "project_context": self._context_payload(context),
            "capability_lens": self._lens_payload(lens),
            "work_anchor": selected.get("area"),
            "state": {
                "availability": selected.get("availability"),
                "reason": selected.get("reason"),
                "repository_roles": provider_state.get("repository_roles", []),
            },
            "summary": (
                f"{selected.get('label')} is available."
                if available
                else f"{selected.get('label')} is blocked: {selected.get('reason')}."
            ),
            "semantic_boundary": (
                "CodingCastle owns technical facts and execution; Flower only composes "
                "read-only discovery in this frame."
            ),
            "continuation_policy": ContinuationPolicy.RETURN_TO_MODEL.value,
            "actions": [],
            "choices": [],
            "page": self._page(0, 0, 0),
            "provider_availability": dict(provider_state),
            "details_available": ["codingcastle_interaction"],
        }

    def _orientation_frame(self, interaction: str, decision: str) -> dict[str, object]:
        discovered = dict(self.discover(interaction, _persist_continuation=False))
        if decision == "select_project":
            values = list(discovered.get("projects") or ())
            choices = [
                {
                    "number": index,
                    "label": f"Open {item.get('name')}",
                    "tool": "fow_interaction",
                    "operation": "select_project",
                    "arguments": {
                        "operation": "select_project",
                        "project_selection": int(item.get("number") or index),
                    },
                    "semantic_inputs": [],
                    "injected_inputs": ["interaction_session_ref"],
                    "risk": "write",
                    "decision_class": "semantic",
                    "effect_class": "projection_state",
                    "admission": "explicit_project_choice",
                    "reason": "Bind the selected lifecycle project.",
                    "continuation_policy": ContinuationPolicy.RETURN_TO_MODEL.value,
                }
                for index, item in enumerate(values, 1)
            ]
            if not choices:
                choices = [
                    {
                        "number": 1,
                        "label": "Create a lifecycle project",
                        "tool": "fow_create_project",
                        "operation": "call",
                        "arguments": {},
                        "semantic_inputs": ["project_id", "name"],
                        "injected_inputs": ["actor", "request_id"],
                        "risk": "write",
                        "decision_class": "semantic",
                        "effect_class": "ledger_mutation",
                        "admission": "handler",
                        "reason": "No lifecycle project exists.",
                        "continuation_policy": ContinuationPolicy.RETURN_TO_MODEL.value,
                    }
                ]
        else:
            values = list(discovered.get("areas") or ())
            choices = [
                {
                    "number": index,
                    "label": f"Open {item.get('label')}",
                    "tool": "fow_interaction",
                    "operation": "select",
                    "arguments": {
                        "operation": "select",
                        "area": int(item.get("number") or index),
                    },
                    "semantic_inputs": [],
                    "injected_inputs": ["interaction_session_ref"],
                    "risk": "write",
                    "decision_class": "semantic",
                    "effect_class": "projection_state",
                    "admission": "work_area_available",
                    "reason": "Open the selected work area.",
                    "continuation_policy": ContinuationPolicy.RETURN_TO_MODEL.value,
                }
                for index, item in enumerate(values, 1)
            ]
        core: dict[str, object] = {
            "contract": FRAME_VERSION,
            "provider": "flow",
            "project_context": discovered.get("project_context"),
            "capability_lens": discovered.get("capability_lens"),
            "work_anchor": None,
            "state": {"decision_required": decision},
            "summary": (
                "Select one project."
                if decision == "select_project"
                else "Select one work area."
            ),
            "semantic_boundary": "Selection changes projection context only.",
            "continuation_policy": ContinuationPolicy.RETURN_TO_MODEL.value,
            "actions": [],
            "choices": choices[:9],
            "page": (
                dict(discovered.get("page") or {})
                if values
                else self._page(len(choices), min(len(choices), 9), 0)
            ),
            "details_available": ["fow_capabilities"],
        }
        core["frame_ref"] = self._fingerprint(core)
        return core

    def _area_inventory(
        self, interaction: str, context: Any
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        lens = self._current_lens(interaction, context)
        prerequisite_state = self._flow_prerequisite_state(context.project_id)
        areas = [
            {
                "number": number,
                "area": str(descriptor["area"]),
                "label": str(descriptor["label"]),
                "purpose": str(descriptor["purpose"]),
                "owner": "Flower MCP",
                "provider": "flow",
                **self._flow_area_availability(
                    str(descriptor["area"]), prerequisite_state, lens=lens
                ),
            }
            for number, descriptor in enumerate(work_area_catalog(), 1)
        ]
        provider_state: dict[str, object] = {
            "mode": "standalone",
            "kind": None,
            "availability": "not_configured",
            "repository_roles": [],
        }
        if self._interaction_provider is None or not context.provider_context_id:
            return areas, provider_state
        try:
            snapshot = self._interaction_provider.discover(
                context.provider_context_id,
                interaction_session_ref=interaction,
            )
        except (
            ImplementationProviderUnavailableError,
            ImplementationProviderContractError,
        ) as exc:
            provider_state.update(
                {
                    "mode": "coordinated_degraded",
                    "kind": getattr(self._interaction_provider, "kind", "provider"),
                    "availability": "unavailable",
                    "reason": str(getattr(exc, "terminal_reason", str(exc))),
                }
            )
            if lens is not None and lens.producing_provider != "flow":
                areas.append(
                    {
                        "number": len(areas) + 1,
                        "area": lens.selected_area,
                        "label": lens.selected_area.replace("_", " ").title(),
                        "purpose": "Previously selected technical work area.",
                        "owner": lens.producing_provider,
                        "provider": lens.producing_provider,
                        "provider_number": 0,
                        "availability": "blocked",
                        "reason": "provider_unavailable",
                        "prerequisites": ["restore_provider"],
                    }
                )
            return areas, provider_state
        provider_state.update(
            {
                "mode": "coordinated",
                "kind": snapshot.provider,
                "availability": snapshot.availability,
                "repository_roles": list(
                    snapshot.project_context.get("repository_roles") or ()
                ),
            }
        )
        start = len(areas)
        for index, item in enumerate(snapshot.areas, 1):
            available = bool(item.get("available"))
            area = str(item.get("area") or "")
            areas.append(
                {
                    "number": start + index,
                    "area": area,
                    "label": area.replace("_", " ").title(),
                    "purpose": str(item.get("purpose") or ""),
                    "owner": str(item.get("owner") or snapshot.provider),
                    "provider": snapshot.provider,
                    "provider_number": int(item.get("provider_number") or index),
                    "availability": (
                        "active"
                        if lens
                        and lens.producing_provider == snapshot.provider
                        and lens.selected_area == area
                        else "available"
                        if available
                        else "blocked"
                    ),
                    "reason": str(item.get("reason") or ""),
                    "prerequisites": list(item.get("prerequisites") or ()),
                }
            )
        return areas, provider_state

    def _flow_area_availability(
        self,
        area: str,
        prerequisite_state: Mapping[str, int],
        *,
        lens: CapabilityLensBinding | None,
    ) -> Mapping[str, object]:
        if lens and lens.producing_provider == "flow" and lens.selected_area == area:
            return {"availability": "active", "reason": "", "prerequisites": []}
        prerequisites: Mapping[str, tuple[bool, str, tuple[str, ...]]] = {
            "milestones": (
                prerequisite_state["requirements"] > 0,
                "requirements_required",
                ("requirements",),
            ),
            "changes": (
                prerequisite_state["milestones"] > 0,
                "milestone_required",
                ("milestones",),
            ),
            "packet_lifecycle": (
                prerequisite_state["changes"] > 0,
                "change_required",
                ("changes",),
            ),
            "campaigns": (
                prerequisite_state["packets"] > 0,
                "packet_required",
                ("packet_lifecycle",),
            ),
        }
        ready, reason, required = prerequisites.get(area, (True, "", ()))
        return {
            "availability": ("available" if ready else "available_with_prerequisites"),
            "reason": "" if ready else reason,
            "prerequisites": [] if ready else list(required),
        }

    def _flow_prerequisite_state(self, project_id: str) -> Mapping[str, int]:
        with self._repository.consistent_read():
            changes = list(self._repository.list_changes(project_id))
            return {
                "requirements": len(self._repository.traceability_matrix(project_id)),
                "milestones": len(self._repository.milestones(project_id)),
                "changes": len(changes),
                "packets": sum(
                    len(item.get("packets", []))
                    for item in changes
                    if isinstance(item, Mapping)
                ),
            }

    def _default_area_action(
        self, area: str, snapshot: Mapping[str, object]
    ) -> Mapping[str, object]:
        active = dict(snapshot.get("active_work") or {})
        packet = dict(active.get("packet") or {})
        campaign = dict(active.get("campaign") or {})
        specs: Mapping[str, tuple[str, str, Mapping[str, object], str]] = {
            "project_bootstrap": (
                "Inspect provider bindings",
                "fow_bootstrap",
                {"operation": "list_provider_bindings"},
                "list_provider_bindings",
            ),
            "requirements": (
                "Inspect requirement traceability",
                "fow_traceability",
                {},
                "call",
            ),
            "goal_graph": (
                "Inspect Goal Graph",
                "fow_goal",
                {"operation": "view"},
                "view",
            ),
            "milestones": ("Inspect next lifecycle work", "fow_what_next", {}, "call"),
            "changes": ("Inspect next lifecycle work", "fow_what_next", {}, "call"),
            "packet_lifecycle": (
                "Inspect current packet",
                "fow_packet_inspect",
                {
                    "packet_id": str(packet.get("packet_id") or ""),
                    "change_id": str(active.get("change_id") or ""),
                    "view": "summary",
                },
                "summary",
            ),
            "assurance": ("Inspect next assurance work", "fow_what_next", {}, "call"),
            "handover": (
                "Inspect project-state snapshot",
                "fow_handover",
                {"operation": "project_state_snapshot"},
                "project_state_snapshot",
            ),
            "campaigns": (
                "Inspect current campaign",
                "fow_campaign_inspect",
                {
                    "campaign_id": str(campaign.get("campaign_id") or ""),
                    "change_id": str(active.get("change_id") or ""),
                    "view": "summary",
                },
                "summary",
            ),
        }
        label, tool, arguments, operation = specs[area]
        if area in {"packet_lifecycle", "campaigns"} and not any(
            value for key, value in arguments.items() if key.endswith("_id")
        ):
            label, tool, arguments, operation = (
                "Inspect next lifecycle work",
                "fow_what_next",
                {},
                "call",
            )
        return self._action(1, label, tool, operation, arguments, required_inputs=())

    def _action_from_route(
        self, route: Mapping[str, object], gate: Mapping[str, object]
    ) -> Mapping[str, object]:
        tool = str(route.get("tool") or "")
        operation = str(route.get("operation") or "call")
        if operation not in operation_names(tool):
            operation = next(
                (
                    fallback
                    for fallback in ("advance", "call")
                    if fallback in operation_names(tool)
                ),
                operation,
            )
        return self._action(
            1,
            str(gate.get("reason") or gate.get("kind") or "Continue current work"),
            tool,
            operation,
            dict(route.get("arguments") or {}),
            required_inputs=tuple(
                str(item) for item in route.get("required_inputs", ())
            ),
            continuation_policy=str(gate.get("continuation_policy") or ""),
        )

    @staticmethod
    def _action(
        number: int,
        label: str,
        tool: str,
        operation: str,
        arguments: Mapping[str, object],
        *,
        required_inputs: tuple[str, ...],
        continuation_policy: str = "",
    ) -> Mapping[str, object]:
        try:
            contract = operation_contract(tool, operation)
        except ValueError as exc:
            raise InteractionProjectionError("interaction_route_unregistered") from exc
        injected_inputs = list(contract.get("injected_inputs") or ())
        injected = set(injected_inputs)
        semantic_required = [
            field for field in required_inputs if field not in injected
        ]
        projected_continuation = str(
            continuation_policy
            or contract.get("continuation_policy")
            or ContinuationPolicy.RETURN_TO_MODEL.value
        )
        if projected_continuation not in {
            item.value for item in ContinuationPolicy
        }:
            raise InteractionProjectionError(
                "interaction_continuation_policy_invalid"
            )
        return {
            "number": number,
            "label": label,
            "tool": tool,
            "operation": operation,
            "arguments": {
                key: value for key, value in arguments.items() if key not in injected
            },
            "required_inputs": list(required_inputs),
            "semantic_inputs": semantic_required,
            "injected_inputs": injected_inputs,
            "risk": str(contract.get("risk") or "write"),
            "decision_class": str(contract.get("decision_class") or "semantic"),
            "effect_class": str(contract.get("effect_class") or "none"),
            "admission": str(contract.get("admission") or "handler"),
            "reason": label,
            "continuation_policy": projected_continuation,
        }

    def _current_lens(
        self, interaction: str, context: Any
    ) -> CapabilityLensBinding | None:
        lens = self._repository.get_interaction_capability_lens(interaction)
        if lens is None:
            return None
        if (
            lens.project_id != context.project_id
            or lens.project_context_revision != context.revision
        ):
            self._repository.clear_interaction_capability_lens(
                interaction, actor="system", request_id="project-context-changed"
            )
            return None
        return lens

    def _require_context(self, interaction: str) -> Any:
        context = self._project_context.current(interaction)
        if context is None:
            raise InteractionProjectionError("project_context_not_selected")
        return context

    @staticmethod
    def _area_by_number(
        areas: list[Mapping[str, object]], number: int
    ) -> Mapping[str, object]:
        if isinstance(number, bool) or not isinstance(number, int):
            raise InteractionProjectionError("interaction_area_number_invalid")
        selected = next(
            (item for item in areas if int(item.get("number") or 0) == number), None
        )
        if selected is None:
            raise InteractionProjectionError("interaction_area_number_invalid")
        return selected

    @staticmethod
    def _context_payload(context: Any) -> Mapping[str, object]:
        return {
            "project_id": context.project_id,
            "revision": context.revision,
            "provider_configured": bool(context.provider_context_id),
        }

    @staticmethod
    def _lens_payload(
        lens: CapabilityLensBinding | None,
    ) -> Mapping[str, object] | None:
        if lens is None:
            return None
        return {
            "provider": lens.producing_provider,
            "area": lens.selected_area,
            "revision": lens.revision,
        }

    @staticmethod
    def _summary(area: str, next_gate: Mapping[str, object]) -> str:
        kind = str(next_gate.get("kind") or "idle")
        reason = str(next_gate.get("reason") or "no pending action")
        return f"{area}: {kind}; {reason}."

    @staticmethod
    def _page(total: int, visible: int, offset: int) -> Mapping[str, object]:
        consumed = offset + visible
        has_more = consumed < total
        return {
            "returned": visible,
            "has_more": has_more,
            "complete": not has_more,
            "visible_count": visible,
            "omitted_count": max(0, total - consumed),
            "semantic_actions": (
                ["more", "refine", "stop"] if has_more else ["refine", "stop"]
            ),
        }

    @staticmethod
    def _fingerprint(value: Mapping[str, object]) -> str:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return "frame:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _bounded_limit(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= 20
        ):
            raise InteractionProjectionError("interaction_limit_invalid")
        return value

    @staticmethod
    def _required_interaction(value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise InteractionProjectionError("interaction_session_ref_required")
        if len(normalized) > 200:
            raise InteractionProjectionError("interaction_session_ref_too_long")
        return normalized


__all__ = [
    "DISCOVERY_VERSION",
    "FRAME_VERSION",
    "InteractionProjectionError",
    "InteractionProjectionService",
]
