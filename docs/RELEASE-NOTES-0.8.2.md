# Flower MCP 0.8.2

This patch corrects campaign Oracle authoring across multiple cases. The next
question shown by Flower and the question admitted by the writer now use the
same current authority. Source questions take priority across the campaign;
optional deterministic IR refinement does not block independent source work.

Live and unsupported profiles retain their declared meaning and the
source-authored path. Historical IR questions remain in the ledger, with no
inferred waiver, attestation, test evidence or acceptance. Stale bindings expose
their actual case/Oracle recovery rather than a question for another revision.

Known question conflicts include bounded expected/received identities, scope,
current authority and an exact read-only recovery call. Mutation uncertainty
remains explicit. Invalid or failed campaign reads are observation errors,
without misleading unknown-write warnings. The existing optional
`expected_fingerprint` is now enforced for `answer_question`; exact original
semantic replay is checked first. See [campaign recovery](CONTINUOUS-RECOVERY.md#campaign-oracle-questions).

## Upgrade

Use the [ordinary same-profile upgrade](UPGRADING.md#preparing-a-082-upgrade).
Keep the same environment, database, profile, YAML and client configuration.
The existing `--upgrade` path refuses an active owner and creates its consistent
SQLite/YAML backup before pip. SQLite stays at schema55; no migration,
dependency, installer algorithm or AGENTS change is required. Keep the backup;
failed pip does not provide an atomic rollback.

No work is resumed automatically. After upgrading, inspect the existing campaign
and follow its current gate; do not replay a sequence of failed mutations blindly
or recreate the project. Earlier releases remain immutable.

## Qualification boundary

Targeted source regressions and independent severe review, followed by public
MCP workflows on isolated source and installed-wheel instances, cover both
Markdown and structured responses, replay, stale authority and restart. The
existing Release CI qualifies the exact final package before publication.

This correction does not add provider-free Oracle execution, certify model
behavior, complete an OpenCode benchmark or qualify witness/cross-server work.
An absent test provider remains an explicit blocked execution prerequisite.
