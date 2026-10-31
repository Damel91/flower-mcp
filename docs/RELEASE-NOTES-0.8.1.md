# Flower MCP 0.8.1

Flower's bootstrap, discovery recipe and persistent project AGENTS template now
explicitly require the coding agent to question factual and technical premises,
including its own preferred solution, seek counterevidence and revise conclusions
when evidence contradicts them.

Known deviations, omissions and substitutions must be disclosed before approval
of the proposal or affected execution, with the original obligation, difference,
reason, behavioral consequences, affected criteria and evidence or uncertainty.
Stakeholder intent stays authoritative; technical choices within that intent
remain the engineer's responsibility. Existing reassessment and scope-confirmation
rules apply. No extra approval after every unit or compulsory opposition/testing
is introduced. See the [bootstrap guide](BOOTSTRAP.md).

## Upgrade

Use the [ordinary same-profile upgrade](UPGRADING.md#preparing-a-081-upgrade).
Keep the existing environment, database, profile, YAML and client configuration.
Stop the owner; the unchanged `--upgrade` path creates its consistent SQLite/YAML
backup before pip. SQLite remains schema55 with no new migration, dependency or
server contract. Keep the backup; failed pip is not an atomic rollback.

Project AGENTS files are not edited by the package installer. Print the new
bootstrap and merge the new subsection into the existing Flower marker while
preserving project locators and custom rules. Earlier releases remain immutable.

## Qualification boundary

The completed semantic review, focused exposure tests and exact resource/package
checks are reused. The Release workflow qualifies this versioned artifact before
publication. Instruction exposure is not proof of model adherence, reduced
sycophancy or stakeholder usability. No provider/model, witness or native client
acceptance is implied.
