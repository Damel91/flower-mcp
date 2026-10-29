# Continuous work and recovery

Flower keeps engineering authority and durable outcomes in its project ledger.
A coding agent can recover the current work through the public MCP interface,
export a complete implementation plan, execute it while Flower is offline and
report the results after reconnecting. Coding, repository investigation and
local verification remain the agent's responsibility.

Use the [engineering cycle](ENGINEERING-CYCLE.md) when recovering context or
completing a bounded increment. Use the [safe upgrade
plan](UPGRADING.md) to preserve an existing installation's ledger and profile;
the already published 0.3.0 assets remain unchanged. Installed distribution metadata
identifies the package version; it does not establish that a development checkout
matches a published release or that a client is attached to the intended ledger.

## Select the intended instance

Use the endpoint configured for the existing Flower instance. Identify the
instance and read a known project before creating work or starting another
server. Different endpoints or profiles can own different ledgers. A successful
connection alone does not establish that the intended project is present.

The installed HTTP probe accepts an explicit endpoint. It does not start Flower,
select another owner, repair configuration or inspect private databases:

```sh
flower-mcp probe --help
flower-mcp probe --endpoint http://127.0.0.1:PORT/mcp ping
flower-mcp probe --endpoint http://127.0.0.1:PORT/mcp list
flower-mcp probe --endpoint http://127.0.0.1:PORT/mcp describe fow_handover
flower-mcp probe --endpoint http://127.0.0.1:PORT/mcp call fow_capabilities '{"view":"summary"}'
```

Replace `PORT` with the configured port; the probe has no default port. An
explicit `FLOW_OF_WORK_MCP_ENDPOINT` environment variable is also supported.
`python -m flow_of_work_mcp.mcp_probe` is the equivalent packaged module entry.
The HTTP probe is separate from the stdio transport used by many coding clients.

Ping returns MCP initialize identity separately from Flower's advertised
`distribution` metadata. The product is `Flower MCP`; the Python distribution
remains `flow-of-work-mcp`. Missing installed metadata is reported as unavailable.
The MCP SDK/serverInfo version and operation registry identity have separate
meanings. `flower-mcp doctor` can inspect local installation/registration state
without connecting to models or starting another server.

Tool calls return both readable Markdown and structured data by default. For
specific inspection, place `--content-only`, `--structured-only` or
`--channel-summary` before the `call` subcommand. Read both channels when
qualifying a workflow; the readable channel is part of the agent interface.
Inspect the application status and MCP `isError` as well as the command exit
code. A received MCP rejection can still have a successful transport exit code.

Read `source_ledger_version_namespace` beside a version counter. Snapshot and
traceability use `requirement_events.max_event_id.v1`; external resume/recovery
use `lifecycle_events.sum_max_event_ids.v1`. These pre-existing clocks measure
different event streams. Their numeric values cannot be compared across
namespaces. Plan/specification revisions and authority fingerprints determine
the issued work's authority; a difference between these counters alone does
not mean that a plan is stale. Frozen historical payloads remain unchanged.

## Recover the current scope

Replace the example IDs below with IDs returned by your Flower instance. A
read-only project snapshot provides the active work, applicable gates, bounded
open decisions and public routes to more detail:

```json
{
  "tool": "fow_handover",
  "arguments": {
    "project_id": "PROJECT_ID",
    "operation": "project_state_snapshot"
  }
}
```

For a particular packet, supply `focus_kind: "packet"` and its ID as `focus_ref`.
Read the current packet and TODO before taking action. A lifecycle action marked
`preparation_required` describes preparation; executable admission still depends
on the accepted plan, semantic/PVP closure and all current guards.

External packet readiness comes from the same mode-aware guard used for
admission. `provider_readiness` preserves contextual provider diagnostics;
its applicability is separate from external readiness. Genuine intent, missing
contracts/checks, stale authority, dependencies, conflicts and inactive work
continue to block the affected work. Snapshot decisions are bounded to the
current focus, with omission counts and canonical detail routes. They are not
a claim that every project question fits in one response. Packet inspection does
not repair or rebase stale plans; ordinary accepted packet mutations own that
boundary. A semantic question can legitimately change the specification revision
even when it does not require new human roadmap confirmation.

