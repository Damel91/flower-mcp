# Now try Flower MCP

[Previous: Operate](06-operate.md) · [Index](README.md)

We followed Spazio Comune from requirements to change. The last step brings
that method into your project: **install Flower and connect your coding agent**.
Spazio Comune remains an educational scenario; the download is the Flower MCP
server, the public name of Flow of Work MCP.

## Public repository and downloads

- [GitHub repository](https://github.com/Damel91/flower-mcp): code, README and current documentation.
- [Published Flower MCP 0.4.1 release](https://github.com/Damel91/flower-mcp/releases/tag/v0.4.1): immutable historical packages and version notes.
- [Installation guide at the source checkpoint](https://github.com/Damel91/flower-mcp/blob/febfdff537cf68a004f2698bcab5ed0db22f3497/docs/INSTALLATION.md): full procedures, configuration and removal.
- [Operating-system prerequisites](https://github.com/Damel91/flower-mcp/blob/febfdff537cf68a004f2698bcab5ed0db22f3497/docs/INSTALLATION.md#prerequisites): what to prepare before downloading.

| File | Purpose |
| --- | --- |
| [install.sh](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh) | Guided installation on macOS and Linux. |
| [install.ps1](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.ps1) | Windows PowerShell launcher from the same release. |
| [install_flower.py](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install_flower.py) | Release Python installer; requires Python 3.11+. |
| [Python wheel](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/flow_of_work_mcp-0.4.1-py3-none-any.whl) | Manual installation of the Python package. |
| [Source archive](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/flow_of_work_mcp-0.4.1.tar.gz) | Packaged release source. |
| [SHA256SUMS](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/SHA256SUMS) | Checksums for release-file verification. |
| [BOOTSTRAP.md](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/BOOTSTRAP.md) | Public instructions for starting agent work with Flower. |
| [Historical optional runtime wheel](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/runtime_llama-0.4.0-py3-none-any.whl) | Runtime `0.4.0` retained in the immutable published release; core installation excludes it. |

The published `v0.4.1` release inventory has eight historical assets, including
`install.ps1` and the optional runtime-llama `0.4.0` wheel. Its Flower wheel's
extra still requires that older runtime. Verify these downloads against the
published `SHA256SUMS`.
The Windows launcher installs the `0.4.1` wheel.
The Python distribution remains `flow-of-work-mcp`; the command is `flower-mcp`.
Download links pin this historical release; the installation guide pins the
current documented source checkpoint. Run release commands only when their matching assets are
published. The current README follows repository updates instead.

## Current source and optional runtime

Current source retains Flower version `0.4.1` as an **unreleased candidate**.
Its builds contain seven Flower assets: wheel, source archive, three installers,
`BOOTSTRAP.md` and `SHA256SUMS`. They no longer copy a runtime wheel. This does
not replace or relabel the eight published Flower assets above.

The current source/candidate `inference` extra selects the independently
published [llama-runtime `0.4.1` release](https://github.com/Damel91/llama-runtime/releases/tag/v0.4.1)
and its [upstream wheel](https://github.com/Damel91/llama-runtime/releases/download/v0.4.1/runtime_llama-0.4.1-py3-none-any.whl).
Its SHA256 is
`8c512eb79b00ac3fdf761036fa0c8d74c24c3581651332736f6a95e6e38ae0aa`.
The upstream wheel includes Apache-2.0 `LICENSE`/`NOTICE` and vendored
llamatelemetry MIT attribution.

From that selected current source, use the dedicated Flower environment:

```sh
.venv/bin/python -m pip install '.[inference]'
.venv/bin/python -m pip check
```

For a verified current candidate wheel, use
`'./dist/flow_of_work_mcp-0.4.1-py3-none-any.whl[inference]'` instead.
Windows uses `& .\.venv\Scripts\python.exe` with the same pip arguments.
The dependency pins the upstream URL and SHA256. Do not use the published
Flower wheel's old extra for this new runtime. See the
[inference guide](https://github.com/Damel91/flower-mcp/blob/febfdff537cf68a004f2698bcab5ed0db22f3497/docs/INFERENCE.md)
for the complete source/wheel route, independent checksum verification and
offline wheelhouse acquisition. Keep the candidate's source commit and checksum
inventory: its filename and version match the historical Flower wheel.
Core installers remain core-only and configure no implicit provider.

## Before installing

| Route | Essential prerequisites |
| --- | --- |
| macOS / Linux, Bash installer | Bash, curl, awk, sha256sum or shasum, shell utilities, HTTPS access and Internet. Suitable Python is reused or prepared by the installer. |
| Windows, PowerShell launcher | Windows PowerShell 5.1+, HTTPS access and Internet. Suitable Python is reused or prepared by the launcher. |
| Manual installation or Python installer | Python 3.11+ with ssl, venv and ensurepip; dependency access. Git is needed only to clone source. |
| Agent connection | Codex, Claude Code, Cursor, Antigravity or Gemini CLI already installed; a writable user directory. |

**The core requires no LM Studio, internal model, CodingCastle or VPN.** Inference
normally remains with your chosen coding agent. Optional Flower internal inference
requires an explicitly installed runtime and configured endpoint; see the
[inference guide](https://github.com/Damel91/flower-mcp/blob/febfdff537cf68a004f2698bcab5ed0db22f3497/docs/INFERENCE.md).
The reader works offline, while a fresh installation downloads packages and dependencies.

## Already using Flower? Keep your ledger

Follow the [safe upgrade plan](https://github.com/Damel91/flower-mcp/blob/febfdff537cf68a004f2698bcab5ed0db22f3497/docs/UPGRADING.md)
using the original environment, profile and profile root. Stop all Flower processes
and coding clients sharing that environment. For an installer-owned installation,
preview the upgrade before changing packages:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh | bash -s -- --upgrade --dry-run
```

On Windows download the new `install.ps1` shown below, then preview without a
client-registration option:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.4.1' -Upgrade -DryRun
```

Add your original `--venv`, `--profile` and `--profile-root` options for custom
paths; Windows uses `-Venv`, `-Profile` and `-ProfileRoot`. Inspect the plan, then
repeat without `--dry-run` / `-DryRun`. The upgrade backs up the selected SQLite
ledger and exact YAML before pip, preserves client registration and applies
no new migration when upgrading 0.4.0 to 0.4.1: schema 55 stays unchanged.
An older 0.3.1/schema52 installation still uses the existing additive migrations
52 to 55 at the next server start. Keep the reported backup paths. The upgrade
never resets the ledger or automatically restores a backup; a failed pip operation
can partly change the environment. Manual pip installations use the
separate backup procedure in the same guide. After restart resume the known
project; do not create a replacement project to recover its state.

This core/profile upgrade does not request the inference extra or change model
settings. Upgrading the optional runtime is an explicit separate operation from
the selected current source/candidate; follow the inference guide before replacing
same-version Flower packages. Preserve the original endpoint and profile.

## Choose a route

### macOS and Linux

After checking prerequisites, the public command starts the guided installer
and lets you choose a client or installation only:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh | bash
```

The script prepares an isolated Python environment and verifies backend and
wheel checksums. You can download and inspect [the script](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh)
before running it. Options and manual procedures are in the complete guide.

### Windows

In a writable directory, download the public launcher and choose a client.
This example uses Codex:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.4.1' -Platform codex
```

Run the commands separately and stop if the download fails. You can inspect the
script before starting it. `-Platform claude-code`, `-Platform cursor`,
`-Platform antigravity` or `-Platform gemini-cli` selects another client;
`-NoRegister` installs without registering one. The execution
policy option applies only to that PowerShell process.

For manual installation, follow [the wheel and checksum procedure](https://github.com/Damel91/flower-mcp/blob/febfdff537cf68a004f2698bcab5ed0db22f3497/docs/INSTALLATION.md#manual-installation-from-a-release-wheel).

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
credentials or personal data. Flower `0.4.1` remains in testing. Installation
mechanics and the coding client's actual usability are separate checks.

[Back to Require](01-require.md) · [GitHub repository](https://github.com/Damel91/flower-mcp) · [Index](README.md)
