# Flower at Linux Day: a 20-minute outline

[Index](README.md) · [Scenario](scenario.md) · [Sources and limits](sources.md)

## Audience and timing

This outline addresses a mixed Linux audience and focuses on practical Flower
use. These timings need an aloud rehearsal, with a dedicated demonstration
project ready before the talk.

| Minutes | Topic |
| --- | --- |
| 0–2 | Conflicting bookings and lost project context |
| 2–5 | Require and Plan: expected behavior and defined work |
| 5–8 | Build: recovering a plan and the agent's responsibilities |
| 8–12 | Verify: reported results, evidence and acceptance |
| 12–14 | Deploy and Operate: delivery and correction within scope |
| 14–17 | Local dashboard: project, packets and retained Markdown |
| 17–19 | Installation, bootstrap and the first project |
| 19–20 | Closing and the first question |

## Opening

"Two people book the same room. The code compiled, the tests were green and the
screen looked good. What had we actually asked the software to do?"

This question introduces Spazio Comune without requiring knowledge of MCP.
Show the logo after the question: the petals name the perspectives, not the answer.

## Main path

| Step | What to show | Message to leave |
| --- | --- | --- |
| [Require](01-require.md) | Two simultaneous requests. | An observable result comes before technology. |
| [Plan](02-plan.md) | The contract between service and interface. | Dependencies need meaning, not just names. |
| [Build](03-build.md) | A plan that survives an interruption. | The agent executes; Flower preserves work authority. |
| [Verify](04-verify.md) | Four state dimensions. | A local check does not promote itself to campaign or acceptance. |
| [Deploy](05-deploy.md) | Delivery with open obligations. | Explicit limits make a promise inspectable. |
| [Operate](06-operate.md) | A bug or a recurring booking? | Correction and new intent require different paths. |

A short talk can use just the six pages. Concepts, tools and sources remain
detours for questions: there is no need to read a catalog on stage. The outline above reserves three minutes for the dashboard without reading the tool catalog.

To discuss the project's origins, open [How I built it](method.md): distinguish
agent-written code from the author's design and decisions. The crops show the
method, not certification of test outcomes.

## Three minutes in the dashboard

Open Flower 0.12.0 at its local `/dashboard` address in advance, with streamable HTTP and a dedicated
demo profile. Sign in with the local account before the talk. During the talk, show a project, its next gate, a packet and
already retained Markdown: **Lettura**, its outline, then **Sorgente**. Switch
the theme to show light/dark preference and the system default without changing
the project.

Explain that deletion requires instance-wide maintenance and explicit
confirmation. Showing its entry point is enough for the talk. Actual deletion
requires a disposable project, verified stop of owned workers and the ordinary
guards. A filled field does not prove that a host stopped. The live dashboard
reads the ledger. The HTML presenting these chapters is the separate offline
presentation reader.

## If we want a real demonstration

The written story is not a transcript. A later demo should select an isolated
project, use current contracts and preserve real receipts:

1. show a criterion without verification or a consumer without a producer;
2. read the gap returned by Flower;
3. complete the declaration and show the updated projection;
4. export the plan and distinguish executable work from deferred obligations.

Do not put invented IDs into calls. Do not use the private runtime project as
though it were a demo environment. Do not show "accepted" without a real
decision. If the network is unavailable, the editorial presentation is already
offline; it must not pretend to be a successful live demo.

## Questions that deserve explicit answers

- **"Why isn't a document enough?"** The exported document is useful. Flower
  adds canonical state, revisions, gates and reconciliation through the server.
- **"Can the model ignore it?"** Yes, an agent can use other tools: Flower is
  not a sandbox for its host. Adherence is tested, not presumed.
- **"Do I need a local model?"** Not for the standalone core. An internal model
  and providers are optional for specific capabilities.
- **"Does it guarantee correct software?"** No. It bounds work, evidence and
  decisions; agent quality, plan quality and oracles remain decisive.
- **"Are Deploy and Operate automated?"** No. The story concerns governed
  delivery and changes, not built-in CI/CD or monitoring.

## Closing

"I am not asking the model to remember better. I am making what we decided,
which work we assigned and what remains before calling it done recoverable."

Close by opening [Now try Flower](try-flower.md): show the repository, release and
installation route for the audience's operating system. Connect bootstrap to
Require's first question, without presenting it as a seventh petal or a demo
already executed.

[Install and try Flower](try-flower.md) · [Index](README.md) · [Tool catalog](tools.md)
