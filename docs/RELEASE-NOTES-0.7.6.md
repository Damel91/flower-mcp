# Flower MCP 0.7.6

A replacement plan can now include answers to the construction questions that
were valid before replacement. Flower records the complete batch and plan in one
transaction, preserving original question identities, submitted answers and
explicit retained/reopened/ceased-applicable outcomes. A future-only new-file
plan no longer deletes a valid question before recording its supplied answer.

New command receipts cover plan, answers, actor, scope and declared revision
conditions. Exact replays remain historical and cannot answer newly introduced
gates or queue provider work again. Changed replays conflict. Historical plan-only
receipts cannot verify supplied answer batches and fail explicitly rather than
silently discarding, remapping or replaying them.

The existing packet history read exposes immutable completion receipts with
provenance and revisions after later plans. Replace-plan and question-batch errors
return structured diagnostics and multiline Markdown, with scoped read-only
recovery guidance. Effects remain unknown where no pre-write proof exists;
rollback is not a global no-effect receipt. See [plan authoring](PLAN-AUTHORING.md).

## Upgrade

Use the [ordinary same-profile upgrade](UPGRADING.md#preparing-a-076-upgrade).
SQLite remains schema55. Keep the same database, profile, YAML and client paths;
stop the owner, preview with `--upgrade --dry-run`, then upgrade with the existing
backup-before-pip installer and restart that profile. Dependencies and installer
algorithms are unchanged. Existing data and unknown historical calls are not
rewritten or replayed. A failed pip install is not an atomic rollback.

The optional runtime/provider configuration, actual project acceptance and paused
witness work are unchanged. This release neither executes repository work nor
automatically recovers an old host operation.