Snapshot `blockers` include the current gate and broader lifecycle obligations.
Each entry carries its source and scope; a traceability obligation can concern a
dependent packet while the selected packet is actionable. Read
`active_work.packet.readiness` for its current execution admission. Preserve
broader verification and acceptance obligations even when that admission allows
the next unit.

The engineer investigates architecture, implementation choices and reuse. An
unresolved requirement, scenario or intended behavior requires clarification.
A discovered implementation mismatch requires canonical intent rereading and an
ordinary corrective packet. Neither a reassuring summary nor a proposed model
answer changes authority by itself.

## Read a frozen handover and compare current authority

An explicitly selected external packet receives the versioned
`recovery.contract: "flower.external-recovery.v1"` block when a new handover is
captured. Capture uses one coherent authority snapshot and the existing
handover payload. The block contains plan revisions/fingerprint, selected unit
outcomes, current gates, deferred obligations, pinned artifact references and
`recovery_calls` for the existing public tools.

Capture is an ordinary durable mutation. Discover its operation contract first:

```json
{
  "tool": "fow_capabilities",
  "arguments": {
    "view": "operation",
    "operation_tool": "fow_handover",
    "operation_name": "create_handover"
  }
}
```

Supply the selected project/change/packet, the applicable run focus, actor and
request identity as advertised. Request replay returns the originally stored
snapshot before recomposition; it does not refresh the historical payload.
Provider-only or unfocused captures retain their established context rather than
inventing an external packet selection.

To read the persisted handover unchanged:

```json
{
  "tool": "fow_handover",
  "arguments": {
    "project_id": "PROJECT_ID",
    "operation": "get_handover",
    "handover_id": "HANDOVER_ID"
  }
}
```

To compare that historical focus against current authority:

```json
{
  "tool": "fow_handover",
  "arguments": {
    "project_id": "PROJECT_ID",
    "operation": "resume_context",
    "handover_id": "HANDOVER_ID"
  }
}
```

Current resume derives the original change/packet/run focus and returns an
explicit `historical_comparison`. Its state is `current`, `stale` or
`legacy_without_recovery`. Conflicting supplied focus IDs are rejected.
`outcomes_may_have_changed` also distinguishes ledger movement from unchanged
plan authority. An old handover without the recovery block remains historical;
get/replay never silently enrich it. Resume does not mutate it.

Recovery lists are bounded to ten, with totals/omissions and exact public calls.
Follow those calls and the tools' pagination contracts for full details. The
work-plan route is `fow_packet_inspect` with `view: "units"` and audit detail.
Artifact reads use the returned generation ID. Provider run steps belonging to
other packets do not become next instructions for the selected external packet.
A bounded handover is a recovery index; the complete exported Markdown is the
offline execution reference.

## Recover original verification evidence

Requirement verification events identify evidence; traceability audit already
provides the full metadata in its paged view. Use an exact positive evidence ID
when you need one complete original body:

```json
{
  "tool": "fow_traceability",
  "arguments": {
    "project_id": "PROJECT_ID",
    "detail_level": "audit",
    "evidence_id": 1
  }
}
```

Replace `1` with an ID returned by this project's evidence. Exact-ID reads require
explicit audit detail, no milestone filter and the default `offset: 0`,
`limit: 10`. Omit those pagination arguments or retain their defaults. Unknown
and foreign project IDs receive the same rejection. The default `evidence_id: 0`
retains ordinary traceability behavior.

Explicit evidence bodies preserve original metadata, declared provenance and
multiline text in both response channels. The read creates no artifact, evidence
record or acceptance. Host-reported observations remain host-reported; reading
them through Flower does not make them provider-audited or independently verified.

