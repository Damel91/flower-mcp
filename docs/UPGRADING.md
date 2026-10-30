# Upgrade Flower without losing project data

## Preparing a 0.7.4 upgrade

Flower 0.7.4 distinguishes global execution admission, PVP preparation and the
semantic findings subgate, with exact declaration diagnostics; see the [release notes](RELEASE-NOTES-0.7.4.md). SQLite remains
schema 55. Dependencies and installer behavior are unchanged. Keep the existing
environment, profile, database, YAML and client configuration. Stop its owners,
then use the ordinary installer with `--upgrade`; it backs up SQLite and YAML
before pip and refuses active ownership.

Download the matching official installer and verify `SHA256SUMS`. Preview with
`python3 -I ./install_flower.py --version 0.7.4 --upgrade --dry-run` and the original
`--venv`, `--profile` and `--profile-root` values. Remove `--dry-run` to apply;
Windows uses `py -3 -I` or the existing PowerShell route below. Restart the same
profile. Keep the backup; failed pip is not an atomic rollback.

This update does not change your plan, execute pending work or resolve uncertain
historical calls automatically. Inspect current authority before deliberately
repairing declarations; preserve existing outcome pins and human approval gates.

<a id="preparing-a-073-upgrade"></a>

## Historical 0.7.3 upgrade checkpoint

