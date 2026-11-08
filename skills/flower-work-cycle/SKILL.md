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
| Author the next packet and its work plan | `packet-work-plan-v2` |
| Host-executed plans, TODOs and outcomes | `standalone-external-plan` |

Use current frames, schemas and exact operation help for arguments. Read
Markdown for orientation and structured results for machine identities and
state. If Flower is unavailable, report the connection as unverified and retain
any previously verified project identity, binding and issued authority. A
project without a verified binding remains unbound. On reconnection, confirm
the intended server and selection before mutations. Use a public probe only
when the host authorizes it and the exact endpoint is known. Keep lifecycle
operations on the public surface. If a gate lacks an exact continuation, read
its scoped object and request public operation help for the intended action.

## Choose the next increment

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
- Present a coherent roadmap once intent supports it and record actual
  stakeholder confirmation when required. Preserve explicit predecessor,
  risk-exception and human-decision gates. Advisory risk and secondary actions
  do not create extra approvals. A review reporting `human_acceptance: false`
  records non-attestation. Scope confirmation is separate from release and
  acceptance.
- From the confirmed roadmap and current gate, pick one next bounded result
  within an eligible milestone. If repository effects for that result already
  exist without admission, use the recovery branch below. Otherwise reuse a
  matching change and packet, or use exact help for `fow_change create_change`
  and `fow_packet_author start_packet` to open what is missing for that result.
  Link the affected requirements and architecture. Keep later work at roadmap
  level until a dependency or the next increment needs it.

## Admit the packet

- Before accepting a new plan, adopt the governing architecture in Flower with
  at least one component and select valid packet references. Keep historical
  plan contracts intact. Close the work definition with an accepted plan, closed
  Packet Validation Projection (PVP), the authorized executor and current admission.
  Each unit needs explicit criterion ownership, dependencies, producer and
  consumer contracts, and checks. Future outputs are declarations. Keep
  campaign, Oracle and other deferred verification separately visible.
- For external coding, select the external agent before drafting units. Read
  the current criterion numbers and the exact authoring contract. Write each
  criterion as an observable outcome. State who implements it and how it will
  be checked. For verification-only work, bind the exact existing baseline or
  producing criterion and order its verifier after that producer.
- On strict PVP, save the complete classification with the current spec and plan
  revisions through `fow_external_work classify_criteria` before plan acceptance.
  Use `implementation` for changed behavior, `verification_only` for a linked
  observation, and `external_authority` only with the scoped accepted authority
  declared by the exact help. When the specification changes, read its current
  criteria before classifying again.
- Declare each local check once with its exact criterion. Use compact authoring
  only when the connected operation help advertises it. Otherwise reuse the
  exact same statement in both arrays. Read the bounded complete validation
  for the current draft before correcting multiple related gaps.
- Hold affected repository effects if intent, technical declarations or
  admission are missing. Investigate and author within confirmed intent.
  For a semantic mismatch, reread the governing Goal, scenario, requirements,
  milestone and packet. Record reassessment and create an ordinary
  finding-linked corrective packet with regression obligations for a correction
  within intent. Changed intent requires ordinary revision and confirmation of
  the affected scope.
  Help the stakeholder resolve any genuine intent gap.

For a concrete two-criterion example or help unwrapping a CodeMode response,
read [Authoring examples](references/authoring-examples.md) when that need arises.

## Work one unit at a time

1. Read the current `fow_external_work todo` for the admitted external-agent
   packet. Take one dependency-ready unit. A draft export carries no execution
   authority.
2. Perform that unit with host tools and run its declared local checks. Register
   governing decisions and discovered gaps in Flower when they arise. Recheck
   affected authority if the decision changes a governing input.
3. Before selecting the next TODO, record the unit's actual completion, failure
   or blocker through `fow_external_work report_outcome`. Carry the issued
   spec/plan revisions, authority fingerprint and exact verification declarations.
   Cite the observed source revision, check evidence and open obligations. If
   reporting is blocked or uncertain, recover the result before advancing.
4. Read the returned gate and refresh the focused state. Continue with the next
   admitted TODO or resolve the reported blocker. Work through the agreed
   increment without introducing per-unit human approval.

## Recover and close

- If the repository already contains work that Flower did not admit, compare
  the bounded scope against its requirements and architecture. Record observed
  changes, source revision, existing evidence and gaps with their original
  provenance. If the scope has no change record, use `fow_change create_change`
  with the verified requirements and source/baseline references. Record actual
  gaps through `fow_assurance record_finding` with the matching scope and anchor.
  A new packet can govern remaining verification against that baseline or
  corrective work from this point forward. Do not report past work as an issued
  TODO outcome or imply past PVP, execution admission or acceptance.
- After interruption or uncertain effects, inspect current state and the
  original request, receipt or outcome before retrying. Reuse identities only
  for exact replay under the operation contract. A successful historical
  receipt records the original effect. At `inspect_historical_outcome`,
  compare the original pin and actual repository effects with
  current authority before reconciling or reporting again. Preserve stale
  evidence on its original date, revision and provenance. Never repeat an
  effect merely because its current receipt is missing.
- When a gate or call is blocked, read the Markdown for the cause, scope and
  next action. Preserve known and missing inputs, expected and received values,
  effect state, request correlation and any read-only inspection route across
  wrappers. Use that route when the cause or effects are unknown. An expected
  operation or suggested continuation does not itself authorize a mutation.
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
- Before presenting acceptance, inspect the exact packet or milestone scope.
  Separate applicable prerequisites, missing registrations and awaited human
  evidence. Compare the agreed scenario with one material failure path and
  reuse existing proof where it covers that behavior. Report only the remaining
  gap if no current proof covers it.
- Report derived progress on current scoped criteria. Progress is unknown
  when scope or a usable denominator is missing. Separate implementation,
  local and deferred verification, host-declared evidence, and stakeholder
  acceptance. At a result checkpoint for the agreed increment or a concrete
  limit, state achieved work and open obligations, ask whether to continue
  or review, and follow the user's actual choice.

## Read and export documents

Use the connected server's advertised operations. In `fow_architecture propose`,
`payload.definition.markdown` can hold prose or a fenced Mermaid diagram. Keep
canonical components, interfaces and decisions in the same revision. Use
`fow_architecture export` with the intended revision to read the full document.
For a fresh requirements catalogue, use `fow_generate_artifacts` with profile
`fow-srs-markdown-v1` and get the generation ID from `fow_get_job`. Read the
catalogue through `fow_get_artifacts` with the exact `generation_id`,
`artifact_kind: requirements_catalogue` and `include_content: true`. Export a
scoped packet plan through `fow_external_work export_plan`. Read returned
Markdown directly. Save a file only when the user or an authorized offline
workflow needs one.
