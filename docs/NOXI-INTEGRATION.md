# Noxi and Flower integration

Flower MCP 0.4.0 introduced durable project architecture and an optional,
explicitly negotiated provider handoff; 0.4.1 retains them. The discovery and
deferred-only authoring correction and sync-only mode described below are newer
unreleased source.
Flower does not install a Noxi agent loop or alter historical release assets.
Actual paired consumer qualification is recorded separately from Flow protocol
tests; check the installed server's capabilities before using optional delivery.

Flower owns requirements, goals, milestones, architecture, packets, dependencies,
outcomes, evidence and handovers. Pi owns its agent loop. Noxi owns the interface,
correlations, process observation and transport. CodingCastle can supply
structural investigation and an optional execution consumer. Noxi should retain
Flower references and correlations rather than copy semantic authority into a
second project store. Importing or indexing a repository does not select its
executor.

## Discover the current contract

Open the normal Flower interaction and select the lifecycle project. Ask
`fow_capabilities` for the `project-architecture-v1` and
`negotiated-provider-handoff-v1` recipes. Request exact operation help with
`view="operation"`, `operation_tool` and `operation_name`; the installed
registry supplies required fields, examples, accepted values and risk.

`fow_architecture` exposes `inspect`, `propose` and `adopt`.
`fow_external_work` retains standalone validation/TODO/export/outcome operations
and adds `provider_validation`, `select_executor` and `negotiate_provider`.
Architecture inspection, provider validation and ordinary lifecycle reads do not
probe a provider, invoke a model or execute code. Negotiation is an explicitly
requested provider probe with a durable result.

## Record project architecture

The engineer investigates canonical intent, code and reusable patterns, then
proposes a complete bounded architecture definition in the existing Flower
ledger. Its three collections are:

- **Components:** identity, name, responsibility, boundaries, invariants and links.
- **Interfaces:** identity, provider/consumer component IDs, kind, contract
  clauses, failure/compatibility behavior and links.
- **Decisions:** identity, statement, rationale, affected component/interface IDs,
  optional superseded decision and links.

Links resolve same-project requirements, Goal nodes, packets and original
evidence. A planned interface or future symbol is design authority; it does not
prove that implementation already exists. Inspect paging completeness before
assuming the whole architecture has been read.
Linked packets contribute their intent, scope and spec context; they do not
recursively import or schedule their work plans.

Propose with the current adopted `expected_revision` (0 initially), actor and
request identity. Adoption names the proposed revision, expected current head
and rationale. Exact replay returns its historical receipt; stale or conflicting
writes reject atomically. Adoption records an engineering decision and remains
distinct from product acceptance. Changed adopted decisions use new identities
with retained explicit supersession lineage.

Ordinary packet creation/revision can select architecture with:

```json
{
  "architecture_refs": [
    {"revision": 1, "kind": "decision", "entity_id": "loop-owner"}
  ]
}
```

Use actual adopted identities from inspection. All selected references pin one
adopted baseline. Omission preserves current references; `[]` clears them through
an ordinary spec revision. Interfaces include their endpoints and decisions
include their subjects/lineage. Select governing decisions explicitly; Flower
does not infer a reverse architecture graph.

Selected definitions, canonical linked intent and provenance join the coherent
authority snapshot and complete export/HAND. Relevant edits, removal or
supersession produce `architecture_authority_stale` until ordinary re-pin/review.
Unrelated architecture adoption and unadopted proposals leave the selected
packet fingerprint stable. Frozen historical handovers remain immutable.

## Choose one executor for new work

Before authoring an enriched plan that could trigger provider delivery, call
`fow_external_work` with current project/change/packet, actor/request identity,
`operation="select_executor"` and the current issued revisions:

```json
{
  "expected_spec_revision": 1,
  "expected_plan_revision": 0,
  "executor": "provider",
  "provider_kind": "codingcastle"
}
```

For standalone work use `executor="external_agent"` and omit `provider_kind`.
The actual adapter kind `codingcastle` differs from the canonical route category
`packet_execution`. Existing `set_mode` external-agent calls use the same
ownership policy.

Selection admits new work; it cannot transfer an existing assignment. Opposite
explicit ownership, legacy external selection, provider history, reports,
started runs or completed work reject transfer as
`executor_transfer_not_supported`. An unselected legacy provider default does
not invent an explicit selection. A transport timeout never permits external
fallback, another writer or completed-unit replay.

## Negotiate optional provider delivery

