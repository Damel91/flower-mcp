# Configure a project's agent instructions

After installing Flower MCP and reloading the selected coding agent, use the
installed command to obtain the model bootstrap:

```sh
flower-mcp bootstrap
```

Use the absolute command path printed by the curl installer if it is not on PATH.
For a source checkout, run `.venv/bin/flower-mcp bootstrap`. The command prints
instructions bundled in the package; it does not change files or start a server.
Each GitHub Release also provides the same instructions as `BOOTSTRAP.md`.

Give your model this request while working in the intended project:

> Run the installed Flower MCP command with `bootstrap` and follow its output to
> update this project's AGENTS.md. Preserve the existing rules, merge one Flower
> section, and verify the connection and explicit lifecycle-project selection.
> Use the current server recipes to begin the work I have authorized. If a project
> choice or connection prerequisite is missing, report it instead of guessing.

Replace "the installed Flower MCP command" with its actual executable path when
needed. If you installed with `--no-register`, first configure the intended agent
using the [installation instructions](INSTALLATION.md).

The model reads existing project instructions, discovers projects through
`fow_interaction`, explicitly selects the intended one and reads the durable
snapshot through `fow_handover`. An empty profile requires a new project only
when your request authorizes creating it. Current `fow_capabilities` recipes
guide the next action. The model adds or updates a bounded Flower section and
keeps your existing build, testing and repository rules.

## Compact guided continuation and explicit details

For `path=guided_engineering`, ordinary state-returning responses show a brief
operational view: current status, counts, the changed answer key/revision, the
first blocker and the current `next_gate`. Repeated answers and audit payloads
stay in complete structured state instead of being echoed after every answer.
The next gate is an action template: supply its actual required inputs and
prerequisites; it is not permission to skip engineering or confirmation.

- `state` reads the compact continuation.
- `state_details` explicitly reads full state and the recent ten-event audit
  window. This window is not the complete audit history.
- `guidance` reads full canonical context and existing gate explanations.
- `roadmap` returns the complete scope reference using explicit existing
  milestone IDs; it never creates missing milestones.

Machine consumers retain `result.bootstrap` and can read the additive
`result.operational_projection` (`flow.guided-bootstrap-operational.v1`). Its
`detail_calls` provide explicit read calls. Normal bounded-identity Markdown is
at most 8,192 characters; unusually large legacy identities retain their exact
read call even if that boundary itself exceeds the budget. No machine gate is
silently truncated. Projection/detail reads invoke no model or provider.

Guided engineering uses selected answers, ordinary canonical authoring,
correspondence and explicit roadmap confirmation. The intake/import paths are
separate; `derive_behavior` is code-import-only and requires its optional
provider/model prerequisites. Request one operation's exact contract through
`fow_capabilities` rather than applying another path's steps.

## The persistent engineering agent template

The printed bootstrap contains one complete, marked template for the project's
`AGENTS.md`. Merge the entire section, including the engineering mindset:

- Help the stakeholder describe scenarios of what the software should do and
  show; ask progressive intent questions needed for the current step.
- Investigate technical architecture, implementation and reusable patterns or
  libraries, then register governing decisions through Flower. Stakeholder
  participation in architecture is explicit.
- Present and record actual roadmap confirmation; complete the milestones in
  that scope without introducing approval after each bounded unit.
- Require a complete accepted plan, closed Packet Validation Projection (PVP)
  and current admission before coding. Keep producer/consumer contracts and
  local versus deferred verification explicit.
- Stop affected work on semantic gaps, reread canonical intent and record its
  reassessment. A finding-linked corrective packet and regression can proceed
  only when the assessment establishes a correction within agreed intent.
- Report Flower's current criterion-based progress and evidence honestly,
  keeping implementation, verification and human acceptance separate. Execute
  authorized offline work from its export and reconcile explicitly later.

The template is embedded in the single canonical resource
`src/flow_of_work_mcp/resources/agent-bootstrap.md`. The installed command and
release's `BOOTSTRAP.md` provide the same complete bytes. Project agents use
Flower's public recipes and durable snapshots; they do not need the development
repository's overlay, implementation indexes or campaign administration.

Printing the template and preserving its package bytes qualify distribution
mechanics. Actual model adherence, cognitive fit and novice usability require
their own trials.

`AGENTS.md` stores stable project locators and operating rules. Requests, cursors,
plan revisions, fingerprints, runtime history and credentials belong outside it.
For public repositories, omit private host/profile paths. A client that does not
load `AGENTS.md` automatically needs its own supported instruction mechanism to
include it; creating the file alone does not activate it in every host.

Reading the bootstrap and updating instructions do not perform engineering
work or grant human acceptance. The model continues only the current authorized
task, using the connected server's current authority and next gate.

## Guided input contracts and recovery

Before recording a selected answer or its canonical correspondence, request
`fow_capabilities(view="operation", operation_tool="fow_bootstrap",
operation_name="record_answer")` or `operation_name="record_correspondence"`.
The operation help includes the exact nested schema, required fields, accepted
values and an example. Replace example locators with current returned identities.
Correspondence uses the recorded answer revision and at least one existing
requirement, goal or milestone; it does not certify semantic truth.

Starting against an existing project requires its registered name. A rejected
start exposes a typed cause, current project/bootstrap context and one explicit
`next_tool_call`. Inspect an active bootstrap instead of starting another. A
changed replay payload requires inspection of its original owner, not a blind
retry. Suggested recovery is never performed automatically.

## Canonical architecture and bounded reconciliation

Use the `provider-agnostic-engineering-cycle` recipe for architecture, work
completion and context recovery. The marked agent template now keeps governing
architecture in Flower, with repository Markdown limited to explanation or a
revision-linked export. Newly accepted plans require adopted architecture and
valid packet references. Existing issued plans retain their contract.

At packet/increment completion, the host compares repository facts with scoped
authority and original evidence, then records the current repository review.
Missing registrations do not prove missing code; historical evidence keeps its
original pin and provenance. Unit outcomes remain true while reconciliation is
open. This is a boundary check, not a review after each tool call or a reason to
repeat previously valid tests. Follow the current frame's next gate and request the named recipe from the
connected server for its exact policy.

Updating Flower does not overwrite existing project instructions. Run the new
`bootstrap` command and explicitly merge its marked section when authorized,
preserving other rules. The host remains responsible for loading that file.
