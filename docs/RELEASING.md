# Flower MCP releases

## 0.6.1 candidate delivery

The current candidate adds the read-only [lens catalog](LENS-CATALOG.md) with
37 tools, 445 fields and 182 routes and unchanged schema 55. Build with
`python tools/build_release.py --version 0.6.1 --output dist`; the reviewed
[0.6.1 notes](RELEASE-NOTES-0.6.1.md) are its release-note authority. Inspect final
bytes/core dependencies, repeat public MCP, qualify a populated owned official
0.6.0 → candidate upgrade with backup-before-pip and the separate 0.3.1 migration, then
require CI on the exact commit before publishing under the specific applicable
human authorization. Check anonymous release assets/HTTPS separately afterward;
Noxi's owner alone updates its preview. Previous 0.6.0 authority is not reused.
No Glama action or U6 work is part of this delivery. Preserve immutable old tags,
resources, license and optional runtime 0.5.0; retain all failed attempts/limits.

The following 0.6.0 paragraphs describe its completed historical release.

The public repository is [Damel91/flower-mcp](https://github.com/Damel91/flower-mcp).
It contains the source, essential documentation and release/install scripts.
Private development documents, configuration, runtime data and qualification
material stay outside this repository and its source distribution.

## Version policy

`pyproject.toml` is the version authority. Public versions use stable SemVer
`MAJOR.MINOR.PATCH`. Published **0.6.0** has an incompatible milestone input
correction and unchanged schema 55. Published tag `v0.6.0` identifies commit `bb43b5a161ecc85e56f1d2dba2c69184da0a02b7` ([release 416096822](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.0)). [Candidate CI](https://github.com/Damel91/flower-mcp/actions/runs/39072677376) and [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39073239681) are separate from anonymous asset checks and the populated-profile HTTPS upgrade.
Historical published `v0.5.2` is
`73cb74497e4ae65c509eb4ac8acf1026cbb0fd30`; `v0.5.1` is
`a87a52f87f16d48a609e304f85b53cc6b221fe66`.
Their seven assets, `v0.5.0` at `a46e0ec0efa335e655f3b5b8d7ecdc3843a0fa3c`,
and historical `v0.4.1`/eight assets remain immutable. A new
release requires a new version and explicit human publication approval; do not
republish a later `main` build under an existing tag. Version 0.5.1 is a patch
for tool-definition help and examples, with unchanged callable input contracts
and schema 55. Version 0.5.0 used a minor increment because `sync_only` added a
public argument; the 37 tool names remain unchanged.
Version 0.6.0 replaces `dependency_closure_ids` with
`prerequisite_requirement_ids`; 37 tool names and 445 inputs do not imply unchanged
callable schemas. Refresh host discovery and document the realized/prerequisite
meaning, historical gap handling and replay/effect recovery before updating users.
Tags use the `v` prefix,
for example `v0.4.1`. Version `0.x` means the public interface is still evolving;
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
   together. Label candidate instructions separately from available published
   downloads; do not present unpublished URLs as working installation commands.
   Update current download examples, release notes and
   [upgrade instructions](UPGRADING.md); retain historical release notes and tags.
   Document material compatibility changes.
2. Preserve the official Apache-2.0 LICENSE and attribution in NOTICE.
3. Prepare the complete source and selective guidance on an isolated candidate
   branch/worktree. Preserve the public bootstrap/CLI, attribution, installer
   safeguards and private-development boundary. Inspect the diff and qualify
   actual source, installed package and populated upgrade fixtures, then require
   CI on that exact candidate commit before moving public `main` for publication.
   CI builds on Python
   3.11–3.14, checks version/license metadata and the packaged LICENSE/NOTICE,
   and runs an installed-wheel smoke check outside the checkout. The installed
   `bootstrap` command must print its bundled instructions without creating a
   profile or configuration.

To qualify a `0.6.0` candidate locally, use Python 3.11 or newer in an
isolated environment and a fresh output directory. These commands do not
publish a release; use the declared version for the release being prepared:

```sh
python -m pip install build
python tools/build_release.py --version 0.6.0 --output dist
```

This creates wheel and source distributions, copies the Bash, PowerShell and Python installer scripts and
`BOOTSTRAP.md`, and writes `SHA256SUMS`: seven candidate assets in total. The
optional runtime is an independent public dependency and is not copied into
Flower assets or either package. Stale or unexpected files in the output directory fail the
build. To verify the resulting asset bytes again without rebuilding:

```sh
python tools/build_release.py --version 0.6.0 --output dist --verify-only
```

The source archive also includes the complete `docs/presentation` corpus: both
languages, generated HTML readers, navigation manifests, shared assets and the
reader build/test helpers. Release verification checks those packaged bytes
against the checkout. Extract the archive and open `docs/presentation/index.html`
to read it offline. These documentation assets are not runtime wheel dependencies.

Use the versioned `docs/RELEASE-NOTES-0.6.0.md` as the reviewed notes source;
`--notes /absolute/private/candidate-notes.md` preserves its prose, Markdown and
newlines while resolving relative guide links to the exact `v0.6.0` tag. The
generated body therefore has its own digest. The source archive must contain
the exact original guide bytes. Keep pending installed,
upgrade, CI and anonymous HTTPS checkpoints explicit until they have actually run.
Local checksum verification does not qualify a future published download.

## Publish explicitly

Publication of 0.6.0 followed human authorization, qualification and exact-commit
CI. Its tag and assets are immutable. That authorization does not approve future
versions, another user's installation or project deletion. An owner performs its
own update and verification against the official assets.

After those gates, in GitHub select **Actions → Release → Run workflow**, choose `main`, and enter
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
The builder verifies that both package metadata files confine the exact public
runtime-llama `0.5.0` URL/SHA256 to the inference extra. It rejects copied runtime
wheels, vendor payloads and runtime core-dependency leakage. Building Flower does
not fetch inference. The optional CI lane installs the candidate wheel's extra,
checks the upstream artifact provenance/attribution and runs gateway regressions;
core/uv/container lanes retain their independent no-inference boundary.
Flower's own Apache LICENSE/NOTICE remain in both packages. Upstream runtime
LICENSE/NOTICE and its vendored MIT attribution remain in that separately
installed distribution. Select the Flower wheel explicitly for core; see
[INFERENCE.md](INFERENCE.md) for the optional installation and offline routes.

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

Current release-download examples in README and INSTALLATION.md select published
0.6.0. A source build is a separate artifact. A published installer
uses a version-pinned URL:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.0/install.sh | bash
```

It prepares the local Python environment, prompts in the terminal for Codex,
Claude Code, Cursor, Antigravity or Gemini CLI, and configures the selected client. The downloaded Python
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

Existing installations follow [UPGRADING.md](UPGRADING.md) instead of creating
a new project. Verify the actual previous published wheel to the new wheel with
the same owned environment and populated profile: read-only plan, active-owner
refusal, consistent backup, YAML/client preservation and public MCP recovery
after restart. Keep source tests, native CI, actual downloaded asset checks and
client usability as separate evidence. Flower 0.6.0 adds no SQLite migration:
an existing supported schema-55 ledger, including published 0.5.2, stays at 55.
The same-schema upgrade fixture must start from actual immutable 0.5.2 assets,
not a source build relabelled with that version. The existing 0.3.1/schema 52 route
still applies additive migrations 52→55 on first server start. Optional
runtime-llama `0.4.0` belongs to the immutable published Flower `0.4.1` release;
published Flower 0.5.2 uses runtime `0.4.1`, while current source selects the
independently published runtime `0.5.0` through its explicit inference extra.
The 0.6.0 release does not replace 0.5.2 assets.
SDK-only adoption preserves the installed Flower artifact/receipt; rerunning its
old extra can select the old SDK again. Updating core/profile state does not request that
extra or migrate model settings. The CI upgrade fixture pins the published 0.3.1
wheel/backend; that path is distinct from 0.5.2→0.6.0 same-schema 55
candidate qualification and official HTTPS delivery. Historical anonymous
0.5.1→0.5.2 and 0.5.0→0.5.1 populated-schema 55 qualifications remain historical.
Retain the earlier
0.4.1→0.5.0 qualification as historical evidence.

Review [release notes](RELEASE-NOTES-0.6.0.md),
[native deletion limits](NATIVE-PROJECT-DELETION.md) and
[advanced configuration](ADVANCED-CONFIGURATION.md) with the exact release commit.
The suspended writer witness is excluded. Native deletion is a separate explicit
host control, never an upgrade or model operation; Windows native purge durability
is unqualified. Candidate builds, native CI, public workflows, whole-ledger
preservation and official delivery are separate checkpoints. No tag or Release
dispatch is part of preparation. The 0.6.0 authorization has been consumed by
that release; a future release needs a new applicable human decision.
