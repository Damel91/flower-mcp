# Flower MCP 0.7.0

Flower makes canonical architecture and bounded repository reconciliation part
of the standalone engineering cycle. Coding agents continue to investigate,
implement and test with their own tools. No internal model or coding provider
is needed for these capabilities.

## What changes

- New plan acceptance requires an adopted nonempty architecture and valid packet
  references. Its immutable acceptance event records engineering-cycle version 1.
- External-agent cycle-1 work records unit outcomes normally, then requires a
  current scoped repository review before final closure or dependent admission.
  Implementation, local verification, reconciliation and human acceptance remain
  distinct. Previously issued plans retain their historical contract.
- `fow_audit_phase` accepts an optional bounded host-declared repository review.
  It uses existing audit/events/jobs, exact request replay, conflict detection,
  source provenance and revision-bound currentness. Original committed audits
  remain recoverable independently of the latest current comparison.
- Full external validation exposes original report history, including outside
  execution admission, without promoting old evidence or relaxing execution guards.
- Host intention-grounding preparation supports an explicit requirement scope;
  omission and an explicit empty selection remain distinct. Actual truncation
  and host-declared scope limitations remain visible.
- Recipes, current gates, Markdown, structured data, offline plan exports and
  the bundled engineering bootstrap describe the same cycle. Default views stay
  compact; full detail remains explicit.

Read [the engineering cycle](ENGINEERING-CYCLE.md), [bootstrap](BOOTSTRAP.md) and
[continuous recovery](CONTINUOUS-RECOVERY.md) for the practical workflow.
The public catalog remains 37 tools and 183 operation routes; the two additive
optional fields bring the flat input-property inventory to 447. A host's explicit
lens determines the smaller surface actually presented to its model.

## Upgrade while preserving SQLite

SQLite remains at schema 55. There is no new migration, dependency change or
change to the existing ownership/backup implementation. Follow the
[same-profile upgrade guide](UPGRADING.md). Keep the original environment,
profile, ledger, YAML, imports/logs and coding-client configuration. Preview with
`--upgrade --dry-run`; stop all owners before the actual upgrade. The installer
refuses active ownership and makes a consistent SQLite backup plus an exact YAML
copy before pip. Keep the backup. Failed pip does not promise automatic restore
or atomic rollback. Restart the intended client using the same profile.

Package installation does not automatically edit existing project `AGENTS.md`.
Run the updated `bootstrap` command and authorize the host to merge its marked
section, preserving other project instructions. Existing accepted plans, outcomes,
receipts, artifacts, evidence and handovers are not rewritten by the update.

## Qualification boundaries

Deterministic tests, actual public MCP workflows from source and a core-only
installed package, offline host execution/restart and independent review qualify
the bounded implementation. Release CI checks the exact published commit and
installed packages across its existing platform matrix. Official asset and
same-schema upgrade receipts are recorded separately after publication.
These checks do not assert unrestricted local-model adherence, novice usability,
human acceptance or CodingCastle/witness qualification. Witness U6 remains deferred.
