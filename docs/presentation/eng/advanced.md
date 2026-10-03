# Flower beyond the standalone path

[Index](README.md) · [Comparison](comparison.md) · [Tool map](tools.md)

**Flower can govern the lifecycle without executing code. Cross-server
integrations connect that lifecycle to an evidence and execution provider
without merging their responsibilities.**

The base path remains the one described in [Build](03-build.md): a coding agent
receives a plan or TODO, works through its own host and reports outcomes. The
integrated path adds direct exchanges with compatible services. CodingCastle is
the technical provider for which the public source contains packet and test
adapters; it is not a dependency of Flower's core.
[Provider factory](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/runtime_factory.py).

## Who owns what

| Party | Responsibility |
| --- | --- |
| Flower | Intent, requirements and scenarios, milestones, changes, semantic packets, findings, campaigns, acceptance and handover. |
| Technical provider | Technical context, target identities, source evidence and, where supported, executable packets, workspace, compilation and tests. |
| Orchestrator | Evidence selection, semantic interpretation, decisions permitted by the current gate and handling gaps. |
| Person | Intent confirmation and the human acceptance and delivery decisions required by the path. |

A reachable provider is not automatically the project's provider. A passing
test is not automatically an accepted milestone. These distinctions are part
of the [public recipes](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Portable associations, not hidden configuration

`fow_bindings` can inspect, export and import host/project or project/provider
associations through versioned JSON receipts. The logical association can
change without restarting the plane: the ledger preserves the choice and
revision, and a conflicting replacement requires an explicit reason.

A receipt does **not** install a server or configure endpoints, credentials or
commands. The operator must already have authorized the provider route. Moving
an association does not mean moving the whole runtime or obtaining authority
to modify a repository.
[Association contract](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/application/association_receipts.py).

## Coordinated lens orientation

When the technical context is associated, `fow_interaction` can combine
Flower's areas with those discovered through `codingcastle_interaction`, showing
availability and prerequisites. Flower retains the coordinated lens; provider
discovery is read-only and does not alter its standalone lens.

A lens changes attention, not the tool catalog, lifecycle or permissions. If
the provider is unavailable, the frame exposes degraded coordinated mode and
any blocked technical area rather than pretending it is available.
[Orientation adapter](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/adapters/implementation_intelligence/interaction_provider.py), [interaction projection](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/application/interaction_projection.py).

## Source snapshots and intent grounding

Evidence adapters receive bounded snapshots of implementation, bootstrap
behavior and packet targets. They check the contract, binding and required
revision references: names or descriptions alone are not current evidence.
Search and the graph remain in the provider; Flower consumes a projection
for its engineering work.
[Snapshot adapters](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/adapters/implementation_intelligence/mcp_provider.py).

Grounding relates intent to observed implementation. `fow_ground_intent` is the
internal path using a model and source provider. `fow_semantic` also offers
host-executed assignments with inputs and an output contract prepared by Flower;
host grounding uses a closed evidence receipt and preserves host-declared
provenance. It does not automatically convert that evidence into provider
attestation.
[Semantic recipe](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## From semantic packet to technical work

Flower maintains ordered instructions, checks, dependencies and unit intent.
The orchestrator chooses readable candidates; the provider resolves exact
technical targets. Graph identities, execution handles and transport
correlations remain behind that boundary rather than becoming content to
paste into a plan.

In the configured path, `fow_packet_advance` can delegate operations to the
`codingcastle_packet` adapter and reconcile receipts. Internal execution and
the workspace belong to CodingCastle; Flower does not become a second
compilation engine. An absent or incompatible provider, or stale evidence,
leaves a gate open rather than authorizing invented execution.
[Packet adapter](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/adapters/implementation_intelligence/packet_provider.py), [reconciliation recipes](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Workspace review and semantic correction

A review must address the current candidate and make targets, coverage and
evidence explicit. Flower records the disposition and finding history; the
provider identifies the workspace. A partial review does not become complete
approval merely because it contains no error.

A semantic defect found after review feeds an ordinary corrective packet. It
is not automatic technical retry of failed compilation. The recipe separates
continuation, verification, remediation and blockage.
[Review and remediation recipes](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Campaigns, oracles and provider tests

Flower defines expected behavior, cases, obligations and oracle meaning. The
provider materializes and runs tests in the supported path. The
`codingcastle_tests` adapter distinguishes orchestrator-supplied source from
deterministic oracle IR; the latter requires a compatible profile declared by
the provider. This is not a promise of universal generation for any language
or framework.

Progression requires materialization authority and current attested results.
A test that compiles but lacks the required attestation cannot establish
authoritative product failure. Acceptance remains a separate decision.
[Test adapter](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/adapters/implementation_intelligence/test_provider.py), [campaign recipes](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Two audiences, two projections

The model receives readable Markdown content. Server-to-server exchanges
instead consume MCP `structuredContent` under versioned contracts: they do
not reinterpret model-facing text as JSON. Readable output and structured
receipts serve different audiences.
[Structured-channel decoding](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/adapters/implementation_intelligence/mcp_provider.py).

## What is present and what remains open

| Area | Status and prerequisites |
| --- | --- |
| Core and external coding-agent plan | Standalone path; no mandatory technical provider or internal model. |
| Association receipts | Contract and services present; a provider route needs operator authorization. |
| Coordinated lens | Optional technical discovery; associated context and available provider, or declared degradation in the frame. |
| Evidence snapshots | Adapters present; a service must honor the specific contract, binding and revision. Merely "speaking MCP" is insufficient. |
| Technical packets and tests | Optional CodingCastle adapters present; they require compatible service, context and capabilities. They do not automatically make every coding agent interchangeable. |
| Internal semantics | Requires an inference runtime; the host alternative exists for supported roles, not every operation. |
| Full cross-server PVP | Explicitly deferred, together with CodingCastle compilation in the IMPL-67 family and paired qualification. Standalone PVP does not certify this path. |

The presence of adapters in source **does not certify every running version
combination**. This page describes capabilities and boundaries of the reference
source, not a new live campaign for the Flower/CodingCastle pair.
[Factory](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/runtime_factory.py), [status declared in recipes](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Spazio Comune with a provider

In our example, Flower preserves the rule "two concurrent bookings must not
occupy the same room" and governs its corrective packet. A compatible provider
supplies targets and workspace; the campaign connects the test to the rule and
its oracle. The technical result returns as evidence, not an automatic delivery
decision.

This is an illustrative path, not an executed run. The architectural benefit
is connecting intent and technical work without giving them one owner. The
standalone path remains sufficient to start using Flower.

[Index](README.md) · [Verify](04-verify.md) · [Integration sources](sources.md#cross-server-integrations)
