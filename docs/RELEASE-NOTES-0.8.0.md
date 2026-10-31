# Flower MCP 0.8.0

Flower can now register directly with **OpenCode V2** through the Python, Bash
and PowerShell installers. Select `opencode`, or run the installed
`flower-mcp install --platform opencode` command for an existing profile.

The adapter generates OpenCode's `mcp.servers` structure with an absolute Python
command array and `codemode: false`, keeping Flower's direct engineering verbs
available to the host. It reuses ownership receipts, pure dry-run and replay,
explicit replacement/backups and owned removal. Configuration and receipt
comparisons preserve JSON types, so numeric zero cannot impersonate a boolean.

The default follows `OPENCODE_CONFIG_DIR`, then `XDG_CONFIG_HOME/opencode`, then
`~/.config/opencode`; an explicit `--client-config` selects another file.
Existing JSONC siblings and V1 server layouts produce actionable diagnostics
rather than a silent conversion or competing configuration. See the
[OpenCode guide](OPENCODE.md) for manual JSONC/HTTP setup and project AGENTS
bootstrap. Existing project rules, provider settings and client approvals remain
under their owners' control.

## Upgrade

Use the [ordinary same-profile upgrade](UPGRADING.md#preparing-a-080-upgrade).
SQLite remains schema55; dependencies and upgrade algorithms are unchanged.
Keep the same environment, database, profile, YAML and client paths. Stop the
owner, preview with `--upgrade --dry-run`, then apply the existing backup-before-
pip upgrade and restart that profile. Keep the backup; failed pip is not an
atomic rollback. Register OpenCode separately after the package upgrade.

No migration, database reset, pending work execution or historical replay is
required. Earlier releases and their assets remain immutable.

## Qualification boundaries

Focused source and installed MCP workflows, generated stdio startup/restart and
an isolated OpenCode2.2.5 connection on macOS arm64 were verified. A cold
one-shot `mcp list` can precede asynchronous plugin activation; inspect a ready
session when checking the connection. This does not certify native model tool
use or native OpenCode execution on Windows/Linux. Release CI qualifies its own
declared installer/package/platform surfaces; it does not imply those additional
acceptances. Provider/model integrations and paused witness work are unchanged.
