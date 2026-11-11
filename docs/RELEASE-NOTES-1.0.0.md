# Flower MCP 1.0.0

Flower 1.0.0 starts the stable public interface series. It keeps project
decisions, plans, verification and handovers connected as an agent moves
from one piece of work to the next.

## Working with Flower

- Project recovery shows the current scope, the reason work is waiting and
  the next operation. Full structured results and audit views remain available.
  Validation points to executor selection or criterion classification when that
  decision comes before plan acceptance. [Engineering cycle](ENGINEERING-CYCLE.md)
- Campaigns expose their current step and the inputs it requires in Markdown.
  A host can run eligible checks and report its evidence. Cases that require a
  provider or independent proof still show that requirement. Campaign evidence
  and acceptance remain separate decisions. [Recovery guide](CONTINUOUS-RECOVERY.md)
- OpenCode V2 can recover the current Flower project context after chat
  compaction when its recovery hook is enabled. [OpenCode setup](OPENCODE.md)
- The dashboard can export the requirements and architecture for the selected
  scope. A guided draft milestone can be revised without changing its ID.
  [Dashboard guide](DASHBOARD.md)

## Install or upgrade

Choose the versioned installer and compare its checksum with the
`SHA256SUMS` file from the same release. For an existing installation, stop Flower and preview with
`--upgrade --dry-run` or PowerShell `-Upgrade -DryRun`. Keep the same
environment, profile and profile root, then apply the upgrade. The installer
backs up SQLite and the profile YAML before installing the package.
SQLite remains at schema 55. Start the same profile when ready and reconnect
to the existing project. [Installation](INSTALLATION.md) · [Upgrade guide](UPGRADING.md)