## Continue an existing engineering cycle

Read guidance without guessing a bootstrap ID:

```json
{
  "tool": "fow_bootstrap",
  "arguments": {
    "project_id": "PROJECT_ID",
    "operation": "guidance",
    "actor": "coding-agent"
  }
}
```

Guidance selects the active cycle of any mode, otherwise the latest guided
cycle. With neither, it advertises an explicit start route. It returns the
selection and existing routes for current work, active-roadmap extension and a
new guided cycle. An explicit historical cycle does not bypass a different
active cycle. Guidance itself starts no cycle and confirms no scope.

Use ordinary canonical authoring to extend an active guided roadmap, then obtain
its current roadmap projection and record actual confirmation. Completed or
cancelled preparation remains historical. A new cycle needs existing scope
authorization or the missing intent confirmation; the agent must not manufacture
it. Technical investigation does not automatically require human approval.

## Execute offline and reconcile outcomes

1. Inspect `fow_external_work` validation and TODO for the selected packet. Resolve
   missing producer/consumer contracts and unit-local verification declarations
   through ordinary accepted mutations before executable closure.
2. Export the complete Markdown through `fow_external_work`, operation
   `export_plan`, using the current specification and plan revisions. Retrieve
   its pinned artifact generation, save the returned Markdown with the host's
   file tools and retain its revisions, authority fingerprint and export identity.
   A draft diagnostic export does not authorize execution.
3. Execute the issued plan in dependency order. Producer declarations describe
   the interfaces to create; future paths/symbols are not assertions that code
   already exists. Consumers reference those producer declarations. Perform the
   unit-local checks at each unit boundary. Campaign, Oracle and explicit-authority
   verification remain deferred obligations until their proper phase.
4. When Flower returns, read current authority and report through
   `fow_external_work`, operation `report_outcome`, using the issued revisions,
   fingerprint, unique report key, source revision, artifacts, produced contracts,
   exact verification declarations and unresolved obligations. Follow the
   discovered operation schema; a handover summary is not a report payload.
5. Recover TODO/validation again. Repeated identical requests are idempotent;
   conflicting reports remain conflicts. Reports against stale authority remain
   history and cannot complete current work. Use explicit `reconcile_outcome`
   with the current revisions and grounded rationale when ordinary reconciliation
   is appropriate; do not rewrite old report provenance or relabel it as current.

For a rejected verification report, inspect the returned diagnostic's field,
unit, criterion, expected and received declarations and its public recovery call.
Copy the exact criterion/kind/statement from the unit's authoritative obligations;
approximate matches are rejected. Invalid reports persist no outcome. Correct the
report only when supported by actual work and evidence.

Agent completion, successful unit checks, campaign/Oracle verification and human
acceptance remain distinct. Flower's recovery and TODO reads execute no code.
They do not certify the semantic truth of a report, general agent usability or
that the stakeholder has accepted the result.

## Original report and repository-review recovery

`fow_external_work` validation with `payload: {"detail":"full"}` returns complete
review detail and a page of original outcome reports. `history_offset` is a
nonnegative integer inside that payload; pages contain up to 20 reports. History
remains readable outside execution admission. If current authority cannot be
resolved, the read returns original provenance plus an explicit diagnostic and
unassessed readiness; it does not grant execution.

For cycle-1 external work, preserve completed implementation/local verification
while resolving the current repository review before final closure or dependent
admission. Read its exact scope/basis/template, supply actual host observations
and follow the returned `fow_audit_phase` job through `fow_get_job`. Exact replay
recovers its original job; changed payload or actor conflicts. A committed audit
remains in structured `original_audit` even after a newer audit or a post-commit
job failure. Current validation is a separate comparison and can be stale.

Original reports/audits never become current semantic proof merely because they
can be read. Preserve dates, revisions, declared provenance and unresolved gaps.
The [engineering cycle guide](ENGINEERING-CYCLE.md) explains historical versus
current coverage and bounded host grounding.
