# Flower MCP 0.6.1

This patch adds complete Flower-owned lens membership for coding hosts while
preserving direct verbs: 37 tools, 445 input fields and 182 operation routes.
The new `fow_interaction(operation="catalog")` route reads raw durable selection
and returns the exhaustive revision-bound machine catalog. Its bounded multiline
Markdown summarizes all nine work areas without exposing the host chat identity.
See the [host catalog guide](LENS-CATALOG.md).

The catalog includes core, primary and companion routes. It observes stale,
foreign, cleared and unselected bindings truthfully, uses one coherent SQLite
snapshot and never repairs selection or contacts a model/provider. Membership
is declared rather than execution admission. Existing issued-choice selection
and ordinary lifecycle gates remain in force. No database migration is added:
SQLite stays at schema 55, with the original projects, revisions, receipts,
evidence, handovers, configuration and client paths preserved.

## Installation and update

Use the [installation guide](INSTALLATION.md) or
[upgrade procedure](UPGRADING.md#preparing-a-061-upgrade). For an installer-owned
profile, verify the exact installer checksum and preview with the original paths:

```sh
python3 -I ./install_flower.py --version 0.6.1 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

After inspecting that plan, execute it with the same paths and without
`--dry-run`. Stop the owners/clients using that environment first. The installer
refuses an active owner and takes a consistent backup before changing packages.
Do not reset SQLite, replace the profile, delete projects or bypass the owned
installation receipt with pip. Windows can use `py -3 -I` and the same backend
options with its actual paths. Manual environments have a separate procedure.
The existing 0.3.1/schema52→55 migration route remains distinct from a
same-schema 0.6.0→0.6.1 upgrade; package downgrade is not database rollback.

The core requires no internal model or provider. The independently published
optional runtime remains [llama-runtime 0.5.0](https://github.com/Damel91/llama-runtime/releases/tag/v0.5.0),
installed only through the explicit inference extra. Advanced settings and
provider boundaries remain in the [advanced guide](ADVANCED-CONFIGURATION.md).
The writer witness/U6 remains excluded and suspended. Historical tags/assets,
including 0.6.0, are not replaced. Native deletion remains a separate explicit
host action; no new deletion qualification is claimed here.

## Qualification boundaries

31 focused catalog cases cover registry closure, schema/help, machine/Markdown
channels, privacy, corrupt/stale/foreign/absent state, clear/restart, whole-ledger
read purity, poisoned optional dependencies and deterministic concurrent reads.
Source and core-only installed public MCP workflows are separately qualified.
Final candidate bytes, populated-profile upgrade, exact CI, anonymous official
assets and actual HTTPS upgrade are separate recorded checkpoints. This document
is reviewed release guidance, not proof that every later checkpoint or owner
update has happened. Version-pinned commands require the corresponding published
assets. Consumer fixtures do not certify model usability, human acceptance or
physical/cross-provider quiescence. Flower remains in testing.
