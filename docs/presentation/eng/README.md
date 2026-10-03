# Flower MCP: from requirements to software

![Flower MCP: Require, Plan, Build, Verify, Deploy, Operate](../assets/flower-mcp-logo.png)

[Italiano](../ita/README.md) · [Available languages](../README.md)

**Writing code is part of the job. Keeping what we wanted, what we built and
what we can demonstrate connected is another.**

This presentation follows the development of **Spazio Comune** ("Shared Space"),
a small room-booking service for an association. One story spans the six petals
of the logo: Require, Plan, Build, Verify, Deploy and Operate.

> Spazio Comune is an educational scenario, not a delivered application or a
> passed benchmark. Conversations, requirements and plans are editorial examples.
> Behaviors attributed to Flower are linked to its public sources.

## One story, six questions

| Chapter | Question | The problem we will encounter |
| --- | --- | --- |
| [1. Require](01-require.md) | What does "book a room" actually mean? | An understandable wish is not yet a defined behavior. |
| [2. Plan](02-plan.md) | Can the plan be executed without inventing its missing parts? | A task list can hide dependencies and decisions. |
| [3. Build](03-build.md) | Who writes the code, and what does Flower maintain? | The agent's work must remain connected to recognizable intent and revision. |
| [4. Verify](04-verify.md) | What exactly have we verified? | "The tests pass" does not mean "the behavior has been accepted." |
| [5. Deploy](05-deploy.md) | What are we authorized to deliver? | A local result does not prove operation in the target environment. |
| [6. Operate](06-operate.md) | Does this issue change the software or change the request? | Fixing a defect and introducing a feature are different decisions. |

The presentation closes with [Now try Flower](try-flower.md): the repository,
public downloads, prerequisites and connecting an agent to your first project.

## Three participants, three responsibilities

- **The person:** clarifies intent, confirms scope and owns the acceptance and
  delivery decisions assigned to them.
- **The coding agent:** investigates, chooses the technical implementation,
  writes code, runs checks and reports results through its host's tools.
- **Flower MCP:** preserves lifecycle state, applies the gates defined by its
  contracts and returns context, work and evidence provenance.

Flower is not a new model and does not replace the coding agent. The core does
not require CodingCastle or an internal model. A capable agent is still needed:
the server does not decide whether a requirement is right or whether the software
has value for its user.

## You can also read by topic

- [The complete scenario](scenario.md): people, scope and open questions.
- [Essential concepts](concepts.md): lenses, packets, PVP, TODOs and current evidence.
- [The public-tool map](tools.md): which tools belong to each area.
- [Comparison with other planes](comparison.md): strengths, tradeoffs and use cases, including the documentary Flow.
- [Advanced integrations](advanced.md): cross-server evidence, packets, workspace and campaigns.
- [How I built it](method.md): agents, the documentary plane, time and source size.
- [Sources and limits](sources.md): the basis of the claims and what we do not promise.
- [The talk outline](talk.md): a short path, questions and useful detours.
- [The local reader](reader.md): offline access to the same Markdown.

This is not a one-way chain. A test can take us back to requirements; an issue in
use can open a change. The petals tell the lifecycle story, not six automatic
steps or six tools to execute in sequence.

**Start with [Require](01-require.md).**
