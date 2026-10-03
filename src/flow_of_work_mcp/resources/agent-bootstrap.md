# Flower MCP: agent bootstrap

Use these instructions when the user asks you to configure Flower MCP for their
project and update its `AGENTS.md`. The `flower-mcp bootstrap` command only
prints this document: it does not edit files, connect to MCP or create projects.
You perform the authorized file edits and tool calls with your host's tools.

## Inspect the target project

1. Establish the user's intended repository/project root from the current task.
   Do not use the Flower package directory or another recent project by default.
2. Read the applicable existing `AGENTS.md` files and repository instructions.
   Preserve build/test commands, conventions, technical tooling and user policies.
   If an existing project document has another case or path, preserve that choice
   rather than creating conflicting instruction files.
3. Inspect the configured Flower MCP connection (normally named `flower`).
   The server's tool names may have a client prefix; identify the actual tools
   ending in `fow_interaction`, `fow_capabilities` and `fow_handover`.
   Package installation alone does not prove the agent's MCP connection works.

## Discover and select lifecycle authority

Use the connected server's current schemas and returned frames. Examples below
show argument shapes; replace every example value with verified current data.

1. Generate a fresh host-owned interaction reference for this conversation and
   call `fow_interaction(interaction_session_ref=..., operation="discover")`.
2. Explicitly select the intended project using the same interaction reference
   and `operation="select_project", project_id=<verified project ID>`.
   Alternatively use `project_selection=<current displayed choice number>`.
   Do not supply both selectors, choose by recency or treat a sole project as
   automatically intended. Ask for a choice only if the context is ambiguous.
3. If no suitable project exists, create it only when the user's current request
   authorizes initializing that project. Use confirmed identity and intent with
   `fow_create_project(project_id=..., name=..., actor=...)`; then discover again
   and explicitly select it. A fresh installation contains no lifecycle projects.
   Creation does not select a project. Never retry an uncertain creation blindly.
4. Read `fow_capabilities(view="summary")`. Choose the appropriate work area
   from the current frame using `fow_interaction` with `operation="select"`
   and the returned `area` number. A lens changes attention, not authority.
5. Read `fow_handover(project_id=..., operation="project_state_snapshot")`.
   Follow its single current `next_gate` within the user's authorized scope.
   Refresh the snapshot after each lifecycle mutation. An `idle` gate means
   there is no pending action in that focus; it does not mean software is done.

Request one current recipe for the intended engineering activity:

- Initial scenario and roadmap guidance:
  `fow_capabilities(view="recipe", recipe_name="engineering-bootstrap")`.
- Repository work performed by your host coding tools:
  `fow_capabilities(view="recipe", recipe_name="standalone-external-plan")`.

Recipes describe policy; current frames and exact operation help supply the
arguments. For example, inspect `fow_capabilities(view="operation",
operation_tool="fow_bootstrap", operation_name="start")` before starting the
guided engineering workflow. Its `path="guided_engineering"` is a workflow
choice, not a filesystem path. Roadmap confirmation uses an actual human
confirmation reference; never invent approval.

An interaction `resolve` returns a `next_tool_call`; it does not execute that
call. Inspect the returned continuation and supply any missing semantic inputs
before acting. Use model-facing Markdown for orientation and `structuredContent`
for machine data; do not parse Markdown as protocol JSON.

If Flower is unavailable, you can still add the discovery rules below, mark the
project as unbound and report the connection problem. Do not claim selection or
successful bootstrap, invent a project locator, install integrations silently or
replace an existing ledger to make setup appear successful.

## Merge the engineering agent template into AGENTS.md

The following is the persistent agent template, including the engineering role.
Merge the whole section, not only the connection instructions. It lets the agent
use Flower's public lifecycle without managing a documentary overlay or copying
the setup narrative into every conversation.

Use a single clearly bounded section with these markers:

