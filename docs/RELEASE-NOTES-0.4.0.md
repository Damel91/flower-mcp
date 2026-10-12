# Flower MCP 0.4.0

This minor release ships the completed architecture and handoff increment after
0.3.1. Flower remains in testing. Published 0.3.1 and its assets are unchanged.

## Architecture and execution authority

- `fow_architecture` adds inspect, propose and adopt operations. Architecture
  revisions are durable, immutable project authority; proposals do not authorize
  execution until ordinary adoption.
- Packets reference selected adopted architecture. Coherent validation, exported
  Markdown and handovers carry it; relevant drift blocks affected work until
  ordinary revision restores closure.
- New work explicitly selects an external agent or optional provider. Reads
  never select an executor, probe a provider or invoke a model.
- Optional provider delivery requires positive capability negotiation and exact
  revision-bound PVP acknowledgements. Uncertain delivery stays uncertain across
  restart; recovery observes the original command rather than inventing success.
- Existing upstream risk decisions, pending questions and frozen running-work
  observation remain authoritative in the negotiated handoff.

Standalone external agents retain complete Markdown export, producer/consumer
contracts, offline execution and durable outcome reconciliation. Host evidence
retains its declared provenance. Implementation, verification and human
acceptance are distinct. See [the integration contract](NOXI-INTEGRATION.md).
Real paired provider qualification and the original full cross-server PVP draft
remain separate; this release does not certify a CodingCastle consumer.

## Update the existing installation

Use the [SQLite-preserving upgrade plan](UPGRADING.md). Keep the original
environment, profile and data paths, stop all clients sharing that environment,
then use the new installer's `--upgrade --dry-run` or PowerShell
`-Upgrade -DryRun`. Inspect the plan and repeat without the preview flag.

Before pip, the installer leases the selected ledger, creates a consistent
SQLite backup and copies the exact YAML. An active owner blocks the upgrade.
Client registration, imports, logs, bindings and existing project data stay in
place. Manual pip installations use the documented backup/manual route; they
are not silently adopted by the release installer.

First server start migrates schema52 to55 additively: seven new tables and two
packet columns. Historical rows, IDs, authority clocks, evidence and immutable
handovers remain intact. `doctor` does not apply these migrations. Reconnect to
the known existing project, inspect its snapshot/HAND and verify another restart.
Keep the backup; downgrading the package does not reverse a migrated ledger.
Pip can partially change an environment on failure; no atomic rollback or
automatic database restore is promised.

## Compatibility and qualification

The public catalog grows from36 to37 tools. Distribution/import names and both
console aliases remain unchanged. Python3.11+ and optional runtime-llama0.4.0
remain supported; core and external-agent work need no inference extra or model
endpoint. Antigravity, Gemini CLI, Windows PowerShell and container instructions
are retained and current. The packaged bilingual reader is refreshed and tested.

The CI-gated release checks exact package inventory/resources, LinuxPython
3.11–3.14, native Windows installation and published0.3.1 upgrade, and Linuxamd64
container persistence. Local public MCP, offline and same-profile restart
evidence remain distinct from native CI and actual downloaded-asset checks.
Target coding-client usability, managed Python on every workstation, other
container architectures and human acceptance need separate evidence.
