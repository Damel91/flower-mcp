# 3. Build: work leaves the server, intent does not

[Previous: Plan](02-plan.md) · [Index](README.md) · [Next: Verify](04-verify.md)

> The plan is ready. The agent starts. Halfway through, the session is interrupted.

## Code has an executor

The agent writes `reserve_room`, runs tests and builds the interface using its
host's tools. Flower **does not open the repository to write that code** and does
not launch those tests in standalone external-agent mode.

From the accepted plan, closed PVP and current admission, Flower can expose a
dependency-ordered TODO. When the agent declares an outcome, Flower preserves
the unit, plan authority, artifact references and checks with their provenance.
It does not turn that declaration into a filesystem audit it never performed.

## If Flower is unavailable

A complete Markdown export preserves the necessary context: intent, criteria,
decisions, contracts, unit order and checks. The host saves the artifact and can
work offline **within the authority it has already received**.

A file named "plan" is not enough. A draft export exposes its gaps and is not
executable authority. A new intent issue or missing authority cannot be resolved
by inventing offline authorization.

## If the plan changes during the interruption

| Event | What must remain distinguishable |
| --- | --- |
| The agent reconnects and reports the same outcome. | An identical replay must not create a second independent result. |
| Two different reports declare an outcome under the same authority. | The conflict requires explicit reconciliation. |
| The current plan has changed. | The old revision's result remains history, not automatic closure of new work. |

The TODO is a state projection, not a parallel list the model must manually
synchronize in chat memory.

## The problem behind the mechanism

A "done" message does not identify which plan was executed, which outputs exist
or what remains open. Continuity does not come from copying the entire chat:
facts, authority and the next gate are recovered from their owner.

Flower does not guarantee every agent will follow an exported plan. It preserves
and checks its own protocol boundary; the agent loop is qualified separately.

## On the public surface

`fow_external_work` offers `export_plan`, `todo`, `report_outcome` and
`reconcile_outcome`. `fow_handover` reconstructs current state and progress.
The relevant recipe is `standalone-external-plan`.

**Question for the audience:** after an interruption, do we resume from the
agent's last sentence or from the work that was actually recorded?

[More: authority and evidence](concepts.md#current-evidence) · [Chapter sources](sources.md#build)

[Previous: Plan](02-plan.md) · [Index](README.md) · [Next: Verify](04-verify.md)
