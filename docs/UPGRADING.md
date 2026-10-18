# Upgrade Flower without losing project data

## Preparing a 0.6.1 upgrade

0.6.1 is the candidate for the read-only [lens catalog](LENS-CATALOG.md).
Its release commands require the corresponding published assets. Official 0.6.0
remains immutable; local source-test wheels with the same metadata are distinct.
Keep the same venv, profile root, database, YAML and client registration. SQLite
stays at schema 55, with the original authority/history/evidence/receipts/HAND.
Stop owners using the environment; verify the backend's SHA256SUMS entry first.
Preview with its existing safeguards and the original paths:

```sh
python3 -I ./install_flower.py --version 0.6.1 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Then execute the inspected command without `--dry-run`, retaining the consistent
backup made before pip. Windows uses `py -3 -I` and its actual paths. The backend
refuses active ownership. Do not delete/reset SQLite or replace project bindings
as an upgrade step. Start the same profile, refresh schemas/registry, inspect
current project state through public MCP, and restart to confirm continuity.
Same-schema0.6.0 → 0.6.1 and predecessor 0.3.1/schema 52→55 checks are separate; no new
migration or atomic package/database rollback is promised. Candidate/local
verification, exact CI, official downloads and owner deployment remain distinct.

The following sections preserve the already published 0.6.0 procedure/history.

**Flower MCP 0.6.0 is published.** Its
[milestone compatibility change](RELEASE-NOTES-0.6.0.md#milestones-realized-work-and-prerequisites)
changes public inputs while preserving SQLite schema 55. The commands below
select official 0.6.0 assets; see the [installation guide](INSTALLATION.md).
Published tag `v0.6.0` identifies commit `bb43b5a161ecc85e56f1d2dba2c69184da0a02b7` ([release 416096822](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.0)). [Candidate CI](https://github.com/Damel91/flower-mcp/actions/runs/39072677376) and [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39073239681) are separate from anonymous asset checks and the populated-profile HTTPS upgrade.
A reviewed wheel can use the manual pip procedure below in a manual environment.
Do not bypass an owned installer's receipt by
updating its Flower version through pip. The Python environment owns code; the
persistent profile owns
`flower.yaml`, lifecycle data, bindings, imports, logs and evidence. Keep their
paths unchanged. This release adds no database migration. Existing receipts,
revisions, evidence and handovers stay in the same profile.

| Existing version | Database behavior on the first 0.6.0 server start |
| --- | --- |
| 0.4.0, 0.4.1, 0.5.0, 0.5.1 or 0.5.2, schema 55 | Schema stays at 55; no new migration. |
| 0.3.1, schema 52 | Existing additive migrations 53–55 create seven tables and two packet columns. |

Existing projects, authority revisions, evidence and handovers remain in the
same database. The installer backs it up before changing packages. `doctor`
reads configuration; it does not start Flower or verify database migration.
After starting Flower, verify the same project through public MCP and restart.
A package downgrade does not reverse a migrated database. Source on `main` is
not a release. Historical 0.5.2 retains 37 tools and its callable lifecycle
contracts. It corrects repeated work in complete recovery without changing the
existing deadlines, authority or gates. It retains 0.5.1's purpose/routing help,
445 input descriptions and conservative annotations; see its [release notes](RELEASE-NOTES-0.5.2.md).
The additive `fow_packet_advance(mode="sync_only")` argument was introduced in
[0.5.0](RELEASE-NOTES-0.5.0.md) and remains available. The suspended writer witness
is excluded.

The safe release upgrade is for environments created by the Flower release
installer. A manual pip environment uses the [manual procedure below](#manual-pip-installations).
Containers retain their existing volume; see [Glama and containers](GLAMA.md).

## Preparing a 0.6.0 upgrade

Keep the same environment, `FLOWER_HOME`, profile, database, YAML and client
registration. Project deletion, creating a replacement project and resetting
bindings are never upgrade steps. All clients/processes sharing the environment
must be stopped before executing an update.

| Starting state | 0.6.0 database behavior |
| --- | --- |
| Published 0.5.2 or another supported schema-55 ledger | Schema stays at 55. Tables, rows, revisions, receipts, evidence and handovers are preserved. |
| Published 0.3.1, schema 52 | Existing additive migrations 53–55 run on first startup. This separate route requires its own qualification. |

For an installer-owned environment, download official 0.6.0 `install_flower.py`
and `SHA256SUMS`, compare the backend checksum, then preview with an already
available Python. Replace every path with the original owned installation values:

```sh
python3 -I ./install_flower.py --version 0.6.0 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Windows uses `py -3 -I` with the same Python-backend options and actual Windows
paths. This preview is not an update. Inspect it before execution.
The official 0.5.2/schema 55 → 0.6.0/schema 55 HTTPS upgrade was checked on a fresh
populated owned fixture. The separate 0.3.1/schema 52 → schema 55 check exercises
existing additive migrations; neither result certifies an unknown workstation.

