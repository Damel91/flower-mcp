# Flower MCP 0.5.0

**Preparation checkpoint, 2026-10-16: unreleased candidate; publication requires
a separate human decision.** This status records preparation, not the result
of a future publishing workflow. This
version gathers completed corrections already present in the public source and
adds their installation and advanced configuration guidance. It excludes the
suspended managed-writer witness. Published 0.4.1 and all historical assets remain
immutable.

## Included changes

- Canonical work-plan mutations and committed add-unit receipts retain the
  mutation's identity and historical revisions on exact replay. A separate
  coherent `current_authority` projection
  reports today's revisions and next gate; reading it does not rewrite history
  or authorize a repeated effect.
- A known repeated validation upgrade remains a rejected
  `packet_validation_already_upgraded` result with current authority and explicit
  read-only recovery calls. Export help describes immutable artifact creation,
  actor/request identity and exact retry versus conflict.
- Provider discovery requests the complete capability catalog. Packet/test
  adapters request the supported verbose response profile, retaining required
  correlations and validation acknowledgement. Deferred-only verification units
  keep their separate deferred obligations without fabricated local checks.
- `fow_packet_advance` adds explicit `mode="sync_only"`. It delivers admitted
  ADD/EDIT/REMOVE deltas and returns at `provider_synchronized` before a new
  START. Pending/UNKNOWN START or STOP remains unchanged and holds later deltas.
  Starting requires a separate explicit `mode="advance"` call; the default
  remains `advance`.
- Each provider RPC has one cumulative timeout covering startup, request,
  transport and owned-process cleanup. A possible write settles as UNKNOWN with
  its original command and fingerprint. Recovery observes/reconciles that same
  command instead of inventing a replacement or duplicate job.
- The optional inference extra uses the independently published, URL/SHA256-pinned
  `runtime-llama` 0.4.1 wheel. Candidate assets and source packages contain no
  copied runtime wheel or vendor payload. Core remains independent of inference.
- [Advanced configuration](ADVANCED-CONFIGURATION.md) now explains internal LLM
  setup, supported host semantic assignments, compatible external provider
  contracts and canonical association receipts.

## Compatibility

The 37 public tool names remain. The additive `sync_only` parameter and its
outcomes change the packet-advancement schema relative to published 0.4.1;
this candidate therefore uses a minor version increment. Existing calls retain
the `advance` default. There is no database migration, new semantic role,
automatic updater or new provider implementation.

SQLite stays at schema 55 for existing schema 55 profiles. An older published
0.3.1/schema 52 installation still uses the existing additive migrations to 55
on its first server start. Agent-declared implementation, verification and human
acceptance remain distinct. Provider adapters require compatible services and
explicit admission; their presence does not certify every Flower/CodingCastle
version combination. No witness, host quiescence, full cross-server PVP or new
paired qualification is claimed.

Python 3.11+ is required. The public command is `flower-mcp`; the Python
distribution remains `flow-of-work-mcp`, import package `flow_of_work_mcp` and
MCP prefix `fow_*`. The license remains [Apache-2.0](../LICENSE), with attribution
in [NOTICE](../NOTICE). Flower remains in testing.

## Upgrade while keeping SQLite

Follow [UPGRADING.md](UPGRADING.md) with the existing environment, profile and
profile-root paths. Stop all Flower processes and coding clients sharing the
environment; the installer never stops them. Preview first with the new
installer's `--upgrade --dry-run` (PowerShell `-Upgrade -DryRun`), then remove only
the preview flag to execute. These prepared download commands work **only after
matching 0.5.0 release assets are published**:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.5.0/install.sh | bash -s -- --upgrade --dry-run
```

On Windows, download and inspect the selected launcher first:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/Damel91/flower-mcp/releases/download/v0.5.0/install.ps1' -OutFile '.\install.ps1'
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.5.0' -Upgrade -DryRun
```

Reuse the original `--venv`, `--profile` and `--profile-root`, or PowerShell
`-Venv`, `-Profile`, `-ProfileRoot`. `--backup-root` / `-BackupRoot` selects a
safe private backup location. The owned installer refuses an active selected
ledger owner, acquires its lease and creates a consistent SQLite backup plus
an exact YAML copy **before pip**. Database/profile paths and client registration
stay unchanged. Imports and logs remain in place; the automatic backup does not
make separate copies of all external files.

A failed package installation can partly change the environment. Backups and
original lifecycle data are retained; there is no atomic pip rollback or
automatic data restore. Do not delete the profile or manufacture a new lifecycle
project to recover work. Manual pip environments use the separate backup and
wheel procedure in the upgrade guide. After restart select the same known
project, inspect its current snapshot/evidence/handover through MCP and verify
another restart before resuming mutations.

Updating core does not request the inference extra or change model settings.
An optional runtime upgrade is a separate explicit package change, described in
[INFERENCE.md](INFERENCE.md).

## Assets and qualification

Candidate builds contain seven assets: Flower wheel, source archive, Bash,
PowerShell and Python installers, `BOOTSTRAP.md`, and `SHA256SUMS`. The independent
runtime wheel is not an eighth Flower asset. No PyPI publication is assumed.

Prior focused source, installed-package and public-workflow evidence supports
the selected corrections. Preparing version 0.5.0 requires a new exact-commit
campaign: packaged-content inspection, core installation without inference,
public MCP on the installed candidate, populated 0.4.1/schema 55 upgrade and
restart, the separate predecessor52→55 route, and current native CI.
Those candidate checkpoints must be reported from their actual results; earlier
passes do not qualify the new artifacts automatically. Live optional inference,
actual provider pairing, hosted Glama deployment, target-client usability and
human acceptance remain separate. Publication is not triggered by a source push.