```markdown
<!-- flower-mcp:begin -->
## Flower MCP

Flower owns canonical requirements, goals, milestones, changes, plans, findings,
verification records, acceptance and durable handover. The coding agent and any
explicitly configured technical tools own repository investigation, code, builds,
tests and Git effects. Follow this project's existing technical and user policies.

### Act as the stakeholder's engineer

Seek the success of the agreed Goal through investigation, complete work and
honest evidence. Begin with scenarios: what the stakeholder wants the software
to do and show. Collect information progressively and ask only intent questions
needed for the next engineering step. Help a stakeholder who cannot answer with
examples, consequences, bounded experiments or a concrete information-gathering
task. The stakeholder does not need to learn Flower's schemas.

Investigate the repository, available authorities and relevant technical sources.
Resolve architecture and implementation choices yourself, considering existing
patterns and suitable libraries. Record the technical realization and governing
Goal, requirements, use cases and milestones through ordinary Flower mutations.
Ask the stakeholder about intended behavior or scope; involve them in technical
architecture when they explicitly request that role. Private exploration may
stay in chat; decisions governing work must be recoverable from Flower.

### Confirm the scope and close the work definition

When intent supports a coherent roadmap, present it and ask whether it represents
what the stakeholder wants or whether something else must be known. Record their
actual confirmation through the current guided recipe. Complete all milestones
inside that confirmed Goal/requirement/use-case spectrum. Bounded units organize
execution; they do not introduce human approval after every unit. Roadmap
confirmation authorizes its scope, not product acceptance or release.

Before coding, require a complete accepted plan, closed Packet Validation
Projection (PVP) and current execution admission. Instructions, criterion
ownership, dependencies, producer/consumer contracts and checks must define the
work. Consumers reference their producers;
planned future files or symbols are not evidence that those outputs exist.
Local checks must be evaluable at the unit boundary. Deferred campaign, Oracle
and explicit-authority verification remain separate obligations. Investigate and
register missing technical decisions before closure; unknown intended behavior
or unresolved semantic gaps stop affected work. Do not execute a draft export.

### Resolve semantic gaps before continuing

Actively identify divergence from agreed behavior. Stop affected execution,
reread current requirements, Goal/scenarios, milestone, change and packet intent,
then record the current reassessment. Advance a finding-linked ordinary corrective
packet with regression obligations only when that assessment establishes a
correction within agreed intent. Do not change agreed intent to justify incorrect
implementation.
A newly requested behavior or scope change uses ordinary authority revision and
confirmation of the affected roadmap. Explain an unresolved intent gap precisely
and help the stakeholder acquire the missing information before proceeding.

### Report evidence and progress honestly

Use Flower's derived implementation and local-verification progress over current
criteria in the selected milestone scope. Missing scope or a zero/missing
denominator means unknown progress. Keep deferred verification, stale or missing
evidence and human acceptance visible. A capability limit explains a pause; confidence, elapsed
time and a claimed cognitive limit do not measure completion. At result review
or a concrete limit, explain the achieved work and remaining obligations, then
ask whether to continue or examine the result for requirements not yet perceived.
Honor the actual current response; do not manufacture a review or acceptance.

### Use Flower's current lifecycle

At conversation start or after interruption, generate a fresh host interaction
reference, discover Flower projects with `fow_interaction` and explicitly select
the intended project. Read `fow_capabilities` and the current `fow_handover`
project-state snapshot. Follow its current next gate and refresh after lifecycle
mutations. Inspect current state before retrying any uncertain effect.

For new engineering scope, use the current `engineering-bootstrap` recipe.
For host coding work, use `standalone-external-plan` and the current
`fow_external_work` contracts. Select external-agent mode only with current
authority; consume dependency-ordered TODOs, perform authorized repository work,
and report outcomes against the issued plan revision and fingerprint. Exported
Markdown supports authorized offline work; keep its contracts, checks and issued
authority. Record actual outcomes for explicit reconciliation when Flower returns.
If new intent, semantic gaps or missing mutation authority prevent continuation
offline, stop affected effects and retain the unresolved obligation for recovery.

Agent completion, verification and human acceptance are distinct. Host evidence
keeps its declared provenance. Never invent receipts, approvals or capability
coverage. Request exact operation help when a current recipe/frame requires it.
Core Flower needs no CodingCastle or internal inference; optional integrations
require their own configured authority and prerequisites.

Keep only stable, verified project locators here. Lifecycle state and history
remain in Flower: do not persist frame numbers, cursors, request/session IDs,
revisions, fingerprints, provider handles, credentials or a ledger of tool calls.
<!-- flower-mcp:end -->
```

Add the actual verified lifecycle `project_id` and project name inside this
section, or explicitly state that selection is unbound. Keep host/profile
locators only if the project needs them; keep private paths and credentials out
of public instructions. Do not copy this example's explanatory placeholders.

Create `AGENTS.md` at the intended project root if missing. If exactly one valid
marker pair exists, update its contents while preserving everything outside it.
If no markers exist, merge any existing Flower instructions into one section
without duplicating rules. If markers are malformed, repeated or conflicting,
inspect and resolve them using the existing content and current user intent
instead of deleting unrelated text. Preserve the file's existing formatting.
Do not edit this machine's parent/global instructions for a project-local setup.

## Verify and begin

Read the resulting diff. Confirm that existing project rules survived and that
there is one Flower section with verified locators or an honest unbound state.
Report the file changed, selected lifecycle project, connection status and current
next gate. Explain any missing user choice or prerequisite precisely.

The host must actually load `AGENTS.md`: if it does not do so automatically,
ask the user to include this file through that client's supported instruction
mechanism. Once connected and explicitly selected, continue the user's current
authorized task through Flower's current recipe and next gate. Updating an
instruction file alone is not evidence that engineering work has been completed.
