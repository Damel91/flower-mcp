# How I built Flower MCP

[Index](README.md) · [Comparing planes](comparison.md) · [Sources and limits](sources.md)

> "I have a job, and I did not personally write a single line of this project's
> code. I designed the system, discussed requirements, guided the agents and
> decided what to verify, correct and accept."

This is the author's account of the method, not an autonomy benchmark.
Delegating code writing did not remove the engineering work: it shifted my
contribution toward intent, architecture, constraints and verification.

## Personal experiments and learning

Flower MCP, the documentary framework and the experimental coding component
are **personal experiments**, started to acquire software-development skills
with emerging technologies. In particular, I explore coding agents, the MCP
protocol, local models and methods to govern and verify software produced with
their help.

These projects are separate from my professional work. Publication shares the
method and usable results of this personal research; it does not represent a
product or activity of my employer.

## Tools and time

| Aspect | How I worked |
| --- | --- |
| Main coding agent | **Codex**, with different models over the course of the project. |
| My role | Design, discussion of choices, review of outcomes and acceptance decisions. |
| The agents' role | Reading code, technical planning, implementation, tests and document updates. |
| Time spent on the server | **Around two months of concentrated development**, carried out after working hours. |
| Wider context | Earlier and ongoing research into coding agents and local models. |

I developed the projects in my personal time, after working hours. I kept my
professional work and this research separate, including their application domains.

The duration is the author's estimate: not a work-hour log or the total research
period. The public copy was prepared toward the end of that process; its Git
creation date is not the start of development. I do not attribute the outcome
to a single model version.

## Before the server: the documentary plane

Flower did not start with a single conversation asking an agent to "build an MCP
server." Work was governed by a **documentary plane**: linked documents separating
requirements, decisions, changes, implementation packets, reviews, findings and
test campaigns.

[![Project authority structure: baseline, campaigns, contracts, diffs, implementation and reviews](../assets/method-authorities.png)](../assets/method-authorities.png)

*A crop of the adopted document structure. It shows categories, not document contents.*

The loop was practical:

1. clarify expected behavior and its limits;
2. record the requirements change and design an implementation chain;
3. give the agent packets with actions, dependencies and checks;
4. inspect the outcome with deterministic tests and live campaigns where relevant;
5. record issues, correct them and decide what to accept;
6. keep documentary and implementation commits separate.

[![Example list of implementation chains and packets](../assets/method-plan.png)](../assets/method-plan.png)

*Plans were persistent artifacts, not just messages to remember in a chat.*

[![Campaign list covering Flower bootstrap, handoff, installation and release](../assets/method-campaigns.png)](../assets/method-campaigns.png)

*A campaign document does not prove that every test passed: outcomes require
their evidence and decisions, which are not published here.*

## Why this method

With interrupted work sessions, I did not want to start over each time by
explaining earlier decisions. Nor did I want a convincing agent response to
automatically become an accepted change.

The plane let me resume from a specific obligation, distinguish a bug from a
new requirement and compare the outcome with the original intent. Documentary
discipline adds work, but makes decisions open to challenge and state recoverable
even when the chat or model changes.

**Flower moves part of that discipline from documents into a server:** state,
revisions, plans, evidence and handovers can be queried through tools. This does
not mean a completed Flower was used to build itself, or that it replaces
engineering judgment.

## How much code exists today

| Public-copy measurement | Value on 3 October 2026 |
| --- | --- |
| Production Python files in `src/flow_of_work_mcp` | **171** |
| Physical lines in those files | **74,586** |
| Included | Code, comments, docstrings and blank lines. |
| Excluded | Tests, development tools, documentation, generated reader and private repositories. |

This counts current source, not every line produced and rewritten during
development. It does not measure quality, useful complexity or hours saved.
The product revision is the one identified in [Sources and limits](sources.md).

From a checkout of that revision, reproduce the count with:

```sh
git ls-files -- 'src/flow_of_work_mcp/*.py' | wc -l
git ls-files -z -- 'src/flow_of_work_mcp/*.py' | xargs -0 wc -l | tail -n 1
```

## Wider research, separate products

I am also building an **experimental coding agent for local models**. The
research goal is to understand how much work smaller models can handle when
context, tasks and verification are better bounded. This is not a guaranteed
capability of this Flower release, or a claim of autonomy already achieved.

Flower is the public software-lifecycle component, usable with different coding
agents. Other experimental components, their internal details and model campaigns
are outside this publication.

## What I am not publishing yet

The [general documentary framework](https://github.com/Damel91/LLMs-flow-of-work)
is separate from the instance actually adopted for this project. **The complete
project plane remains private**: it contains personal data and internal material,
and its sanitization has not yet been planned.

This page publishes only three local crops of file lists, without the desktop,
sidebars, personal paths or file contents. Original screenshots are not part of
the presentation or distributed package. The crops illustrate the method;
they do not replace an audit of the private history.

[Index](README.md) · [How this method becomes Plan](02-plan.md)
