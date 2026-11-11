# 6. Operate: when the world responds

[Previous: Deploy](05-deploy.md) · [Next: try Flower](try-flower.md) · [Index](README.md)

> "There was a conflict last night. And we need to book every Tuesday."

## Two reports, two paths

The first can be a defect against SC-R1: two incompatible confirmations. The
second introduces recurring bookings, excluded from the first scope. Combining
them into one "fix" risks changing the product without saying so.

| Report | Question before modifying anything |
| --- | --- |
| Two confirmations for the same interval | Which evidence demonstrates a divergence from current intent? |
| A booking every Tuesday | How does scope change, and which new rules must be clarified and confirmed? |

The agent investigates the defect with its tools. Flower does not monitor the
service, autonomously collect incidents or diagnose Spazio Comune's database.

## Correct without rewriting the past

For a divergence, the agent records a finding, rereads the current requirement,
scenario, milestone and packet, and declares an intent reassessment. Only a
current assessment establishing a correction within agreed intent admits that
corrective path.

The new packet stays linked to the finding and carries a regression obligation.
An assessment does not prove the bug is solved; subsequent results must still
support its disposition.

Recurring bookings follow the ordinary intent-change path: new rules, revisions
and confirmation of affected scope. SC-R1 is not retroactively rewritten to
justify two incorrect confirmations.

## If the person or agent changes

Another session selects the project and recovers a snapshot. It can read current
state and history without treating the model as the system of record. The next
gate guides work; it does not guarantee every semantic decision will be correct.

## The project in the browser

The person can inspect the projects in their profile directly. When Flower
runs with streamable HTTP, open its local `/dashboard` address and sign in
with the OS account that owns the Flower profile. Its sections show requirements, roadmap, packets,
verification and Oracles, architecture and retained evidence. Browser project
selection leaves chat contexts unchanged.

Retained Markdown opens in **Lettura**, with a heading outline, formatted tables
and code. **Sorgente** and download preserve the original document. HTML and
images remain inert. The view identifies limits and partial content without
turning them into completeness or acceptance. Its theme follows the system,
with a manual light or dark preference stored in the browser.

To delete a project, select **Elimina progetto** and enter its exact ID and
your local account password. Flower briefly puts the instance into maintenance
to remove its own records for that project. If the response is interrupted,
refresh the project list to check the outcome.

To restore a saved archive, open **Backup → Ripristina archivio**, select a
Flower ZIP, and enter a new profile name. Flower leaves the new profile inactive.
See the [dashboard guide](https://github.com/Damel91/flower-mcp/tree/main/docs/DASHBOARD.md)
for access and recovery. The [offline presentation reader](reader.md) runs
independently of the live dashboard.

## The problem behind the mechanism

The lifecycle does not end at first delivery. We must preserve the reason for
a change, the authority admitting it and the distinction between old evidence
and new work. A message log does not replace these relationships.

## On the public surface

`fow_assurance` records findings, reassessments and corrective links;
`fow_revise_requirement` preserves revisions; `fow_change` governs changes;
`fow_handover` supports recovery. The story can return to Require or Plan:
there is no need to declare a new project for every correction.

**Question for the audience:** will the next agent know whether to repair an
unfulfilled promise or design a new one?

[More: history and current state](concepts.md#current-evidence) · [Chapter sources](sources.md#operate)

The presentation now moves from the story to your project: [install and try Flower](try-flower.md).

[Previous: Deploy](05-deploy.md) · [Next: try Flower](try-flower.md) · [Index](README.md) · [Back to Require](01-require.md)
