"""Authority-gated bootstrap and bounded code-first behavior derivation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from flow_of_work_mcp.core.domain import (
    BaselineImportPlan,
    ImportedRequirement,
    ImportedSequence,
    ImportedUseCase,
    RequirementDraft,
    SequenceDraft,
    SourceAnchor,
    UseCaseDraft,
)
from flow_of_work_mcp.core.domain.bootstrap import (
    BootstrapBehaviorSnapshot,
    BootstrapBehaviorSnapshotRequest,
    BootstrapPath,
)
from flow_of_work_mcp.core.errors import (
    BootstrapBlockedError,
    ImplementationProviderError,
    InputValidationError,
    ModelGatewayError,
)
from flow_of_work_mcp.core.ports import (
    BaselineImportRepository,
    BootstrapBehaviorProvider,
    BootstrapRepository,
    ModelGateway,
    ModelRequest,
)
from flow_of_work_mcp.application.lifecycle_control import LifecycleControlService


_CODE_CAPABILITY = "bootstrap-behavior-snapshot-v1"
_MAX_DRAFT_ITEMS = 32
_MAX_TEXT = 1_000


@dataclass(frozen=True)
class BootstrapBehaviorDraftPolicy:
    """Hard bounds for a code-derived proposal, not product discovery."""

    max_input_chars: int = 24_000
    max_output_tokens: int = 2_000
    prompt_version: str = "bootstrap-behavior-draft-v1"

    def __post_init__(self) -> None:
        if self.max_input_chars <= 0 or self.max_output_tokens <= 0:
            raise ValueError("bootstrap behavior draft bounds must be positive")


class BootstrapBehaviorDraftService:
    """Transforms closed structural evidence into a non-canonical behavior draft."""

    def __init__(self, gateway: ModelGateway, policy: BootstrapBehaviorDraftPolicy | None = None) -> None:
        self._gateway = gateway
        self._policy = policy or BootstrapBehaviorDraftPolicy()

    def derive(self, snapshot: BootstrapBehaviorSnapshot) -> Mapping[str, object]:
        if not snapshot.anchors:
            raise BootstrapBlockedError("bootstrap_behavior_insufficient_evidence")
        scope, input_truncated = self._scope(snapshot)
        request = ModelRequest(
            role_id="bootstrap_behavior_deriver",
            messages=(
                {
                    "role": "system",
                    "content": (
                        "Derive current observed software behavior from the closed evidence set. "
                        "Return JSON only with use_cases, sequences, requirements and open_questions. "
                        "Every candidate must cite one or more supplied evidence_anchor_ids. "
                        "Use IDs UC-OBS-NNN, SQ-OBS-NNN and FR-OBS-NNN or NFR-OBS-NNN. "
                        "Do not propose future features, a roadmap, a milestone, fallback behavior or "
                        "acceptance policy. Do not invent anchor IDs or source paths."
                    ),
                },
                {"role": "user", "content": json.dumps(scope, sort_keys=True)},
            ),
            output_schema={
                "type": "object",
                "required": ["use_cases", "sequences", "requirements", "open_questions"],
            },
            max_output_tokens=self._policy.max_output_tokens,
            request_id=f"bootstrap:{snapshot.project_id}:{snapshot.source_revision}",
        )
        try:
            result = self._gateway.invoke(request)
        except ModelGatewayError as exc:
            raise BootstrapBlockedError(f"bootstrap_behavior_model_{exc.terminal_reason}") from exc
        if result.terminal_reason != "completed":
            raise BootstrapBlockedError(f"bootstrap_behavior_model_{result.terminal_reason}")
        parsed = self._parse(result.structured_output, snapshot)
        return {
            "draft_version": "bootstrap-behavior-draft-v1",
            "provider_id": snapshot.provider_id,
            "scope_id": snapshot.scope_id,
            "source_revision": snapshot.source_revision,
            "surfaces": list(snapshot.surfaces),
            "input_truncated": input_truncated or snapshot.truncated,
            "model": result.model,
            "usage": dict(result.usage),
            "usage_derived_fields": list(result.usage_derived_fields),
            "transport": dict(result.transport),
            "prompt_version": self._policy.prompt_version,
            **parsed,
        }

    def _scope(self, snapshot: BootstrapBehaviorSnapshot) -> tuple[dict[str, object], bool]:
        remaining = self._policy.max_input_chars
        anchors: list[dict[str, object]] = []
        truncated = False
        for anchor in snapshot.anchors:
            rendered = {
                "anchor_id": anchor.anchor_id,
                "kind": anchor.kind,
                "label": anchor.label,
                "summary": anchor.summary,
                "source_path": anchor.source_path,
                "evidence_ids": list(anchor.evidence_ids),
                "dependency_anchor_ids": list(anchor.dependency_anchor_ids),
                "test_evidence_ids": list(anchor.test_evidence_ids),
                "metadata": dict(anchor.metadata),
            }
            encoded = json.dumps(rendered, sort_keys=True)
            if len(encoded) > remaining:
                truncated = True
                break
            anchors.append(rendered)
            remaining -= len(encoded)
        if not anchors:
            raise BootstrapBlockedError("bootstrap_behavior_input_budget_exhausted")
        return (
            {
                "contract_version": _CODE_CAPABILITY,
                "project_id": snapshot.project_id,
                "provider_id": snapshot.provider_id,
                "scope_id": snapshot.scope_id,
                "source_revision": snapshot.source_revision,
                "surfaces": list(snapshot.surfaces),
                "anchors": anchors,
            },
            truncated,
        )

    @staticmethod
    def _parse(
        payload: Mapping[str, Any] | None,
        snapshot: BootstrapBehaviorSnapshot,
    ) -> Mapping[str, object]:
        if not isinstance(payload, Mapping):
            raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
        anchor_ids = {anchor.anchor_id for anchor in snapshot.anchors}
        use_cases = _parse_use_cases(payload.get("use_cases"), anchor_ids)
        known_use_cases = {item["source_id"] for item in use_cases}
        sequences = _parse_sequences(payload.get("sequences"), anchor_ids, known_use_cases)
        requirements = _parse_requirements(payload.get("requirements"), anchor_ids)
        open_questions = _parse_text_list(payload.get("open_questions"), "open_questions", limit=_MAX_DRAFT_ITEMS)
        if not use_cases or not sequences or not requirements:
            raise BootstrapBlockedError("bootstrap_behavior_shape_incomplete")
        return {
            "use_cases": use_cases,
            "sequences": sequences,
            "requirements": requirements,
            "open_questions": open_questions,
        }


class BootstrapService:
    """Coordinates durable bootstrap state without assuming a specific provider."""

    def __init__(
        self,
        *,
        repository: BootstrapRepository,
        baseline_repository: BaselineImportRepository,
        lifecycle: LifecycleControlService,
        import_root: str | Path,
        behavior_provider: BootstrapBehaviorProvider | None = None,
        model_gateway: ModelGateway | None = None,
    ) -> None:
        self._repository = repository
        self._baseline_repository = baseline_repository
        self._lifecycle = lifecycle
        self._import_root = Path(import_root).expanduser().resolve()
        self._behavior_provider = behavior_provider
        self._drafter = (
            BootstrapBehaviorDraftService(model_gateway) if model_gateway is not None else None
        )

    def start(
        self,
        project_id: str,
        *,
        project_name: str,
        path: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        try:
            selected = BootstrapPath(path)
        except ValueError as exc:
            accepted = tuple(item.value for item in BootstrapPath)
            raise InputValidationError(
                "bootstrap path is a workflow mode, not a filesystem path",
                field="path",
                received_value=path,
                accepted_values=accepted,
            ) from exc
        return self._repository.start_bootstrap(
            project_id,
            project_name=project_name,
            path=selected.value,
            actor=actor,
            request_id=request_id,
        )

    def state(self, project_id: str, bootstrap_id: str) -> Mapping[str, object]:
        return self._repository.bootstrap_state(project_id, bootstrap_id)

    def resume(
        self, project_id: str, bootstrap_id: str, *, actor: str, request_id: str = ""
    ) -> Mapping[str, object]:
        return self._repository.resume_bootstrap(
            project_id, bootstrap_id, actor=actor, request_id=request_id
        )

    def record_intake(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        intake: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        _bounded_mapping(intake, "intake")
        return self._repository.record_bootstrap_intake(
            project_id, bootstrap_id, intake=intake, actor=actor, request_id=request_id
        )

    def record_contradiction(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        contradiction: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        _bounded_mapping(contradiction, "contradiction")
        return self._repository.record_bootstrap_contradiction(
            project_id,
            bootstrap_id,
            contradiction=contradiction,
            actor=actor,
            request_id=request_id,
        )

    def confirm_intake(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        confirmation_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        state = self.state(project_id, bootstrap_id)
        path = str(state["path"])
        intake = _mapping(state.get("intake"), "intake")
        _validate_intake(path, intake)
        self._validate_source_scope(path, intake)
        return self._repository.confirm_bootstrap_intake(
            project_id,
            bootstrap_id,
            confirmation_reference=_required_short(confirmation_reference, "confirmation_reference"),
            actor=actor,
            request_id=request_id,
        )

    def derive_behavior(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        state = self.state(project_id, bootstrap_id)
        if str(state.get("path")) != BootstrapPath.CODE_IMPORT.value:
            raise BootstrapBlockedError("bootstrap_behavior_derivation_requires_code_import")
        if str(state.get("stage")) != "ready_for_derivation":
            raise BootstrapBlockedError("bootstrap_behavior_derivation_not_ready")
        if self._behavior_provider is None:
            raise BootstrapBlockedError("bootstrap_behavior_provider_unconfigured")
        if self._drafter is None:
            raise BootstrapBlockedError("bootstrap_behavior_model_unconfigured")
        intake = _mapping(state.get("intake"), "intake")
        snapshot_request = BootstrapBehaviorSnapshotRequest(
            project_id=project_id,
            scope_id=_required_short(str(intake.get("provider_scope_id") or ""), "provider_scope_id"),
            source_revision=_required_short(str(intake.get("source_revision") or ""), "source_revision"),
            surfaces=_string_tuple(intake.get("surfaces"), "surfaces"),
            max_anchors=int(intake.get("max_anchors", 64)),
        )
        try:
            snapshot = self._behavior_provider.snapshot(snapshot_request)
        except ImplementationProviderError as exc:
            self._repository.mark_bootstrap_blocked(
                project_id,
                bootstrap_id,
                reason=exc.terminal_reason if hasattr(exc, "terminal_reason") else "bootstrap_behavior_provider_unavailable",
                actor=actor,
                request_id=request_id,
            )
            raise BootstrapBlockedError(
                getattr(exc, "terminal_reason", "bootstrap_behavior_provider_unavailable")
            ) from exc
        if snapshot.project_id != project_id or snapshot.scope_id != snapshot_request.scope_id:
            self._block_derivation(
                project_id,
                bootstrap_id,
                reason="bootstrap_behavior_provider_binding_mismatch",
                actor=actor,
                request_id=request_id,
            )
            raise BootstrapBlockedError("bootstrap_behavior_provider_binding_mismatch")
        if snapshot.provider_id != str(intake.get("provider_target") or ""):
            self._block_derivation(
                project_id,
                bootstrap_id,
                reason="bootstrap_behavior_provider_target_mismatch",
                actor=actor,
                request_id=request_id,
            )
            raise BootstrapBlockedError("bootstrap_behavior_provider_target_mismatch")
        if snapshot.source_revision != snapshot_request.source_revision:
            self._block_derivation(
                project_id,
                bootstrap_id,
                reason="bootstrap_behavior_provider_revision_mismatch",
                actor=actor,
                request_id=request_id,
            )
            raise BootstrapBlockedError("bootstrap_behavior_provider_revision_mismatch")
        if snapshot.surfaces != snapshot_request.surfaces:
            self._block_derivation(
                project_id,
                bootstrap_id,
                reason="bootstrap_behavior_provider_surfaces_mismatch",
                actor=actor,
                request_id=request_id,
            )
            raise BootstrapBlockedError("bootstrap_behavior_provider_surfaces_mismatch")
        try:
            draft = self._drafter.derive(snapshot)
        except BootstrapBlockedError as exc:
            self._repository.mark_bootstrap_blocked(
                project_id, bootstrap_id, reason=exc.reason, actor=actor, request_id=request_id
            )
            raise
        return self._repository.record_bootstrap_behavior_draft(
            project_id, bootstrap_id, draft=draft, actor=actor, request_id=request_id
        )

    def complete(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        completion_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        state = self.state(project_id, bootstrap_id)
        path = str(state.get("path") or "")
        reference = _required_short(completion_reference, "completion_reference")
        if path == BootstrapPath.GUIDED_ENGINEERING.value:
            raise BootstrapBlockedError("guided_bootstrap_requires_guided_complete")
        if path == BootstrapPath.CODE_IMPORT.value:
            if str(state.get("stage")) != "awaiting_authority_acceptance":
                raise BootstrapBlockedError("bootstrap_behavior_acceptance_not_ready")
            draft = _mapping(state.get("behavior_draft"), "behavior_draft")
            baseline = self._baseline_repository.import_baseline(
                self._baseline_plan(project_id, draft),
                actor=actor,
                # A baseline may commit immediately before process interruption.
                # The bootstrap identity, rather than a caller retry id, makes
                # the later completion retry replay that same canonical import.
                request_id=f"bootstrap:{bootstrap_id}:code-baseline",
            )
            completed = self._repository.complete_bootstrap(
                project_id,
                bootstrap_id,
                completion_reference=reference,
                handoff=self._handoff(project_id, bootstrap_id=bootstrap_id, path=path),
                actor=actor,
                request_id=request_id,
            )
            return {**dict(completed), "baseline": dict(baseline)}
        return self._repository.complete_bootstrap(
            project_id,
            bootstrap_id,
            completion_reference=reference,
            handoff=self._handoff(project_id, bootstrap_id=bootstrap_id, path=path),
            actor=actor,
            request_id=request_id,
        )

    def cancel(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.cancel_bootstrap(
            project_id,
            bootstrap_id,
            reason=_required_short(reason, "reason"),
            actor=actor,
            request_id=request_id,
        )

    @staticmethod
    def _baseline_plan(project_id: str, draft: Mapping[str, object]) -> BaselineImportPlan:
        provider_id = _required_short(str(draft.get("provider_id") or ""), "provider_id")
        revision = _required_short(str(draft.get("source_revision") or ""), "source_revision")
        content = json.dumps(draft, sort_keys=True, separators=(",", ":"))
        anchor_path = f"provider://{provider_id}/{revision}"
        requirements = tuple(
            ImportedRequirement(
                source_id=str(item["source_id"]),
                draft=RequirementDraft(
                    title=str(item["title"]),
                    statement=str(item["statement"]),
                    category=str(item["category"]),
                    rationale="Observed behavior accepted through code-first bootstrap.",
                    source_anchor=_anchor_text(anchor_path, item),
                ),
                source_anchor=_anchor(anchor_path, item),
            )
            for item in _list(draft.get("requirements"), "requirements")
        )
        use_cases = tuple(
            ImportedUseCase(
                source_id=str(item["source_id"]),
                draft=UseCaseDraft(
                    title=str(item["title"]),
                    actor=str(item["actor"]),
                    objective=str(item["objective"]),
                    observable_outcome=str(item["observable_outcome"]),
                    preconditions=tuple(item["preconditions"]),
                    postconditions=tuple(item["postconditions"]),
                    invariants=tuple(item["invariants"]),
                    source_anchor=_anchor(anchor_path, item),
                ),
            )
            for item in _list(draft.get("use_cases"), "use_cases")
        )
        sequences = tuple(
            ImportedSequence(
                source_id=str(item["source_id"]),
                draft=SequenceDraft(
                    title=str(item["title"]),
                    participants=tuple(item["participants"]),
                    normal_steps=tuple(item["normal_steps"]),
                    expected_effects=tuple(item["expected_effects"]),
                    alternate_steps=tuple(item["alternate_steps"]),
                    failure_steps=tuple(item["failure_steps"]),
                    source_anchor=_anchor(anchor_path, item),
                ),
                related_use_case_source_id=str(item["related_use_case_source_id"]),
            )
            for item in _list(draft.get("sequences"), "sequences")
        )
        return BaselineImportPlan(
            project_id=project_id,
            source_path=anchor_path,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            profile_id="flow-code-bootstrap-v1",
            profile_version="1.0",
            requirements=requirements,
            use_cases=use_cases,
            sequences=sequences,
            origin="derived_from_code",
        )

    def _handoff(
        self, project_id: str, *, bootstrap_id: str, path: str
    ) -> Mapping[str, object]:
        actions = []
        for action in self._lifecycle.what_next(project_id):
            value = asdict(action)
            value["kind"] = action.kind.value
            value["execution_class"] = action.execution_class.value
            actions.append(value)
        if path == BootstrapPath.REQUIREMENTS_CREATION.value:
            actions.insert(
                0,
                {
                    "action_id": f"bootstrap:{bootstrap_id}:draft-requirements",
                    "kind": "draft_requirements",
                    "execution_class": "governed_decision",
                    "priority": 10,
                    "rationale": "human-authority intent requires a structured requirements or SRS draft",
                    "requirement_ids": [],
                    "goal_node_ids": [],
                    "candidate_ids": [],
                    "milestone_ids": [],
                    "audit_ids": [],
                    "automatic_eligible": False,
                },
            )
        return {"scope_id": "project-default", "actions": actions}

    def _validate_source_scope(self, path: str, intake: Mapping[str, object]) -> None:
        if path != BootstrapPath.REQUIREMENTS_IMPORT.value:
            return
        source = Path(str(intake.get("source_path") or "")).expanduser().resolve()
        try:
            source.relative_to(self._import_root)
        except ValueError as exc:
            raise BootstrapBlockedError("bootstrap_source_outside_import_root") from exc

    def _block_derivation(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str,
    ) -> None:
        self._repository.mark_bootstrap_blocked(
            project_id,
            bootstrap_id,
            reason=reason,
            actor=actor,
            request_id=request_id,
        )


def _parse_use_cases(value: object, anchor_ids: set[str]) -> list[dict[str, object]]:
    items = _list(value, "use_cases")
    parsed: list[dict[str, object]] = []
    for item in items:
        source_id = _required_short(str(item.get("source_id") or ""), "use_case.source_id")
        if not source_id.startswith("UC-OBS-"):
            raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
        parsed.append(
            {
                "source_id": source_id,
                "title": _required_short(str(item.get("title") or ""), "use_case.title"),
                "actor": _required_short(str(item.get("actor") or ""), "use_case.actor"),
                "objective": _required_short(str(item.get("objective") or ""), "use_case.objective"),
                "observable_outcome": _required_short(
                    str(item.get("observable_outcome") or ""), "use_case.observable_outcome"
                ),
                "preconditions": _parse_text_list(item.get("preconditions"), "use_case.preconditions"),
                "postconditions": _parse_text_list(item.get("postconditions"), "use_case.postconditions"),
                "invariants": _parse_text_list(item.get("invariants"), "use_case.invariants"),
                "evidence_anchor_ids": _parse_anchor_ids(item.get("evidence_anchor_ids"), anchor_ids),
            }
        )
    _unique_ids(parsed)
    return parsed


def _parse_sequences(
    value: object, anchor_ids: set[str], known_use_cases: set[str]
) -> list[dict[str, object]]:
    items = _list(value, "sequences")
    parsed: list[dict[str, object]] = []
    for item in items:
        source_id = _required_short(str(item.get("source_id") or ""), "sequence.source_id")
        related = _required_short(
            str(item.get("related_use_case_source_id") or ""), "sequence.related_use_case_source_id"
        )
        if not source_id.startswith("SQ-OBS-") or related not in known_use_cases:
            raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
        parsed.append(
            {
                "source_id": source_id,
                "title": _required_short(str(item.get("title") or ""), "sequence.title"),
                "related_use_case_source_id": related,
                "participants": _parse_text_list(item.get("participants"), "sequence.participants", required=True),
                "normal_steps": _parse_text_list(item.get("normal_steps"), "sequence.normal_steps", required=True),
                "expected_effects": _parse_text_list(item.get("expected_effects"), "sequence.expected_effects", required=True),
                "alternate_steps": _parse_text_list(item.get("alternate_steps"), "sequence.alternate_steps"),
                "failure_steps": _parse_text_list(item.get("failure_steps"), "sequence.failure_steps"),
                "evidence_anchor_ids": _parse_anchor_ids(item.get("evidence_anchor_ids"), anchor_ids),
            }
        )
    _unique_ids(parsed)
    return parsed


def _parse_requirements(value: object, anchor_ids: set[str]) -> list[dict[str, object]]:
    items = _list(value, "requirements")
    parsed: list[dict[str, object]] = []
    for item in items:
        source_id = _required_short(str(item.get("source_id") or ""), "requirement.source_id")
        category = str(item.get("category") or "").strip()
        if not source_id.startswith(("FR-OBS-", "NFR-OBS-")) or category not in {
            "functional",
            "non_functional",
        }:
            raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
        parsed.append(
            {
                "source_id": source_id,
                "title": _required_short(str(item.get("title") or ""), "requirement.title"),
                "statement": _required_short(str(item.get("statement") or ""), "requirement.statement"),
                "category": category,
                "evidence_anchor_ids": _parse_anchor_ids(item.get("evidence_anchor_ids"), anchor_ids),
            }
        )
    _unique_ids(parsed)
    return parsed


def _parse_anchor_ids(value: object, allowed: set[str]) -> list[str]:
    anchors = _parse_text_list(value, "evidence_anchor_ids", required=True)
    if any(anchor not in allowed for anchor in anchors):
        raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
    return anchors


def _parse_text_list(
    value: object, field: str, *, required: bool = False, limit: int = 16
) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
    parsed = [_required_short(str(item or ""), field) for item in value]
    if len(set(parsed)) != len(parsed) or (required and not parsed):
        raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
    return parsed


def _list(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not value or len(value) > _MAX_DRAFT_ITEMS:
        raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
    if any(not isinstance(item, Mapping) for item in value):
        raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")
    return [dict(item) for item in value]


def _unique_ids(items: list[Mapping[str, object]]) -> None:
    ids = [str(item["source_id"]) for item in items]
    if len(set(ids)) != len(ids):
        raise BootstrapBlockedError("bootstrap_behavior_model_output_invalid")


def _required_short(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > _MAX_TEXT:
        raise ValueError(f"{field} is invalid")
    return text


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    parsed = tuple(_required_short(str(item or ""), field) for item in value)
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{field} values must be unique")
    return parsed


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BootstrapBlockedError(f"bootstrap_{field}_missing")
    return dict(value)


def _bounded_mapping(value: Mapping[str, object], field: str) -> None:
    if len(value) > 32:
        raise ValueError(f"{field} exceeds 32 fields")
    if any(not isinstance(key, str) or not key or len(key) > 128 for key in value):
        raise ValueError(f"{field} contains an invalid key")
    try:
        rendered = json.dumps(dict(value), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON serializable") from exc
    if len(rendered) > 16_000:
        raise ValueError(f"{field} exceeds 16000 characters")


def _validate_intake(path: str, intake: Mapping[str, object]) -> None:
    common = ("source_identity", "source_ownership")
    required_by_path = {
        BootstrapPath.REQUIREMENTS_IMPORT.value: (*common, "source_path", "standard_profile"),
        BootstrapPath.REQUIREMENTS_CREATION.value: (*common, "product_intent", "standard_profile"),
        BootstrapPath.CODE_IMPORT.value: (
            *common,
            "provider_scope_id",
            "provider_target",
            "source_revision",
            "surfaces",
            "integration_intent",
            "source_authority",
            "analysis_depth",
            "required_output",
            "stop_condition",
            "required_provider_capability",
        ),
    }
    required = required_by_path.get(path)
    if required is None:
        accepted = tuple(item.value for item in BootstrapPath)
        raise InputValidationError(
            "bootstrap path is a workflow mode, not a filesystem path",
            field="path",
            received_value=path,
            accepted_values=accepted,
        )
    for field in required:
        try:
            if field == "surfaces":
                _string_tuple(intake.get(field), field)
            elif field == "required_provider_capability":
                if _required_short(str(intake.get(field) or ""), field) != _CODE_CAPABILITY:
                    raise ValueError("code bootstrap requires bootstrap-behavior-snapshot-v1")
            else:
                _required_short(str(intake.get(field) or ""), field)
        except ValueError as exc:
            raise BootstrapBlockedError(f"bootstrap_intake_missing_or_invalid_{field}") from exc
    if "max_anchors" in intake:
        try:
            max_anchors = int(intake["max_anchors"])
        except (TypeError, ValueError) as exc:
            raise BootstrapBlockedError("bootstrap_intake_missing_or_invalid_max_anchors") from exc
        if not 1 <= max_anchors <= 128:
            raise BootstrapBlockedError("bootstrap_intake_missing_or_invalid_max_anchors")


def _anchor(source_path: str, item: Mapping[str, object]) -> SourceAnchor:
    anchor_ids = _parse_text_list(item.get("evidence_anchor_ids"), "evidence_anchor_ids", required=True)
    return SourceAnchor(
        source_path=source_path,
        line_start=1,
        line_end=1,
        label="|".join(anchor_ids),
    )


def _anchor_text(source_path: str, item: Mapping[str, object]) -> str:
    return f"{source_path}#{_anchor(source_path, item).label}"