Flower 0.7.3 improves [PVP authoring guidance](PLAN-AUTHORING.md) and structured
unit-revision errors; its [release notes](RELEASE-NOTES-0.7.3.md) retain the original
scope. Its official installer and `SHA256SUMS` remain on
[release 0.7.3](https://github.com/Damel91/flower-mcp/releases/tag/v0.7.3).
Use `--version 0.7.3 --upgrade --dry-run` with the existing environment/profile;
remove `--dry-run` to apply that historical version. Schema55, database/YAML/client
paths and ordinary backup-before-pip behavior remain unchanged. The current
operational examples below select 0.7.4 assets when available.

<a id="preparing-a-072-upgrade"></a>

## Historical 0.7.2 upgrade checkpoint

Flower 0.7.2 validates packet architecture references before lifecycle repair and
preserves read-only roadmap gates; see the [release notes](RELEASE-NOTES-0.7.2.md).
SQLite remains schema 55. Dependencies, installer behavior and existing contracts
are unchanged. Reuse the same environment, profile, database, YAML and client
configuration. Stop its owners, then use the ordinary installer with `--upgrade`;
it backs up SQLite and YAML before pip and refuses active ownership.

Download the matching official installer and verify `SHA256SUMS`. To preview,
use `python3 -I ./install_flower.py --version 0.7.2 --upgrade --dry-run` with your
original `--venv`, `--profile` and `--profile-root` options. Remove `--dry-run`
to apply. Windows uses `py -3 -I` or the PowerShell route below. Restart the same
profile after installation. Keep the backup; failed pip is not an atomic rollback.

An uncertain historical071 packet revision requires separate
[owner reconciliation](PACKET-REVISION-RECOVERY.md). Updating the package does not
replay work or rewrite an earlier response. Older checkpoints retain their pins.

<a id="preparing-a-071-upgrade"></a>

## Historical 0.7.1 upgrade checkpoint

Flower 0.7.1 corrects architecture rejection diagnostics; see the
[release notes](RELEASE-NOTES-0.7.1.md). Schema 55, dependencies and installer
behavior are unchanged. Keep the same environment, profile, database, YAML and
client configuration. The ordinary upgrade backs up SQLite and YAML before pip
and refuses an active owner; no separate data migration is needed.

Download the matching official installer and verify its SHA256SUMS. Preview with
`python3 -I ./install_flower.py --version 0.7.1 --upgrade --dry-run` and your
original `--venv`, `--profile` and `--profile-root` values; stop all owners and
repeat without `--dry-run` to apply. Windows uses `py -3 -I` or the existing
PowerShell route below. Keep the backup and restart the same profile.

If recovering the retained malformed070 proposal, perform the separate
[read-only source assessment](ARCHITECTURE-RECOVERY.md) against the retained070
package before retiring it. Updating code alone does not rewrite the original
unknown response or replay work. Historical checkpoints below retain their pins.

<a id="preparing-a-070-upgrade"></a>

## Historical 0.7.0 upgrade checkpoint

Flower 0.7.0 adds the [bounded engineering cycle](ENGINEERING-CYCLE.md); see the
[release notes](RELEASE-NOTES-0.7.0.md). SQLite remains at schema 55 with no new
migration or dependency change. Use the matching [official assets](https://github.com/Damel91/flower-mcp/releases/tag/v0.7.0)
and SHA256SUMS. Tag `v0.7.0` identifies commit
`ae96517e34f8c0b622249f22667f8f3471128dc4`; the
[Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/40911424880)
passed all eight jobs. Official wheel SHA256:
`60d48ddc702b662e53115698bbf2c603b124461980571e2f9251abeb950ee0d0`.

Keep the original environment, profile, ledger, YAML, imports/logs and coding-
client configuration. Preview the same-profile plan:

```sh
python3 -I ./install_flower.py --version 0.7.0 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Stop all owners before running the reviewed command without `--dry-run`. The
unchanged installer refuses active ownership and creates a consistent SQLite
backup and exact YAML copy before pip. Retain that backup. Failed pip does not
promise automatic restore or atomic rollback. Restart the intended client with
the same profile; inspect the known existing project rather than creating a
replacement. Windows uses `py -3 -I` or the PowerShell route below.

Existing issued plans, outcomes, receipts, evidence, handovers and stored exports
retain their original authority. New acceptances require adopted architecture;
new external-agent cycle-1 work also requires a current repository review before
final closure or dependent admission. Historical evidence is not erased or
promoted to current proof. Updating the package does not automatically edit
project `AGENTS.md`: print the new `bootstrap` and authorize its bounded merge.
An ordinary upgrade replaces the package in the existing environment; it does
not recreate the profile or database.

The following historical sections retain their original pins and test evidence.

## Preparing a 0.6.5 upgrade

Flower 0.6.5 improves guided bootstrap responses and exact operation help; see the
[release notes](RELEASE-NOTES-0.6.5.md). Use its checksum-verified
[official assets](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.5).
The tag identifies commit `2eaf234cecfdacaa75610eeb1949293beb5c5f45`;
the official wheel SHA256 is
`48da3678367b8cc99e3cf81669f004960d04c4969523ac6ad4fa4e5c609198f4`.
The [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39682198095)
passed all eight jobs, including installed upgrade checks.
SQLite remains at schema 55; there is no new migration, model
requirement or change to the existing backup/upgrade implementation.

Keep the original environment, profile, ledger, YAML, import/log paths and client
configuration. Download the official installer and SHA256SUMS, then inspect the
same-profile plan:

```sh
python3 -I ./install_flower.py --version 0.6.5 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Stop all owners of that environment/ledger before running the reviewed plan
without `--dry-run`. The installer refuses active ownership and makes a
consistent SQLite backup plus an exact YAML copy before pip. Keep that backup;
retain the same client/profile paths and restart the intended client. Existing
requirements, revisions, receipts, evidence and handovers stay in that ledger.
Failed pip does not promise automatic restore or atomic rollback. Windows uses
`py -3 -I` or the PowerShell examples below.

An update does not clear historical unknown results or authorize replay. Noxi's
actual preview update is a separate owner operation after its active run stops;
it must preserve chat/data. Runtime-llama and paused pipelines are unchanged.
The 0.6.4 and earlier sections below preserve their historical pins and evidence.

## Preparing a 0.6.4 upgrade

0.6.4 is published: tag `v0.6.4`, commit `76b3fbd666f027a8c2007819e5ae589828cdf731`
([release 418844855](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.4)).
The [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39490419031)
passed all eight jobs. Seven anonymous assets match SHA256SUMS; wheel SHA256:
`572baa55357ffe35b31d6dfb9c4229f1495b814bb72f22d4c46b22a4f8e83d67`. The [release notes](RELEASE-NOTES-0.6.4.md) explain
packet-start effect proof and genuine uncertainty. SQLite schema 55 and dependencies
remain unchanged; historical request recovery is a separate native host operation.

Use the original environment, profile, ledger, YAML, import/log paths and client
configuration. Verify the new official `install_flower.py` and `SHA256SUMS`, then
preview the ordinary same-profile plan:

```sh
python3 -I ./install_flower.py --version 0.6.4 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Stop every owner/client sharing that environment/ledger, then run the reviewed
plan without `--dry-run`. The unchanged installer rejects active ownership and
backs up SQLite consistently plus exact YAML before pip. Preserve the backup;
never reset projects, replace bindings or bypass an owned receipt with manual
pip. Windows uses `py -3 -I` or the PowerShell instructions below. An installation
update and a consumer's historical request recovery are separate steps. Retain
original unknown responses; do not repeat an uncertain operation to obtain a
new receipt. Restart/reconnect the intended client using the same profile.
Failed pip does not promise automatic restore or atomic rollback.

The 0.6.3 and earlier sections below retain their historical pins and evidence.
Current operational commands later in this guide select 0.7.4.

## Preparing a 0.6.3 upgrade

Tag `v0.6.3` identifies commit `e6e6649bf631ed986217bf758ff3d9d8d389937e`
([release 418513137](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.3)).
The wheel SHA256 is `dc1716e87c10f5417693edd7ed6656b49da95c7c9e72c27e7a3c9b952f613f20`.
The [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39439773272)
passed all eight jobs; seven downloaded official assets match SHA256SUMS.

**0.6.3 is published.** Its [focused HTTP cleanup correction](RELEASE-NOTES-0.6.3.md)
adds no database migration or transport/schema change. Existing schema-55 data,
revisions, receipts, evidence, handovers and historical artifacts remain in the
same ledger. Stdio is unchanged. The release and installed-artifact checkpoints
are separate from the already qualified corrected-source behavior; candidate
preparation does not update a real installation or prove a named client connected.

Download the official 0.6.3 `install_flower.py` and
`SHA256SUMS`, verify that backend's exact checksum, then preview with the existing
environment and data paths:

```sh
python3 -I ./install_flower.py --version 0.6.3 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Use the matching official assets for this command. Windows uses `py -3 -I` and its actual paths. Keep the original
venv, profile root, database, YAML, import/log paths and client configuration.
Stop every Flower owner/client sharing the environment before executing the
inspected command without `--dry-run`. The existing installer refuses an active
selected-ledger owner and creates a consistent SQLite backup plus an exact YAML
copy before pip. Keep that private backup. Do not reset projects, replace
bindings, move the ledger or bypass the owned installation receipt with manual
pip. Manual environments use the separate procedure later in this guide.

After upgrade, reconnect the host using its intended transport and the same
profile, inspect the known project through public MCP, and confirm continuity
after restart. Restarting a coding client and confirming its own stdio connection
is a distinct client check; an HTTP shutdown result does not prove it. Genuine
cleanup failures must be investigated, not dismissed as successful termination.
Failed pip does not promise automatic restoration or atomic package/database
rollback. The predecessor 0.3.1/schema52-to55 route remains separate.

The historical 0.6.2 checkpoint below retains its exact release, commit, digest,
commands and qualification evidence. General operational commands below follow the current release, separately from this historical checkpoint.

## Preparing a 0.6.2 upgrade

0.6.2 is published with [readable lifecycle references](readable-lifecycle-example.md).
Use tag `v0.6.2`, commit `12ad69317dab92bdba06ae113ac22d107d259236`
([release 416738867](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.2)), and its own `SHA256SUMS`.
The official Flower wheel SHA256 is
`0e2a37013bcfcce0476edf1324e6a660bd5ac3c8ea783d62cf7cf8a3148df182`.
Retain the original environment, profile root, SQLite database, YAML and coding
client configuration. There is no new migration for an existing schema-55 ledger.
Requirements, authority revisions, receipts, verification, frozen handovers and
historical generated artifacts remain intact. Current derived Markdown changes;
an old generation or request replay is not rewritten.

Verify the downloaded backend's checksum before using its original ownership,
preview and consistent-backup safeguards:

```sh
python3 -I ./install_flower.py --version 0.6.2 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Stop all Flower owners/clients sharing that environment, then execute the
inspected command without `--dry-run`. Windows uses `py -3 -I` and its actual
paths. Keep the backup created before pip. The backend refuses an active owner;
failed pip does not promise automatic restoration or atomic package/DB rollback.
Start the same profile, inspect the known project through public MCP and verify
another restart. Do not reset projects, replace bindings or bootstrap a new
project to recover old work.

The actual official HTTPS 0.6.1 → 0.6.2 qualification used a fresh owned macOS
fixture: 349 schema objects, 130 tables and 261 existing rows at schema 55.
Pure preservation included every existing row, revision, receipt and artifact,
exact immutable YAML/client/auxiliary files and original paths. The operational
server log retained its original byte prefix and file identity; only attributed
startup messages were appended. Active-owner refusal, a pure dry
run, consistent backup before pip, public recovery, restart and offline reference
reading passed across 320 probe invocations and 217 tool calls. A separately
declared generation trial added 31 rows; those new test mutations are not part
of the pure-upgrade claim. All five owned server processes were stopped.
[Exact CI](https://github.com/Damel91/flower-mcp/actions/runs/39168606257), the
[Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39169849356), anonymous asset checks
and this same-schema HTTPS trial are distinct from the retained CI migration
check from published 0.3.1/schema 52 to 55 on Linux and Windows.

For Flower integrated in Noxi, use its existing native application updater and
inspect the proposed components. Select Flower only; a Flower update does not
authorize changing Noxi, CodingCastle or another module. Its owner preserves
SQLite, chats/project/configuration and auxiliary state, retains its previous
managed generation and verifies recovery plus another restart. This route and
any declared managed-generation path transition have their own provenance.
The owned same-path fixture above does not establish actual Noxi adoption,
unknown OS/client usability, model quality or human acceptance.

The following 0.6.1 and 0.6.0 checkpoints retain their original pins and commands.

## Preparing a 0.6.1 upgrade

0.6.1 is published with the read-only [lens catalog](LENS-CATALOG.md).
Use its verified release assets, identified by tag `v0.6.1` at commit
`8de41beb1368ef772755b068b7404a91d3197f49`
([release 416461595](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.1)).
Earlier published releases are preserved by policy; locally rebuilt wheels with
the same metadata remain separate artifacts.
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
Same-schema 0.6.0 → 0.6.1 and predecessor 0.3.1/schema 52 → 55 checks are separate;
no new migration or atomic package/database rollback is promised.

The actual official HTTPS upgrade was checked on a fresh owned macOS profile:
349 schema objects, 130 tables and 187 rows in the populated test ledger, with
schema 55, revisions,
receipts, evidence, handovers, YAML, client configuration and original paths
preserved. Active-owner refusal, a pure dry run, consistent backup before pip,
public MCP recovery and restart passed across 108 probes and 79 tool calls.
All 186 installed source/resource files matched the official wheel/source bytes.
[Exact candidate CI](https://github.com/Damel91/flower-mcp/actions/runs/39129035522),
the [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39130028443/attempts/2),
anonymous assets and this populated upgrade are distinct checks. No real user
installation was changed. This does not qualify an unknown OS, model usability,
an actual client deployment or human acceptance.

The following paragraphs retain the historical 0.6.0 compatibility checkpoint.
The general preview, execution and manual-pip instructions later in this guide
select selected 0.7.4 assets assets.

**Flower MCP 0.6.0 is published.** Its
[milestone compatibility change](RELEASE-NOTES-0.6.0.md#milestones-realized-work-and-prerequisites)
changed public inputs while preserving SQLite schema 55. Its historical
checkpoint below retains the original 0.6.0 commands. The current operational
examples follow later; see the [installation guide](INSTALLATION.md).
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

The remaining operational commands select selected **0.7.4** assets. See the
[current release notes](RELEASE-NOTES-0.7.4.md) and the retained
[0.6.0 compatibility notes](RELEASE-NOTES-0.6.0.md).
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
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.7.4/install.sh | bash -s -- --upgrade --dry-run
```

Windows, run the download separately and inspect the script before execution:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/Damel91/flower-mcp/releases/download/v0.7.4/install.ps1' -OutFile '.\install.ps1'
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.7.4' -Upgrade -DryRun
```

For a custom installation, add its original environment and data options to
both preview and execution. For example, on macOS/Linux:

```sh
python3 -I ./install_flower.py --version 0.7.4 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state'
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.7.4' -Upgrade -DryRun -Venv 'C:\absolute\flower-venv' -Profile 'default' -ProfileRoot 'C:\absolute\private\flower-state'
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
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.7.4/install.sh | bash -s -- --upgrade
```

For Windows:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.7.4' -Upgrade
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
advertised installed distribution version is **0.7.4**, select the **known existing project**,
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
Download the 0.7.4 Flower wheel and `SHA256SUMS`, and compare the exact wheel's
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
/absolute/flower-venv/bin/python ./backup_flower.py /absolute/private/profile/ledger.sqlite3 /absolute/private/profile/flower.yaml /absolute/private/backups/before-0.7.4
```

On Windows use `& 'C:\absolute\flower-venv\Scripts\python.exe'` and your actual
absolute paths. Stop if backup or integrity checking fails. Filesystem access
controls on Windows should restrict the backup directory to your account.
Back up separate imported source files as needed; the script covers the ledger
and its configuration.

Upgrade the verified core wheel **in the same environment**, then check dependencies:

```sh
.venv/bin/python -m pip install --upgrade ./flow_of_work_mcp-0.7.4-py3-none-any.whl
.venv/bin/python -m pip check
```

```powershell
& .\.venv\Scripts\python.exe -m pip install --upgrade .\flow_of_work_mcp-0.7.4-py3-none-any.whl
& .\.venv\Scripts\python.exe -m pip check
```

Replace `.venv` with the existing absolute environment path. Do not recreate it,
delete the profile, run uninstall or change `FLOWER_HOME`. Finish with the same
profile diagnosis and public MCP project/restart checks above. Keep the backup;
manual pip has the same partial-failure and explicit-recovery boundaries.
