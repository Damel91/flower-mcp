# Now try Flower MCP

[Previous: Operate](06-operate.md) · [Index](README.md)

We followed Spazio Comune from requirements to change. The last step brings
that method into your project: **install Flower and connect your coding agent**.
Spazio Comune remains an educational scenario; the download is the Flower MCP
server, the public name of Flow of Work MCP.

## Public repository and downloads

- [GitHub repository](https://github.com/Damel91/flower-mcp): code, README and current documentation.
- [Flower MCP 0.6.1 release](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.1): seven published release assets.
- [Current installation guide](https://github.com/Damel91/flower-mcp/tree/main/docs/INSTALLATION.md): procedures, configuration and removal.
- [Operating-system prerequisites](https://github.com/Damel91/flower-mcp/tree/main/docs/INSTALLATION.md#prerequisites): what to prepare before downloading.

| File | Purpose |
| --- | --- |
| [install.sh](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.sh) | Guided installation on macOS and Linux. |
| [install.ps1](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.ps1) | Windows PowerShell launcher from the same release. |
| [install_flower.py](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install_flower.py) | Release Python installer; requires Python 3.11+. |
| [Python wheel](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/flow_of_work_mcp-0.6.1-py3-none-any.whl) | Manual installation of the Python package. |
| [Source archive](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/flow_of_work_mcp-0.6.1.tar.gz) | Packaged release source. |
| [SHA256SUMS](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/SHA256SUMS) | Checksums for release-file verification. |
| [BOOTSTRAP.md](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/BOOTSTRAP.md) | Public instructions for starting agent work with Flower. |

The published `v0.6.1` release contains seven Flower assets and no runtime wheel.
Verify downloads against its `SHA256SUMS`. The Windows launcher installs 0.6.1.
Historical [0.4.1](https://github.com/Damel91/flower-mcp/releases/tag/v0.4.1) retains eight historical assets,
including optional runtime-llama `0.4.0`; that old Flower extra remains unchanged.
The Python distribution is `flow-of-work-mcp`; the command is `flower-mcp`.
Current operational guide links follow mutable `main`. The
[historical installation guide](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/INSTALLATION.md) and
[historical prerequisites](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/INSTALLATION.md#prerequisites)
retain their frozen source checkpoint. The immutable 0.6.0 archive keeps its
preparation-era guides; later current documentation does not replace those bytes.

## Current source and optional runtime

Flower `0.6.1` contains seven Flower assets: wheel, source archive,
three installers, `BOOTSTRAP.md` and `SHA256SUMS`. It does not bundle a runtime
wheel or replace the historical 0.4.1 assets.

The current-source `inference` extra selects the independently
published [llama-runtime `0.5.0` release](https://github.com/Damel91/llama-runtime/releases/tag/v0.5.0)
and its [upstream wheel](https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/runtime_llama-0.5.0-py3-none-any.whl).
Its SHA256 is
`dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13`.
The upstream wheel includes Apache-2.0 `LICENSE`/`NOTICE` and vendored
llamatelemetry MIT attribution.

Published Flower `0.6.1` and its matching source select runtime `0.5.0`.
Historical Flower `0.6.0` selected the same optional runtime.
Historical Flower `0.5.2` still selects runtime `0.4.1`; its assets are immutable.
Use this source command only in a fresh/manual Flower environment:

```sh
.venv/bin/python -m pip install '.[inference]'
.venv/bin/python -m pip check
```

For a **local 0.6.1 source/candidate wheel**, use a fresh/manual environment.
This local-build example is separate from the verified published artifact:

```sh
.venv/bin/python -m pip install './dist/flow_of_work_mcp-0.6.1-py3-none-any.whl[inference]'
```

Flower 0.6.1 is published at commit
`8de41beb1368ef772755b068b7404a91d3197f49`. Verify its official wheel against
its own `SHA256SUMS`; the release and local build are separate artifacts.
The extra selects runtime `0.5.0`. A rebuilt same-version source wheel
is a separate artifact; earlier published assets remain immutable.

For the verified published `0.5.2` wheel, use
`'./dist/flow_of_work_mcp-0.5.2-py3-none-any.whl[inference]'` instead; it selects
runtime `0.4.1`, not the new current-source pin.
This command is for fresh/manual environments. An installer-owned environment
must use its exact already-owned wheel/build and receipt after its ordinary
core upgrade; a later source build with the same version is not that receipt's artifact.
Windows uses `& .\.venv\Scripts\python.exe` with the same pip arguments.
For runtime `0.5.0` in an existing optional installation, update only the SDK
through its verified URL/hash and preserve the installed Flower wheel/receipt.
Reinstalling its old extra can select the old SDK again. See the
[inference guide](https://github.com/Damel91/flower-mcp/tree/main/docs/INFERENCE.md)
for the current source/wheel route, exact owned-build rules, independent checksum
verification and offline acquisition. This operational link follows mutable
`main`; frozen source references remain historical. Keep the selected source
commit and checksum inventory. Verify the selected wheel against its own
release/build checksums; the historical `0.4.1` wheel remains immutable.
Core installers remain core-only and configure no implicit provider.

The [current advanced configuration guide](https://github.com/Damel91/flower-mcp/tree/main/docs/ADVANCED-CONFIGURATION.md)
explains LLM roles, YAML, external provider contracts and association receipts.
This link follows mutable `main`; the runtime source references elsewhere retain
their historical frozen checkpoint. Version 0.6.0 separates realized milestone
requirements from earlier prerequisites, certifies only correlated pre-write
milestone rejections, and adds explicit host-only native project purge.
It retains 0.5.2's recovery correction and earlier tool help. Refresh the host's
schema: `prerequisite_requirement_ids` replaces `dependency_closure_ids`; use `[]`
when none apply. Native deletion is never an MCP tool or upgrade step; see its
[limits](https://github.com/Damel91/flower-mcp/tree/main/docs/NATIVE-PROJECT-DELETION.md).
Windows native purge durability remains unqualified. The writer witness remains
deferred. The commands below install published 0.6.1;
installation mechanics and provider/client usability remain separate evidence.

Version 0.6.1 adds a complete read-only lens operation catalog so a host can
present relevant direct verbs while retaining ordinary execution gates. See the
[current catalog guide](https://github.com/Damel91/flower-mcp/tree/main/docs/LENS-CATALOG.md).
Seven anonymous assets and an owned macOS HTTPS 0.6.0 → 0.6.1 upgrade were verified
separately from source, installed-package and CI checks. No real user installation
was changed; this does not certify an unknown OS, model usability or acceptance.
Published tags and assets are preserved by policy, not GitHub-enforced immutability.

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
[inference guide](https://github.com/Damel91/flower-mcp/tree/main/docs/INFERENCE.md).
The reader works offline, while a fresh installation downloads packages and dependencies.

## Already using Flower? Keep your ledger

Follow the [current safe upgrade plan](https://github.com/Damel91/flower-mcp/tree/main/docs/UPGRADING.md)
(the [historical guide](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/UPGRADING.md) retains its source checkpoint)
using the original environment, profile and profile root. Stop all Flower processes
and coding clients sharing that environment. For an installer-owned installation,
preview the upgrade before changing packages:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.sh | bash -s -- --upgrade --dry-run
```

On Windows download the new `install.ps1` shown below, then preview without a
client-registration option:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.1' -Upgrade -DryRun
```

Add your original `--venv`, `--profile` and `--profile-root` options for custom
paths; Windows uses `-Venv`, `-Profile` and `-ProfileRoot`. Inspect the plan, then
repeat without `--dry-run` / `-DryRun`. The upgrade backs up the selected SQLite
ledger and exact YAML before pip, preserves client registration and applies
no new migration when upgrading a schema 55 profile to 0.6.1.
An older 0.3.1/schema 52 installation still uses the existing additive migrations
52 to 55 at the next server start. Keep the reported backup paths. The upgrade
never resets the ledger or automatically restores a backup; a failed pip operation
can partly change the environment. Manual pip installations use the
separate backup procedure in the same guide. After restart resume the known
project; do not create a replacement project to recover its state.

This core/profile upgrade does not request the inference extra or change model
settings. Upgrading the optional runtime is an explicit separate operation from
the selected current source/candidate; follow the inference guide before changing
Flower packages. An installer-owned core must first complete its normal owned
upgrade; then its extra must use the exact verified Flower wheel/build recorded
in its receipt, matching version and SHA256. Do not install a source rebuild or
a different build over it through pip alone. Use a separate manual environment
for source/candidate trials. Preserve the original endpoint and profile.

## Choose a route

### macOS and Linux

After checking prerequisites, the public command starts the guided installer
and lets you choose a client or installation only:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.sh | bash
```

The script prepares an isolated Python environment and verifies backend and
wheel checksums. You can download and inspect [the script](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.sh)
before running it. Options and manual procedures are in the complete guide.

### Windows

In a writable directory, download the public launcher and choose a client.
This example uses Codex:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.1' -Platform codex
```

Run the commands separately and stop if the download fails. You can inspect the
script before starting it. `-Platform claude-code`, `-Platform cursor`,
`-Platform antigravity` or `-Platform gemini-cli` selects another client;
`-NoRegister` installs without registering one. The execution
policy option applies only to that PowerShell process.

For manual installation, follow [the current wheel and checksum procedure](https://github.com/Damel91/flower-mcp/tree/main/docs/INSTALLATION.md#manual-installation-from-a-release-wheel).
The [historical procedure](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/INSTALLATION.md#manual-installation-from-a-release-wheel) remains a source reference.

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
credentials or personal data. Flower `0.6.1` remains in testing. Installation
mechanics and the coding client's actual usability are separate checks.

[Back to Require](01-require.md) · [GitHub repository](https://github.com/Damel91/flower-mcp) · [Index](README.md)
