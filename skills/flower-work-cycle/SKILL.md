---
name: flower-work-cycle
description: Start or resume a Flower MCP engineering cycle, define or execute a governed packet, and reconcile evidence or hand over work. Use when Flower governs the user's project, including work from an issued offline plan.
---

# Flower work cycle

Use Flower for canonical intent, architecture, plans, lifecycle, verification
records, acceptance and handover. Use the host's authorized tools for repository
investigation, edits, builds, tests and Git. Follow applicable project instructions
when present. Activate this workflow with the instructions already loaded.
Do not create or copy `AGENTS.md`, run `/init`, or install or reinstall Flower
merely to activate the skill. Use the existing `flower-mcp bootstrap` guidance
when the user explicitly requests setup.

If the full persistent Flower bootstrap template is absent from loaded
instructions, read [Bootstrap constraints](references/bootstrap-constraints.md)
before following this workflow. A skill activation block alone still requires
that reference.

## Bind the intended work

1. Establish the repository/worktree, project and user-authorized scope. Discover
   the connected Flower tools and their actual names. Use the host-provided
   interaction reference or create one if the host owns that choice. Keep it
   stable for the same conversation across interruptions and use a new one for
   a genuinely new conversation.
2. Discover projects via `fow_interaction` and explicitly select the intended
   existing project. Confirm a choice if discovery and the task leave it
   ambiguous. Create a project only when no existing project fits the verified
   new scope and the current request authorizes creation. Then rediscover and
   select it. Keep locators and interaction state in their proper scope. Global
   instructions contain no project state.
3. Read `fow_capabilities` summary and `fow_handover` project-state snapshot.
   Use the current lens for attention. Follow the single current `next_gate`
   within authorized scope, and refresh after lifecycle mutations. An idle
   focus means no next action there. A suggested gate, lens or resolved
   `next_tool_call` proposes an action; check its authority and inputs before
   calling it.

Use the current recipe for the phase:

| Phase | Recipe to request from `fow_capabilities` |
| --- | --- |
| Scenario intake and roadmap confirmation | `engineering-bootstrap` |
| Architecture, context recovery and repository review | `provider-agnostic-engineering-cycle` |
| Host-executed plans, TODOs and outcomes | `standalone-external-plan` |

Use current frames, schemas and exact operation help for arguments. Read
Markdown for orientation and structured results for machine identities and
state. If Flower is unavailable, report the connection as unverified and retain
any previously verified project identity, binding and issued authority. A
project without a verified binding remains unbound. On reconnection, confirm
the intended server and selection before mutations. Use a public probe only
when the host authorizes it and the exact endpoint is known. Keep lifecycle
operations on the public surface.

## Define and admit work

- Start from scenarios about what the software must do and show. Gather only
  the intent needed for the next bounded step. Help the stakeholder answer with
  examples, consequences or a concrete information-gathering task.
- Investigate repository patterns, prior requirements and technical reuse.
  Resolve implementation choices within agreed intent. Question your own and
  the stakeholder's factual premises and seek evidence that could overturn a
  proposal. Explain search limits and remaining uncertainty. Disclose deviations
  before proposal approval or affected execution, naming the original
  obligation, change, reason, consequences, affected criteria and evidence.
  Record the governing Goal, requirements, scenarios, milestones and technical
  decisions in Flower.
- Use guidance to recover an existing cycle or establish new scope. Present a
  coherent roadmap once intent supports it. Record actual stakeholder
  confirmation when the workflow requires it. Continue confirmed scope when
  entry and execution predicates permit. Preserve explicit predecessor,
  risk-exception and human-decision gates. Advisory risk and secondary actions
  do not create extra approvals. A review reporting `human_acceptance: false`
  records non-attestation. Scope confirmation is separate from release and
  acceptance.
- Before accepting a new plan, adopt the governing architecture in Flower with
  at least one component and select valid packet references. Keep historical
  plan contracts intact. Close the work definition with an accepted plan, closed
  Packet Validation Projection (PVP), the authorized executor and current admission.
  Each unit needs explicit criterion ownership, dependencies, producer and
  consumer contracts, and checks. Future outputs are declarations. Keep
  campaign, Oracle and other deferred verification separately visible.
- Hold affected repository effects if intent, technical declarations or
  admission are missing. Investigate and author within confirmed intent.
  For a semantic mismatch, reread the governing Goal, scenario, requirements,
  milestone and packet. Record reassessment and create an ordinary
  finding-linked corrective packet with regression obligations for a correction
  within intent. Changed intent requires ordinary revision and confirmation of
  the affected scope.
  Help the stakeholder resolve any genuine intent gap.

## Execute, recover and close

- For host coding, use authorized external-agent mode and consume the current
  dependency-ordered TODO. Carry the issued specification revision, plan
  revision, authority fingerprint and exact verification declarations into
  actual outcome reports. Work through admitted units without introducing
  per-unit human approval. A draft export carries no execution authority.
- After interruption or uncertain effects, inspect current state and the
  original request, receipt or outcome before retrying. Reuse identities only
  for exact replay under the operation contract. A successful historical
  receipt records the original effect. At `inspect_historical_outcome`,
  compare the original pin and actual repository effects with
  current authority before reconciling or reporting again. Preserve stale
  evidence on its original date, revision and provenance. Never repeat an
  effect merely because its current receipt is missing.
- Offline, execute only the bounded effects authorized by an exact issued
  executable plan. Retain its contracts, checks, identifiers, observed effects
  and open obligations. Hold affected effects if new intent, missing authority
  or a semantic gap prevents continuation. Reconnect, inspect current state and
  report against the original issued authority before ordinary reconciliation.
  Edits to exported Markdown cannot revise Flower's authority.
- At recovery and packet completion, compare the repository against the scoped
  requirements, adopted architecture, Goal grounding, checks and outcomes.
  Distinguish missing registration from missing implementation. Reuse a current
  review and its evidence while the relevant basis remains unchanged. If the
  current gate requires a review, record real host observations for its exact
  scope and basis. Where cycle-1 requires review, keep completed unit outcomes
  and local checks visible while closure or dependent admission waits.
  Use the durable handover to preserve unresolved work and its evidence.
- Report derived progress on current scoped criteria. Progress is unknown
  when scope or a usable denominator is missing. Separate implementation,
  local and deferred verification, host-declared evidence, and stakeholder
  acceptance. At a result checkpoint for the agreed increment or a concrete
  limit, state achieved work and open obligations, ask whether to continue
  or review, and follow the user's actual choice.
