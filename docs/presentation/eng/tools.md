# The public-tool map

[Index](README.md) · [Concepts](concepts.md) · [Sources](sources.md#catalog)

Names retain the technical `fow_` prefix. A client may add its own prefix. This
map describes the **36 tools in the reference source**; it is not a list of
payloads to copy. A multiplexed tool offers several operations with different
prerequisites. The current server catalog remains the operational authority.

## Orientation and bootstrap

| Tool | Purpose |
| --- | --- |
| `fow_capabilities` | Read a summary, one recipe, an operation contract or detailed documentation. |
| `fow_create_project` | Create an isolated lifecycle project. Creation does not select it. |
| `fow_interaction` | Select a project and lens, obtain an operational frame and resolve a choice. Resolution suggests a call; it does not execute it. |
| `fow_bootstrap` | Manage intake, answers, correspondences, roadmap and confirmations. Binding operations have their own prerequisites. |

## Requirements and behavior

| Tool | Purpose |
| --- | --- |
| `fow_register_requirement` | Register a canonical requirement. |
| `fow_get_requirement` | Retrieve a requirement and immutable history. |
| `fow_revise_requirement` | Append a revision instead of overwriting its predecessor. |
| `fow_set_requirement_lifecycle` | Execute a policy-permitted transition. |
| `fow_goal` | Define and read use cases, sequences and behavioral expectations. |
| `fow_validate_srs` | Start structural SRS validation with durable job state. Semantics use a distinct path. |
| `fow_import_srs` | Validate and atomically import an accepted initial baseline. |
| `fow_revise_srs_baseline` | Classify and register a baseline revision with source provenance. |

## Milestones

| Tool | Purpose |
| --- | --- |
| `fow_promote_milestone` | Define the scope and policies of a planned milestone. |
| `fow_accept_milestone` | Record governed acceptance with required evidence. It is not a synonym for planning. |

## Changes and work

| Tool | Purpose |
| --- | --- |
| `fow_change` | Govern changes, dependencies, state and evidence; packets have dedicated surfaces. |
| `fow_packet_author` | Build canonical packets, units, declarations and plans. |
| `fow_packet_advance` | Advance deterministic gates to a decision or asynchronous boundary. The selected technical path may require a provider. |
| `fow_packet_inspect` | Read scope, units, gates or history through bounded projections. |
| `fow_external_work` | Validate a standalone plan, select external mode, export Markdown, read TODOs and record/reconcile outcomes. It does not execute code. |
| `fow_run` | Manage implementation-run records, steps, dependencies and work views. It is not a new coding agent. |
| `fow_what_next` | Derive next work from durable state, with pagination. |

## Evidence and campaigns

| Tool | Purpose |
| --- | --- |
| `fow_record_verification` | Record declared deterministic or live evidence. It does not generate test results by itself. |
| `fow_traceability` | Read a paginated project traceability projection. |
| `fow_audit_phase` | Start a phase audit on declared scope; prerequisites depend on the audit. |
| `fow_assurance` | Record findings, reassess intent, link corrections and govern assurance decisions. |
| `fow_campaign_author` | Build campaigns, cases, obligations, oracles and materialization authority. |
| `fow_campaign_advance` | Advance deterministic work to a semantic, technical or evidence boundary. Technical execution requires an available path. |
| `fow_campaign_inspect` | Read a campaign, working sheet, components or history. |

## Continuity and artifacts

| Tool | Purpose |
| --- | --- |
| `fow_handover` | Read a coherent snapshot, progress and bounded history; create or recover a handover. |
| `fow_generate_artifacts` | Start artifact generation under supported profiles with a durable job. |
| `fow_get_artifacts` | Retrieve stored artifact metadata and content. |
| `fow_get_job` | Observe job state. Observation does not restart it. |
| `fow_list_jobs` | List a project's jobs. |

## Associations and optional semantics

For ownership and prerequisites of the integrated path, see
[cross-server features](advanced.md).

| Tool | Purpose | Limit to remember |
| --- | --- | --- |
| `fow_bindings` | Inspect, export or import host/provider association receipts. | Receipts do not install endpoints, credentials or commands. |
| `fow_semantic` | Inventory roles; prepare, inspect, submit and adopt SRS/grounding results; or explicitly invoke internal mode. | Host execution requires no internal model; internal mode does. Unsupported roles remain visible as a limit. |
| `fow_ground_intent` | Start internal intent grounding. | Requires a model and source provider; it is not a core standalone prerequisite. |

## Discover details without memorizing everything

Read-only call examples, without invented project locators:

```json
{"view": "recipe", "recipe_name": "standalone-external-plan"}
```

```json
{"view": "operation", "operation_tool": "fow_external_work", "operation_name": "export_plan"}
```

These are `fow_capabilities` arguments, not plan-execution commands. The recipe
explains the workflow; the operation contract exposes fields and constraints;
the current frame provides choices permitted by the project state.

[Index](README.md) · [Follow Build in the story](03-build.md)
