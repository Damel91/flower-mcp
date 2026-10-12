# Flower MCP 0.4.1

This patch corrects SRS rejection diagnostics. When an import or baseline
revision produces several findings with the same code, Flower now stores a
unique summary of codes while retaining every complete finding in the public
job result. A structurally rejected source completes with an explicit rejected
audit and creates no requirements baseline. A source outside the allowed import
root still produces a blocked job.

## Compatibility

There are no new public tools, operation parameters or database migrations.
The 37-tool interface and schema 55 remain unchanged. Architecture authority,
executor selection, standalone PVP export and optional provider negotiation
were introduced in 0.4.0 and are retained. This patch does not add a compatible
provider or qualify a new CodingCastle pairing.

Python 3.11+ and optional runtime-llama 0.4.0 remain unchanged. Core installation
and host execution need no inference dependency or model endpoint. The public
name is Flower MCP; the distribution remains `flow-of-work-mcp`, with both
console aliases preserved. Flower remains in testing.

## Update an existing installation

Use the [safe upgrade plan](UPGRADING.md) and its
[prerequisites](INSTALLATION.md#prerequisites). Keep the existing environment,
`FLOWER_HOME`, profile and profile-root paths. Stop all Flower processes and
coding clients sharing that environment before updating. Preview the plan with
the new release installer, then remove only the preview flag to execute it:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh | bash -s -- --upgrade --dry-run
```

On Windows, download and inspect the launcher first:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.ps1' -OutFile '.\install.ps1'
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.4.1' -Upgrade -DryRun
```

Supply the original `--venv`, `--profile` and `--profile-root` values for custom
paths; Windows uses `-Venv`, `-Profile` and `-ProfileRoot`. These commands require
the matching published release assets. An ordinary source push does not publish them.

The existing owned-installation upgrade acquires the selected ledger's lease,
creates a consistent SQLite backup and copies the exact profile YAML before
pip. It preserves client registration and data paths. Backups remain available
on package failure; there is no atomic pip rollback or automatic data restore.
Manual pip installations use the separate backup procedure in the upgrade guide.

Upgrading 0.4.0→0.4.1 leaves schema 55 unchanged. Upgrading an older 0.3.1/schema52
installation still uses the existing additive 53–55 migrations on first server
start. `doctor` does not perform or verify these migrations. Reconnect with the
same profile, inspect a known project/evidence/handover through public MCP and
verify another restart before resuming mutations. Existing releases and assets
remain immutable.

## Verification boundaries

Focused regression coverage includes import and revision rejection, all rich
findings, unchanged baseline authority, request replay and source-path refusal.
Installed-package tests, live public MCP, native CI, anonymous asset delivery,
target-client usability and human acceptance are separate checkpoints. Check
the exact release commit and its CI results; a local source test does not
qualify another operating system or establish a paired provider contract.

The patch preserves the existing import and job protocol contracts; it does not
establish content-bound import or new recovery guarantees.
