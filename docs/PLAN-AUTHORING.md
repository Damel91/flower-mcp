# Flower plan authoring repair descriptor v1

**Status:** Flower 0.7.6 public reference
**Scope:** additive observation metadata and ordinary existing plan-authoring operations

## Scope and invariants
An open PVP holds affected repository effects; engineering investigation and
ordinary authoring continue within confirmed intent. Neither a hint nor an
accepted plan invents evidence or human acceptance. Product intent/scope missing
after investigation requires clarification; technical realization is engineer-owned.
PVP derivation, gap order, fingerprint, gates and mutation CAS remain unchanged.
No plan/criterion/patch is generated. Existing next_gate tool/operation read
navigation remains intact; consumers may prefer its repair descriptor for authoring
help without treating it as an executable command.

## Additive shape
For active snapshots with known declaration gaps, next_gate.repair contains:
- contract_version: flow.plan-authoring-repair.v1
- ready_to_call: false; execution_allowed: false
- authoring_scope: confirmed_intent_only
- operation: {tool, operation, arguments}, containing existing route, canonical
  project_id/change_id/packet_id, operation and current expected_spec_revision/
  expected_plan_revision. client_unit_key only when known exactly from projection.
- required_input: missing semantic inputs plus actor/request_id; client_unit_key
  when no target can be determined from the recorded gap.
- help_route: fow_capabilities arguments view=operation, operation_tool and
  operation_name matching the suggested existing operation.
- inspection_route: exact scoped fow_external_work validation detail=full.
- obligation: the selected existing gap, unchanged. It can differ from next_gap
  only when work_plan_not_accepted precedes a known repairable declaration gap.
- guidance: bounded prose explaining engineering choice and preservation obligations.
This object is a descriptor, never an authority mutation or ready-to-call payload.

## Bounded routing
unit_check_verification_missing selects revise_unit for gap.unit_key.
criterion_owner_missing/verification_intent_missing suggest revise_unit without
selecting an owner; engineer chooses the appropriate unit after inspecting current
criteria/plan. planned_contract_missing suggests revise_unit without a selected unit:
the producer may be incomplete OR the consumer may name the wrong contract. Engineer
chooses the correct side; presence of a producer is not proof its declaration is wrong.
contract_not_in_dependency_closure suggests revise_unit for the consumer and explains
the choice between a corrected requires declaration and explicit set_dependencies
with its complete list, never an automatically added edge.

When next_gap is work_plan_not_accepted, select the first known repairable declaration
gap for observation guidance while preserving next_gap/order. Do not suggest premature
acceptance or a mutation if no known declaration gap exists. Other leading gaps retain
existing diagnostic navigation and no new repair object. Inactive packets get no
mutation hint. Each descriptor retains original projection facts; no competing graph.

## Semantic and temporal correspondence
implements lists investigated active criterion numbers implemented by that unit.
verifies contains criterion/kind/statement and any required authority_ref. Each
unit_checks statement needs a same-unit kind=unit_check verification statement,
exact after canonical text normalization. It need not equal criterion prose;
implements does not determine its criterion. One check may verify multiple active
criteria. Verification-only criterion coverage can be legitimate. Deferred intents
never satisfy local checks; empty unit_checks requires exclusively deferred nonempty
verifies under the existing domain rule. Do not delete, weaken or defer an obligation
merely to silence a gap. A justified erroneous declaration is revised through normal
authority, preserving intent. provides promises planned contracts; requires refers to
producer_unit_key/contract_name/use rather than copying clauses or asserting files exist.

## Ordinary workflow and consumption
Read current full validation/criteria and exact help. Investigate meaning, submit an
explicit revise_unit (or replace_plan when genuinely replacing the plan) with current
CAS/actor/new request identity. Array fields replace whole arrays; preserve applicable
existing declarations. Read returned new authority, review and ordinary accept_work_plan,
then revalidate; a new proposal is not executable automatically. Do not replay completed
work or restamp old outcome pins. Hints do not bypass guided intent/approval/admission.
Offline: execute only closed issued authority; a new gap stops affected effects while
investigation and proposed declarations are retained for ordinary accepted online
mutations/revalidation. Markdown edits alone never change Flower.

