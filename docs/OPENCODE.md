# OpenCode V2 setup

Flower connects to OpenCode through its ordinary MCP support. The model keeps
its coding tools; Flower supplies durable requirements, architecture, plans,
evidence and continuation. No Flower-side model or optional inference package
is required.

**Availability:** this adapter is currently unreleased development source.
Published Flower 0.7.6 packages and installers do not contain it. The commands
below require a candidate built from the source containing the adapter; they do
not upgrade an existing installation or reserve a future release version.

## Prerequisites and candidate installation

Install OpenCode separately and use Python 3.11 or newer. Integration targets
**OpenCode V2**, with native connection checks against 2.2.5 on macOS arm64.
OpenCode V1 uses a different configuration; migrate it using OpenCode's own
instructions before selecting this adapter.

For a separate development installation, from this checkout:

```sh
python3 -m venv /absolute/path/to/flower-opencode-venv
/absolute/path/to/flower-opencode-venv/bin/python -m pip install .
/absolute/path/to/flower-opencode-venv/bin/flower-mcp install --platform opencode --dry-run
/absolute/path/to/flower-opencode-venv/bin/flower-mcp install --platform opencode
```

On Windows, use the environment's `Scripts\python.exe` and
`Scripts\flower-mcp.exe`. Python, Bash and PowerShell installer choices include
OpenCode in this source; their pinned release defaults still point to 0.7.6.
Use the local candidate route above until the new adapter has release assets.
Windows native OpenCode execution requires its own qualification.

If Flower with this adapter is already installed, run only its `install`
registration command. There is no need to reinstall Python or replace the
database just to connect another client.

## Select the configuration and profile

The default selected file is `opencode.json` in:

1. `OPENCODE_CONFIG_DIR`, when set;
2. `$XDG_CONFIG_HOME/opencode`, when set;
3. `~/.config/opencode`, otherwise.

Directory overrides must be absolute. An explicit file always wins for Flower:

```sh
flower-mcp install --platform opencode --client-config /absolute/project/opencode.json --profile my-project --dry-run
flower-mcp install --platform opencode --client-config /absolute/project/opencode.json --profile my-project
flower-mcp doctor --platform opencode --client-config /absolute/project/opencode.json --profile my-project
```

If you use OpenCode's `OPENCODE_CONFIG` custom-file setting, select that file
explicitly with `--client-config`. Flower does not scan or rewrite all OpenCode
configuration layers. OpenCode's effective configuration may override the entry
in another file; inspect it in the client after registration.

Dry-run writes nothing. Repeated owned registration is a no-op. A foreign or
edited Flower entry requires review and explicit `--replace`, which retains a
private backup. Owned `uninstall --platform opencode` removes only Flower's entry;
the profile, database and other client settings remain.

## Generated entry and JSONC

Flower generates this V2 structure with actual absolute paths:

```json
{
  "mcp": {
    "servers": {
      "flower": {
        "type": "local",
        "command": ["/absolute/venv/bin/python", "-m", "flow_of_work_mcp.cli", "serve", "--config", "/absolute/profile/flower.yaml", "--transport", "stdio"],
        "disabled": false,
        "codemode": false
      }
    }
  }
}
```

`codemode: false` keeps Flower's direct verbs in the model's native tool list.
The adapter preserves your permissions, other servers and timeout settings;
it does not choose a model or grant tool approvals.

OpenCode reads JSONC after the corresponding JSON file. To avoid installing an
entry that is overridden by an existing `opencode.jsonc`, implicit registration
stops when that sibling exists. Flower edits strict JSON only and does not strip
comments or trailing commas. Merge the entry above manually into JSONC using
your actual executable and profile paths, or explicitly select a strict JSON
file after checking precedence. Manual edits do not create a Flower ownership
receipt; remove such an entry manually too.

## Bootstrap your project

From the project, ask your agent to run the installed absolute
`flower-mcp bootstrap` command and merge its returned Flower block into the
project's `AGENTS.md`. Preserve existing project instructions and the Flower
block markers. This is the same provider-neutral engineering policy used by
other clients; OpenCode reads project `AGENTS.md` natively.

The installer returns `bootstrap_command` as its next step. It does not overwrite
AGENTS automatically. OpenCode's `/init` is not a substitute for Flower's policy.

## Connection and shared runtimes

Reload the OpenCode session after registration and check `opencode mcp list`.
A connected server proves a connection, not that your model followed the
engineering cycle. Ask the agent to discover Flower capabilities and resume the
selected project using the bootstrap instructions. `doctor` reports selected
files; it does not start or probe the client.

If another server owns the same Flower profile, stop that owner first or use a
separate profile. For simultaneous clients sharing one lifecycle database, use
one existing HTTP runtime rather than starting another stdio writer. Configure
the OpenCode entry manually as:

```json
{
  "mcp": {
    "servers": {
      "flower": {
        "type": "remote",
        "url": "http://127.0.0.1:8010/mcp",
        "oauth": false,
        "codemode": false
      }
    }
  }
}
```

Use the endpoint you actually started; the example does not launch it. See the
[server startup](INSTALLATION.md#profiles-and-server-startup) and
[existing-data upgrade instructions](UPGRADING.md).

The adapter does not change SQLite schema or the upgrade procedure. Keep the
same profile and database paths during an ordinary Flower upgrade.

References: [OpenCode V2 MCP](https://opencode.ai/v2/docs/mcp-servers/),
[configuration](https://opencode.ai/v2/docs/config/) and
[project instructions](https://opencode.ai/v2/docs/instructions/).
