# Noxi and Flower integration

Flower MCP 0.4.0 adds durable
project architecture and an optional, explicitly negotiated provider handoff.
Published 0.3.1 remains immutable; Flower does not install a Noxi agent loop.
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

The consumer owns materialization/compiler behavior and returns a matching
context/authority/unit acknowledgement with a compilation digest. Flower requires
current matching unit acknowledgements before START. A digest records declared
materialization; it does not satisfy deferred verification, prove host evidence
was provider-audited or establish human acceptance. Missing/mismatched replies
after a possible write retain unknown delivery and reconcile only the same
durable command. STOP/STATUS may observe the admitted run using its frozen
context without admitting new stale coding work.

Compatible unenriched legacy commands keep v2 delivery. The original full
cross-server PVP draft and CodingCastle IMPL-67 remain deferred; this bounded
Flow bridge does not establish their acceptance. Consumer implementation and real
paired qualification must be coordinated separately.

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
Published 0.3.1 remains its separately qualified schema 52 release. This source
increment is distributed as 0.4.0/schema55.

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
