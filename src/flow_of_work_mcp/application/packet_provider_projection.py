"""Provider-neutral packet capabilities and portable semantic projection."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.packet_provider import PacketProviderMode
from flow_of_work_mcp.core.errors import ImplementationProviderUnavailableError
from flow_of_work_mcp.core.ports.packet_provider import PacketProvider


class PacketProviderProjectionService:
    def __init__(
        self,
        *,
        mode: PacketProviderMode | str = PacketProviderMode.AGNOSTIC,
        provider: PacketProvider | None = None,
    ) -> None:
        self._mode = PacketProviderMode(mode)
        self._provider = provider

    @property
    def mode(self) -> str:
        return self._mode.value

    @property
    def provider(self) -> PacketProvider | None:
        return self._provider

    def capability(self, project_id: str) -> Mapping[str, object]:
        configured = self._provider is not None
        bound = False
        if configured:
            try:
                self._provider.session_for_project(project_id)
                bound = True
            except ImplementationProviderUnavailableError:
                bound = False
        state = (
            "agnostic"
            if self._mode == PacketProviderMode.AGNOSTIC
            else "provider_pending"
            if not configured or not bound
            else "provider_configured"
        )
        return {
            "mode": self._mode.value,
            "provider_kind": (
                self._provider.kind if self._provider is not None else ""
            ),
            "configured": configured,
            "project_bound": bound,
            "state": state,
            "health": (
                "not_applicable"
                if self._mode == PacketProviderMode.AGNOSTIC
                else "not_probed"
                if configured and bound
                else "unavailable"
            ),
            "provider_required": self._mode == PacketProviderMode.REQUIRED,
            "technical_execution_claimed": False,
        }

    def portable_packet(
        self,
        *,
        project_id: str,
        change_id: str,
        packet: Mapping[str, object],
        work_plan: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        units: list[Mapping[str, object]] = []
        for item in (work_plan or {}).get("units", []):
            if not isinstance(item, Mapping):
                continue
            file_path = str(item.get("file_path") or "")
            target_description = str(item.get("target_description") or "")
            operation_kind = str(item.get("operation_kind") or "")
            target = (
                {
                    "kind": "future_path",
                    "relative_path": file_path,
                    "member_label": str(item.get("member_label") or ""),
                    "surface": str(item.get("surface") or "repo"),
                }
                if file_path
                else {
                    "kind": "described_current_target",
                    "description": target_description or "selected current target",
                    "member_label": str(item.get("member_label") or ""),
                    "surface": str(item.get("surface") or "repo"),
                }
            )
            destination = (
                {
                    "kind": "future_path",
                    "relative_path": file_path,
                    "member_label": str(item.get("member_label") or ""),
                    "surface": str(item.get("surface") or "repo"),
                }
                if operation_kind == "extract_move"
                else None
            )
            if destination is not None:
                target = {
                    "kind": "described_current_target",
                    "description": target_description or "selected current target",
                    "member_label": str(item.get("member_label") or ""),
                    "surface": str(item.get("surface") or "repo"),
                }
            units.append(
                {
                    "client_unit_key": str(item.get("client_unit_key") or ""),
                    "operation_kind": operation_kind,
                    "target": target,
                    **({"destination": destination} if destination is not None else {}),
                    "instructions": list(item.get("instructions") or ()),
                    "constraints": list(item.get("constraints") or ()),
                    "out_of_scope": list(item.get("out_of_scope") or ()),
                    "unit_checks": list(item.get("unit_checks") or ()),
                    "depends_on": list(item.get("depends_on") or ()),
                    "replaces": list(item.get("replaces") or ()),
                }
            )
        return {
            "contract_version": "flow.portable_packet.v1",
            "project_id": project_id,
            "change_id": change_id,
            "packet_id": str(packet.get("packet_id") or ""),
            "flow_spec_revision": int(
                packet.get("spec_revision") or packet.get("current_revision") or 0
            ),
            "purpose": str(packet.get("purpose") or "implementation"),
            "title": str(packet.get("title") or ""),
            "objective": str(packet.get("objective") or ""),
            "rationale": str(packet.get("rationale") or ""),
            "completion_criteria": list(packet.get("completion_criteria") or ()),
            "in_scope": list(packet.get("in_scope") or ()),
            "out_of_scope": list(packet.get("out_of_scope") or ()),
            "invariants": list(packet.get("invariants") or ()),
            "requirement_ids": list(packet.get("requirement_ids") or ()),
            "goal_ids": list(packet.get("goal_ids") or ()),
            "units": units,
            "unresolved_questions": list(
                packet.get("unresolved_questions") or ()
            ),
            "execution_disposition": "provider_pending",
            "technical_execution_claimed": False,
        }


__all__ = ["PacketProviderProjectionService"]
