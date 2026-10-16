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

After restart, discover `fow_capabilities`: it must identify distribution0.5.2.
Select the same existing lifecycle project and inspect its complete recovery,
receipts, evidence and handovers; restart again before resuming mutations.

## Evidence and limits

Before packaging, the exact correction passed deterministic scope/currentness,
mutable-copy, dependency/semantic-gate and reference-projection tests. Actual
public source and isolated core-only installed qualification each used18packets,
33dependency edges and3requirements. Complete recovery changed from20.9seconds
(source comparison) to1.75–1.76seconds, and from20.25seconds to1.66–1.68seconds
(installed comparison), under the original10-second test deadline. Old timeout
failures are retained. Complete old/new/restart snapshots match except generated
timestamps; read-purity checks cover all130tables. These are declared fixture
measurements, not a universal speed or production acceptance guarantee.

Noxi independently qualified the complete snapshot adapter route, with all31
engineering routes exposed in its catalog, on a coherent owned copy: reads1.985–2.114seconds before/after restart, original10seconds
unchanged. State/currentness is owner-reported; two contexts/two events are
explicit setup additions. No copied management database was inspected by the
Flow implementation agent. This isolated result does not itself update or
accept a user's installation or close a runtime finding.

The release workflow gates publication on the exact commit's LinuxPython
3.11–3.14 installed-wheel checks, Windows launcher/installed upgrade and Linux
container/public MCP. Seven assets are built: wheel, source archive, three
installers, BOOTSTRAP.md and SHA256SUMS. No runtime wheel is embedded. Anonymous
released-asset inspection and same-schema published051→052 upgrade are separate
post-publication checkpoints; source tests alone do not establish delivery.
Native client workflows, physical/provider acceptance and unknown target OS
remain separate. Flower remains in testing.
