# Advanced configuration: models and external providers

Flower works with an external coding agent and a persistent SQLite ledger without
an internal model or technical provider. Add an integration only for the operation
you need. This guide describes **Flower 0.5.2**, not an additional
service bundled with Flower. Published 0.4.1 remains a separate, immutable release.

## Choose the required integration

| Work | Prerequisites | Public entry point |
| --- | --- | --- |
| Requirements, plans, TODO, offline outcomes and handover | Flower core and the coding agent | Discover the current lifecycle recipe with `fow_capabilities`. |
| Host SRS semantic validation | Core, an importable SRS and the host agent | `fow_semantic`, role `srs_semantic_validation`, mode `host`. |
| Host intent grounding | Core, selected canonical goals and a closed host evidence receipt | `fow_semantic`, role `intention_grounding`, mode `host`. |
| Internal SRS semantic validation | The optional inference extra and a configured llama.cpp model | `fow_semantic`, role `srs_semantic_validation`, mode `internal`. |
| Internal intent grounding | Internal inference and a bound implementation-graph snapshot provider | `fow_semantic`, role `intention_grounding`, mode `internal`; existing `fow_ground_intent` route. |
| Observed-behavior drafting from existing code | Internal inference, a bootstrap-behavior provider and confirmed code-import intake | `fow_bootstrap`, operation `derive_behavior`. Host semantic assignments for this role are unsupported. |
| Packet target evidence | A bound service implementing the packet-evidence snapshot contract | Discover the packet-reconciliation recipe and its required evidence scope. |
| Optional technical packet/test execution | A compatible CodingCastle service, explicit project/session association and current admission | Packet/test lifecycle recipes and the [integration guide](NOXI-INTEGRATION.md). |

A provider is compatible only when it implements the specific versioned
contract. An arbitrary MCP server, an OpenAI-compatible chat API or a repository
graph is not automatically interchangeable with these adapters. The coding agent
still owns repository investigation, implementation and checks in the standalone
path. The suspended writer witness is not part of this release.

## Preserve the existing profile

Use `flower-mcp doctor` with the same `--profile` and `--profile-root` arguments
as your registered client to locate its existing `flower.yaml` and database.
For an explicit operator YAML, inspect that file and retain its runtime paths.
Back up before changing an existing installation; see [safe upgrades](UPGRADING.md).

Stop the Flower process that owns this profile before changing YAML. Merge the
blocks below into that file; do not replace its `runtime`, `logging` or other
integration settings. Keep `schema_version: 1`, the same database, import root,
logs and client command. Restart only this Flower instance to load configuration.
Never create a new profile or reset the ledger to enable a model.

Relative paths in explicit YAML resolve against that YAML's directory. Starting
with `--config /absolute/private/operator.yaml` cannot be combined with profile
selection. A registered stdio client starts Flower itself: do not also start a
second owner against its database.

Transport routes are operator configuration. Project associations are separate
ledger records: import/export through `fow_bindings` can change those associations
without restarting Flower or the host. An association cannot enable a disabled
route or change an endpoint.

## Enable internal inference explicitly

For a manual environment, install the selected Flower source or reviewed 0.5.2
release wheel with its `inference` extra. An installer-owned environment must
first complete its normal core upgrade, preserving its installation receipt;
then add inference from the exact verified Flower wheel/build recorded in its
installation receipt, matching both version and SHA256. A source or rebuilt
same-version wheel is not that receipt's artifact. Do not replace
an owned 0.4.1 or 0.5.0 installation with a 0.5.2 wheel through pip alone. Follow
[INFERENCE.md](INFERENCE.md) for exact upstream URL/SHA256, Windows commands,
offline acquisition and an explicit optional-runtime upgrade. Core installers
omit this extra. Enabling YAML does not install it.

