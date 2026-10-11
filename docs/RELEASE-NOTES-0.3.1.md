# Flower MCP 0.3.1

This patch ships the continuous-use corrections implemented after 0.3.0 and
adds a safe update path for an existing installer-owned environment. Flower
remains in testing. Published 0.3.0 assets are unchanged.

## Continuous external-agent work

- External readiness follows the mode-applicable admission guards. Optional
  provider history remains contextual and does not block external execution.
- New external handovers freeze a coherent recovery projection, including
  issued plan authority, unit outcomes, verification obligations and public
  recovery calls. Replays retain the original payload; current resume compares
  authority and labels stale or legacy snapshots explicitly.
- Exact original evidence can be inspected through traceability audit. Host
  provenance, multiline Markdown and nested evidence remain intact.
- Continuation and offline outcome guidance distinguish original issued plan
  revisions from current reconciliation authority. Diagnostics identify the
  precise mismatching unit, criterion or field.
- Installed distribution identity and an explicit-endpoint HTTP probe help
  identify the intended Flower instance separately from MCP SDK identity.

See [continuous work and recovery](CONTINUOUS-RECOVERY.md). Existing historical
handovers are not silently enriched, and source counters carry namespaces rather
than becoming interchangeable revision numbers. A remaining phase label may
describe the broader verification stage; use the returned admission guards and
next action to determine actual work. Local verification, deferred campaigns
and human acceptance remain separate.

## Preserve the existing installation

The new release installers support `--upgrade --dry-run` (PowerShell
`-Upgrade -DryRun`) before an owned update. Execution leases the selected
ledger, creates a consistent SQLite backup and exact YAML copy, then upgrades
the existing environment. It preserves profile configuration, lifecycle data,
imports, logs, bindings and client registration. An active runtime blocks the
operation; no process is stopped automatically.

Upgrade defaults to no registration; client-selection flags are rejected.
Keep the same environment and profile paths and stop all clients sharing that
environment. Backup and original data remain after a failure, but pip is not
an atomic rollback mechanism. There is no automatic data restore or migration
of arbitrary manual environments. See the [complete upgrade plan](UPGRADING.md)
for previews, execution, recovery and the manual pip route.

## Compatibility and qualification

The SQLite schema, 36 public tool names, Python distribution/import names and
both console aliases remain unchanged. Optional runtime-llama remains 0.4.0;
core installation and host execution require no inference dependency or endpoint.
Antigravity/Gemini CLI registration, Windows PowerShell installation and container
support introduced earlier remain available.

Qualification separates deterministic tests, actual installed public MCP
mechanics, offline/restart recovery, original-to-new package upgrade and native
CI. The CI-gated release builds the four Linux Python versions, Windows launcher
and installed core, and Linux amd64 container. Actual downloaded release assets
must also pass checksum and upgrade checks; source tests alone do not establish
that result. Native coding-client usability, managed Python setup on every
workstation, other container architectures and human product acceptance require
separate evidence. No cross-server PVP or provider pairing is certified here.
