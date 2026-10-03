# Now try Flower MCP

[Previous: Operate](06-operate.md) · [Index](README.md)

We followed Spazio Comune from requirements to change. The last step brings
that method into your project: **install Flower and connect your coding agent**.
Spazio Comune remains an educational scenario; the download is the Flower MCP
server, the public name of Flow of Work MCP.

## Public repository and downloads

- [GitHub repository](https://github.com/Damel91/flower-mcp): code, README and current documentation.
- [Flower MCP 0.1.0 release](https://github.com/Damel91/flower-mcp/releases/tag/v0.1.0): packages and version notes.
- [Installation guide for the documented revision](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/docs/INSTALLATION.md): full procedures, configuration and removal.
- [Operating-system prerequisites](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/docs/INSTALLATION.md#prerequisites): what to prepare before downloading.

| File | Purpose |
| --- | --- |
| [install.sh](https://github.com/Damel91/flower-mcp/releases/download/v0.1.0/install.sh) | Guided installation on macOS and Linux. |
| [install.ps1](https://raw.githubusercontent.com/Damel91/flower-mcp/main/tools/install.ps1) | Windows PowerShell launcher, distributed through the current repository. |
| [install_flower.py](https://github.com/Damel91/flower-mcp/releases/download/v0.1.0/install_flower.py) | Release Python installer; requires Python 3.11+. |
| [Python wheel](https://github.com/Damel91/flower-mcp/releases/download/v0.1.0/flow_of_work_mcp-0.1.0-py3-none-any.whl) | Manual installation of the Python package. |
| [Source archive](https://github.com/Damel91/flower-mcp/releases/download/v0.1.0/flow_of_work_mcp-0.1.0.tar.gz) | Packaged release source. |
| [SHA256SUMS](https://github.com/Damel91/flower-mcp/releases/download/v0.1.0/SHA256SUMS) | Checksums for release-file verification. |
| [BOOTSTRAP.md](https://github.com/Damel91/flower-mcp/releases/download/v0.1.0/BOOTSTRAP.md) | Public instructions for starting agent work with Flower. |

Release `v0.1.0` contains six assets; `install.ps1` is available from public
source, not that release. The Windows launcher installs the `0.1.0` wheel.
The Python distribution remains `flow-of-work-mcp`; the command is `flower-mcp`.
Downloads and anonymous access were checked on 3 October 2026. The guide is pinned
to this presentation's documented revision; the README and launcher on `main`
follow repository updates instead.

## Before installing

| Route | Essential prerequisites |
| --- | --- |
| macOS / Linux, Bash installer | Bash, curl, awk, sha256sum or shasum, shell utilities, HTTPS access and Internet. Suitable Python is reused or prepared by the installer. |
| Windows, PowerShell launcher | Windows PowerShell 5.1+, HTTPS access and Internet. Suitable Python is reused or prepared by the launcher. |
| Manual installation or Python installer | Python 3.11+ with ssl, venv and ensurepip; dependency access. Git is needed only to clone source. |
| Agent connection | Codex, Claude Code or Cursor already installed; a writable user directory. |

**The core requires no LM Studio, internal model, CodingCastle or VPN.** Inference
remains with your chosen coding agent. The reader works offline, while a fresh
installation downloads packages and dependencies.

## Choose a route

### macOS and Linux

After checking prerequisites, the public command starts the guided installer
and lets you choose a client or installation only:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.1.0/install.sh | bash
```

The script prepares an isolated Python environment and verifies backend and
wheel checksums. You can download and inspect [the script](https://github.com/Damel91/flower-mcp/releases/download/v0.1.0/install.sh)
before running it. Options and manual procedures are in the complete guide.

### Windows

In a writable directory, download the public launcher and choose a client.
This example uses Codex:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/Damel91/flower-mcp/main/tools/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Platform codex
```

Run the commands separately and stop if the download fails. You can inspect the
script before starting it. `-Platform claude-code` or `-Platform cursor` selects
another client; `-NoRegister` installs without registering one. The execution
policy option applies only to that PowerShell process.

For manual installation, follow [the wheel and checksum procedure](https://github.com/Damel91/flower-mcp/blob/ddc83c6c79638eda63edae5be1bd9789faa44a2e/docs/INSTALLATION.md#manual-installation-from-a-release-wheel).

## From installation to the first requirement

1. Keep the executable path and bootstrap command returned by the installer.
   After registration, reload the client and approve its MCP connection as
   requested. The client starts the registered server.
2. Ask the agent to run `flower-mcp bootstrap` using that path. The command prints
   instructions; the agent integrates them into the selected project, preserving
   existing rules. [The public bootstrap](../../BOOTSTRAP.md) explains this step.
3. The agent reads `fow_capabilities`, discovers and explicitly selects the project
   through `fow_interaction`; for a fresh ledger, it first creates the agreed
   project with `fow_create_project`.
4. Retrieve the snapshot through `fow_handover` and start with Require's question:
   **what behavior do we want, in which scenario and within which limits?**

Use a separate project for a first trial: revisit Spazio Comune, clarify a use
case and work toward an exportable plan. Successful installation and `doctor`
alone do not prove client connection: check that the agent can see the tools
and retrieve a snapshot.

If you encounter an issue, report it in the [repository issues](https://github.com/Damel91/flower-mcp/issues)
with your operating system, version, client, operation and error, without
credentials or personal data. Flower `0.1.0` is a first version under testing.

[Back to Require](01-require.md) · [GitHub repository](https://github.com/Damel91/flower-mcp) · [Index](README.md)
