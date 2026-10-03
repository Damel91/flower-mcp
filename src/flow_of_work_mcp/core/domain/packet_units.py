"""Packet unit proposal value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping
import re

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_operations import PacketTaskOperationKind
from flow_of_work_mcp.core.domain.paths import repo_relative_file_path
from flow_of_work_mcp.core.domain.provider_surfaces import (
    codingcastle_provider_surface,
)


_PACKET_UNIT_PROPOSAL_ID_RE = re.compile(r"^PUNIT-[0-9]{6}$")


class PacketUnitProposalStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    RESIDUAL = "residual"


@dataclass(frozen=True)
class PacketUnitProposalDraft:
    change_id: str
    packet_id: str
    operation_kind: PacketTaskOperationKind | str
    target_binding_ids: tuple[str, ...]
    goal: str
    file_path: str = ""
    intent_points: tuple[str, ...] = ()
    acceptance_checks: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    context_refs: tuple[Mapping[str, object], ...] = ()
    source_reason: str = ""
    target_adequacy: Mapping[str, object] = field(default_factory=dict)
    residual_reason: str = ""
    surface: str = "repo"

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        object.__setattr__(
            self,
            "operation_kind",
            PacketTaskOperationKind(self.operation_kind),
        )
        object.__setattr__(
            self,
            "target_binding_ids",
            tuple(required_text(str(item), "target_binding_ids") for item in self.target_binding_ids),
        )
        if self.operation_kind != PacketTaskOperationKind.NEW_FILE and not self.target_binding_ids:
            raise ValueError("non-new-file proposal requires target_binding_ids")
        file_path = repo_relative_file_path(self.file_path)
        if self.operation_kind == PacketTaskOperationKind.NEW_FILE and not file_path:
            raise ValueError("new-file proposal requires file_path")
        if self.operation_kind != PacketTaskOperationKind.NEW_FILE and file_path:
            raise ValueError("file_path is only valid for new-file proposals")
        object.__setattr__(self, "file_path", file_path)
        object.__setattr__(self, "goal", required_text(self.goal, "goal"))
        object.__setattr__(self, "intent_points", _text_tuple(self.intent_points))
        object.__setattr__(self, "acceptance_checks", _text_tuple(self.acceptance_checks))
        object.__setattr__(self, "constraints", _text_tuple(self.constraints))
        object.__setattr__(self, "out_of_scope", _text_tuple(self.out_of_scope))
        object.__setattr__(self, "depends_on", _text_tuple(self.depends_on))
        object.__setattr__(
            self,
            "context_refs",
            tuple(dict(item) for item in self.context_refs if isinstance(item, Mapping)),
        )
        object.__setattr__(self, "source_reason", str(self.source_reason or "").strip())
        object.__setattr__(self, "target_adequacy", dict(self.target_adequacy or {}))
        object.__setattr__(self, "residual_reason", str(self.residual_reason or "").strip())
        object.__setattr__(
            self,
            "surface",
            codingcastle_provider_surface(required_text(self.surface, "surface")),
        )


def validate_packet_unit_proposal_id(proposal_id: str) -> str:
    value = required_text(proposal_id, "packet_unit_proposal_id")
    if not _PACKET_UNIT_PROPOSAL_ID_RE.fullmatch(value):
        raise ValueError("packet_unit_proposal_id must match PUNIT-000000")
    return value


def _text_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in values if str(item).strip())
