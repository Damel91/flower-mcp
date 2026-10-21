# Flower MCP 0.6.0

This minor version corrects the public milestone contract, adds trustworthy
pre-effect rejection evidence and provides native project deletion controls.
It retains 37 MCP tool names and 445 input parameters, with a **breaking change
to one input's name and meaning**. SQLite remains at schema 55. Core lifecycle,
external-agent plans, TODO and offline reconciliation require no internal model
or technical provider. Flower remains in testing.

Earlier releases, including
[0.5.2](https://github.com/Damel91/flower-mcp/releases/tag/v0.5.2), retain their
original tags and assets. Version-pinned installation commands require the
corresponding published assets. Prepublication qualification uses local candidate
assets and does not establish anonymous HTTPS delivery. Source, installed-package,
exact-commit CI, released-asset checks and an owner's actual update are separate
evidence scopes; the behavior described here does not certify those checkpoints.

## Milestones: realized work and prerequisites

`fow_promote_milestone` replaces `dependency_closure_ids` with
`prerequisite_requirement_ids`. There is no old-name alias. Refresh the host's
tool schema and operation help before submitting a milestone:

```json
{"view":"operation","operation_tool":"fow_promote_milestone","operation_name":"call"}
```

This is the argument object for `fow_capabilities`.

| Field | Meaning in 0.6.0 |
| --- | --- |
| `requirement_ids` | Nonempty unique list of requirements realized by this milestone. |
| `prerequisite_requirement_ids` | Unique requirements assigned to earlier milestones in the same project; `[]` for the first milestone or when none apply. |

The lists must be disjoint. Do not copy the current milestone's requirements
into its prerequisite list. For example, a first milestone can realize
`REQ-000001` with `prerequisite_requirement_ids: []`; a successor realizing
`REQ-000002` can reference `REQ-000001` only after an earlier milestone owns it.
Use actual IDs returned by the selected project's canonical records.

Prior ownership uses the persisted milestone order. All eligible earlier owners
are shown when several exist. Membership proves a declared dependency, not its
implementation, verification or acceptance. Prerequisites appear as context and
producer references in exported plans; they do not inflate the current milestone's
work or completion percentage.

Existing schema-55 rows and frozen exports are preserved. The private inclusive
storage column remains an implementation detail. Historical entries whose extra
requirements have no earlier owner, or whose prerequisites are missing or retired,
produce explicit gaps. Affected readiness, TODO, export, guided completion and
acceptance fail closed. Do not create fictitious producer milestones or acceptance
evidence to clear them: inspect the original intent and resolve the plan through
ordinary authorized lifecycle work. Old export bytes remain historical evidence;
changed authority can make their current use stale.

New promotion events fingerprint the complete normalized original request,
including actor and initial acceptance evidence. An exact retry can recover its
result even after later acceptance changes the row. Conflicting original inputs
are rejected. An old request without a verifiable original fingerprint returns
`milestone_request_replay_unverifiable` without writing; inspect the durable state
before deciding what distinct work is still needed.

## Rejections and uncertain effects

Audited milestone validation that finishes before the first write returns
`result.operation_state: "rejected"`, `result.effect_state: "none"` and an
`effect_receipt` with contract `flow.operation-effect.v1`,
`basis: "pre_effect_validation"` and `mutation_started: false`. Its `tool`,
`operation`, `project_id` and `request_id` must match the original invocation and
audit reference. Input diagnostics identify a bounded problematic value, rule and
next action; model-facing Markdown retains line breaks.

An error status, corrective suggestion or familiar diagnostic code alone is not
proof of no effect. Failures after dispatch, possible commit or response conversion
retain `effect_state: "unknown"` unless certified otherwise. Inspect the original
durable state before retrying a mutation. An unavailable or lost response does not
authorize a duplicate mutation or external execution.

## Native project deletion

The new `flower-mcp project-purge prepare|inspect|delete|reconcile` command is a
native user/host control. It is **not an MCP tool or model task**. See the complete
[native deletion guide](NATIVE-PROJECT-DELETION.md) before using it.

The host explicitly selects an owned ledger and project, stops its runtime and
workers, prepares an immutable inventory, then supplies the same deletion UUID,
exact fingerprint, project confirmation and actual host stop reference. Busy
ownership, stale preparation, incompatible schema, unsafe paths, foreign-key
corruption and unproven external writers block deletion. Flower does not stop
another process or certify physical quiescence from a declaration.

Deletion, SQLite scrub and native host cleanup remain distinct. Reconcile can
inspect an interrupted intent and resume committed deletion's scrub; it cannot
start a merely prepared deletion or delete a recreated project. Only verified
`scrubbed` confirms Flower data cleanup; host acknowledgement then removes the
minimal adjacent journal. Other projects, their counters and original configuration
remain outside the selected deletion. Historical ledgers require separate explicit
selection and independent preparation; Flower does not search the disk for them.

Native deletion requires durable directory synchronization. If unavailable, it
returns `native_purge_durability_unavailable` before deleting project data.
Windows native purge durability has not been qualified. Windows installation,
stdio/MCP checks and POSIX native deletion evidence are separate. Cleanup does not
certify forensic erasure of filesystem snapshots, external backups or SSD media.

## Upgrade while preserving SQLite

Follow [UPGRADING.md](UPGRADING.md), keeping the original environment, profile,
database, YAML and client configuration. Stop every Flower process/client sharing
that environment. Preview the new backend with `--upgrade --dry-run`; use the same
`--venv`, `--profile`, `--profile-root` and optional private `--backup-root` when
executing. An active owner refuses the upgrade. A consistent SQLite backup and
exact YAML copy must complete **before pip** changes packages. Preserve that backup
and verify the known existing project through MCP after startup and another restart.

| Starting ledger | Database behavior |
| --- | --- |
| Published 0.5.2 or another supported schema-55 installation | Schema remains 55; original tables, rows, history, receipts, revisions, evidence and handovers stay in place. |
| Published 0.3.1, schema 52 | Existing additive migrations 53–55 apply on first startup. This is a separate qualification route. |

Local candidate upgrades use reviewed local assets through an explicitly bounded
qualification acquisition step. They do not prove future official HTTPS delivery.
Until 0.6.0 assets are published, its download URLs and normal release-install
execution are unavailable. Manual candidate wheels use fresh/manual environments;
do not pip-replace an installer-owned Flower package or edit its receipt.
Manual existing environments follow the backup procedure in the upgrade guide.
There is no automatic restore or atomic package rollback, and downgrading a package
does not reverse a database migration. Project deletion is never an upgrade step.

After publication, the checked release installer can preview the owned upgrade:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.0/install.sh | bash -s -- --upgrade --dry-run
```

For Windows, only after those assets exist, download and inspect the launcher:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/Damel91/flower-mcp/releases/download/v0.6.0/install.ps1' -OutFile '.\install.ps1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.0' -Upgrade -DryRun
```

Run the download separately and stop on failure. Retain original path arguments,
inspect the plan, then remove only the dry-run flag. See the installation guide
for Bash/curl/checksum utilities, Python and PowerShell prerequisites.

## Packages and optional inference

The version's seven assets are:

- `flow_of_work_mcp-0.6.0-py3-none-any.whl`
- `flow_of_work_mcp-0.6.0.tar.gz`
- `install.sh`
- `install.ps1`
- `install_flower.py`
- `BOOTSTRAP.md`
- `SHA256SUMS`

Compare each selected asset with its own `SHA256SUMS` and retain the exact source
commit. Both Python packages retain Apache-2.0 `LICENSE`/`NOTICE`; the packaged
bootstrap resource, printed `bootstrap` command and `BOOTSTRAP.md` asset agree.
The source archive includes the public guides and offline presentation readers.

The optional `inference` extra selects the independent public `runtime-llama`
`0.5.0` wheel by exact URL and SHA256:
`dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13`.
It is not bundled in Flower assets or installed by core installers. Immutable
Flower 0.5.0/0.5.1/0.5.2 extras retain runtime 0.4.1; historical Flower 0.4.1
retains its runtime 0.4.0 and eight assets. See [INFERENCE.md](INFERENCE.md) for
explicit model setup, supported host assignments and SDK-only updates.

## Qualification boundaries

Qualification separates source deterministic checks and isolated public MCP/native
workflows from installed-artifact workflows, both response channels, offline
reconciliation, restart, whole-ledger preservation, supported 52→55 migration and
exact-commit CI. Results must identify the actual source/artifact and owned fixture;
a source pass is not an installed or official HTTPS pass. The guide describes the
required checks without claiming that an unrecorded checkpoint has passed.

The writer witness/U6, pipeline resumption, provider compilation, physical host
acceptance, cross-server qualification and another user's installation are outside
this version. Optional adapters still need their declared prerequisites; missing
dependencies block the affected operation. Host-reported evidence retains its
provenance. This release does not certify a coding model's understanding or human
acceptance of the software it builds.

## Published delivery record

This record preserves the package-verification checkpoint previously included
in the project README. Client adoption and user acceptance have their own
verification records.

Flower `0.6.0` is published and remains in testing. Published tag `v0.6.0` identifies commit `bb43b5a161ecc85e56f1d2dba2c69184da0a02b7` ([release 416096822](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.0)). [Candidate CI](https://github.com/Damel91/flower-mcp/actions/runs/39072677376) and [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39073239681) are separate from anonymous asset checks and the populated-profile HTTPS upgrade.
The official assets and a fresh owned 0.5.2/schema55 → 0.6.0/schema55 HTTPS upgrade
were checked separately from source, installed-package and CI checks.
No user installation or real project deletion was used for those checks.
The incompatible milestone input is documented above; refresh the host schema.
The writer witness remains deferred. Windows native purge durability and real
Noxi/client acceptance remain separate qualifications.
