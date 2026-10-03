# 2. Plan: a list is not yet a plan

[Previous: Require](01-require.md) · [Index](README.md) · [Next: Build](03-build.md)

> "Let's build the API, calendar and tests. Then deliver."

## A hidden dependency

The calendar unit wants to use an API that does not exist yet. If the plan
contains only activity names, the agent can invent its signature, states and
outcome semantics. Two components compile separately but speak different languages.

In our example, the agent chooses a technical implementation and records it:
a `reserve_room` function returns confirmation, conflict or a temporary error.
This is a **declaration of what will be produced**, not evidence that the function
is already available.

## An educational packet, not an API recipe

| Unit | Ordered action | Produces or consumes | Check at its boundary |
| --- | --- | --- | --- |
| A: service | Implement the atomic booking decision and agreed outcomes. | Produces the "booking outcome" contract. | Service test: concurrent requests do not produce two confirmations. |
| B: interface | Consume A's contract, display outcomes and handle the temporary error. | Explicitly requires A's contract. | Checks for the three outcomes and the distinction between error and confirmation. |
| C: integration | Connect the components and prepare the simultaneous-request procedure. | Depends on the required components already being produced. | Available local verification; the real-environment check remains separate. |

The units belong to a packet: an increment with intent, scope and completion
criteria. The table explains its structure; it does not contain complete Flower
operation payloads and does not authorize execution by itself.

## What Flower checks

The **Packet Validation Projection, PVP**, derives closure from plan data:
which unit implements each criterion, who produces a contract, which predecessors
make it available to its consumer, and which checks are local or deferred.

A consumer does not maintain a second copy of its producer's clauses. An absent
producer, or one unavailable in the declared order, leaves a gap. A structurally
closed plan cannot ignore a current semantic blocker: **closure, plan acceptance
and execution admission are distinct**.

## The problem behind the mechanism

The model needs to know what it can use **now**. A planned future must not become
present source evidence. Separating declarations, dependencies and outcomes makes
this distinction inspectable without asking the user to approve every unit.

PVP does not demonstrate that `reserve_room` is correct or choose the best
architecture. Technical design and clause quality remain the agent's work.

## On the public surface

`fow_promote_milestone` defines milestone scope and policies; `fow_change` governs
the change; `fow_packet_author` builds packets and plans; `fow_external_work`
exposes standalone validation and handoff.

**Question for the audience:** could another agent execute this increment
without reopening every decision made by the first?

[More: PVP](concepts.md#pvp) · [Chapter sources](sources.md#plan)

[Previous: Require](01-require.md) · [Index](README.md) · [Next: Build](03-build.md)