## Revise-unit mutation errors
A failed revise_unit is distinct from a blocked PVP read. Its existing lifecycle
repair can precede the failure; a structured rejection retains effect_state=unknown
and original request correlation, with no no-effect receipt. Inspect current state
before explicit reconciliation; never replay automatically. This adds no descriptor
field and does not reclassify observational PVP blocks as uncertain mutations.

## Read the execution decision and the preparation gate

Current validation (standard or full) and blocked TODO expose
`gate_context`, contract `flow.external-work-gates.v1`. Read its global
`execution_allowed` first. `validation.next_gate` retains the PVP preparation
route and incomplete repair descriptor even when the primary gate is roadmap
confirmation. `admission` is only the first observed guard result; `not_evaluated`
means TODO stopped earlier, not that admission passed. `engineer_gate` checks
semantic findings only and cannot grant overall permission.

For a local-check mismatch, `validation.diagnostic` preserves the original
received and candidate strings. `expected_count: 1` means one distinct declared
same-unit `kind=unit_check` comparison candidate. It does **not** mean a test ran
or passed, or that the candidate is semantically correct. Compare exact canonical
statements, investigate the intended criterion and revise legitimate declarations
through ordinary current-authority mutations, review/accept and revalidation.
Never copy a candidate blindly, infer criterion ownership or weaken obligations.

A blocked read is an observation, not uncertain mutation effects. When current
authority cannot be resolved, full history retains its provenance without inventing
current context or repair. Actual roadmap consent/delegation may be recorded by
the agent through canonical `confirm_roadmap`, with current roadmap fingerprint
and an applicable confirmation reference. No separate native UI is required;
missing consent must never be fabricated. This does not accept implementation.

### Continue confirmed milestone scope

Continue within the confirmed roadmap when actual current entry and execution
predicates permit. Do not ask for a fresh approval after every milestone merely
because a repository review reports `human_acceptance: false`: the review does
not attest product acceptance. Secondary actions are ordered options or context,
not additional conjunctive admission gates. Narrative risk treatment is recorded
engineering context; its advisory traceability review is not a stakeholder decision.
Honor explicitly configured accepted-predecessor policies, real intent questions,
risk exceptions and other genuine human decisions. Never infer consent or acceptance.

For current snapshots, `secondary_actions_policy` explains this boundary. A
`review_milestone_risk` action keeps its identity but is `orchestration`; its
snapshot gate uses `kind: intent_work`, `advisory: true` and
`establishes_global_admission: false`, with a scoped `fow_traceability` read.
It is not inserted in open stakeholder decisions merely because risk prose exists.
Actual risk exception references, findings, campaigns and acceptance guards remain.

## Replacing a plan with construction answers

`fow_packet_author` with `operation: "replace_plan"` accepts an optional complete
batch of at most 64 distinct current question IDs. Read the packet's current gates
and exact operation help first. Flower validates the original specification/plan
conditions, records the answers against that pre-replacement question basis and
replaces the plan in one transaction. The ordinary applicability policy still
removes inapplicable questions or reopens changed dependencies.

The `engineering_questions` receipt preserves each original question and submitted
answer, its recorded status, and disposition: `retained`,
`reopened_by_changed_dependency` or `ceased_applicable`. A historical answer does
not answer a new gate. Current continuation and historical mutation revisions are
separate. Existing PVP fingerprints and admission predicates are unchanged.

New replay identity covers the normalized plan, complete answers, actor, scope and
supplied revision conditions. Keep the exact original request for reconciliation;
a changed command with the same key conflicts. Legacy plan-only receipts cannot
prove supplied answer identity: `legacy_compound_receipt_unverifiable` requires
explicit inspection rather than backfill or an automatic retry under a new key.

After a lost response or an unknown-effect error, use the existing read-only
`fow_packet_inspect` with `view: "history"`, `detail_level: "audit"`, packet scope
and pagination. Completion events retain full receipts, actor and revision even
after a successor plan. Inspect current gates separately. Failure and rollback do
not prove global absence of effects: lifecycle bookkeeping may precede the plan
transaction. Preserve prior applied operations and original unknown history;
reconcile deliberately. Upgrading does not replay or resolve old calls.
