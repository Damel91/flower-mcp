# Flower lens operation catalog

Flower 0.6.1 adds a complete, read-only catalog for hosts that present a relevant
subset of direct tools to a coding model. Flower keeps all 37 tool names and
445 input fields. The canonical registry now has 182 operation routes. A host
selects supported operations from the declared lens membership; it does not infer
an allowlist from one current recommendation or maintain a competing area map.

## Read the catalog

Call `fow_interaction` with the host's existing stable per-chat reference:

```json
{"operation":"catalog","interaction_session_ref":"<host-owned stable chat reference>"}
```

The host owns this identity, keeps it private and injects it into calls. Do not
place it in the model's system prompt. Read the successful application envelope
at `structuredContent.result`; the complete catalog is at
`structuredContent.result.result`. Its `contract` is
`flow.lens-operation-catalog.v1`, `scope` is `flower_public_operations` and
`complete` is `true`. Ordinary non-success responses are not complete catalogs.
The separate multiline Markdown summarizes the state and all nine lenses; it
omits the session reference and full schemas. Do not parse it as JSON.

Exact operation inputs remain discoverable through `fow_capabilities`:

```json
{"view":"operation","operation_tool":"fow_interaction","operation_name":"catalog"}
```

## Membership and revisions

| Field | Meaning |
| --- | --- |
| `operations` | Every unique `(tool, operation)` with canonical area, owner, risk, effect and continuation metadata. |
| `core_operations` | 17 orientation/control routes: every interaction route, capabilities, create project, project-state snapshot and what-next. |
| `lenses` | All nine canonical Flow areas with primary and companion operation references, availability, prerequisites and selection. |
| `registry_version`, `catalog_revision` | The same `flow.operations.<16 hex>` value; exact help and expanded membership participate in its hash. |
| `interaction_revision` | Deterministic `flow.interaction-catalog.<64 hex>` snapshot token, stable across unchanged reads and restart. |
| `revisions` | Durable project-context and lens event heads, including clear and invalidation. |
| `project_context`, `capability_lens` | Raw observed bindings; foreign or stale state is reported without repair. |
| `selection_state`, `selection_reason` | Explicit absent, unselected, current, stale or foreign classification. |
| `execution_admission` | Always `not_evaluated`; membership grants no lifecycle permission. |

Core and primary memberships are disjoint and exhaust the registry. Companion
references include relevant context/inspection, asynchronous observation and
cross-area workflow routes. For example, a changes lens can consume TODO work,
report its outcome and reconcile it through ordinary existing gates. A host
intersects exact `(tool, operation)` pairs with its supported adapters. Simple
`call` identities have no operation input; some multiplexers use `view` instead.
Fetch exact help rather than sending an `operation` field to every tool.

Area availability describes coarse prerequisites only. A selected milestone lens
can still require requirements. Configured provider settings do not prove a
provider is available. Operation descriptors say `availability: declared` and
`reason: operation_admission_not_evaluated`; packet, provider, model and execution
checks remain with their normal handlers.

## Selection and recovery

Keep one durable interaction per chat. Use ordinary `fow_interaction` discovery
and its issued choices to select or switch project and work lens. A catalog
contains no numeric selectors or executable next-action arguments. For an active
tool batch, settle its results before switching the bound selection and before
constructing the next model request. Restore the original chat interaction when
recovering a session; an unrelated interaction is not evidence of its selection.

A stale binding selects no Flow lens. Explicit ordinary interaction mutations
resolve it; reading the catalog never clears it, allocates a continuation or
repairs authority. If the catalog cannot be read or validated, fail closed and
show a recovery/update explanation. Do not substitute all tools, old frame
recommendations or a consumer-owned area map.

The catalog reads existing schema-55 state in one consistent SQLite snapshot.
It creates no new ledger store, migration, event, receipt or sequence and probes
no model or provider. Repeated identical reads and restart preserve the token;
selection, cleared event heads, registry or presented availability changes
invalidate it. The token is scoped to the bound connection/ledger, not server
authentication or a replacement for packet/provider/acceptance revisions.

Foreign provider selection is explicit, but the complete scope remains Flower
operations. CodingCastle and native host/Pi tool profiles retain their own
catalog authorities. This feature implements no writer witness or U6 integration.

## Upgrade boundary

0.6.0 does not support `catalog`. Use the reviewed
[SQLite-preserving upgrade procedure](UPGRADING.md#preparing-a-061-upgrade) and
refresh tool schemas and registry after installing 0.6.1. A locally built wheel
with metadata 0.6.0 is not the immutable official 0.6.0 wheel. Host fixtures,
source tests, installed package checks, CI, official downloads and an owner's
actual deployment are separate evidence; none alone certifies model usability or
human acceptance.
