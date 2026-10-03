# 1. Require: behavior before code

[Index](README.md) · [Scenario](scenario.md) · [Next: Plan](02-plan.md)

> "I don't want the same room to be booked twice."

## The question hidden inside the request

The agent could start with a calendar, login and database. Marta could approve
an attractive screen without noticing that the central behavior is still undefined.

Luca and another person see an available room at the same time. Both press
"Book." What should happen? An availability list updated before the click does
not answer that question.

The first job is to make intent observable: **one confirmation, an explicit
conflict for the other request and no invented confirmation when the outcome
is missing**. The engineer/agent owns the technical solution; Marta clarifies
the result she needs, without having to choose a database isolation level.

## What Flower preserves

The agent registers the requirement, rationale, use case and sequence. Guided
bootstrap can preserve selected answers with provenance and link them to
canonical entities. Correspondence is a judgment declared by the host, not
automatic semantic proof.

| Story element | Why it matters |
| --- | --- |
| Requirement SC-R1 | Defines the result to preserve. |
| Use case "Book a room" | Explains actor, goal and observable outcome. |
| A sequence with two requests | Exposes a conflict hidden by the happy path. |
| Marta's answer linked to scope | Makes the decision recoverable instead of leaving it in chat. |

A derived roadmap is presented to the person and confirmed with a real reference.
**Confirming scope does not accept software that has not been produced.**

## The problem behind the mechanism

A conversation can contain proposals, observations and decisions with different
authority. A new session must not turn the last sentence it read into a new
requirement. Revisioned requirements, linked answers and confirmed scope make
the governing intent explicit.

Flower does not prevent an external agent from using other tools outside that
workflow: its gates govern server operations. Agent adherence to instructions
remains something to test on its host.

## On the public surface

`fow_bootstrap` guides intake; `fow_register_requirement` registers a requirement;
`fow_goal` holds use cases, sequences and expectations. `fow_capabilities` exposes
the `engineering-bootstrap` recipe and exact operation contracts.

**Question for the audience:** if we change agents tomorrow, will the new agent
know why we chose this behavior, or find only a screen that has already been built?

[More: intent and lenses](concepts.md#lenses) · [Chapter sources](sources.md#require)

[Index](README.md) · [Next: Plan](02-plan.md)
