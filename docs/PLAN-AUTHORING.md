# Flower plan authoring repair descriptor v1

**Status:** Flower 0.7.4 public reference
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
