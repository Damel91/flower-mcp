"""Packet residual-risk pressure value objects."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text


_PRESSURE_ID_RE = re.compile(r"^PRESS-[0-9]{6}$")


class SemanticConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImprovementPressure(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class PacketPressureSource(StrEnum):
    DETERMINISTIC = "deterministic"
    ORCHESTRATOR = "orchestrator"
    PROVIDER = "provider"
    AUTHORITY = "authority"


@dataclass(frozen=True)
class PacketPressureDraft:
    change_id: str
    packet_id: str
    semantic_confidence: SemanticConfidence | str
    improvement_pressure: ImprovementPressure | str
    residual_risks: tuple[str, ...]
    challenge_questions: tuple[str, ...]
    accepted_risk_refs: tuple[str, ...] = ()
    source: PacketPressureSource | str = PacketPressureSource.DETERMINISTIC
    packet_revision: int = 0
    profile: str = "balanced"

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        object.__setattr__(self, "semantic_confidence", SemanticConfidence(self.semantic_confidence))
        object.__setattr__(self, "improvement_pressure", ImprovementPressure(self.improvement_pressure))
        object.__setattr__(self, "residual_risks", _unique_texts(self.residual_risks, "residual_risks"))
        object.__setattr__(
            self,
            "challenge_questions",
            _unique_texts(self.challenge_questions, "challenge_questions"),
        )
        object.__setattr__(
            self,
            "accepted_risk_refs",
            _unique_texts(self.accepted_risk_refs, "accepted_risk_refs")
            if self.accepted_risk_refs
            else (),
        )
        object.__setattr__(self, "source", PacketPressureSource(self.source))
        if self.packet_revision < 0:
            raise ValueError("packet_revision cannot be negative")
        object.__setattr__(self, "profile", _profile(self.profile))


def validate_pressure_id(pressure_id: str) -> str:
    value = required_text(pressure_id, "pressure_id")
    if not _PRESSURE_ID_RE.fullmatch(value):
        raise ValueError("pressure_id must match PRESS-000000")
    return value


def _profile(value: str) -> str:
    normalized = str(value or "balanced").strip()
    if normalized not in {"balanced", "strict_local_orchestrator", "minimal"}:
        raise ValueError("profile must be balanced, strict_local_orchestrator or minimal")
    return normalized


def _unique_texts(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(required_text(str(item), field) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must be unique")
    return normalized
