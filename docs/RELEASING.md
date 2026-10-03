# Flower MCP releases

The public repository is [Damel91/flower-mcp](https://github.com/Damel91/flower-mcp).
It contains the source, essential documentation and release/install scripts.
Private development documents, configuration, runtime data and qualification
material stay outside this repository and its source distribution.

## Version policy

`pyproject.toml` is the version authority. Public versions use stable SemVer
`MAJOR.MINOR.PATCH`; the current version is `0.1.1`. Tags use the `v` prefix,
for example `v0.1.1`. Version `0.x` means the public interface is still evolving;
document compatibility changes before incrementing the minor version. Use patch
increments for fixes that preserve the advertised interface. A future `1.0.0`
requires a deliberately declared stable public interface.

The public product and repository are Flower MCP / `flower-mcp`. The Python
distribution remains `flow-of-work-mcp`, the import package remains
`flow_of_work_mcp`, and both existing console commands are preserved.

## Prepare the release

1. Update `pyproject.toml`, the version in README/installation examples and the
   default release version in `tools/install.sh`, `tools/install.ps1` and
   `tools/install_flower.py`
   together. Document material compatibility changes.
2. Preserve the official Apache-2.0 LICENSE and attribution in NOTICE.
3. Commit the complete public source on `main` and push to the public repository.
   Inspect the diff and CI results before publishing. CI builds on Python
   3.11–3.14, checks version/license metadata and the packaged LICENSE/NOTICE,
   and runs an installed-wheel smoke check outside the checkout. The installed
   `bootstrap` command must print its bundled instructions without creating a
   profile or configuration.

To qualify the current `0.1.1` checkout locally, use Python 3.11 or newer in an
isolated environment and a fresh output directory. These commands do not
publish a release; use the declared version for the release being prepared:

```sh
python -m pip install build
python tools/build_release.py --version 0.1.1 --output dist
```

This creates wheel and source distributions, copies the Bash, PowerShell and Python installer scripts and
`BOOTSTRAP.md`, and writes `SHA256SUMS`. Stale or unexpected files in the output directory fail the
build. To verify the resulting asset bytes again without rebuilding:

```sh
python tools/build_release.py --version 0.1.1 --output dist --verify-only
```

The source archive also includes the complete `docs/presentation` corpus: both
languages, generated HTML readers, navigation manifests, shared assets and the
reader build/test helpers. Release verification checks those packaged bytes
against the checkout. Extract the archive and open `docs/presentation/index.html`
to read it offline. These documentation assets are not runtime wheel dependencies.

## Publish explicitly

In GitHub, select **Actions → Release → Run workflow**, choose `main`, and enter
the new version declared in `pyproject.toml` (without `v`). An existing tag
cannot be reused. Dispatching the workflow authorizes
publishing the selected commit. Ordinary pushes, pull requests and tags do not
publish a release. The workflow must already be on the default branch for
manual dispatch. See [GitHub's manual workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

The workflow checks the requested version against `pyproject.toml`, reruns CI,
downloads the artifacts from that run and verifies their checksums. Only the
final publishing job receives `contents: write`; repository Actions policy
must permit it. No personal access token or PyPI credential is needed.

The following inventory is for releases built from current source. The Windows
launcher is a release asset, not a separate download from mutable `main`.
After checks pass, the workflow creates
the requested new version tag at the full tested SHA and publishes:

- `flow_of_work_mcp-VERSION-py3-none-any.whl`
- `flow_of_work_mcp-VERSION.tar.gz`
- `install.sh`
- `install.ps1`
- `install_flower.py`
- `BOOTSTRAP.md`
- `SHA256SUMS`

`VERSION` is the requested version declared in `pyproject.toml`.

Release notes include version, license and installation commands. No packages
are published to PyPI. The install script downloads the explicit wheel asset;
GitHub's automatic tagged source archives are additional downloads.

The generated notes include a PowerShell command for the included `install.ps1`,
with the selected version explicit. The launcher downloads that version's
Python backend and wheel. Do not invoke it before those release assets exist;
building locally does not publish them.

The canonical agent bootstrap is
`src/flow_of_work_mcp/resources/agent-bootstrap.md`. Both packages include that
resource; `BOOTSTRAP.md` is an exact copy published alongside the installers.
The build checks its bytes in the wheel, source archive and release asset and
includes its checksum in `SHA256SUMS`. Edit the canonical resource when changing
the model instructions, then rebuild the release.

An existing tag is rejected. If publishing is interrupted, inspect workflow
logs, the remote tag and release assets before retrying. Use a new version for
corrected published bytes. GitHub CLI creates the missing tag at the explicitly
supplied target and uploads assets before publication; see [the release command](https://cli.github.com/manual/gh_release_create).

## Install the release

The primary installer uses a version-pinned URL:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.sh | bash
```

It prepares the local Python environment, prompts in the terminal for Codex,
Claude Code or Cursor, and configures the selected client. The downloaded Python
backend and wheel are checked against the release's `SHA256SUMS`.

Manual installation from the wheel or source distribution is documented in
[INSTALLATION.md](INSTALLATION.md), together with profiles, client configuration
and explicit upgrades. The Python backend also supports unattended installation
with an explicit `--platform` or `--no-register`. For Windows, the current source
PowerShell launcher prepares Python and invokes that same backend; see the
installation guide. It is included as `install.ps1` in the release.

After installation, run `flower-mcp bootstrap` and give its output to the coding
agent. The release's `BOOTSTRAP.md` provides the same instructions without
running the installed command. See [BOOTSTRAP.md](BOOTSTRAP.md) for the workflow.