Flower currently uses the independently published `runtime-llama` 0.4.1 library
with backend `llamacpp`. The operator supplies the already running llama.cpp
endpoint, loads the model and configures its context, slots and hardware.
Flower does not download or launch models.

Merge this model block, replacing the alias and bounds with the endpoint's actual
settings:

```yaml
model:
  enabled: true
  backend: llamacpp
  model: your-exact-loaded-model-alias
  base_url: http://127.0.0.1:8080
  context_length: 32768
  idle_timeout_sec: 60
  verify_ssl: true
  temperature: 0.1
  reasoning: "off"
  api_key_env: FLOWER_MODEL_API_KEY
```

Use the exact case-sensitive model alias from the endpoint's `/v1/models` catalog.
`base_url` identifies the server and omits a trailing `/v1`. The example context
32768 is not a claim about your model. `idle_timeout_sec` bounds streaming
inactivity; it is not a promised total duration for an engineering operation.
`reasoning` accepts `auto`, `off`, `on`, `low`, `medium` or `high`. `auto` follows
the model default; thinking can consume a role's bounded output budget and leave
a truthful `length_cap` result.

Keep credentials in the environment variable named by `api_key_env`, available
to the process that starts Flower. A terminal variable is not necessarily
inherited by a separately launched graphical client. Configure that environment
through your client's supported mechanism, then reconnect. Omit `api_key_env`
when the endpoint needs no key; never put a key in YAML, a URL, project evidence
or an association receipt. Keep TLS verification enabled for HTTPS endpoints.

Legacy `backend: lmstudio` and `auto_load` are rejected with migration guidance,
including when inference is disabled. Replace the backend/endpoint and remove
`auto_load`; do not copy old workstation configuration into a fresh installation.

### Prepare, execute, validate and adopt

After project selection, first call:

```json
{"project_id":"example","operation":"inventory"}
```

This is the argument object for `fow_semantic`. Replace `example` with the
selected lifecycle project throughout these examples. Inventory reports supported
roles and configured prerequisites; configured availability does not certify a
live endpoint or a ready selected model.

For an SRS available under Flower's configured import root:

```json
{
  "project_id":"example",
  "operation":"prepare",
  "role":"srs_semantic_validation",
  "execution_mode":"host",
  "source_path":"requirements.md",
  "standard_profile":"fow-srs-markdown-v1",
  "actor":"engineering-agent",
  "request_id":"example-srs-host-prepare-1"
}
```

Read the returned assignment and its exact prompt, allowed references, output
contract and source fingerprint. The host performs the assignment and submits
the contract-shaped result with `operation="submit"`, its returned
`assignment_id`, `executor_ref`, actor and request identity. Do not invent IDs or
replace the output contract with prose. `inspect` recovers durable assignment
state after interruption.
Use a new request key for each distinct mutation and retain it for an exact
retry; changing input under an existing replay key conflicts. The example key
is illustrative and must not be reused for another source or assignment.

To use the configured internal model, prepare with `execution_mode="internal"`,
then explicitly call `execute_internal` for the returned assignment. Preparing
does not execute it. Use a different prepare request key for this different mode.
Replace the placeholder with its actual returned assignment ID:

```json
{
  "project_id":"example",
  "operation":"execute_internal",
  "assignment_id":"<returned internal assignment_id>",
  "actor":"engineering-agent",
  "request_id":"example-srs-internal-execute-1"
}
```

Both modes use the same role validator. If the result is
validated and current, `adopt` records its canonical audit; review the disposition
and findings before continuing. Adoption is distinct from baseline import,
successful product verification and human acceptance. Invalid, stale or
noncompleted results do not become successful authority, and an internal failure
does not silently switch execution to the host.
Supply actor and an operation-specific request key for submit/adopt as well;
host submission additionally names the actual `executor_ref` and role-shaped
`result`. The prepared contract defines that result, so no canned answer is
provided here.

