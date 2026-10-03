# Which plane for which job?

[Index](README.md) · [Concepts](concepts.md) · [Advanced integrations](advanced.md)

**The useful comparison is not "who has more tools", but "which state must
survive the conversation, and who governs changes to it".**

Flower is not the only project that organizes an agent's work. Some tools focus
on specifications, others on backlogs or task gates. The documentary Flow of
Work instead starts with readable, versionable contracts without requiring an
MCP server.

## How to read this comparison

A survey of official sources consulted on **2 October 2026**. The table lists
documented capabilities; strengths, tradeoffs and recommended cases are an
editorial assessment, not results from a comparative benchmark.

We have not installed and qualified every project. A feature not mentioned here
**must not be treated as absent**. Stars, contributor counts and tool counts do
not measure the correctness of the software produced.

## Five alternatives, five centers of gravity

| Plane | Center of gravity | Strengths | Tradeoff to consider | Recommended use case |
| --- | --- | --- | --- | --- |
| [Flower MCP](../../../README.md) | Requirements, goals, milestones, changes, work, evidence, acceptance and handover in a persistent ledger. | Connects intent and current work; separates completion, verification and acceptance; offers Markdown plans and TODOs for external agents. | More concepts to learn than a backlog. Host declarations are not an automatic source-code audit. | A product spanning multiple iterations, where the reasons for work, verified outcomes and open obligations must remain visible. |
| [Documentary LLM Flow of Work](https://github.com/Damel91/LLMs-flow-of-work) | Markdown contracts, authorities and implementation chains; **not an MCP server**. | Git-inspectable documents; usable in chat; `flowctl` helpers for checks and orientation. | Human routing and documentary discipline remain central; consistency is not entirely governed by a server ledger. | A team or engineer making method and decisions explicit without introducing a persistent service. |
| [Spec Workflow MCP](https://github.com/Pimzino/spec-workflow-mcp) | Requirements → Design → Tasks specifications, approvals and tracking. | Dashboard, VS Code integration, revisions and implementation logs. | The approval path requires human coordination through its interface; document approval does not prove implemented behavior. | A feature to clarify and approve before implementation. |
| [Task Master AI](https://github.com/eyaltoledano/claude-task-master) | PRD to backlog: tasks, dependencies, expansion and next work. | MCP and CLI access; assistance with decomposition and research. | AI commands need inference access; the generated plan needs judgment, not just execution. | Turning a product brief into operational tasks for a coding agent. |
| [MCP Task Orchestrator](https://github.com/jpicklyk/task-orchestrator) | Persistent work items, dependencies, note schemas and server-governed transitions. | Server-side structural gates and actor attribution. | Work schemas need design; required notes and valid transitions do not themselves demonstrate semantic correctness. | Coordinating agents or sessions with required deliverables before progression. |

## Where Flower fits

Flower's design choice is to preserve a **lifecycle chain of authority**, not
just a task list: requirement and scenario, milestone scope, change, plan,
finding, verification, acceptance and handover. Revisions and evidence
provenance help prevent yesterday's result from becoming completion of today's
work. The core can do this without CodingCastle or an internal model.
[Flower sources](sources.md#plan), [external work](sources.md#build).

**Server-side gates are not exclusive to Flower.** The comparison with Task
Orchestrator primarily concerns the governed domain, not the presence or
absence of structural control. Choosing Flower should reflect a need for its
lifecycle connections; for a simple task queue they may be unnecessary cost.

Portable plans do not eliminate the ledger: an exported document permits
offline work, but outcomes, current revision and decisions must be reconciled
on return. [Advanced integrations](advanced.md) add evidence and technical
execution through providers; they are not required for the standalone path.

## One story, different choices

For **Spazio Comune**, the practical question might be:

- "I want Git-readable contracts and decisions, with a person at the helm":
  start with the documentary Flow.
- "I want to approve the booking specification before implementing it":
  consider Spec Workflow MCP.
- "I have a PRD and need an actionable backlog": consider Task Master AI.
- "Several agents must provide required notes and respect dependencies":
  consider Task Orchestrator.
- "I must distinguish the initial request, concurrency defect, correction,
  verified regression and milestone acceptance": consider Flower.

These are selection guidelines, not a ranking. An evening prototype and a
service maintained for months may need different governance levels. More
structure helps only when it addresses a real problem.

## Before choosing

Ask each solution the same questions: where state lives, how it recovers after
interruption, which decisions block progression, what counts as evidence and
how much work it asks of the user. Then try the same small scenario on your
own host and agent.

This comparison does not certify performance, security, model autonomy or
Flower's superiority. Such claims require comparable campaigns, not just
reading READMEs.

[Index](README.md) · [Comparison sources](sources.md#comparing-planes) · [Cross-server features](advanced.md)
