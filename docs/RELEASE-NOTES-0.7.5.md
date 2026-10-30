# Flower MCP 0.7.5

Recorded milestone risk treatment no longer manufactures a human approval gate.
The existing `review_milestone_risk` action remains visible with its identity and
priority, but is an orchestration advisory linked to a scoped traceability read.
Snapshots classify it as `intent_work`, with `advisory: true` and
`establishes_global_admission: false`, rather than acceptance/open decisions.
Original risk prose is retained; no text matching infers consent or accepted risk.

Snapshots explain that secondary actions are ordered options or context, not
conjunctive admission prerequisites. Repository review Markdown explains that
`human_acceptance: false` means non-attestation, not a new approval requirement
before each subsequent confirmed milestone. Full requested review coverage and
original structured flags remain intact. Recipe, help, offline plans and shipped
bootstrap repeat the distinction. See [engineering cycle](ENGINEERING-CYCLE.md).

Actual entry/dependency/PVP/semantic/roadmap predicates and explicit
`entry_policy.requires_milestone` eligibility are unchanged. Genuine risk exceptions,
finding/campaign decisions and human acceptance still require their ordinary
authority/evidence. Nothing accepts a milestone or resumes a real project on update.

## Upgrade

Use the [ordinary same-profile upgrade](UPGRADING.md#preparing-a-075-upgrade).
Keep the existing SQLite database, YAML, client configuration and environment.
Schema55, dependencies and installer algorithm are unchanged; the existing installer
backs up before pip and rejects active ownership. No migration or reset is needed.

## Verification boundary

Focused regressions and source/installed public MCP qualify narrative advisory,
scoped routes, unchanged entry eligibility, non-attestation/full review presentation,
read-only SQLite state and both response channels. Independent severe review and
existing exact-commit Release CI gate publication. Private baseline fixture failures
remain recorded separately, without weakening tests or claiming they passed.
Native preview adoption belongs to its owner. No benchmark acceptance, model quality,
new runtime, U6 or product acceptance is inferred.
