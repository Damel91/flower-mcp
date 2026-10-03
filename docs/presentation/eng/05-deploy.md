# 5. Deploy: deliver a bounded promise

[Previous: Verify](04-verify.md) · [Index](README.md) · [Next: Operate](06-operate.md)

> "It works on my computer. Shall we make it available to the association?"

## The environment changes, not just the address

Spazio Comune must use the target database, manage credentials and permissions,
and survive a restart. Local checks remain useful evidence, but do not by
themselves demonstrate these behaviors.

The agent prepares the technical implementation, uses available tools and reports
what it actually executed. The person retains the delivery and irreversible-effect
authority assigned to them.

**Flower is not a deployer, credential manager or CI/CD system.** The Deploy
petal represents governed delivery: scope, evidence, open obligations,
acceptance decisions and recoverable state.

## Delivery in our story

| Statement | The condition that must be explicit |
| --- | --- |
| "This is the first version." | Which scope and behaviors does it include? |
| "These checks passed." | Which results, environment and revision? |
| "This verification remains open." | Who performs it, and why was it not marked completed? |
| "The association accepts the result." | Is there a real decision by the competent authority, not agent-generated text? |

A planned milestone and an accepted milestone are distinct states. Flower
provides governed transitions and evidence references; it does not unilaterally
choose the risk threshold Marta must accept.

## The problem behind the mechanism

If delivery is only a chat message, a successor can confuse produced software
with accepted software. A recoverable handover must say what exists, what
governs the work and which obligation remains open.

A record is not production-grade certification. Even an explicitly experimental
first release can have a precise, honest handover.

## On the public surface

`fow_accept_milestone` governs the required acceptance; `fow_handover` returns
snapshots and handovers; `fow_get_artifacts` retrieves available artifacts.
Exporting a plan and accepting software are not the same operation.

**Question for the audience:** can Spazio Comune's recipients distinguish what
was delivered from what was merely promised?

[More: responsibilities](concepts.md#responsibilities) · [Chapter sources](sources.md#deploy)

[Previous: Verify](04-verify.md) · [Index](README.md) · [Next: Operate](06-operate.md)
