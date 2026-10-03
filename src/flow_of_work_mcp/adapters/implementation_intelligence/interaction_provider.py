"""Read-only CodingCastle interaction discovery over the public MCP route."""

from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.adapters.implementation_intelligence.mcp_provider import (
    McpToolClient,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError,
    ImplementationProviderUnavailableError,
)
from flow_of_work_mcp.core.ports.interaction_provider import (
    TechnicalInteractionSnapshot,
)


class McpCodingCastleInteractionProvider:
    def __init__(
        self,
        *,
        client: McpToolClient,
        tool_name: str = "codingcastle_interaction",
    ) -> None:
        if str(tool_name or "").strip() != "codingcastle_interaction":
            raise ValueError(
                "CodingCastle interaction provider requires codingcastle_interaction"
            )
        self._client = client
        self._tool_name = "codingcastle_interaction"

    @property
    def kind(self) -> str:
        return "codingcastle"

    def discover(
        self,
        provider_context_id: str,
        *,
        interaction_session_ref: str,
    ) -> TechnicalInteractionSnapshot:
        context = str(provider_context_id or "").strip()
        if not context:
            raise ImplementationProviderUnavailableError(
                "interaction_provider_context_unbound"
            )
        payload = _unwrap(
            self._client.call_tool(
                self._tool_name,
                {
                    "session_id": context,
                    "operation": "discover",
                    # Flow owns the coordinated lens. Provider discovery must
                    # not create or alter CodingCastle's standalone lens slot.
                    "interaction_session_ref": "",
                    "limit": 9,
                    "page_action": "refine",
                    "detail_level": "standard",
                },
            )
        )
        if str(payload.get("contract") or "") != (
            "codingcastle.work-area-discovery.v1"
        ):
            raise ImplementationProviderContractError(
                "interaction_provider_contract_version_mismatch"
            )
        project_context = payload.get("project_context")
        areas = payload.get("areas")
        if not isinstance(project_context, Mapping) or not isinstance(areas, list):
            raise ImplementationProviderContractError(
                "interaction_provider_discovery_invalid"
            )
        normalized: list[Mapping[str, object]] = []
        for item in areas:
            if not isinstance(item, Mapping):
                raise ImplementationProviderContractError(
                    "interaction_provider_area_invalid"
                )
            area = str(item.get("area") or "").strip()
            purpose = str(item.get("purpose") or "").strip()
            if not area or not purpose:
                raise ImplementationProviderContractError(
                    "interaction_provider_area_invalid"
                )
            normalized.append(
                {
                    "area": area,
                    "provider_number": int(item.get("number") or len(normalized) + 1),
                    "purpose": purpose,
                    "owner": str(item.get("owner") or "CodingCastle"),
                    "available": bool(item.get("available")),
                    "reason": str(item.get("reason") or ""),
                    "prerequisites": [
                        str(value) for value in item.get("prerequisites", [])
                    ],
                }
            )
        return TechnicalInteractionSnapshot(
            contract="flow.technical-interaction-snapshot.v1",
            provider=self.kind,
            provider_context_id=context,
            project_context=dict(project_context),
            areas=tuple(normalized),
        )


def _unwrap(payload: Mapping[str, object]) -> Mapping[str, object]:
    current: object = payload
    for _ in range(4):
        if not isinstance(current, Mapping):
            break
        status = str(current.get("status") or "").strip().lower()
        if status and status not in {"ok", "success", "accepted"}:
            reason = str(current.get("reason") or "interaction_provider_rejected")
            raise ImplementationProviderUnavailableError(reason)
        result = current.get("result")
        if isinstance(result, Mapping):
            current = result
            continue
        return dict(current)
    raise ImplementationProviderContractError("interaction_provider_result_invalid")


__all__ = ["McpCodingCastleInteractionProvider"]
