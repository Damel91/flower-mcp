# Flower MCP 0.1.1

Installation and documentation update. The product remains in testing; this
patch does not change the public MCP interface or lifecycle behavior.

## Included in this release

- Windows PowerShell launcher `install.ps1`, published alongside the Bash and
  Python installers and included in `SHA256SUMS`.
- Installer defaults and public installation commands pinned to `0.1.1`.
- Bilingual, scenario-led presentation under `docs/presentation`, including
  offline HTML readers, the public tool map, optional cross-server features,
  author methodology and installation through the first project bootstrap.
- Only reviewed presentation crops are packaged. Original operator screenshots,
  private development documents and runtime data are excluded.

The Python distribution remains `flow-of-work-mcp`; the primary command is
`flower-mcp`. Core installation does not require CodingCastle, LM Studio or an
internal model. Python 3.11+ and Apache-2.0 licensing are unchanged.

## Install

macOS / Linux:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.sh | bash
```

Windows, in a writable directory:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Platform codex
```

Run the two Windows commands separately, inspect the script before execution,
and stop if download fails. Use `-Platform claude-code`, `-Platform cursor` or
`-NoRegister` as appropriate. Execution policy is changed only for that process.
See [installation](INSTALLATION.md) for prerequisites, checksum verification,
upgrades and client setup. Updating an existing installer-owned environment
requires explicit `--upgrade` / `-Upgrade`; the lifecycle ledger stays outside it.

Run the returned `bootstrap_command` and give its output to the coding agent,
preserving the selected project's existing instructions. A successful install
or doctor check does not prove that the client has connected through MCP.

## Qualification boundary

Release CI checks packages and installed-wheel public MCP behavior on Ubuntu
with Python 3.11-3.14. Windows CI checks PowerShell 5.1 helpers and the current
installed wheel's metadata, dependencies, bootstrap and public MCP lifecycle
outside the checkout, with no client registration. This is not an end-to-end
release-download installer test. Managed Python preparation on Windows and the target workstation/client
workflow still require their separate tests.

No packages are published to PyPI. Git publication dates describe this public
snapshot, not the beginning of the personal experiments described in the presentation.
