# Spazio Comune: a story to follow

[Index](README.md) · [Require](01-require.md)

## "We need a website to book our rooms"

An association manages two rooms. Bookings happen through messages and a shared
spreadsheet. Two people can believe they have secured the same space. The
coordinator must reconstruct who requested what and which request is confirmed.

**Marta** coordinates the association. **Luca** organizes meetings. A **coding
agent** helps build the service. Flower maintains the service's engineering
project, not the members' bookings: the application database and the engineering
ledger are different things.

## The story's initial scope

The first version offers an availability view, a booking request, an explicit
outcome and cancellation by authorized people. Payments, recurring bookings and
external notifications are outside this first scope.

The rules do not become true because we write them here. In the story, we assume
Marta has clarified them and the agent has registered them in the Flower project:

| Educational label | Agreed behavior |
| --- | --- |
| SC-R1 | Two confirmed bookings cannot occupy the same room during the same interval. |
| SC-R2 | The interface distinguishes confirmation, conflict and temporary unavailability: an error never implies confirmation. |
| SC-R3 | A member cancels their own booking; the coordinator can also manage other members' bookings. |
| SC-R4 | The cancellation outcome makes the new availability observable. |

`SC-R1` and the other labels only help us follow the story. **They are not IDs
issued by Flower.** Real IDs, revisions and fingerprints come from the server;
we do not invent them to make a demonstration look credible.

## The two recurring questions

1. **Simultaneous requests:** both people can see the room as available. Which
   component must prevent two confirmations?
2. **A missing confirmation:** the connection drops. Luca tries again. How do
   we distinguish a new request from observing an existing result?

These are product problems the agent must investigate and implement. Flower
helps record their meaning and verification obligations; it does not automatically
implement concurrency or idempotency in the booking service.

## What this story is not

It is not proof that a local model can build Spazio Comune. It is not a performance
comparison with other agents. It is not a declaration of security, compliance or
production-grade quality. It is a concrete way to understand what Flower governs
before, during and after coding.

[Back to the index](README.md) · [Enter the first scenario](01-require.md)
