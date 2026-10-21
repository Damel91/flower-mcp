# Flower MCP 0.5.2

This patch corrects the repeated authority reads and shared-predecessor PVP
computation behind `FIND-000023`: a complete project recovery could exceed an
agent's 10-second deadline. It retains the full snapshot, dependencies, findings,
verification obligations, fingerprints and next gates. It does not raise the
server or host deadlines.

Reuse lasts only within one coherent read or projection invocation. Atomic
writes, fresh calls, authority changes and restarts evaluate current authority.
Returned mutable results remain independent. The direct traceability projection
also uses the existing coherent-read boundary.

The 37 public tools, 445 input parameters, schemas, operation registry and
SQLite schema 55 remain unchanged. This patch retains 0.5.1's tool descriptions
and Glama-informed discovery improvements. It does not claim a new Glama score
or account build. Core still requires no model/provider; optional runtime-llama
0.4.1 keeps its independent URL and SHA256. The writer witness and U6 integration
remain deferred.

## Upgrade without losing SQLite

Use the [complete upgrade guide](UPGRADING.md), keeping the original environment,
profile, database and client configuration. Stop the Flower processes and clients
sharing that environment; the installer never stops them. Inspect the new
installer and preview first:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.5.2/install.sh | bash -s -- --upgrade --dry-run
```

Add the original `--venv`, `--profile`, `--profile-root` and an optional private
`--backup-root` when using custom paths. Once the preview identifies the existing
state correctly, repeat with only `--dry-run` removed. Active ownership refuses
the upgrade. A consistent SQLite backup and exact YAML copy are made before pip
changes packages. Retain that backup privately. Schema 55 remains 55; existing
schema52→55 additive migration support is unchanged. Package rollback is not
atomic and a package downgrade does not undo database migrations.

Windows PowerShell:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/Damel91/flower-mcp/releases/download/v0.5.2/install.ps1' -OutFile '.\install.ps1'
```

Inspect the downloaded script before executing it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.5.2' -Upgrade -DryRun
```

Inspect the script, retain the original `-Venv`, `-Profile`, `-ProfileRoot` and
optional `-BackupRoot`, then remove only `-DryRun`. Do not pass fresh-install
registration flags during an owned upgrade. Manual pip installations use the
separate checked-wheel/backup procedure in the upgrade guide.

After restart, discover `fow_capabilities`: it must identify distribution 0.5.2.
Select the same existing lifecycle project and inspect its complete recovery,
receipts, evidence and handovers; restart again before resuming mutations.

## Evidence and limits

Before packaging, the exact correction passed deterministic scope/currentness,
mutable-copy, dependency/semantic-gate and reference-projection tests. Actual
public source and isolated core-only installed qualification each used 18 packets,
33 dependency edges and 3 requirements. Complete recovery changed from 20.9 seconds
(source comparison) to 1.75–1.76 seconds, and from 20.25 seconds to 1.66–1.68 seconds
(installed comparison), under the original 10-second test deadline. Old timeout
failures are retained. Complete old/new/restart snapshots match except generated
timestamps; read-purity checks cover all 130 tables. These are declared fixture
measurements, not a universal speed or production acceptance guarantee.

Noxi independently qualified the complete snapshot adapter route, with all 31
engineering routes exposed in its catalog, on a coherent owned copy: reads 1.985–2.114 seconds before/after restart, original 10 seconds
unchanged. State/currentness is owner-reported; two contexts/two events are
explicit setup additions. No copied management database was inspected by the
Flow implementation agent. This isolated result does not itself update or
accept a user's installation or close a runtime finding.

The release workflow gates publication on the exact commit's Linux Python
3.11–3.14 installed-wheel checks, Windows launcher/installed upgrade and Linux
container/public MCP. Seven assets are built: wheel, source archive, three
installers, BOOTSTRAP.md and SHA256SUMS. No runtime wheel is embedded. Anonymous
released-asset inspection and same-schema published 0.5.1→0.5.2 upgrade are separate
post-publication checkpoints; source tests alone do not establish delivery.
Native client workflows, physical/provider acceptance and unknown target OS
remain separate. Flower remains in testing.

## Publication checkpoint

[Flower MCP 0.5.2](https://github.com/Damel91/flower-mcp/releases/tag/v0.5.2) is published
at `73cb74497e4ae65c509eb4ac8acf1026cbb0fd30`. The exact source CI passed all six
jobs; [Release run 38948057867](https://github.com/Damel91/flower-mcp/actions/runs/38948057867)
passed all eight. The official wheel SHA256 is
`cadd427cd4342a23f8f2d23f074f2fb9cab931c3ba5f170323dd16020e570cff`.
Its digest is distinct from the locally built candidate archive; installed source
identity must match the tag. Existing 0.5.0 and 0.5.1 assets remain immutable.
The immutable 0.5.2 source archive retains preparation-era availability wording;
these later current guides record actual publication without replacing that tag.

All seven official assets were then downloaded anonymously and checked against
GitHub's digests, SHA256SUMS and the exact tagged source. The wheel's 184 product
files match the source and the installed package. A separate populated macOS
test installation upgraded from the actual published 0.5.1 assets to these
actual 0.5.2 assets through the unmodified downloaded installer. Forty-nine public
MCP calls covered the original state, upgrade and restart. All 349 schema objects,
130 tables, 140 rows and counters, original paths, YAML/client bytes, receipts,
evidence and handovers were preserved; a consistent backup was observed before
pip. This owned-fixture result is distinct from another user's installation,
the unchanged 10-second adapter qualification and human acceptance.

## Published delivery record

This record preserves the package-verification checkpoint previously included
in the project README. Client adoption and user acceptance have their own
verification records.

Flower `0.5.2` is published and remains in testing. Its
[release notes](docs/RELEASE-NOTES-0.5.2.md), the historical
[0.4.1 release notes](docs/RELEASE-NOTES-0.4.1.md) and
[installation status](docs/INSTALLATION.md#testing-status-and-release-access)
distinguish installed-package and CI checks from end-to-end installer and
target-client qualification.
The patch corrects repeated authority reads and shared-predecessor PVP work in
complete project recovery, preserving full results, gates and the existing
deadlines. It retains 0.5.1's descriptions for all 37 tools and 445 inputs,
conservative MCP annotations and canonical examples, together with the
0.5.0 receipt/error-recovery corrections, explicit sync-only provider delivery
and bounded provider RPCs, with the same callable contracts and schema 55. The writer witness remains deferred; this release does not claim
its integration or cross-server acceptance.
The immutable release archive retains its preparation-era documentation; these
current guides on `main` align installation instructions with the published assets.
