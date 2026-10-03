"""Semantic lifecycle policy for model-facing Flower orchestration.

Recipes explain why a lifecycle activity exists, who owns its authority, what
the orchestrator must decide, and when it must stop. Executable mechanics come
from the current interaction frame or one exact operation-contract request.
"""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping


RECIPE_CONTRACT_VERSION = "flow.lifecycle-recipe.v2"


def _recipe(
    name: str,
    label: str,
    *,
    area: str,
    intent: str,
    authority_owner: str,
    authority_boundary: str,
    semantic_decisions: tuple[str, ...],
    evidence: tuple[str, ...],
    stop_conditions: tuple[str, ...],
    escalation_conditions: tuple[str, ...],
    safety_notes: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "contract_version": RECIPE_CONTRACT_VERSION,
        "name": name,
        "label": label,
        "area": area,
        "intent": intent,
        "authority": {
            "owner": authority_owner,
            "boundary": authority_boundary,
        },
        "semantic_decisions": list(semantic_decisions),
        "required_evidence": list(evidence),
        "stop_conditions": list(stop_conditions),
        "escalation_conditions": list(escalation_conditions),
        "safety_notes": list(safety_notes),
        "action_source": (
            "current interaction frame or explicit operation-contract detail"
        ),
    }


_RECIPES: Mapping[str, dict[str, Any]] = MappingProxyType(
    {
        "engineering-bootstrap": _recipe(
            "engineering-bootstrap", "Guide scenarios into a confirmed engineering roadmap",
            area="project_bootstrap",
            intent="Progressively clarify stakeholder intent, author canonical scope and execute the entire confirmed milestone spectrum with honest progress.",
            authority_owner="Stakeholder intent; Flower canonical requirements, Goal Graph and milestones; host investigation/execution",
            authority_boundary="Host correspondence is declared judgment. Human roadmap confirmation authorizes scope execution, not software acceptance. Relevant canonical intent changes require renewed correspondence/confirmation; unassigned or unrelated draft intake does not govern the confirmed scope.",
            semantic_decisions=("What should the software do and show in the next scenario?", "Which intent gaps prevent the next engineering decision?", "Does the derived roadmap reflect the stakeholder's intended spectrum?", "At a concrete boundary, continue within scope or review results for missed intent?"),
            evidence=("fow_bootstrap guidance and selected typed answers", "ordinary canonical requirements/use cases/milestones and correspondence", "derived roadmap fingerprint and explicit human confirmation", "project_progress separates implementation/local verification/deferred authority/acceptance"),
            stop_conditions=("intent mismatch, stale correspondence or confirmation", "missing executable plans for a selected milestone", "capability/evidence boundary prevents completing the spectrum"),
            escalation_conditions=("intended behavior or scope remains unresolved after canonical reread and engineer investigation", "stakeholder explicitly requests architecture participation"),
            safety_notes=("Start with path=guided_engineering on a new or populated project; read guidance. Record only selected governing answers, keep private exploration private.", "Use ordinary canonical authoring, record_correspondence, roadmap with explicit milestone_ids, then confirm_roadmap using the displayed fingerprint and actual human confirmation_reference.", "Prepare accepted external plans/PVP for every confirmed milestone; complete closes initial preparation and hands off TODO execution. It never claims implementation completion.", "At a result checkpoint read fow_handover project_progress, then record_continuation with continue|review, current roadmap/progress fingerprints and the actual human reference.", "Architecture, implementation and reuse are engineer-owned by default. Investigate technical gaps yourself; use examples/consequences to help the stakeholder resolve intent. No arbitrary unit/question-count interruption or automatic model invocation.", "For implementation divergence, reread canonical requirement/Goal/scenario/milestone/change/packet intent, record intent reassessment and use ordinary finding-linked corrective work with regression evidence. New requested behavior requires ordinary intent revision and affected scope confirmation."),
        ),
        "standalone-external-plan": _recipe(
            "standalone-external-plan", "Prepare and consume an offline Flower plan",
            area="packet_lifecycle",
            intent="Close semantic criteria and producer/consumer contracts, then export complete Markdown or read a dependency-ordered TODO for an external coding agent.",
            authority_owner="Flower canonical packet/work-plan lifecycle",
            authority_boundary="The agent owns investigation/code/build/test effects. Flower records declared outcomes; completion, verification and human acceptance are distinct.",
            semantic_decisions=(
                "Which recorded intent, decisions, criteria and unresolved questions govern this packet?",
                "What contract does each producer promise and which declared predecessors do consumers use?",
                "Which checks are evaluable now, and which campaign/Oracle/human obligations are deferred?",
                "Is external_agent mode explicitly selected and the current accepted plan/PVP closed?",
            ),
            evidence=("current accepted packet/work-plan", "stable criterion/unit numbers and bounded implements/provides/requires/verifies declarations", "coherent authority fingerprint", "host-declared outcome/evidence provenance"),
            stop_conditions=("missing ownership, verification intent or predecessor contract", "unresolved intent or stale authority", "conflicting reports need explicit reconciliation", "provider/agent execution mode change lacks explicit authority"),
            escalation_conditions=("intended behavior or scope remains unresolved after canonical reread and engineer investigation", "stakeholder explicitly requests architecture participation", "a concrete capability/evidence limit prevents further autonomous work"),
            safety_notes=(
                "Request fow_external_work exact operation help on demand: upgrade_validation, validation, set_mode, export_plan, todo, report_outcome, reconcile_outcome.",
                "Author units through fow_packet_author with declarations in the same unit payload. Consumer requires references producer_unit_key/contract_name/use, never copies producer clauses.",
                "Export returns an immutable artifact and complete Markdown. The host writes it with file tools; offline edits do not mutate Flower.",
                "After offline execution reconnect, retrieve current authority and report against the original issued fingerprint; stale results remain history.",
                "Full cross-server PVP, CodingCastle compilation/IMPL-67 and paired qualification remain deferred.",
                "The engineer chooses architecture, implementation and reuse, and records technical decisions before closure. Reread canonical intent and reassess semantic findings before ordinary corrective work; never alter agreed intent to justify an implementation defect.",
            ),
        ),
        "portable-associations": _recipe(
            "portable-associations", "Exchange canonical association receipts",
            area="project_bootstrap",
            intent="Move host/project and optional provider associations through strict versioned JSON without restarting the lifecycle plane or host.",
            authority_owner="Flower canonical association and binding services",
            authority_boundary="A receipt is explicit import/export evidence. It cannot configure transport, credentials, commands or repository auditing authority.",
            semantic_decisions=("Which lifecycle project and association purpose are intended?", "Does a changed association have an explicit replacement reason?"),
            evidence=("fow_bindings inspect/export receipts", "already operator-authorized provider route when needed"),
            stop_conditions=("cross-project, unknown contract or unsupported route", "conflicting import lacks replacement reason"),
            escalation_conditions=("operator integration configuration or active shared provider route must change",),
            safety_notes=("Use fow_bindings inspect, export and import. Host association needs no provider.", "Legacy private YAML seeding is a bounded coordinated migration; current explicit ledger bindings win. New standalone profiles contain no project associations."),
        ),
        "host-semantic-assignment": _recipe(
            "host-semantic-assignment", "Perform a bounded semantic assignment",
            area="requirements",
            intent="Prepare durable semantic input, explicitly execute with host or internal model, validate the answer and adopt only through existing lifecycle authority.",
            authority_owner="Flower role contract, shared validator and canonical audit lifecycle",
            authority_boundary="Structural output validation is not proof of semantic truth. Adoption records a validation audit; baseline import and human acceptance are separate.",
            semantic_decisions=("Which supported role and explicit execution mode are required?", "Are supplied input/evidence and allowed references current?", "Does the validated answer leave rejected/needs-review obligations open?"),
            evidence=("fow_semantic inventory", "immutable prepared prompt/output contract and source fingerprint", "actor/executor provenance and validation result"),
            stop_conditions=("unsupported role or missing source/runtime prerequisite", "stale input or invalid/invented identities", "conflicting result or interrupted internal execution"),
            escalation_conditions=("semantic result requires a material human intent decision",),
            safety_notes=("Use inventory -> prepare -> inspect -> submit -> adopt. Host execution survives restart without polling or an internal model.", "execute_internal is explicit on an internal assignment and shares its validator; failure never silently selects a host result.", "Host SRS validation and intention grounding are supported. Grounding takes a strict closed evidence receipt and preserves host-declared provenance/currentness. Host observed-behavior drafting remains unsupported.", "Guided bootstrap uses the approved progressive scenario-first policy; inspect the engineering-bootstrap recipe."),
        ),
        "milestone-planning": _recipe(
            "milestone-planning",
            "Freeze a planned milestone",
            area="milestones",
            intent=(
                "Freeze one bounded requirement and dependency closure without "
                "claiming acceptance before governed evidence exists."
            ),
            authority_owner="Flower milestone lifecycle",
            authority_boundary=(
                "Planning freezes scope; only governed evidence can accept the milestone."
            ),
            semantic_decisions=(
                "Which current requirements and dependencies belong to this milestone?",
                "Are entry, exit, and risk policies explicit enough to freeze scope?",
                "Does any evidence already qualify as governed acceptance evidence?",
            ),
            evidence=(
                "current requirement revisions and source anchors",
                "dependency closure",
                "governed acceptance references when acceptance is requested",
            ),
            stop_conditions=(
                "scope is not bounded enough to freeze",
                "future research is mixed with implementable milestone scope",
                "acceptance is requested from planning-only evidence",
            ),
            escalation_conditions=(
                "a requirement conflict or unresolved dependency changes milestone meaning",
            ),
            safety_notes=(
                "A source or specification reference does not by itself prove acceptance.",
            ),
        ),
        "packet-work-plan-v2": _recipe(
            "packet-work-plan-v2",
            "Author a temporally closed packet",
            area="packet_lifecycle",
            intent=(
                "Translate one accepted change into stable, ordered, independently "
                "reviewable implementation units."
            ),
            authority_owner="Flower packet lifecycle and orchestrator intent",
            authority_boundary=(
                "Flower owns semantic units; the implementation provider owns exact "
                "technical identities and execution."
            ),
            semantic_decisions=(
                "What exact behavior or contract must change?",
                "Which accepted target owns that change?",
                "What ordered implementation actions must be performed there?",
                "Which existing contracts must be reused rather than redeclared?",
                "Which predecessor output must exist first?",
                "What exclusion prevents duplicate, dead, or widened work?",
                "What local observable check proves this unit complete?",
            ),
            evidence=(
                "current readable target or explicit future destination",
                "ordered instructions, checks, constraints, and dependencies",
                "current packet working sheet and unresolved gates",
            ),
            stop_conditions=(
                "an existing target remains ambiguous or ungrounded",
                "instructions or unit checks are incomplete",
                "a construction, risk, or authority gate remains unresolved",
                "the configured provider cannot honor the packet socket contract",
            ),
            escalation_conditions=(
                "the requested change cannot be bounded without revising accepted intent",
            ),
            safety_notes=(
                "Keep provider graph, target, revision, replay, and transport identities out of semantic units.",
                "Objectives provide context but never replace ordered instructions.",
                "Stable unit numbers are never compacted or reused.",
                "Provider receipts travel through structuredContent; never recover packet state by parsing model-facing Markdown.",
            ),
        ),
        "packet-remediation-v2": _recipe(
            "packet-remediation-v2",
            "Turn accepted findings into a successor packet",
            area="assurance",
            intent=(
                "Correct one closed set of current findings through the ordinary packet "
                "lifecycle while preserving their evidence and regression obligations."
            ),
            authority_owner="Flower assurance and packet lifecycle",
            authority_boundary=(
                "Review findings justify correction scope; they do not authorize hidden "
                "provider retries or semantic acceptance."
            ),
            semantic_decisions=(
                "Does rereading current canonical requirement, Goal, scenario, milestone, change and packet intent classify the finding as correction within intent, intent change required or missing clarification?",
                "Which unresolved findings belong to the same governed change?",
                "What correction and regression evidence closes each finding?",
                "Can predecessor scope be reused, or must accepted intent be narrowed?",
                "Is this an in-run technical failure eligible for provider resume, or a reviewed post-run defect requiring a successor packet?",
            ),
            evidence=(
                "current canonical intent context and durable intent reassessment",
                "current finding dispositions and source anchors",
                "predecessor packet relation",
                "required regression evidence",
            ),
            stop_conditions=(
                "a finding is terminal, stale, or belongs to another change",
                "the correction has no observable regression obligation",
                "current output and outcome evidence have not been technically and semantically reviewed",
            ),
            escalation_conditions=(
                "intended behavior or scope remains unresolved after canonical reread and engineer investigation",
                "stakeholder explicitly requests architecture participation",
            ),
            safety_notes=(
                "Remediation is packet purpose and lineage, not a parallel packet schema.",
                "Choose architecture, implementation and reuse as the engineer. A current correction-within-intent reassessment permits ordinary corrective work; requested intent changes require ordinary revision and affected confirmation.",
                "Resume only an unreviewed in-run provider failure; use a successor packet for a reviewed post-run defect.",
            ),
        ),
        "project-state-recovery-v1": _recipe(
            "project-state-recovery-v1",
            "Recover current project authority",
            area="handover",
            intent=(
                "Recover one coherent current project boundary after start, reconnect, "
                "compaction, or orchestrator handoff."
            ),
            authority_owner="Flower handover and canonical lifecycle stores",
            authority_boundary=(
                "The snapshot is read-only and cannot manufacture progress, acceptance, or intent."
            ),
            semantic_decisions=(
                "Does the single current gate require a semantic decision or more evidence?",
                "Which referenced detail is necessary for that decision?",
            ),
            evidence=(
                "current project-state snapshot and completeness report",
                "only the detail references required by the current gate",
            ),
            stop_conditions=(
                "required authority or evidence is unavailable",
                "the retained snapshot is no longer current",
                "the next gate requires a decision the orchestrator cannot authorize",
            ),
            escalation_conditions=(
                "canonical sources disagree about the current lifecycle boundary",
            ),
            safety_notes=(
                "Follow exactly one current gate and refresh after every material lifecycle mutation.",
            ),
        ),
        "closed-packet-workflow-v1": _recipe(
            "closed-packet-workflow-v1",
            "Drive one packet to a reviewable boundary",
            area="packet_lifecycle",
            intent=(
                "Author, reconcile, execute, and observe one packet until a semantic, "
                "provider, review, or terminal boundary is reached."
            ),
            authority_owner="Flower packet lifecycle with configured provider",
            authority_boundary=(
                "Flower advances semantic state; provider execution remains provider-owned "
                "and workspace acceptance remains explicit."
            ),
            semantic_decisions=(
                "Is the work plan complete and accepted for execution?",
                "Which current semantic or target gate must be answered?",
                "What disposition does the current workspace review support?",
            ),
            evidence=(
                "accepted packet plan",
                "current provider observation or terminal receipt",
                "current workspace review evidence",
            ),
            stop_conditions=(
                "instructions, engineering answers, or risk authority are incomplete",
                "the provider is unavailable, unbound, or contract-incompatible",
                "workspace output requires semantic review",
            ),
            escalation_conditions=(
                "technical output conflicts with accepted packet intent",
            ),
            safety_notes=(
                "Observe admitted asynchronous work; do not reproduce provider identities or retry choreography.",
                "Use the provider's structuredContent receipt for machine reconciliation; its Markdown projection is for model reading only.",
            ),
        ),
        "implementation-provider-binding": _recipe(
            "implementation-provider-binding",
            "Bind an implementation provider",
            area="project_bootstrap",
            intent=(
                "Bind one Flower project to an explicitly configured provider scope without "
                "transferring lifecycle ownership."
            ),
            authority_owner="Flower Project Context and operator configuration",
            authority_boundary=(
                "Flower stores the binding; the provider retains its technical context and identities."
            ),
            semantic_decisions=(
                "Which configured provider kind and scope belong to this project?",
                "Which authorized surfaces are needed?",
                "Does replacing an existing binding have an explicit reason?",
            ),
            evidence=(
                "configured provider inventory",
                "current binding state",
                "explicit replacement rationale when applicable",
            ),
            stop_conditions=(
                "the provider kind or surface is not configured",
                "the provider scope is ambiguous",
                "a conflicting binding exists without replacement authority",
            ),
            escalation_conditions=(
                "provider reachability cannot establish identity or contract compatibility",
            ),
            safety_notes=(
                "Provider availability never implies a project choice or authority transfer.",
                "Provider contract negotiation uses structuredContent and fails closed when that channel is absent.",
            ),
        ),
        "packet-evidence-reconciliation": _recipe(
            "packet-evidence-reconciliation",
            "Ground packet targets in provider evidence",
            area="packet_lifecycle",
            intent=(
                "Resolve semantic target descriptions against current provider evidence "
                "without exposing provider-owned identities as Flower authoring work."
            ),
            authority_owner="Flower semantic packet and implementation provider evidence",
            authority_boundary=(
                "The orchestrator selects readable evidence; the provider resolves and "
                "retains exact technical identity."
            ),
            semantic_decisions=(
                "Which readable candidate is the intended mutation target?",
                "Which candidates are context only?",
                "Is evidence complete enough to accept the unit plan?",
            ),
            evidence=(
                "current provider candidate set",
                "provider completeness and freshness receipt",
                "packet-relevant residual dispositions",
            ),
            stop_conditions=(
                "no candidate matches the intended target",
                "provider evidence is incomplete, stale, or contradicted",
                "a semantic residual remains unresolved",
            ),
            escalation_conditions=(
                "target choice would require inventing or widening accepted intent",
            ),
            safety_notes=(
                "Readable ordinals are action-scoped choices, never durable packet data.",
                "Flower consumes provider structuredContent directly and never parses provider Markdown as JSON.",
            ),
        ),
        "workspace-review-continuation-v1": _recipe(
            "workspace-review-continuation-v1",
            "Disposition a provider workspace review",
            area="assurance",
            intent=(
                "Record one bounded review of the current provider workspace and route "
                "its disposition to verification, remediation, or blockage."
            ),
            authority_owner="Orchestrator review and Flower assurance",
            authority_boundary=(
                "Provider evidence identifies the candidate; Flower owns finding lineage "
                "and the orchestrator owns semantic disposition."
            ),
            semantic_decisions=(
                "Is review coverage complete for the current candidate?",
                "Is the candidate approved, finding-bearing, or rejected?",
                "What bounded correction and scope does each finding require?",
            ),
            evidence=(
                "current workspace candidate and review reference",
                "reviewed targets and evidence references",
                "typed findings or current same-packet finding identities",
            ),
            stop_conditions=(
                "the review does not address the current candidate",
                "complete coverage lacks required evidence",
                "approval is partial or accompanied by findings",
            ),
            escalation_conditions=(
                "review evidence cannot distinguish a technical defect from changed intent",
            ),
            safety_notes=(
                "Exact receipt fields come from operation help, not from memorized recipe prose.",
                "Model-facing review text and provider-neutral structured evidence are separate projections of the same current receipt.",
            ),
        ),
        "qualified-campaign-workflow-v1": _recipe(
            "qualified-campaign-workflow-v1",
            "Build and close a qualified campaign",
            area="campaigns",
            intent=(
                "Define behavioral obligations and oracles, materialize tests through an "
                "authorized provider, and close only from current attested evidence."
            ),
            authority_owner="Flower campaign lifecycle and orchestrator oracle authority",
            authority_boundary=(
                "Flower owns behavioral meaning and acceptance; the provider owns technical "
                "materialization and execution."
            ),
            semantic_decisions=(
                "Which governed change, behavior, and obligation does the campaign cover?",
                "Is the oracle complete and who attests its meaning?",
                "Should source-authored or typed-oracle materialization be used?",
                "Does current evidence authorize promotion or require remediation?",
            ),
            evidence=(
                "closed campaign scope, cases, obligations, and oracle answers",
                "current materialization attestation",
                "authoritative deterministic and live run evidence",
            ),
            stop_conditions=(
                "scope, obligation, binding, or oracle meaning is unresolved",
                "evidence is stale, incomplete, flaky, or environment-blocked",
                "authoritative product failure requires packet remediation",
                "the test provider is unavailable or rejects the command",
            ),
            escalation_conditions=(
                "oracle meaning or acceptance authority cannot be established deterministically",
            ),
            safety_notes=(
                "A compiling but unattested test cannot establish authoritative product failure.",
                "Provider identities and raw internal representations remain behind the provider boundary.",
                "Campaign provider evidence is accepted only from the structured channel; readable Markdown is not a transport contract.",
            ),
        ),
    }
)