A new enriched handoff requires a configured canonical `packet_execution`
binding and a consumer that positively advertises the exact supported versions.
Call `negotiate_provider` explicitly with current spec/plan revisions. The
receipt binds capability support to selection, provider/context/binding revision
and current semantic authority. Authority changes require explicit new negotiation
before fresh work. The first admitted command pins its canonical provider route;
a later rebind cannot transfer that packet, even through another negotiation.
No URL, credential or executable command is supplied in a receipt.

Read `provider_validation` with optional `{"detail":"full"}` to inspect
provider-scoped semantic closure and current executor/capability admission.
This is a pure read. Missing, unavailable, malformed or incompatible support
blocks enriched dispatch and explains its prerequisite.

The bounded bridge uses `flow.packet_provider.semantic.v3` and typed
`flow.packet_validation_context.v1` outside technical `semantic_input`.
It preserves stable criteria, implementation declarations, canonical producer
contracts, resolved consumer references, selected architecture and exact
authority/context fingerprints. Future files and symbols remain planned.
Unit-local checks stay separate from deferred campaign, Oracle and
explicit-authority obligations; those deferred obligations do not become current
coding tasks.

### Unreleased discovery and temporal-authoring correction

Flower calls `codingcastle_packet` and `codingcastle_tests` with the canonical
`detail_level="verbose"` response profile. CodingCastle permits only `minimal`,
`standard` and `verbose`; the former `audit` request value is invalid. Packet
responses below `verbose` omit `result.audit`, which Flower needs for durable
correlations and `validation_ack`. Test calls also retain the complete integration
response. This profile choice leaves receipt fields, wire versions and recovery
guards unchanged. Flower's own tools retain their separately defined detail levels.

The source after published 0.4.1 explicitly requests
`codingcastle_capabilities({"group":"all"})`. A complete registry without a
`packet_validation` advertisement is unsupported. A known overview health object
is also unsupported; it never advertises execution support. Invalid envelopes
are contract errors and explicit provider rejections retain their bounded reason.
No alternate route or legacy-receipt downgrade is attempted. Only an explicit
compatible v3/context-v1/receipt-v3 advertisement authorizes new enriched work.

Planned contract `kind` is semantic (`symbol`, `api`, `data_shape`, `protocol`,
`behavioral_boundary`). Its only optional technical fields are `file_path`,
`symbol` and `signature`. There is no `symbol_kind` or AST `expected_kind` field;
do not derive one from the semantic kind. Unsupported consumer materialization
must reject before effect. Resolve technical gaps through investigation and
ordinary accepted plan authority; new fields require a versioned contract.

For a PVP unit with nonempty exclusively deferred `verifies`, canonical authoring
can retain `unit_checks=[]`. Legacy units and units with local or mixed intents
still require local checks. The context carries the exact empty
`local_verification` and separate deferred intents. No compiler may fabricate a
local check or turn a deferred obligation into current work. Consumer technical
validation remains independently required. An outcome may report
`verification=[]` when no local check applies; local progress is not_applicable,
with no percentage for zero applicable criteria. Deferred checks and acceptance
remain pending. Exported Markdown explains that distinction for offline work.

The consumer owns materialization/compiler behavior and returns a matching
context/authority/unit acknowledgement with a compilation digest. Flower requires
current matching unit acknowledgements before START. A digest records declared
materialization; it does not satisfy deferred verification, prove host evidence
was provider-audited or establish human acceptance. Missing/mismatched replies
after a possible write retain unknown delivery and reconcile only the same
durable command. STOP/STATUS may observe the admitted run using its frozen
context without admitting new stale coding work.

`compiled_context_sha256` must identify the actual deterministic technical
representation materialized by the consumer, persisted atomically with its
effect and ACK. An echo or rehash of the incoming context is not compilation
evidence. Flower validates format and correlation and preserves consumer-declared
provenance; the digest alone does not independently audit compiler contents.

Compatible unenriched legacy commands keep v2 delivery. The original full
cross-server PVP draft and CodingCastle IMPL-67 remain deferred; this bounded
Flow bridge does not establish their acceptance. Consumer implementation and real
paired qualification must be coordinated separately.

## Synchronize deltas before execution (unreleased)

Use `fow_packet_advance` with top-level `mode="sync_only"` to deliver admitted
ADD/EDIT/REMOVE without starting execution. Discover the installed operation
schema first: the default remains `mode="advance"`, and historical published
0.4.1 does not contain this new mode. Use current packet identities and revisions
from inspection, for example:

```json
{
  "project_id": "example-project",
  "packet_id": "PACKET-000001",
  "actor": "coding-agent",
  "request_id": "sync-authored-deltas-1",
  "mode": "sync_only",
  "expected_spec_revision": 1,
  "expected_plan_revision": 2
}
```

