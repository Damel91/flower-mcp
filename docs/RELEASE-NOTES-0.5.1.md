# Flower MCP 0.5.1

This patch improves the public MCP tool definitions. It keeps the same lifecycle
operations, callable input types, defaults, validation, response envelopes and
SQLite schema as published 0.5.0. The managed-writer witness remains deferred.
Flower remains in testing; this document is version-pinned release guidance,
not a claim that an external build, installation or evaluation has passed.

## Tool definition improvements

Glama's Tool Definition Quality Score feedback helped identify vague tool
purposes, missing parameter documentation and undisclosed effects. The resulting
changes were checked against Flower's code and canonical operation contracts;
Glama's assessment is an input to that engineering review, not functional
certification or an endorsement. A new score is reported only when observed.

- All 37 tools explain their purpose, selection, prerequisites and effects.
- All 445 top-level input parameters have explicit help, with contextual
  distinctions for numbered interaction choices, source anchors and payloads.
- MCP annotations distinguish 9 entirely read-only tools from mixed mutations
  and optional external execution. They are advisory and do not authorize work.
- All 181 canonical operation examples validate structurally against unchanged
  SDK input models. Example IDs and current-gate references are placeholders;
  callers must obtain actual project authority before using them.
- Exact operation help remains available through
  `fow_capabilities(view="operation", operation_tool=..., operation_name=...)`.
  Metadata changes invalidate the existing registry fingerprint/cache.

No new tool, planner, mutable plan store, provider, internal model requirement,
automatic updater or database migration is introduced. Existing gates, replay/
conflict/stale outcomes, producer/consumer contracts, verification obligations
and human acceptance remain unchanged. Core and external-agent work need no
internal inference dependency. Optional runtime-llama remains independently
published 0.4.1, with its existing URL/SHA256 pin; it is not a Flower release asset.

## Upgrade while preserving SQLite

The version-pinned download commands require actual published 0.5.1 assets.
During release preparation, use only the verified candidate assets in a new
isolated test environment. Published 0.5.0 and all its assets remain immutable.

For an existing installer-owned installation, keep its existing environment,
profile, profile root, SQLite/YAML and client configuration paths. Stop only
Flower processes/clients sharing that installation before performing the update.
Do not delete the profile, create a replacement ledger or bypass its owner lock.

Download and inspect the 0.5.1 launcher. Preview first:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.5.1/install.sh | bash -s -- --upgrade --dry-run
```

For a custom installation, pass its original `--venv`, `--profile` and
`--profile-root` on both preview and execution. Choose a private backup directory
with `--backup-root` when required. Review the returned existing paths, version
and backup plan, then repeat without `--dry-run`:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.5.1/install.sh | bash -s -- --upgrade
```

Windows PowerShell uses the same Python backend and ownership safeguards:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/Damel91/flower-mcp/releases/download/v0.5.1/install.ps1' -OutFile '.\install.ps1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.5.1' -Upgrade -DryRun
```

Inspect the downloaded script and the returned plan. For custom paths, retain
the original `-Venv`, `-Profile` and `-ProfileRoot`; choose `-BackupRoot` as needed.
After stopping the relevant Flower owners, repeat without `-DryRun`.

The installer makes a consistent SQLite backup and exact profile-YAML copy
before pip changes. Active ownership refuses the upgrade. It does not stop
clients, reset/rehome the database, adopt another environment, restore backups
automatically or promise atomic package rollback. Registration is preserved;
do not pass fresh-install client-selection flags during an owned upgrade.

Existing schema 55 remains 55. The separately supported older 0.3.1/schema 52
installation still uses existing additive 52→55 migrations on first restart.
Manual installations must follow the manual consistent-backup route in the
[upgrade guide](UPGRADING.md); ordinary pip alone does not preserve an
installer-owned environment's ownership receipt.

Restart Flower with the same profile and client configuration. Verify actual
distribution 0.5.1 through `fow_capabilities`, updated input descriptions and
annotations through MCP discovery, then select the known existing project and
recover its requirements, packets, evidence and handover. MCP SDK/protocol and
Glama platform-release labels are distinct from Flower's distribution version.

## Qualification boundaries

Source/installed compatibility, real public MCP responses, same-schema55
preservation, native CI, anonymous delivery and Glama account builds are recorded
separately in current guidance after their actual verification. Full local schema 55
preservation on one host does not certify another OS. Hosted storage, live LLM/
physical provider execution, witness/U6, agent usability and human acceptance
remain distinct. No user's installation is changed by the release tests.
