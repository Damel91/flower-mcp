"""Versioned, deterministic engineering-question applicability policy."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Mapping

from flow_of_work_mcp.core.domain.packet_construction import PacketQuestionCategory


QUESTION_POLICY_VERSION = "engineering-question-policy-v2"


@dataclass(frozen=True)
class EngineeringQuestionRule:
    key: str
    category: PacketQuestionCategory
    prompt: str
    dependency_keys: tuple[str, ...]
    operation_kinds: frozenset[str] = frozenset()
    required: bool = True
    waiver_allowed: bool = False
    deterministic_evidence_allowed: bool = False

    def applies_to(self, operation_kinds: frozenset[str]) -> bool:
        return not self.operation_kinds or bool(self.operation_kinds & operation_kinds)


_CODE_KINDS = frozenset(
    {
        "modify_existing",
        "delete_existing",
        "new_file",
        "extract_move",
        "insert_in_file",
        "replace_region",
        "refactor",
        "test_only",
        "remediation",
    }
)
_EXISTING_KINDS = frozenset(
    {
        "modify_existing",
        "delete_existing",
        "extract_move",
        "insert_in_file",
        "replace_region",
        "refactor",
        "remediation",
    }
)

QUESTION_RULES: tuple[EngineeringQuestionRule, ...] = (
    EngineeringQuestionRule(
        "entrypoint_surface",
        PacketQuestionCategory.ENTRYPOINT_SURFACE,
        "Which external or boundary-facing entrypoint observes this behavior?",
        ("objective", "goal_ids", "in_scope"),
        _CODE_KINDS,
        waiver_allowed=True,
    ),
    EngineeringQuestionRule(
        "target_selection",
        PacketQuestionCategory.TARGET_SELECTION,
        "Which provider-backed symbols or files are accepted targets, and which candidates were rejected?",
        ("target_policy", "navigation_audit_ids", "target_binding_ids"),
        _CODE_KINDS,
        deterministic_evidence_allowed=True,
    ),
    EngineeringQuestionRule(
        "symbol_contract",
        PacketQuestionCategory.SYMBOL_CONTRACT,
        "What current inputs, outputs, invariants and compatibility constraints govern the accepted symbols?",
        ("target_binding_ids", "invariants", "objective"),
        _EXISTING_KINDS,
    ),
    EngineeringQuestionRule(
        "new_target_rationale",
        PacketQuestionCategory.TARGET_SELECTION,
        "Why is a new file or symbol required instead of reusing an accepted existing target?",
        ("objective", "target_binding_ids", "in_scope"),
        frozenset({"new_file"}),
        required=False,
    ),
    EngineeringQuestionRule(
        "impact",
        PacketQuestionCategory.IMPACT,
        "Which callers, callees, dependencies or lifecycle facts are affected?",
        ("target_binding_ids", "candidate_set_ids", "context_snapshot_ids", "objective"),
        _CODE_KINDS,
        deterministic_evidence_allowed=True,
    ),
    EngineeringQuestionRule(
        "compatibility_and_failure",
        PacketQuestionCategory.SYMBOL_CONTRACT,
        "Which compatibility, failure and fallback behavior must remain observable?",
        ("invariants", "out_of_scope", "completion_criteria"),
        _CODE_KINDS,
        waiver_allowed=True,
    ),
    EngineeringQuestionRule(
        "cleanup",
        PacketQuestionCategory.CLEANUP,
        "Which moved, superseded, duplicated or unused code must be removed or explicitly preserved?",
        ("target_binding_ids", "out_of_scope", "objective"),
        frozenset({"delete_existing", "extract_move", "refactor", "remediation"}),
        waiver_allowed=True,
    ),
    EngineeringQuestionRule(
        "test_evidence",
        PacketQuestionCategory.TEST_EVIDENCE,
        "Which deterministic or live evidence will prove this packet complete?",
        ("completion_criteria", "goal_ids", "invariants"),
        deterministic_evidence_allowed=True,
    ),
    EngineeringQuestionRule(
        "authority_blocker",
        PacketQuestionCategory.AUTHORITY_BLOCKER,
        "Which human or product-authority decision remains unresolved, if any?",
        ("unresolved_questions",),
        required=False,
    ),
)


def applicable_question_rules(
    operation_kinds: Iterable[str], *, target_policy: str, profile: str
) -> tuple[EngineeringQuestionRule, ...]:
    kinds = frozenset(str(item) for item in operation_kinds if str(item))
    if target_policy == "documental_only":
        kinds = frozenset()
    rules = [rule for rule in QUESTION_RULES if rule.applies_to(kinds)]
    if kinds == {"new_file"}:
        # Future files have neither an existing mutation target nor observable
        # pre-execution impact. Their authored paths are the only factual
        # targets until provider execution materializes them.
        rules = [
            rule
            for rule in rules
            if rule.key not in {"target_selection", "impact"}
        ]
    if not kinds:
        rules = [rule for rule in rules if not rule.operation_kinds]
    if profile == "minimal":
        rules = [rule for rule in rules if rule.key not in {"compatibility_and_failure", "cleanup"}]
    return tuple(rules)


def dependency_fingerprint(packet: Mapping[str, object], keys: Iterable[str]) -> str:
    payload = {
        "policy_version": QUESTION_POLICY_VERSION,
        **{key: packet.get(key) for key in sorted(set(keys))},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def question_is_required(
    rule: EngineeringQuestionRule,
    packet: Mapping[str, object],
) -> bool:
    """Return whether canonical packet evidence leaves this question unresolved."""

    if rule.key == "authority_blocker":
        return _has_values(packet, "unresolved_questions")
    if not rule.required:
        return False
    if rule.key == "entrypoint_surface":
        return not (
            _has_values(packet, "goal_ids")
            or _has_values(packet, "in_scope")
        )
    if rule.key == "target_selection":
        return not _has_values(packet, "target_binding_ids")
    if rule.key in {"symbol_contract", "compatibility_and_failure"}:
        return not _has_values(packet, "invariants")
    if rule.key == "impact":
        # Navigation metadata proves that evidence exists, not that impact has
        # been classified. Closure requires an explicit answer and subsequent
        # reconciliation policy.
        return True
    if rule.key == "cleanup":
        return not _has_values(packet, "out_of_scope")
    if rule.key == "test_evidence":
        return not _has_values(packet, "completion_criteria")
    return True


def question_prompt(
    rule: EngineeringQuestionRule,
    packet: Mapping[str, object],
) -> str:
    """Project authority questions verbatim; retain canonical guidance otherwise."""

    if rule.key != "authority_blocker":
        return rule.prompt
    questions = [
        str(item).strip()
        for item in packet.get("unresolved_questions", [])
        if str(item).strip()
    ]
    if not questions:
        return rule.prompt
    return "Authority decisions still unresolved: " + "; ".join(questions)


def _has_values(packet: Mapping[str, object], key: str) -> bool:
    value = packet.get(key)
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(str(item).strip() for item in value)
    return bool(str(value or "").strip())