_RECIPE_ORDER = (
    "engineering-bootstrap",
    "project-state-recovery-v1",
    "standalone-external-plan",
    "portable-associations",
    "host-semantic-assignment",
    "milestone-planning",
    "packet-work-plan-v2",
    "closed-packet-workflow-v1",
    "packet-evidence-reconciliation",
    "packet-remediation-v2",
    "workspace-review-continuation-v1",
    "implementation-provider-binding",
    "qualified-campaign-workflow-v1",
)

if set(_RECIPE_ORDER) != set(_RECIPES):
    raise RuntimeError("recipe order and semantic recipe registry diverged")


def get_recipe(name: str) -> dict[str, Any] | None:
    recipe = _RECIPES.get(str(name or "").strip())
    return deepcopy(recipe) if recipe is not None else None


def all_recipes() -> list[dict[str, Any]]:
    return [deepcopy(_RECIPES[name]) for name in _RECIPE_ORDER]


def list_recipes() -> list[dict[str, Any]]:
    return [
        {
            "name": recipe["name"],
            "label": recipe["label"],
            "area": recipe["area"],
            "intent": recipe["intent"],
        }
        for recipe in (_RECIPES[name] for name in _RECIPE_ORDER)
    ]


def recipe_names() -> tuple[str, ...]:
    return _RECIPE_ORDER


__all__ = [
    "RECIPE_CONTRACT_VERSION",
    "all_recipes",
    "get_recipe",
    "list_recipes",
    "recipe_names",
]
