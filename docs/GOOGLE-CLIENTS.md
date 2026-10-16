# Antigravity and Gemini CLI

Flower supports installation targets `antigravity` and `gemini-cli` on Windows,
macOS and Linux. The ordinary installer installs Flower core; no Flower model,
Google Cloud project, gcloud tool or inference extra is needed for MCP. Install
and sign in to your chosen Google coding client separately using its official
instructions. Flower does not install a Google app or change its tool approvals.

## Prerequisites and installation

Follow [installation prerequisites](INSTALLATION.md) for your OS, including
Python 3.11+ for manual installation, or the managed Python option in the release
installer. On macOS/Linux the release frontend also needs Bash, curl, awk and
sha256sum or shasum. Windows uses PowerShell 5.1+ and Invoke-WebRequest; curl is
not needed for that PowerShell route. Network access is needed to download
release assets and Python dependencies.

Select either client with the release installer:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.5.0/install.sh | bash -s -- --platform antigravity
# For Gemini CLI, replace antigravity with gemini-cli.
```

On Windows, download and inspect install.ps1 as described in the main guide:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version 0.5.0 -Platform antigravity
# For Gemini CLI, use -Platform gemini-cli.
```

Updating Flower code uses the separate [safe upgrade route](UPGRADING.md),
without changing the existing Google client registration. The commands below
register a client; they are not needed for an ordinary package upgrade.
Use the already installed Flower environment's absolute executable path:

```sh
/absolute/flower-venv/bin/flower-mcp install --platform gemini-cli --dry-run
/absolute/flower-venv/bin/flower-mcp install --platform gemini-cli
/absolute/flower-venv/bin/flower-mcp doctor --platform gemini-cli
```

On Windows use `& 'C:\absolute\flower-venv\Scripts\flower-mcp.exe'` with the
same arguments. Substitute `antigravity` for that client. Stop on a conflict;
`install --replace` is the explicit replacement route and retains a backup.
Repeated owned installation makes no changes. `doctor` checks files without
starting Flower, querying a model or claiming the coding client connected.

## Configuration locations

| Client | Default user file | Explicit project file |
| --- | --- | --- |
| Antigravity | `~/.gemini/config/mcp_config.json` | `<project>/.agents/mcp_config.json` |
| Gemini CLI | `~/.gemini/settings.json` | `<project>/.gemini/settings.json` |

`~` is your home directory on all three OSes, for example `C:\Users\you` on
Windows. Gemini CLI's `GEMINI_CLI_HOME` changes its home root; Flower appends
`.gemini/settings.json` to that root. This does not change Antigravity's default.
An explicit `--client-config /absolute/file.json` selects that one file instead.
Use the same file argument for install, doctor and uninstall. Project settings
or administrator policies can affect the configuration the Google client uses.

For Antigravity versions showing a different path in **View raw config**, select
that exact file using `--client-config`. Flower does not search or migrate old
configurations. Both clients receive a `mcpServers.flower` entry with an absolute
Python command and separate arguments for Flower's stdio server and persistent
profile. No shell command, URL, credential or automatic trust is inserted.

Flower's managed JSON registration requires strict JSON with unique keys.
Gemini's native editor can accept comments; if your file contains comments,
use the client's native/manual editing route instead. Flower refuses that file
without stripping comments or changing unrelated preferences. For manual
configuration, add the following entry to the client's `mcpServers` object with
your actual absolute installed console path, preserving existing content:

```json
{
  "flower": {
    "command": "/absolute/flower-venv/bin/flower-mcp",
    "args": ["serve", "--profile", "default", "--transport", "stdio"]
  }
}
```

On Windows use the absolute `Scripts\\flower-mcp.exe` path instead. This manual
route creates the default persistent profile on first startup. A manually added
entry has no Flower ownership receipt; edit/remove it through the client rather
than Flower's managed uninstall.

## Connect and start a project

In Antigravity, open its MCP management interface and refresh/reload the
configuration. In Gemini CLI, start a new session after Flower edits settings;
inspect `/mcp` and `/mcp schema`. A reload within an existing Gemini session
can restart the already known servers, so use a new session to read file changes.
The client still controls trust and tool approval.

Once connected, give your agent the output of `flower-mcp bootstrap` so it can
merge Flower's engineering instructions into the intended project's AGENTS.md.
Flower's public capabilities and guided bootstrap then handle the lifecycle.
The print-only bootstrap command does not change your instruction file itself.

Antigravity reads the project's AGENTS.md. Gemini CLI normally reads GEMINI.md:
after merging Flower's template into AGENTS.md, add the following import to the
project's GEMINI.md, preserving any existing instructions:

```markdown
@./AGENTS.md
```

In Gemini CLI run `/memory reload`, then `/memory show` to verify that Flower's
instructions were loaded. Alternatively, explicitly include AGENTS.md in your
Gemini `context.fileName` setting. Flower's installer changes neither instruction
files nor this context setting. See [Gemini instruction files](https://geminicli.com/docs/cli/gemini-md/)
and [Antigravity rules](https://antigravity.google/docs/rules).

To remove only Flower's owned registration, run `flower-mcp uninstall --platform
antigravity` or `--platform gemini-cli`, with the same profile and config options.
Persistent projects, ledger and evidence remain on disk.

## Compatibility evidence

The qualification checks registration, replay, conflicts and owned removal,
then launches the generated entry through public MCP across a restart. This is
installed-server and configuration proof. Native Antigravity/Gemini model
usability and client-specific approval behavior require separate client testing;
those applications are not installed in the qualification environment.

Configuration references checked 2026-10-11:
[Antigravity MCP](https://antigravity.google/docs/mcp),
[Gemini CLI MCP](https://geminicli.com/docs/tools/mcp-server/),
[Gemini configuration](https://geminicli.com/docs/reference/configuration/),
[Gemini MCP commands](https://geminicli.com/docs/reference/commands/#mcp).