Use the verified **0.6.0** installer and checksums, preview with the
same original paths, then execute only the inspected plan. The backend refuses
an active owner and makes a consistent SQLite backup plus exact YAML copy before
pip. Keep the backup privately, inspect the known existing project through public
MCP after startup, and repeat the read after another restart. Installer-owned
receipts must name the actual installed Flower artifact; do not edit them or
replace that package through pip.

For a **manual pip environment**, apply the [manual backup procedure below](#manual-pip-installations)
using a new private backup directory, then install the reviewed
`flow_of_work_mcp-0.6.0-py3-none-any.whl` in its existing environment and run
`pip check`. Check the wheel's exact SHA256 first. A fresh environment
and an existing manual upgrade are different operations. Neither a package
downgrade nor pip failure automatically restores a database or environment.

### Refresh the milestone contract and inspect historical state

Reload/reconnect the host so it reads 0.6.0's current tool schemas and operation
help. `fow_promote_milestone` uses a nonempty `requirement_ids` list for work
realized by this milestone and a disjoint `prerequisite_requirement_ids` list for
requirements owned by earlier milestones in the same project. Use `[]` when none
apply. The old `dependency_closure_ids` input is rejected; there is no alias.

The upgrade preserves historical rows and frozen exports. Derived reads can now
show prerequisite mapping/current-authority gaps, stale plan fingerprints or an
unverifiable legacy replay. These are lifecycle observations, not lost database
rows. Inspect the original requirement/goal/milestone intent and resolve affected
work through ordinary authorized mutations. Do not invent earlier producers or
acceptance to clear a guard. A prerequisite is not new current work, and its
membership is not completion evidence.

A certified `flow.operation-effect.v1` rejection proves only the correlated
pre-write invocation had no effect. For an uncertain result or legacy request
without an original fingerprint, inspect durable state before retrying; a new
request key is not a substitute for that inspection. Retain original evidence
and handover payloads while assessing current authority.

The remaining commands select the **published 0.6.0** procedure. See the
[release notes](RELEASE-NOTES-0.6.0.md) for compatibility changes and limits.
Native project deletion is never an upgrade step.

## Identify and stop the existing installation

1. Find the absolute Flower executable and the profile arguments already used
   by your coding client. Reuse the original `--venv`, `--profile` and
   `--profile-root` values. `FLOWER_HOME` can affect the default profile root;
   do not change it during an update.
2. Run that existing executable with `doctor` and the same profile options.
   Check its profile configuration and database path. Published 0.3.0's
   `doctor` does not report the installed distribution version; use the same
   environment's Python command below when that field is unavailable. The new
   upgrade preview also reports the old installed version. Diagnosis reads
   configuration; it does not establish an MCP connection.
3. Record a known lifecycle project ID and, when relevant, its handover ID.
   Resume that project after updating; creating a replacement project is not
   an upgrade or a recovery step.
4. Stop **all Flower processes and coding clients sharing the environment**.
   A client may automatically restart its stdio server, so disconnect/close it
   before updating. The installer never stops processes. It leases only the
   selected database; it cannot prove that another profile's process has stopped.
   Do not run concurrent installers or updates against the same environment;
   the selected-database lease is not a global installation lock.

Read the installed version with the existing interpreter, replacing the example
environment path:

```sh
/absolute/flower-venv/bin/python -I -c "from importlib.metadata import version; print(version('flow-of-work-mcp'))"
```

```powershell
& 'C:\absolute\flower-venv\Scripts\python.exe' -I -c "from importlib.metadata import version; print(version('flow-of-work-mcp'))"
```

Default installation environments and profile roots are separate:

| OS | Installation environment | Persistent profile root |
| --- | --- | --- |
| macOS | `~/Library/Application Support/Flower MCP Install/venv` | `~/Library/Application Support/Flower MCP` |
| Windows | `%LOCALAPPDATA%\Flower MCP Install\venv` | `%LOCALAPPDATA%\Flower MCP` |
| Linux | `$XDG_DATA_HOME/flower-mcp-install/venv`, or `~/.local/share/flower-mcp-install/venv` | `$XDG_DATA_HOME/flower-mcp`, or `~/.local/share/flower-mcp` |

An explicit `--profile-root` or `FLOWER_HOME` overrides the persistent root.
The selected profile normally lives under `profiles/NAME/flower.yaml`; use
`doctor` to discover its actual database path instead of guessing.

## Preview an owned release upgrade

Download and inspect the **new version's** installer. It understands the safe
upgrade options; an older downloaded script does not acquire new behavior.
Prerequisites remain those in [INSTALLATION.md](INSTALLATION.md#prerequisites).

macOS/Linux, with default installation paths:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.0/install.sh | bash -s -- --upgrade --dry-run
```

Windows, run the download separately and inspect the script before execution:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/Damel91/flower-mcp/releases/download/v0.6.0/install.ps1' -OutFile '.\install.ps1'
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.0' -Upgrade -DryRun
```

For a custom installation, add its original environment and data options to
both preview and execution. For example, on macOS/Linux:

```sh
python3 -I ./install_flower.py --version 0.6.0 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state'
```

Here `install_flower.py` is the selected new backend, checked against its own
`SHA256SUMS`. This backend supports the read-only preview with an existing Python
interpreter. Execution downloads the matching release wheel. The launchers
perform the backend checksum check.
On Windows, the corresponding PowerShell options are `-Venv`, `-Profile` and
`-ProfileRoot`; the Python backend uses the same long flags on every OS.

For example, preview an existing custom Windows installation with its original
values, replacing these example paths:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.0' -Upgrade -DryRun -Venv 'C:\absolute\flower-venv' -Profile 'default' -ProfileRoot 'C:\absolute\private\flower-state'
```

The returned `flower.release-upgrade-plan.v1` identifies the previous/requested
version, environment, existing profile/config/database, backup location and
restart actions. Verify that it names your existing data. The Python backend's
dry run does not download a wheel, create/acquire a runtime lock, start Flower,
write lifecycle files or mutate packages. Downloading the launcher/backend is
a separate preparation step. The Bash/PowerShell frontends can download the
backend or prepare managed Python even with a dry-run flag. For a strictly
read-only local plan, use an already available Python interpreter and the local,
previously downloaded and checksum-verified `install_flower.py` command above.

Upgrade defaults to no client registration. Do not pass `--platform` or
`--client-config` with `--upgrade`; they are rejected. A deliberate registration
change uses the separate installed `flower-mcp install` command after the update.
The backend refuses absent/foreign environments, an invalid or missing profile,
receipt/version divergence, downgrades and unsafe overlapping paths. It does
not adopt a manual environment, discover a different profile or relocate data.

## Execute and resume

After inspecting the plan and stopping clients, repeat the same command without
`--dry-run` / `-DryRun`. For default macOS/Linux paths:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.0/install.sh | bash -s -- --upgrade
```

For Windows:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.0' -Upgrade
```

The backend verifies the release wheel, acquires the existing selected-ledger
ownership lease and creates an exclusive private backup directory. SQLite's
backup API makes a consistent database copy; the exact profile YAML is copied
alongside it before pip runs. The lease stays held through package installation,
version checking and diagnosis. An active owner blocks the update; do not delete
lock files or try to bypass it.

Backups default to `upgrade-backups` under the selected profile root, outside
the code environment. `--backup-root /absolute/private/backups` or PowerShell
`-BackupRoot` selects a safe alternative. `--dry-run` and `--backup-root` are
upgrade-only. Keep backups private: they contain project authority and evidence.
The automatic backup covers the database and profile YAML, not a separate copy
of all imports or logs. The original imports, logs and registrations stay in place.

On success, retain the returned old/new versions and backup paths. Run the
same absolute Flower executable with `doctor` and the original profile options,
then reconnect/reload your coding client. Ask the agent to check Flower's
advertised installed distribution version is **0.6.0**, select the **known existing project**,
read its current snapshot and use `fow_handover` with `resume_context` when a
handover is available. Get/replay preserves historical handover payloads; current
resume compares authority instead of rewriting them. Verify another restart
against that same profile before resuming mutations.

## Failed updates and recovery

Stop on failure and inspect the reported stage and retained paths. Original
lifecycle data and completed backups are retained. A package installation can
partly change the environment before failing; the installer does not promise an
atomic pip rollback, restore a database automatically or silently repair a
version/receipt mismatch. Do not repeatedly retry a mismatched environment or
delete its receipt to force adoption.

Diagnose the installed version and dependency state with that environment's
interpreter. Preserve the backup, installation receipt and error before an
explicit repair. Reinstalling the exact verified intended wheel can be part of
a diagnosed package repair; changing client ownership or data is a separate
operation. For data recovery, keep the original profile untouched, restore the
backup into a separate private runtime directory and explicitly select a copied
configuration pointing there. Never overwrite a running or existing ledger.
Do not run an older Flower against the migrated ledger. A recovery requiring
an older package also requires its matching saved database/profile in a
separate private directory; preserve the original files.

## Manual pip installations

Manual environments have no release-installer ownership receipt. Do not create
one by hand. Stop all clients sharing the environment, record the existing
profile/config/database paths with `doctor`, and back up before pip mutation.
Download the 0.6.0 Flower wheel and `SHA256SUMS`, and compare the exact wheel's
SHA256 using the [manual installation checks](INSTALLATION.md#manual-installation-from-a-release-wheel).

For a consistent SQLite backup, save the following as `backup_flower.py` outside
the profile. It uses Python's standard library. Pass the actual existing database
and YAML paths from diagnosis, plus a **new absolute backup directory outside
the environment and profile**. It refuses to reuse a backup directory. All
Flower processes must already be stopped; this manual script does not manage
the runtime lease.

```python
import os
from pathlib import Path
import sqlite3
import sys

if len(sys.argv) != 4:
    raise SystemExit("Supply database, YAML and new absolute backup directory.")
paths = [Path(value).expanduser() for value in sys.argv[1:]]
if not all(path.is_absolute() for path in paths):
    raise SystemExit("Use absolute paths.")
database, config, destination = (path.resolve() for path in paths)
if not database.is_file() or not config.is_file():
    raise SystemExit("Supply existing database, existing YAML and new backup directory.")
if destination.is_relative_to(database.parent) or destination.is_relative_to(config.parent):
    raise SystemExit("Choose a backup directory outside the profile.")
destination.mkdir(mode=0o700, parents=True, exist_ok=False)
backup = destination / "ledger.sqlite3"
descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(descriptor)
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
    with sqlite3.connect(backup) as target:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise SystemExit("Backup integrity check failed; do not upgrade.")
yaml_copy = destination / "flower.yaml"
descriptor = os.open(yaml_copy, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(descriptor, "wb") as output:
    output.write(config.read_bytes())
print(destination)
```

Use your existing environment's Python to run this script. For example:

```sh
/absolute/flower-venv/bin/python ./backup_flower.py /absolute/private/profile/ledger.sqlite3 /absolute/private/profile/flower.yaml /absolute/private/backups/before-0.6.0
```

On Windows use `& 'C:\absolute\flower-venv\Scripts\python.exe'` and your actual
absolute paths. Stop if backup or integrity checking fails. Filesystem access
controls on Windows should restrict the backup directory to your account.
Back up separate imported source files as needed; the script covers the ledger
and its configuration.

Upgrade the verified core wheel **in the same environment**, then check dependencies:

```sh
.venv/bin/python -m pip install --upgrade ./flow_of_work_mcp-0.6.0-py3-none-any.whl
.venv/bin/python -m pip check
```

```powershell
& .\.venv\Scripts\python.exe -m pip install --upgrade .\flow_of_work_mcp-0.6.0-py3-none-any.whl
& .\.venv\Scripts\python.exe -m pip check
```

Replace `.venv` with the existing absolute environment path. Do not recreate it,
delete the profile, run uninstall or change `FLOWER_HOME`. Finish with the same
profile diagnosis and public MCP project/restart checks above. Keep the backup;
manual pip has the same partial-failure and explicit-recovery boundaries.