Synchronization can scaffold a provider draft, resolve a current target decision,
deliver deltas and reconcile their exact receipts. It is an explicit provider
operation with ledger effects, not a pure read. Existing PVP, negotiation,
currentness, ownership and correlation guards still apply. It does not accept
plans, advance evidence/acceptance work, send START/STOP or cancel a run.

At the execution boundary, `advancement.state="provider_synchronized"` and
`reason="sync_only_start_boundary"` mean the call stopped before sending START.
They preserve the actual provider state/run phase; they do not assert that an
earlier run never started. Inspect the result or author further deltas, retaining
`mode="sync_only"` on subsequent synchronization calls. Starting requires a
separate explicit `mode="advance"` call with current revisions; the synchronized
response returns that decision to the model rather than starting automatically.

A pending, delivering or unknown START/STOP remains unchanged and holds later
deltas in order. The response returns `provider_control_pending`,
`reason="sync_only_control_pending"` and the exact `pending_control` identity.
Use read-only `fow_packet_inspect` with `view="gates"` to inspect it before
choosing a separate control/recovery action. Explicit retry of a rejected control
is also held. An unknown delta reconciles only its original durable command;
an unresolved UNKNOWN never authorizes falling through to START. START/STOP
decisions, private force flags and non-provider semantic decisions conflict with
sync-only mode and are rejected before effects.

This addition changes no provider wire/context/ACK schema or SQLite schema.
Source/installed public-MCP checks with a synthetic provider and real paired
Noxi pre-first-START qualification are recorded separately. The mode does not
qualify a consumer or complete the deferred full cross-server PVP contract.

## Provider timeouts and exact recovery (unreleased)

The configured `timeout_seconds` is one total budget per provider RPC, including
startup, request processing, implicit tool discovery and session cleanup.
One `fow_packet_advance` call can perform several RPCs; the setting is not a
total deadline for the whole packet advancement. Allow ordinary startup costs
when choosing the budget for your deployment.

Expiry returns the sanitized reason `implementation_provider_timeout`.
After a possible write, Flower records UNKNOWN with the original durable
command, captured context and fingerprint. A response received before expiry
is still not adopted if its invocation fails to finish within the budget.
The agent must inspect and reconcile that same command; a timeout does not
establish rejection, completion or permission to create a replacement job.
The consumer must persist its exact ACK atomically with its effect and replay
that ACK idempotently when the original command returns.

`sync_only` continues to hold an uncertain START/STOP unchanged. Choosing the
ordinary recovery route remains a separate explicit decision. The timeout
correction changes no provider wire/context/ACK or SQLite schema. Its source,
installed-package and actual Noxi consumer qualification are recorded separately;
historical published 0.4.1 does not contain this unreleased correction.

## Upgrade and persistence boundary

This development increment adds SQLite migrations 53–55 for immutable
architecture revisions/adoptions, packet architecture references, executor
selection/capability receipts and captured transport admissions. Existing
project rows, historical evidence and frozen handovers are preserved; no
architecture, executor or capability acceptance is inferred for old work.

Use the existing [backed-up upgrade procedure](https://github.com/Damel91/flower-mcp/blob/main/docs/UPGRADING.md) with the same
profile, environment and database path. Stop the Flower processes using that
installation before upgrading; the installer refuses a database in active use.
Inspect the dry-run plan and retain its consistent SQLite backup and profile
copy. Normal startup performs the additive migration transaction. A package
version rollback alone does not roll back a migrated ledger; restore the
matching saved database/profile only through an explicit recovery procedure.
Published 0.3.1 remains its separately qualified schema 52 release. Published
0.4.0 and 0.4.1 use schema55; this discovery/authoring correction adds no migration.

## Continue while Flower is offline

Standalone external-agent work retains complete immutable Markdown export. The
host writes that returned artifact with its file tools; the agent can investigate,
code, build and test from the reference while Flower is offline. Selected
architecture, producer/consumer contracts, instructions, checks and deferred
obligations travel with the plan, without Noxi or CodingCastle handles.

On reconnect compare current validation/TODO authority, then report outcomes in
dependency order using the original issued spec/plan revisions, authority
fingerprint and exact verification declarations. Never rewrite old evidence to
look current. Reports preserve declared provenance; stale and conflicting reports
remain explicit and require ordinary reconciliation. Completion, verification
and human acceptance remain distinct. A provider-selected reference does not
authorize switching to an external executor offline.

The standalone predecessor frontier retains its existing external-agent closure
rules. This increment does not qualify arbitrary mixed provider/external-agent
packet chains. Provider-scoped admission can consume canonical predecessor
closure, but executor transfer during admitted work remains unavailable.
