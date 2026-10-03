"""Revisioned packet work-plan value objects and deterministic validation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import normalize_declarations

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_operations import PacketTaskOperationKind
from flow_of_work_mcp.core.domain.paths import repo_relative_file_path
from flow_of_work_mcp.core.domain.provider_surfaces import (
    codingcastle_provider_surface,
)


_WORK_PLAN_ID_RE = re.compile(r"^WPLAN-[0-9]{6}$")
_CLIENT_UNIT_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_MAX_UNITS = 256
_MAX_LIST_ITEMS = 128
_MAX_TEXT_LENGTH = 4096


class PacketWorkPlanStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    LEGACY_NON_EXECUTABLE = "legacy_non_executable"


@dataclass(frozen=True)
class WorkPlanUnit:
    """One caller-authored unit in a complete packet work plan."""

    client_unit_key: str
    operation_kind: PacketTaskOperationKind | str
    instructions: tuple[str, ...]
    mutation_target_binding_id: str = ""
    target_description: str = ""
    member_label: str = ""
    file_path: str = ""
    context_target_binding_ids: tuple[str, ...] = ()
    unit_checks: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    replaces: tuple[str, ...] = ()
    surface: str = "repo"
    implements: tuple[int, ...] = ()
    provides: tuple[Mapping[str, object], ...] = ()
    requires: tuple[Mapping[str, object], ...] = ()
    verifies: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        key = required_text(self.client_unit_key, "client_unit_key")
        if not _CLIENT_UNIT_KEY_RE.fullmatch(key):
            raise ValueError(
                "client_unit_key must contain only letters, digits, dot, underscore or dash"
            )
        object.__setattr__(self, "client_unit_key", key)
        operation_kind = PacketTaskOperationKind(self.operation_kind)
        if operation_kind == PacketTaskOperationKind.REVIEW_ONLY:
            raise ValueError("review_only is not executable in a packet work plan")
        object.__setattr__(self, "operation_kind", operation_kind)

        mutation_binding = str(self.mutation_target_binding_id or "").strip()
        target_description = _bounded_text(
            self.target_description, "target_description"
        )
        member_label = _bounded_text(self.member_label, "member_label")
        if mutation_binding and target_description:
            raise ValueError(
                "unit cannot declare both a target binding and target description"
            )
        file_path = repo_relative_file_path(self.file_path)
        if operation_kind == PacketTaskOperationKind.NEW_FILE:
            if mutation_binding:
                raise ValueError("new-file unit cannot declare a mutation target binding")
            if target_description:
                raise ValueError("new-file unit cannot declare target_description")
            if not file_path:
                raise ValueError("new-file unit requires file_path")
        elif operation_kind == PacketTaskOperationKind.EXTRACT_MOVE:
            if not mutation_binding and not target_description:
                raise ValueError(
                    "extract-move unit requires a target binding or readable target description"
                )
            if not file_path:
                raise ValueError("extract-move unit requires destination file_path")
        else:
            if not mutation_binding and not target_description:
                raise ValueError(
                    "existing-target unit requires a target binding or readable target description"
                )
            if file_path:
                raise ValueError(
                    "file_path is only valid for new-file or extract-move units"
                )
        object.__setattr__(self, "mutation_target_binding_id", mutation_binding)
        object.__setattr__(self, "target_description", target_description)
        object.__setattr__(self, "member_label", member_label)
        object.__setattr__(self, "file_path", file_path)

        declarations = normalize_declarations({field: getattr(self, field) for field in ("implements", "provides", "requires", "verifies")})
        for field, value in declarations.items():
            object.__setattr__(self, field, tuple(value))

        instructions = _bounded_text_tuple(
            self.instructions, "instructions", required=True, preserve_duplicates=True
        )
        context_bindings = _bounded_text_tuple(
            self.context_target_binding_ids, "context_target_binding_ids", unique=True
        )
        if mutation_binding and mutation_binding in context_bindings:
            raise ValueError("mutation target cannot also be a read-only context target")
        object.__setattr__(self, "instructions", instructions)
        object.__setattr__(self, "context_target_binding_ids", context_bindings)
        object.__setattr__(
            self,
            "unit_checks",
            _bounded_text_tuple(self.unit_checks, "unit_checks", required=True),
        )
        object.__setattr__(
            self, "constraints", _bounded_text_tuple(self.constraints, "constraints")
        )
        object.__setattr__(
            self, "out_of_scope", _bounded_text_tuple(self.out_of_scope, "out_of_scope")
        )
        object.__setattr__(
            self, "depends_on", _bounded_text_tuple(self.depends_on, "depends_on", unique=True)
        )
        object.__setattr__(self, "replaces", _bounded_text_tuple(self.replaces, "replaces"))
        object.__setattr__(self, "surface", _surface(self.surface))

    @property
    def mutation_identity(self) -> tuple[str, str]:
        if self.file_path:
            return ("future_output", self.file_path)
        if self.target_description:
            return ("described_target", self.target_description)
        return ("binding", self.mutation_target_binding_id)


@dataclass(frozen=True)
class PacketWorkPlanDraft:
    """A complete authored revision, validated before persistence."""

    change_id: str
    packet_id: str
    packet_revision: int
    units: tuple[WorkPlanUnit, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        if int(self.packet_revision) <= 0:
            raise ValueError("packet_revision must be positive")
        object.__setattr__(self, "packet_revision", int(self.packet_revision))
        units = tuple(self.units)
        if not units:
            raise ValueError("packet work plan requires at least one unit")
        if len(units) > _MAX_UNITS:
            raise ValueError(f"packet work plan supports at most {_MAX_UNITS} units")
        if any(not isinstance(unit, WorkPlanUnit) for unit in units):
            raise TypeError("units must contain WorkPlanUnit values")
        _validate_plan_graph(units)
        object.__setattr__(self, "units", units)


@dataclass(frozen=True)
class PacketWorkPlan:
    """Typed identity for a persisted work-plan revision."""

    work_plan_id: str
    plan_revision: int
    status: PacketWorkPlanStatus | str
    draft: PacketWorkPlanDraft

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_plan_id", validate_packet_work_plan_id(self.work_plan_id))
        if int(self.plan_revision) <= 0:
            raise ValueError("plan_revision must be positive")
        object.__setattr__(self, "plan_revision", int(self.plan_revision))
        object.__setattr__(self, "status", PacketWorkPlanStatus(self.status))


def validate_packet_work_plan_id(value: str) -> str:
    work_plan_id = required_text(value, "work_plan_id")
    if not _WORK_PLAN_ID_RE.fullmatch(work_plan_id):
        raise ValueError("work_plan_id must match WPLAN-000000")
    return work_plan_id


def _validate_plan_graph(units: tuple[WorkPlanUnit, ...]) -> None:
    by_key: dict[str, WorkPlanUnit] = {}
    for unit in units:
        if unit.client_unit_key in by_key:
            raise ValueError(f"duplicate client_unit_key: {unit.client_unit_key}")
        by_key[unit.client_unit_key] = unit

    for unit in units:
        for dependency in unit.depends_on:
            if dependency == unit.client_unit_key:
                raise ValueError(f"unit cannot depend on itself: {unit.client_unit_key}")
            if dependency not in by_key:
                raise ValueError(
                    f"unknown dependency for {unit.client_unit_key}: {dependency}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError("packet work plan dependency graph contains a cycle")
        if key in visited:
            return
        visiting.add(key)
        for dependency in by_key[key].depends_on:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in by_key:
        visit(key)

    owners: dict[tuple[str, str], list[str]] = {}
    for unit in units:
        owners.setdefault(unit.mutation_identity, []).append(unit.client_unit_key)
    for identity, owner_keys in owners.items():
        if len(owner_keys) < 2:
            continue
        for index, left in enumerate(owner_keys):
            for right in owner_keys[index + 1 :]:
                if not (_depends_transitively(by_key, left, right) or _depends_transitively(by_key, right, left)):
                    raise ValueError(
                        "repeated mutation target requires an unambiguous dependency order: "
                        f"{identity[1]}"
                    )


def _depends_transitively(
    by_key: dict[str, WorkPlanUnit], unit_key: str, possible_predecessor: str
) -> bool:
    pending = list(by_key[unit_key].depends_on)
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == possible_predecessor:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(by_key[current].depends_on)
    return False


def _bounded_text_tuple(
    values: tuple[str, ...],
    field_name: str,
    *,
    required: bool = False,
    unique: bool = False,
    preserve_duplicates: bool = False,
) -> tuple[str, ...]:
    if len(values) > _MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} supports at most {_MAX_LIST_ITEMS} items")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        if len(value) > _MAX_TEXT_LENGTH:
            raise ValueError(f"{field_name} item exceeds {_MAX_TEXT_LENGTH} characters")
        if unique and value in seen:
            raise ValueError(f"{field_name} contains duplicate value: {value}")
        if not preserve_duplicates and value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if required and not normalized:
        raise ValueError(f"{field_name} requires at least one item")
    return tuple(normalized)


def _bounded_text(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{field_name} exceeds {_MAX_TEXT_LENGTH} characters")
    return normalized


def _surface(value: str) -> str:
    return codingcastle_provider_surface(required_text(value, "surface"))