For host intent grounding, choose actual `goal_node_ids` from the selected
project and supply a `flower-host-grounding-evidence-v1` receipt as
`host_evidence`. Its closed fields are `contract_version`, `source_identity`,
`source_revision`, `truncated` and `anchors`. Every anchor declares `anchor_id`,
`kind`, `label` and `summary`; dependencies must refer to anchors in that same
receipt. Optional source paths are portable repository-relative paths, not host
absolute paths. Request the current operation help before assembling the receipt.
Submit the same declared `source_revision` with the result. The server records
host-declared evidence/currentness; it does not independently inspect the source
or relabel that evidence as provider-audited.

## Configure external technical providers

Provider transport uses HTTP(S) Streamable HTTP MCP. These are separately managed
services: Flower does not install them, start them, index their repositories or
grant them access. Establish the service's documented tools, contracts and
intended scope before enabling its route.

### Snapshot routes

The three optional keys under `providers` have different contracts:

| YAML key / binding kind | Required response contract | Use |
| --- | --- | --- |
| `implementation_graph` | `implementation-graph-snapshot-v1` | Bounded source evidence for internal intent grounding. |
| `bootstrap_behavior` | `bootstrap-behavior-snapshot-v1` | Observed-behavior drafting from confirmed code-import intake. |
| `packet_evidence` | `packet-evidence-snapshot-v1` | Revision-bound evidence for packet reconciliation. |

For a service that actually exposes the direct implementation-graph tool:

```yaml
providers:
  implementation_graph:
    enabled: true
    url: http://127.0.0.1:8020/mcp
    tool: implementation_graph_snapshot
    invocation: direct
    surfaces: [repo]
    bindings: []
```

The URL is an illustrative operator-selected endpoint, not a Flower default or
an automatically installed service. Merge this entry with existing `providers`;
leave unused entries disabled. Use the service's real tool name. `bindings: []`
keeps project associations out of YAML; import them through the ledger below.

A provider exposing its contract behind a public gateway can instead use
`invocation: advanced`. Set its actual gateway `tool`, `session_id`, `domain` and
`operation` from that provider's public discovery. Flower calls that tool with
`session_id`, `domain`, `operation` and a nested `arguments` contract object.
In direct mode those three advanced fields must be omitted. A per-project
provider context is supported by advanced routes and rejected by direct routes.

Authorize only the needed `surfaces`; receipts can select a subset of those
configured surfaces. Bootstrap configuration currently uses the surface
vocabulary `repo`, `workspace`, `docs`, `test_repo`, `cc_test` and requires `repo`.
The other snapshot routes must match their provider's supported scope and surfaces.
Snapshot validation checks identities, revisions and completeness; a name or
free-text description is insufficient evidence.

### Packet and test execution routes

The current execution adapters specifically support CodingCastle. Configure only
the route you intend to use, with an endpoint and session actually supplied by
that service's operator:

```yaml
packet_provider:
  mode: auto
  kind: codingcastle
  endpoint: http://127.0.0.1:8020/mcp
  tool: codingcastle_packet
  timeout_seconds: 30
  bindings: []

test_provider:
  mode: agnostic
  kind: codingcastle
  endpoint: ""
  tool: codingcastle_tests
  timeout_seconds: 30
  bindings: []
```

`agnostic` does not construct that execution adapter. `auto` uses it when
configured; `required` rejects missing configuration and requires the provider
for the relevant operation. Configure tests separately when needed; enabling
packet delivery does not enable test execution or internal inference.

`timeout_seconds` is a cumulative budget for each provider RPC, including startup,
transport and cleanup. One lifecycle call can perform several RPCs. A timeout
after a possible write leaves the original command UNKNOWN; it does not prove
the provider stopped or authorize another executor. Inspect and reconcile that
same command and fingerprint. See [exact recovery](NOXI-INTEGRATION.md).

