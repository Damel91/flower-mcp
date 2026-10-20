# Flower MCP installation

For the published packet-start correction 0.6.4, use its checksum-verified official assets. Existing installations follow the [SQLite-preserving upgrade](UPGRADING.md#preparing-a-064-upgrade);
keep the same environment, profile root, ledger, YAML and client settings.
See the [release notes](RELEASE-NOTES-0.6.4.md) for receipt semantics and limits.

## Historical published 0.6.2

The [0.6.2 notes](RELEASE-NOTES-0.6.2.md) and
[readable lifecycle guide](readable-lifecycle-example.md) describe complete
Markdown lifecycle records, roadmaps and generated references. Canonical
authority, gates and the structured application envelope are retained; derived
Markdown values change in both response channels. Historical commands in this section
select published 0.6.2 assets; use `--version 0.6.2` / `-Version 0.6.2`
explicitly and retain the exact wheel's checksums and installation receipt.
Existing profiles follow the [0.6.2 upgrade](UPGRADING.md#preparing-a-062-upgrade):
same SQLite schema 55 and paths, consistent backup before pip, no project reset.

Flower MCP requires Python 3.11 or newer and is licensed under
[Apache-2.0](../LICENSE), with attribution in [NOTICE](../NOTICE).
The distribution is `flow-of-work-mcp`; the primary command is `flower-mcp`.
Core runs without a model, CodingCastle or a private network.

## Testing status and release access

Flower remains in testing. Release-download commands select tag `v0.6.2`, commit
`12ad69317dab92bdba06ae113ac22d107d259236`
([release 416738867](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.2)).
[Candidate CI](https://github.com/Damel91/flower-mcp/actions/runs/39168606257) passed six jobs;
the [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39169849356) passed all eight.
Seven anonymous assets and a separate populated macOS HTTPS 0.6.1 → 0.6.2
upgrade passed artifact and preservation checks. Source, installed package, CI,
official download, owned upgrade and an actual client's deployment are distinct
evidence. Noxi adoption remains its owner's separate checkpoint.

Release 0.6.2 has seven assets: the Flower wheel, source archive, three installers,
`BOOTSTRAP.md` and `SHA256SUMS`. Official wheel SHA256:
`0e2a37013bcfcce0476edf1324e6a660bd5ac3c8ea783d62cf7cf8a3148df182`.
Its optional extra selects independent
[llama-runtime 0.5.0](https://github.com/Damel91/llama-runtime/releases/tag/v0.5.0);
that SDK is not a Flower asset or embedded package payload. Historical 0.4.1
retains its eight assets and older optional runtime wheel.
Published tags and assets are preserved by maintainer policy; GitHub does not
enforce immutability for this release. Current source and guides do not replace
published bytes. Automatic installers require public GitHub asset access;
authenticating an initial script download does not authenticate later requests.

Prerequisites and manual/Windows/core procedures below remain explicit. Native
Windows CI checks PowerShell 5.1 helpers and installed core mechanics. Managed
Python preparation when Python is absent, unknown workstations, manual Windows
routes, real coding-client usability and human acceptance require their own
qualification. Windows native project deletion durability remains unqualified.

## Historical published 0.6.2 and selected source

The release-wheel procedures select official 0.6.2 bytes verified against that
release's `SHA256SUMS`. A source build with the same version is a different
artifact; never pip-replace an installer-owned artifact or rewrite its receipt.

For a fresh test environment, use the [source route](#manual-installation-from-source)
or the verified published wheel. From the directory containing that wheel
and its own `SHA256SUMS`, compare the exact wheel entry first:

```sh
sha256sum flow_of_work_mcp-0.6.2-py3-none-any.whl
# macOS alternative: shasum -a 256 flow_of_work_mcp-0.6.2-py3-none-any.whl
python3 -m venv .venv-flower-candidate
.venv-flower-candidate/bin/python -m pip install ./flow_of_work_mcp-0.6.2-py3-none-any.whl
.venv-flower-candidate/bin/python -m pip check
.venv-flower-candidate/bin/flower-mcp bootstrap
```

Windows PowerShell, after the same checksum comparison:

```powershell
Get-FileHash .\flow_of_work_mcp-0.6.2-py3-none-any.whl -Algorithm SHA256
py -3 -m venv .venv-flower-candidate
& .\.venv-flower-candidate\Scripts\python.exe -m pip install .\flow_of_work_mcp-0.6.2-py3-none-any.whl
& .\.venv-flower-candidate\Scripts\python.exe -m pip check
& .\.venv-flower-candidate\Scripts\flower-mcp.exe bootstrap
```

Run commands separately and stop on a mismatch or failure. This is core-only;
normal dependencies still need package access. Use a new test profile when
qualifying a fresh installation. An existing installation follows the
[SQLite-preserving upgrade procedure](UPGRADING.md#preparing-a-062-upgrade)
instead; do not recreate its environment/profile or pip-replace an installer-owned
package. The official asset checks do not certify an untested operating system
or client; Windows native purge durability remains unqualified.

## Published 0.6.1

The preserved [0.6.1 notes](RELEASE-NOTES-0.6.1.md) introduced the read-only lens
catalog. Its tag remains `8de41beb1368ef772755b068b7404a91d3197f49`
([release 416461595](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.1)).
[Candidate CI](https://github.com/Damel91/flower-mcp/actions/runs/39129035522)
passed six jobs, and its
[Release workflow, attempt 2](https://github.com/Damel91/flower-mcp/actions/runs/39130028443/attempts/2)
retains eight successful results. Its seven anonymous assets and populated
0.6.0 → 0.6.1 HTTPS upgrade are historical, separate checks.

## Published 0.6.1 and selected source

The historical [0.6.1 upgrade checkpoint](UPGRADING.md#preparing-a-061-upgrade)
and its assets remain available. The current operational examples after Prerequisites select published 0.6.4.

The historical 0.6.0 tag remains
`bb43b5a161ecc85e56f1d2dba2c69184da0a02b7`
([release 416096822](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.0)).
Its [candidate CI](https://github.com/Damel91/flower-mcp/actions/runs/39072677376),
[Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39073239681),
asset checks and 0.5.2-to-0.6.0 HTTPS upgrade are earlier, separate checkpoints.

After updating a host, refresh Flower's tool schema: milestone promotion now uses
`prerequisite_requirement_ids`, not `dependency_closure_ids`. Core plans and host
semantic work still need no model. The optional runtime-llama 0.5.0 installation
is a separate choice. Native project deletion is a distinct host control, never
an installation or upgrade step; see [its guide](NATIVE-PROJECT-DELETION.md).
Windows installation/stdio compatibility does not qualify native purge durability.

## Prerequisites

These prerequisites cover core installation. Choose your route before installing extra tools:

| Route | What you must have first |
| --- | --- |
| Bash release installer, macOS/Linux | Bash, curl, awk, sha256sum or shasum, standard shell utilities, HTTPS trust and Internet access. Suitable Python is reused; otherwise the script prepares managed Python 3.11. |
| Manual source clone | Git, Python 3.11+ with ssl, venv and ensurepip; authorized repository access while private. |
| Manual downloaded wheel or source archive | Python 3.11+ with ssl, venv and ensurepip; downloaded files and Internet access for dependencies. Git and curl are not required. |
| PowerShell release launcher, Windows | Windows PowerShell 5.1+, HTTPS trust and Internet access; suitable Python is reused or managed Python 3.11 is prepared. No Git or curl required. |
| Python release installer, including Windows | Python 3.11+ with ssl, venv and ensurepip; public release download access. Git and curl are not required. |
| Agent registration | The selected Codex, Claude Code, Cursor, Antigravity or Gemini CLI client must be installed to use the integration. Flower does not install it. |

Use a writable user directory for the environment, temporary downloads, Flower
profiles and client configuration. Flower itself does not require a system-wide
installation; operating-system package managers may request administrator
permission to install prerequisites. Installation needs HTTPS access to GitHub
release assets and package dependencies on PyPI. Managed Python setup also uses
Astral's uv installer and its runtime downloads. An offline exported work plan is
a different capability from an offline fresh package installation.

Run each command separately and stop if it fails. Do not continue after a failed
Python version check, package installation, checksum or registration preflight.

### macOS prerequisite setup

Check the downloader and shell:

```sh
curl --version
bash --version
command -v awk
command -v shasum
```

macOS includes curl, as described in the
[curl macOS guide](https://everything.curl.dev/install/macos.html).
If you want the Homebrew build and already have Homebrew, install it with:

```sh
brew install curl
"$(brew --prefix curl)/bin/curl" --version
```

Homebrew curl is separate from the system executable. Use that full path instead
of `curl` in the download command when choosing it. See
[Homebrew](https://brew.sh/) if the package manager is not installed; it is optional
for Flower. The Bash release installer can prepare Python, so a separate Python
installation is not needed for that route.

For manual installation, check:

```sh
python3 --version
python3 -c "import sys, ssl, venv, ensurepip; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
```

If Python is missing or too old, install a supported Python 3.11+ release using
[Python's macOS installer](https://www.python.org/downloads/macos/), then reopen
Terminal and repeat the check. For source cloning, check `git --version`; install
Git using the [Git macOS instructions](https://git-scm.com/install/mac) if absent.
Git is unnecessary for a downloaded release wheel.

### Linux prerequisite setup

The package commands depend on your distribution. On Ubuntu/Debian, obtain the
Bash installer prerequisites with:

```sh
sudo apt update
sudo apt install bash curl ca-certificates gawk coreutils
```

Check them:

```sh
bash --version
curl --version
command -v awk
command -v sha256sum
```

For curl on Fedora, the corresponding command is `sudo dnf install curl`.
See [curl's Linux installation guide](https://everything.curl.dev/install/linux.html)
for other package managers. The Bash installer also uses standard `uname`,
`mktemp`, `rm` and `sh`; minimal images must provide those utilities.

For manual installation on Ubuntu, install the full Python runtime and its
virtual-environment support:

```sh
sudo apt install python3-full
python3 --version
python3 -c "import sys, ssl, venv, ensurepip; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
```

The distribution's default Python must meet Flower's minimum version. If it is
older, obtain a supported interpreter using your distribution's documented
procedure, or use the Bash installer to prepare managed Python. Keep the system
Python intact. See [Ubuntu's Python setup guide](https://ubuntu.com/developers/docs/howto/python-setup/).
For source cloning on Ubuntu/Debian, install Git with `sudo apt install git` and
check `git --version`; other distributions use their own package manager.
A downloaded wheel does not require Git.

### Windows prerequisite setup

For the automatic launcher, check Windows PowerShell 5.1 or newer:

```powershell
$PSVersionTable.PSVersion
```

The launcher prepares Python when needed. The following Python setup is required
only for the manual routes or direct Python backend. The examples use PowerShell.
The Python installer can also run from another
terminal; PowerShell is not a dependency of Flower's Python runtime. Check:

```powershell
py -3 --version
py -3 -c "import sys, ssl, venv, ensurepip; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
```

If Python is missing or too old, get the Python Install Manager from
[python.org](https://www.python.org/downloads/) or the Microsoft Store, following
[Python's Windows installation guide](https://docs.python.org/3/using/windows.html).
After installing the manager, reopen PowerShell and install a supported runtime,
for example:

```powershell
pymanager install 3.11
py -3.11 --version
```

Use the selected interpreter consistently: the examples below use `py -3` when
its selected runtime is 3.11 or newer. Substitute `py -3.11` or another installed
supported version when needed. If an existing Python installation exposes only
`python`, use that command after checking its version and modules. Do not use the
minimal embeddable Python distribution for venv-based installation.

For source cloning, install [Git for Windows](https://git-scm.com/install/windows),
reopen PowerShell and check `git --version`. Downloaded wheels and the Python
release installer require neither Git nor curl. The examples call the venv's
executables directly, so no activation or execution-policy change is necessary.

Default persistent profiles require `LOCALAPPDATA`. If that variable is absent,
select a writable absolute `--profile-root` explicitly. The target Windows
workstation and client still require their own test, beyond the recorded CI scope.

## Automatic installation with curl

On macOS or Linux, after prerequisite setup, with release assets publicly accessible:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.4/install.sh | bash
```

Choose Codex, Claude Code, Cursor, Antigravity, Gemini CLI, or installation without agent registration.
The installer creates a dedicated virtual environment, obtains Python 3.11 if
no suitable interpreter is available, downloads the release wheel, checks its
SHA-256 checksum and installs the declared dependencies. It then invokes
Flower's agent registration and doctor commands. Reload the selected client
and follow its connection/trust prompt.

The published `v0.6.4` assets contain the Python installer, model `BOOTSTRAP.md`
and `SHA256SUMS`. Anonymous download access is unavailable while the repository
is private. Downloads and dependency installation need Internet access.

For unattended use, select the destination explicitly:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.4/install.sh | bash -s -- --platform codex
```

Use `--platform claude-code`, `--platform cursor`, `--platform antigravity`,
`--platform gemini-cli` or `--no-register` as needed.
`--client-config`, `--profile`, `--profile-root` and `--venv` select custom paths.
An existing environment requires explicit `--upgrade`. The installer prints
the absolute command path; agent configuration uses the installed interpreter
directly and needs no shell activation.

## Automatic installation on Windows with PowerShell

The launcher source is [tools/install.ps1](../tools/install.ps1). From an existing
checkout, invoke it in a dedicated process; no activation or global execution
policy change is needed:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\install.ps1 -Version 0.6.4 -Platform codex
```

The launcher is available as a version-pinned release asset. Download it, then run it in
an isolated PowerShell process with an explicit client or `-NoRegister`:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.6.4/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Platform codex
```

The process-only execution-policy option does not change the user or machine
policy. Where organizational policy prevents script execution, use the manual
wheel route. This launcher does not require curl, Git or preinstalled Python.
It reuses a suitable Python 3.11+ or prepares managed Python 3.11 through pinned
uv. Temporary uv/bootstrap files are removed; managed Python remains under
`%LOCALAPPDATA%\Flower MCP Install\python` because the installed venv needs it.
Persistent PATH and Python registry registrations are not changed.

The launcher verifies the downloaded `install_flower.py` SHA256 against the
selected release manifest; that backend verifies and installs the wheel and
owns registration/diagnosis. Download/checksum/native command failures stop
installation. The existing backend controls environment retention on failures.
The default venv is `%LOCALAPPDATA%\Flower MCP Install\venv`.

Options are PowerShell named parameters:

- Fresh installation requires exactly one of `-Platform codex|claude-code|cursor|antigravity|gemini-cli` or `-NoRegister`.
- Upgrade implies no registration; omit `-Platform` and `-ClientConfig`.
- The published 0.6.4 launcher defaults to that version.
  Use `-Version 0.6.4` explicitly when selecting the current release.
- `-Venv 'C:\Users\tester\Flower test\venv'` selects an installation location.
- `-Upgrade` explicitly upgrades an environment already owned by the backend.
- `-DryRun` previews an upgrade without package or lifecycle data changes;
  `-BackupRoot` chooses its private backup directory. Both require `-Upgrade`.
- `-Profile default` and `-ProfileRoot 'C:\Users\tester\Flower data'` select lifecycle storage.
- `-ClientConfig 'C:\Users\tester\Agent config\config.json'` requires `-Platform`.

For installation without client registration:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version 0.6.4 -NoRegister
```

The user/client controls connection and trust. Neither installation nor doctor
certifies the target workstation or client experience. Report the Windows
version, Python version, client and actual outcome when testing.

For a first workstation test, retain the installer output and exit code, then
reload the client, approve its MCP connection and confirm that Flower's public
tools are available. Ask the agent to run the installed `flower-mcp bootstrap`,
select or create a test project, and retrieve its handover snapshot. Record
whether each boundary succeeded; installation success alone does not qualify
the client workflow. Use the absolute executable path printed by the installer
if `flower-mcp` is not on PATH.

The Windows script, Python backend and wheel above all refer to the same
`v0.6.4` release. Source checkout installation is a separate route.

## Python release installer on Windows

The existing `install_flower.py` backend includes Windows path handling but
requires a preinstalled Python 3.11+ and publicly accessible release assets.
It does not install Python on Windows or authenticate GitHub downloads.
With release assets publicly accessible, download it in PowerShell:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.6.4/install_flower.py" -OutFile ".\install_flower.py"
py -3 .\install_flower.py --version 0.6.4 --platform codex
```

Use `--platform claude-code`, `--platform cursor`, `--platform antigravity`,
`--platform gemini-cli` or `--no-register` as needed.
The default environment is `%LOCALAPPDATA%\Flower MCP Install\venv`; the installer
checks the release wheel checksum, installs dependencies, and runs registration
and diagnosis when selected. `--venv`, `--profile-root` and `--client-config`
select custom paths; `--upgrade` is required for an environment already owned
by this installer. The returned `command` and `bootstrap_command` give exact
executable paths. In PowerShell, invoke a quoted path using `&`.

During private testing, even an authenticated script download cannot grant the
backend access to its remaining assets. Use the manual wheel route below.
For managed Python preparation, use the PowerShell release launcher above.

## Manual installation from source

Have Git and Python 3.11+ available, then clone with authorized access if private.
These examples install the checked-out source revision. To use the exact
published `v0.6.4` bytes, select the release wheel route instead.
No checkout configuration file needs to be copied.
Record the selected commit with `git rev-parse HEAD` and retain build provenance.
Source on `main` may differ from the immutable release; the published wheel
route below installs exact 0.6.4 bytes verified against its `SHA256SUMS`.

**macOS/Linux:**

```sh
git clone https://github.com/Damel91/flower-mcp.git
cd flower-mcp
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m pip check
```

**Windows, in PowerShell:**

```powershell
git clone https://github.com/Damel91/flower-mcp.git
cd flower-mcp
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install .
& .\.venv\Scripts\python.exe -m pip check
```

Keep the environment path stable after client registration. Run each step
separately and stop on errors. Use the venv command paths in the following sections;
activation is optional and unnecessary for these examples.

These commands install core only. For the current source/release optional
runtime, use the explicit [inference-extra route](INFERENCE.md#fresh-source-or-candidate-installation).
The historical 0.4.1 wheel's older extra constraint does not select the new
upstream runtime.

## Manual installation from a release wheel

Download `flow_of_work_mcp-0.6.4-py3-none-any.whl` and `SHA256SUMS` from the
[GitHub Release](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.4), using
an authorized browser or GitHub CLI while it is private. Put both files in the
same writable directory, then open a terminal there. Have Python 3.11+ ready;
Git and curl are not needed.

**macOS/Linux:** check the digest first:

```sh
# Linux
sha256sum flow_of_work_mcp-0.6.4-py3-none-any.whl
# macOS
shasum -a 256 flow_of_work_mcp-0.6.4-py3-none-any.whl
```

Compare the hash with the wheel's exact entry in `SHA256SUMS`. Stop if it differs.
Then install:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./flow_of_work_mcp-0.6.4-py3-none-any.whl
.venv/bin/python -m pip check
```

**Windows, in PowerShell:** check the digest first:

```powershell
Get-FileHash .\flow_of_work_mcp-0.6.4-py3-none-any.whl -Algorithm SHA256
Get-Content .\SHA256SUMS
```

Compare `Hash` with the exact wheel entry, ignoring letter case. Stop if it differs.
Then install:

```powershell
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install .\flow_of_work_mcp-0.6.4-py3-none-any.whl
& .\.venv\Scripts\python.exe -m pip check
```

The package is not assumed to be available on PyPI; pip obtains its declared
dependencies there. The release source archive is an alternative input for pip.
Startup uses bundled Markdown grammars and needs no parser downloads.

## Register a coding agent

Use the command in your installation environment for the chosen client.
For the manual `.venv` used above:

**macOS/Linux:**

```sh
.venv/bin/flower-mcp install --platform codex --dry-run
.venv/bin/flower-mcp install --platform codex
.venv/bin/flower-mcp doctor --platform codex
```

**Windows, in PowerShell:**

```powershell
& .\.venv\Scripts\flower-mcp.exe install --platform codex --dry-run
& .\.venv\Scripts\flower-mcp.exe install --platform codex
& .\.venv\Scripts\flower-mcp.exe doctor --platform codex
```

For a release installer environment, use its returned absolute `command` path
instead. Run preflight first and stop on a conflict before actual registration.
Supported platform names are `codex`, `claude-code`, `cursor`, `antigravity` and `gemini-cli`. Defaults target
the user's Codex TOML, Claude Code user JSON, Cursor user JSON or the selected
Google client's user JSON. See [Google clients](GOOGLE-CLIENTS.md) for the exact
Antigravity/Gemini paths, environment override and connection steps. Use
`--client-config /absolute/path` for another supported config file.
Claude Code's nested local-scope config is unsupported. JSON must be strict JSON.

The generated stdio entry uses absolute interpreter and profile paths. Reload
the client after registration. `doctor` inspects files; connection and trust
remain controlled by the selected client.

`--dry-run` creates no profiles or registration files. Repeated owned
registration is a no-op. A foreign or edited entry is a conflict;
`install --replace` explicitly replaces it and preserves a private backup.
Unrelated client settings remain in place.

## Bootstrap the project's AGENTS.md

After the agent has connected to Flower, ask it to run `flower-mcp bootstrap`
using the installed executable path and follow the output to update the intended
project's `AGENTS.md`. The model preserves existing rules, merges one bounded
Flower section, discovers lifecycle projects and selects the intended project
explicitly. The command itself only prints bundled instructions.

See [agent bootstrap](BOOTSTRAP.md) for a ready-to-use model request.
Both release installers return `bootstrap_command` and the next setup step.
For a manual install, the corresponding print-only commands are:

```sh
.venv/bin/flower-mcp bootstrap
```

```powershell
& .\.venv\Scripts\flower-mcp.exe bootstrap
```

Installation without registration still requires connecting the selected agent.
The command prints instructions; it does not edit AGENTS.md itself.

## Profiles and server startup

First registration or profile-based startup creates a persistent core profile.
`--profile NAME` defaults to `default`. `--profile-root /absolute/path` or
`FLOWER_HOME` selects its storage root; otherwise Flower uses the platform's
user data directory:

- macOS: `~/Library/Application Support/Flower MCP`
- Linux: `$XDG_DATA_HOME/flower-mcp`, or `~/.local/share/flower-mcp`
- Windows: `%LOCALAPPDATA%\Flower MCP`

Profiles live in `profiles/NAME/flower.yaml` with ledger, logs and an imports
folder. They stay outside the installed package and survive upgrades and
registration removal. Defaults disable models and providers and contain no
lifecycle projects. `install --import-root /absolute/path` selects the initial
document import root. Existing profile YAML is validated and preserved.

For the manual macOS/Linux environment (use the installer's returned absolute
command for an automatic installation):

```sh
.venv/bin/flower-mcp serve
.venv/bin/flower-mcp serve --profile example --profile-root /absolute/private/state
.venv/bin/flower-mcp serve --config /absolute/path/to/operator.yaml --transport stdio
```

For direct stdio startup with the manual Windows environment:

```powershell
& .\.venv\Scripts\flower-mcp.exe serve --transport stdio
```

A registered client starts the server itself; do not also start a separate process
on that profile. PowerShell's `&` also invokes the absolute command printed by an
installer when its path is quoted and includes spaces.

`--config` uses an explicit operator YAML and cannot be combined with profile
selection. Paths in that YAML resolve relative to the YAML itself.
One process owns each ledger. Use separate profiles for independent agent
sessions, or one HTTP server for deliberately shared access:

```sh
.venv/bin/flower-mcp serve --profile example --profile-root /absolute/private/state \
  --transport streamable-http --host 127.0.0.1 --port 8015
```

HTTP client configuration is manual; agent registration configures stdio.
Do not delete lock files to bypass an active owner.

## Upgrades and removal

Use the [complete safe upgrade plan](UPGRADING.md) before updating an existing
installation. The commands below select published 0.6.4.
Stop **all Flower processes and coding clients sharing the
installation environment**; the installer does not stop services. Keep the same
environment, profile name and profile root. For an installer-owned environment:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.4/install.sh | bash -s -- --upgrade --dry-run
```

Inspect the plan, then repeat without `--dry-run`. For custom paths, include
the original `--venv`, `--profile` and `--profile-root` options in both commands.
Upgrade defaults to no registration; `--platform` and `--client-config` are
rejected. The backend requires an existing owned environment and valid existing
profile, acquires the selected ledger's ownership lease and creates a consistent
SQLite backup plus the exact profile YAML before changing packages. An active
owner blocks the update. `--backup-root` selects a safe private backup location.
The launchers may download their backend or prepare managed Python even when
previewing. For a strictly read-only local plan, use existing Python with a
local, checksum-verified `install_flower.py --upgrade --dry-run` as shown in the
upgrade guide.

On Windows, download and inspect the current `install.ps1`, then preview:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.4' -Upgrade -DryRun
```

Repeat without `-DryRun` to execute; preserve custom `-Venv`, `-Profile` and
`-ProfileRoot` options. Use `-BackupRoot` for an explicit backup root.

Manual pip environments use the [manual backup and wheel upgrade
procedure](UPGRADING.md#manual-pip-installations); they are not silently adopted
by the release installer. Upgrading an existing schema 55 profile to 0.6.4
adds no migration. An older 0.3.1/schema 52 ledger uses the existing
additive migrations to schema 55 on first server start. Diagnosis alone does not
start Flower or verify migration.
Keep the backup and verify the same project after startup and another restart.
An optional-runtime upgrade is a separate explicit package change; a core/profile
upgrade does not request the inference extra or change endpoint settings.
Follow the [runtime upgrade procedure](INFERENCE.md#upgrading-the-optional-runtime)
when moving to the current source/release dependency.
Failures retain original lifecycle data and completed backups, but pip may have
partly changed the environment. There is no automatic restore or atomic package
rollback. Restart with the same profile, verify a known project through MCP and
resume its current state before new work.

Keep the interpreter path stable. If it changes, explicitly replace the owned
client entry. Registration removal preserves profiles and ledgers. For the manual
macOS/Linux environment (or use the installer's returned absolute command):

```sh
.venv/bin/flower-mcp uninstall --platform codex --dry-run
.venv/bin/flower-mcp uninstall --platform codex
```

For the manual Windows environment:

```powershell
& .\.venv\Scripts\flower-mcp.exe uninstall --platform codex --dry-run
& .\.venv\Scripts\flower-mcp.exe uninstall --platform codex
```

Removal requires an owned entry matching current bytes. Edited entries are
refused; unrelated settings remain in place. Reinstall reuses the profile.

## First use and recovery

A fresh ledger contains no projects. Create the intended project with
`fow_create_project(project_id, name, actor)`, then select it through
`fow_interaction` with a fresh `interaction_session_ref`,
`operation="select_project"` and explicit `project_id`.
For existing ledgers, discover and select the intended project.
Use `fow_capabilities` for operations and recipes, and `fow_handover` with
`operation="project_state_snapshot"` for durable state and the next gate.

Stop Flower before making a file backup. Preserve the SQLite database and any
`-wal`/`-shm` companions together. Keep backups and logs private. Restore into
a new runtime directory and point a copied config there; never reset a ledger
as an installation step. Recover through project selection and the durable
snapshot instead of replaying an uncertain mutation.

## Optional integrations

Core installers do not install inference or configure a provider. Current
source/release internal semantic execution uses the optional public
`runtime-llama` `0.5.0` wheel through an exact upstream URL/SHA256 dependency and
an operator-managed llama.cpp endpoint. Historical Flower 0.5.2 still selects
runtime 0.4.1; its release remains immutable. Retain the selected artifact's exact
commit, version and checksum; matching a version alone is not package identity.
Use a fresh/manual environment for current-source extra installation,
or the targeted SDK-only procedure to preserve an installed Flower artifact and
receipt. Core-only environments need no SDK. The runtime
remains independently distributed; Flower does not copy it into release
assets or source archives.

See [INFERENCE.md](INFERENCE.md) for checksum verification, Linux/macOS and
Windows installation, endpoint configuration and migration from the historical
LM Studio backend. Host-produced semantic results need no inference extra.

Operator YAML controls optional provider transport routes. Project associations
are managed with `fow_bindings`; receipts cannot inject transport URLs,
credentials or commands. Inference configuration does not migrate lifecycle
projects or accepted authority.

See [advanced configuration](ADVANCED-CONFIGURATION.md) for supported model roles,
operator route setup, project association receipts and explicit semantic execution.
It does not require a provider for standalone plans or qualify a running pairing.
