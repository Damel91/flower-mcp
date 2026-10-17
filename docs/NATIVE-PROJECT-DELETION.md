# Native project deletion

Flower's `project-purge` CLI deletes the selected project's ledger data. It is a
native host administration control, deliberately absent from MCP tools and the
model operation catalog. A host such as Noxi owns the user's confirmation,
stopping actual workers, local chat/session cleanup and overall completion.
Do not expose this command to a model through a shell or tool dispatcher.
An actor string or same-user OS invocation does not authenticate a human.

Use a current Flower installation against an existing owned schema55 ledger.
The command never creates a profile, boots an old server, migrates a database,
runs lifecycle recovery, initializes a model/provider or stops remote work.
It preserves other projects, global sequences, configuration, source repositories,
imports/exports, shared logs and external backups. It creates no archive or
backup of the deleted project's contents.

## Before deletion

The native host must stop its chat/Pi/Bash workers and its Flow process, prevent
automatic respawn, and retain an opaque reference to its stop evidence. The
existing OS ledger lease refuses a live Flow owner. Never unlink a lock file to
override ownership. An old lock file alone does not prove a process is active.

Resolve actual external activity through the existing provider workflows first.
Uncertain deliveries and active/unknown packet providers block deletion. A
delivered packet START must have correlated retained binding/receipt proof;
missing bindings are blockers even when SQLite foreign keys remain valid. A
newer binding cannot close an unknown older-generation START. Historical closure
requires exact original or same-generation terminal command evidence; ambiguous
status-only historical correlation remains blocked. A
delivered test RUN needs a complete, integrity-preserved terminal `completed`
receipt correlated to that original RUN command. A separate REPORT cannot prove
that correlation in schema55 and does not waive the blocker. Unavailable
providers are not a substitute for terminal evidence.

Historical unknown local mutations can be deleted after the runtime is stopped;
their earlier outcome is never relabelled `none`. An externally referenced
implementation run needs ordinary terminal reconciliation. The host may instead
declare an exact `--host-stopped-run-id RUN-000001` only for an execution it owns
and has actually stopped. This is `host_declared` evidence and cannot waive
packet/test providers owned by another process/server.

## Native workflow

Choose a fresh canonical UUID for one intent, and use it unchanged throughout.
These examples use illustrative identifiers; replace the config, project and
UUID with the selected native host's values.

```sh
flower-mcp project-purge prepare \
  --config /absolute/owned/flower.yaml \
  --project-id my-project \
  --deletion-id 118f2a65-1413-4c14-b37c-9a96584a5489

flower-mcp project-purge inspect \
  --config /absolute/owned/flower.yaml \
  --project-id my-project \
  --deletion-id 118f2a65-1413-4c14-b37c-9a96584a5489
```

Inspect the blockers and copy the exact `prepared_fingerprint` from prepare.
Delete requires that fingerprint, the same explicit project confirmation, and
the native host's stop reference:

```sh
flower-mcp project-purge delete \
  --config /absolute/owned/flower.yaml \
  --project-id my-project \
  --deletion-id 118f2a65-1413-4c14-b37c-9a96584a5489 \
  --expected-fingerprint REPLACE_WITH_EXACT_PREPARED_SHA256 \
  --confirm-project-id my-project \
  --host-quiescence-ref native-host:stopped-workers-42
```

Instead of `--config`, use both `--profile PROFILE` and
`--profile-root /absolute/owned/root`. Paths must exist, be owned local regular
files and not traverse symbolic links. Config/database hard-link aliases are
refused. Do not combine config selection with profile selection. The Python
module entry point is `python -m flow_of_work_mcp.cli project-purge ...` inside
the selected Flower virtual environment.

Prepare records an immutable inventory; it does not delete project data.
Changes to another project's unrelated rows do not stale that inventory.
Changes to the target do: inspect the old/current fingerprints and create a new
explicit preparation ID. Existing intents are never silently rebased. Replaying
the same ID with a different project/config/ledger identity is refused.

Delete atomically removes all known direct, indirect and no-FK project records,
including applicable historical project-context transitions. It preserves other
projects' current contexts/lenses and unrelated events. Unknown schema, foreign
key corruption or cross-project dependencies fail closed.

## Result and recovery

Each syntactically valid invocation returns one JSON object and newline on
stdout. Exit codes are `0` success, `2` rejected, `3` blocked, `4` failed. Syntax
errors use ordinary argument-parser exit2/stderr. Diagnostics contain safe causes
and next actions, never YAML contents, SQL payloads or arbitrary exception text.

`project_effect_state` is cumulative knowledge of this intent, not simply the
current call's writes. `none` is a known pre-delete state; `unknown` requires
inspection; `applied` means deletion is known to have committed or actual complete
absence has been established from a durable deleting intent. A later argument
error does not erase previously known `applied`.

`ledger_deleted` is partial completion: the SQLite records have been removed,
but scrub remains incomplete. Flower verifies `secure_delete=ON`, truncates WAL,
compacts the database, then checks integrity and absence. Only `scrubbed` confirms
Flow data deletion complete. This does not certify Noxi's local chat cleanup,
physical host quiescence or forensic erasure on SSD/filesystem snapshots.

After a lost response or interrupted scrub:

```sh
flower-mcp project-purge reconcile \
  --config /absolute/owned/flower.yaml \
  --project-id my-project \
  --deletion-id 118f2a65-1413-4c14-b37c-9a96584a5489
```

Reconcile never executes a merely prepared deletion, or deletes data still
present after rollback. If the original project remains, inspect it and use
delete only with the original explicit confirmation/fingerprint. If deletion
committed, reconcile can resume scrub. Recreated projects are blocked, never
deleted as recovery. A missing journal and absent project show absence and an
unknown request, not an invented receipt.

The private adjacent `<database>.project-purge/<UUID>.json` journal holds only
IDs, schema/file identity, fingerprints, counts, stage, timestamps and declared
host stop references. It contains no copied requirements, chat or evidence
payloads. After verified Flow scrub and completed native host cleanup:

```sh
flower-mcp project-purge reconcile \
  --config /absolute/owned/flower.yaml \
  --project-id my-project \
  --deletion-id 118f2a65-1413-4c14-b37c-9a96584a5489 \
  --acknowledge-host-cleanup
```

This removes that intent's minimal journal. Other intents are not implicitly
acknowledged. No original conversation archive is retained by this operation.

## Owned historical generations and platform limits

The host enumerates its owned historical generations containing the project;
Flower does not discover ledgers or walk the disk. Invoke the current CLI with
each generation's explicit config. Prepare every selected ledger before any
project DELETE, aggregate the independent results, and recover/acknowledge each
bound intent separately. Any unsupported, busy, unsafe or unproven generation
means aggregate cleanup is incomplete. Never boot the historical runtime merely
to delete its project, or delete external unowned backup copies.

The native command requires demonstrable durable directory synchronization on
the selected platform/filesystem. If unavailable, it reports
`native_purge_durability_unavailable` before project deletion. Windows native
purge durability has not been qualified; this is separate from Flower's Windows
installation/stdio compatibility. Do not weaken durability or claim completion
to bypass a platform blocker.