Flower's current provider route configuration has no custom headers, token or
OAuth setup fields. Do not invent such keys or embed credentials in endpoint
URLs. Use an endpoint reachable under the operator's supported access controls;
deployments requiring additional provider authentication need an explicit
supported integration before they can be claimed compatible.

## Import a project association

Select or create the intended lifecycle project through the ordinary public
workflow. Call `fow_bindings` with `operation="inspect"` to see its current
associations and `authorized_routes`. Never infer authorization from a reachable
URL. A host association needs no technical provider:

```json
{
  "contract":"flow.project-association.v1",
  "project_id":"example",
  "association":{
    "kind":"host",
    "host_id":"linux-workstation",
    "repository_locator":"/home/alice/src/example"
  }
}
```

A direct implementation-graph association uses the already authorized logical
route, not its endpoint:

```json
{
  "contract":"flow.project-association.v1",
  "project_id":"example",
  "association":{
    "kind":"implementation_provider",
    "provider_kind":"implementation_graph",
    "route_id":"configured-mcp/implementation_graph",
    "scope_id":"provider-owned-scope",
    "provider_context_id":"",
    "surfaces":["repo"],
    "repository":null
  }
}
```

Replace the project, host/repository locator, route and provider scope with the
actual intended identities. Import with `fow_bindings`, `operation="import"`,
the receipt as `association_receipt`, actor and request identity. For
`packet_execution` or `test_execution`, use the corresponding authorized route,
`scope_id: ""`, `surfaces: []` and the actual session in `provider_context_id`.
Only `test_execution` can include a non-null provider `repository` selector.

An identical import returns the existing revision. A conflicting import reports
current/proposed associations and requires an explicit `replacement_reason`.
Export with `operation="export"` and either `association_kind="host"` plus
`host_id`, or `association_kind="implementation_provider"` plus `provider_kind`.
The host can save the returned JSON with its file tools. Receipts contain
associations, never transport URLs, credentials or executable commands.

A rebind does not transfer already admitted work to a new executor. For new
provider work follow explicit executor selection, negotiation and the current
PVP/admission gates in [NOXI-INTEGRATION.md](NOXI-INTEGRATION.md). Read-only
validation and TODO consumption do not execute code. Explicit
`fow_packet_advance(mode="sync_only")` delivers admitted deltas and returns
before a new START; it does not establish that an earlier run never started.

## Check availability and recover honestly

After restart, select the same lifecycle project. Use `fow_capabilities` to read
current recipes and exact operation help (`view="operation"`,
`operation_tool`, `operation_name`), then `fow_semantic(operation="inventory")`
and `fow_bindings(operation="inspect")` for the relevant setup. Configuration
and discovery are separate from an explicitly requested live execution.

| Result | Next action |
| --- | --- |
| Inference extra missing while `model.enabled: true` | Install the selected extra, or explicitly disable internal inference and use the supported host path. Startup explains the prerequisite. |
| `semantic_internal_runtime_unconfigured` | Inspect role inventory and configure internal inference; host execution is a separate explicit assignment. |
| Unsupported semantic role | Read inventory. Host observed-behavior drafting is not implemented; missing configuration cannot enable it. |
| `association_route_unauthorized` / disabled provider kind | Obtain operator route authorization before importing a provider association. |
| Unbound project, missing provider context or incompatible contract | Inspect binding/discovery and correct that prerequisite through ordinary authorized configuration or mutation. |
| Stale source/authority or invalid semantic output | Prepare from current authority, investigate gaps and submit the required contract; do not adopt stale results. |
| `implementation_provider_timeout` / uncertain delivery | Inspect and reconcile the original durable command; retain its identity and evidence. No automatic external fallback or duplicate START. |

Keep source tests, installed-package checks, live model/provider execution and
target-client usability as separate evidence. A configured optional adapter
does not certify a real provider pairing. Do not delete ownership locks, ledger
rows or receipt history to recover an integration. Preserve the existing profile,
use its durable handover and report unavailable checkpoints as blocked.
