# Optional internal inference

Flower core and host-executed semantic assignments run without a model or
inference dependency. Only an explicitly requested internal semantic execution
uses this integration. Flower generates bounded semantic output; it does not
execute returned tool calls or provide an embedding/retrieval consumer.

## Install the optional runtime

Current Flower source is an **unreleased `0.5.0` candidate**. Its `inference`
extra selects the independently published `runtime-llama` `0.4.1` distribution,
imported as `runtime_llama`. Its exact dependency is:

```text
runtime-llama @ https://github.com/Damel91/llama-runtime/releases/download/v0.4.1/runtime_llama-0.4.1-py3-none-any.whl#sha256=8c512eb79b00ac3fdf761036fa0c8d74c24c3581651332736f6a95e6e38ae0aa
```

- [Upstream release](https://github.com/Damel91/llama-runtime/releases/tag/v0.4.1).
- [Upstream wheel](https://github.com/Damel91/llama-runtime/releases/download/v0.4.1/runtime_llama-0.4.1-py3-none-any.whl).
- SHA256: `8c512eb79b00ac3fdf761036fa0c8d74c24c3581651332736f6a95e6e38ae0aa`.
- The upstream wheel includes its Apache-2.0 `LICENSE`/`NOTICE` and the vendored
  llamatelemetry MIT attribution. Flower does not replace these with its own notices.

The immutable published [Flower `v0.4.1` release](https://github.com/Damel91/flower-mcp/releases/tag/v0.4.1)
still has eight historical assets, including runtime `0.4.0`; its Flower wheel's
extra still requires that older runtime. Its [release notes](RELEASE-NOTES-0.4.1.md)
describe those published bytes. Current candidate builds use Flower version `0.5.0`, contain seven assets and
carry no runtime wheel or vendored runtime payload. Retain the selected source
commit and candidate `SHA256SUMS`; preparing a candidate does not publish it.

### Install from current source or a candidate wheel

Use the dedicated Flower environment while all Flower processes and coding
clients sharing it are stopped. The `.venv` paths below refer to the
[manual source installation](INSTALLATION.md#manual-installation-from-source).
The source command below is for **fresh or manual environments only**. For an
installer-owned environment, first upgrade the core through its owned installer.
Then use the exact verified Flower wheel/build already recorded in that
installation's private `.flower-release-install.json`: compare the wheel's
SHA256 with the receipt's `sha256` field as well as its version and release
`SHA256SUMS`. Same version alone is insufficient. Do not install a source checkout
or a rebuilt same-version wheel into an owned environment, and do not edit its
receipt to make a mismatch disappear.

Do not pip-install a 0.5.0 candidate over an owned 0.4.1 environment: that skips
the installer's backup/lease/version receipt workflow. Before publication the
release installer cannot download 0.5.0 assets. Use a separate disposable manual
environment for candidate trials.

From the selected current source checkout or its extracted candidate source,
inside that fresh/manual environment:

```sh
.venv/bin/python -m pip install '.[inference]'
.venv/bin/python -m pip check
```

Alternatively, verify the selected Flower wheel against its own build's
`SHA256SUMS`. In an owned environment it must also be the exact wheel/build
already named by that environment's receipt, as described above:

```sh
.venv/bin/python -m pip install './dist/flow_of_work_mcp-0.5.0-py3-none-any.whl[inference]'
.venv/bin/python -m pip check
```

Windows uses the source command only in a fresh/manual environment:

```powershell
& .\.venv\Scripts\python.exe -m pip install '.[inference]'
& .\.venv\Scripts\python.exe -m pip check
```

For the Windows candidate-wheel alternative replace `'.[inference]'` with
`'./dist/flow_of_work_mcp-0.5.0-py3-none-any.whl[inference]'`.
These routes fetch the exact upstream URL and check its SHA256, then resolve
normal dependencies such as `requests`. They do not use a Flower-owned runtime
asset or require an upstream PyPI publication. Core installers intentionally
omit the extra and never configure a provider. Enabling YAML alone installs
nothing.

### Verified download and offline installation

On a connected machine, download the upstream wheel directly, or acquire the
complete dependency set from the selected candidate wheel into a new dedicated
directory. This example uses that machine's chosen Python interpreter:

```sh
python -m pip download --only-binary=:all: --dest wheelhouse './dist/flow_of_work_mcp-0.5.0-py3-none-any.whl[inference]'
```

Use a machine with the target Python version, operating system and architecture,
or select compatible target wheels explicitly. Verify the Flower candidate
against its build's `SHA256SUMS` and verify the upstream runtime independently:

```sh
sha256sum wheelhouse/runtime_llama-0.4.1-py3-none-any.whl
# macOS alternative:
shasum -a 256 wheelhouse/runtime_llama-0.4.1-py3-none-any.whl
```

Windows:

```powershell
Get-FileHash .\wheelhouse\runtime_llama-0.4.1-py3-none-any.whl -Algorithm SHA256
```

The runtime digest must equal
`8c512eb79b00ac3fdf761036fa0c8d74c24c3581651332736f6a95e6e38ae0aa`;
stop on mismatch. Retain a checksum inventory for the entire wheelhouse and
verify it after transfer. Copy only that reviewed candidate and its complete
dependency set to the offline machine; do not mix historical release wheels
or unrelated packages into the directory.

Save this as `install_offline.py` beside `wheelhouse` and run it with the offline
Flower environment's Python (`.venv/bin/python install_offline.py`, or
`& .\.venv\Scripts\python.exe .\install_offline.py` in PowerShell):

```python
from pathlib import Path
import subprocess
import sys

wheels = sorted(Path("wheelhouse").glob("*.whl"))
if not wheels:
    raise SystemExit("The reviewed wheelhouse is empty")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "--no-index", *map(str, wheels)],
    check=True,
)
subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
```

This installs the local Flower package, explicitly selected runtime and local
dependency closure together. It deliberately does not request the extra again:
the extra contains an HTTPS direct reference, which can require network access
even with a wheelhouse. The offline reader or an exported work plan alone does
not provide an offline package installation. Use this script for a fresh/manual
environment. For an installer-owned environment the Flower wheel must match
the exact existing receipt's version and `sha256`, not just its version number.
It is not an offline replacement for the owned core upgrade and its receipt.

### Upgrading the optional runtime

First follow [safe upgrades](UPGRADING.md) to preserve the same environment,
profile, exact YAML and SQLite ledger. A core/profile upgrade does not request
the inference extra, migrate model settings or change its endpoint; it is not
an optional-runtime upgrade. An already installed runtime can remain unchanged.

To move an existing installation to the new runtime, first complete the core
upgrade through the appropriate [owned or manual procedure](UPGRADING.md), then
select the exact verified installed Flower wheel/build recorded by the owned
receipt, or the reviewed wheel for a manual environment. Do not substitute a
source rebuild with the same version. The old published Flower wheel
still requires runtime `0.4.0`; installing runtime `0.4.1` beside that old
extra is not the supported new route. The commands below assume the core is
already at `0.5.0` and, for an owned environment, the selected wheel's SHA256
exactly matches its receipt. Preview the package change with
`--dry-run`, inspect it, then repeat without `--dry-run`:

```sh
.venv/bin/python -m pip install --dry-run --upgrade './dist/flow_of_work_mcp-0.5.0-py3-none-any.whl[inference]'
```

After approving that plan locally, apply it and check the resulting environment:

```sh
.venv/bin/python -m pip install --upgrade './dist/flow_of_work_mcp-0.5.0-py3-none-any.whl[inference]'
.venv/bin/python -m pip check
```

Windows uses the same arguments with `& .\.venv\Scripts\python.exe`.
Record the installed Flower source/build and runtime versions, retain upstream
attribution, then restart only the owned Flower instance with the original
profile. Package and mocked-gateway checks do not establish model readiness,
live inference or hosted deployment.

## Operator configuration and migration

Use a private explicit operator YAML or edit the owned profile's `flower.yaml`
while Flower is stopped. Retain its existing runtime, logging and provider
sections. The model block is:

```yaml
model:
  enabled: true
  backend: llamacpp
  model: your-exact-loaded-model-alias
  base_url: http://127.0.0.1:8080
  context_length: 32768
  idle_timeout_sec: 60
  verify_ssl: true
  temperature: 0.1
  reasoning: "off"
  api_key_env: FLOWER_MODEL_API_KEY
```

Use the exact case-sensitive alias observed in the endpoint's `/v1/models`
catalog and a context bound supported by that already loaded model. The example
32768 is not a claim about your model. `base_url` includes the port and omits a
trailing `/v1`. Credentials belong in the named environment variable; omit
`api_key_env` when no key is needed. TLS verification defaults to true. `reasoning: "off"` is explicit for this
bounded JSON role example. `auto` follows the model default; thinking can consume
the role's output budget and produce a truthful `length_cap` blocker.

Migrating an old profile requires replacing `backend: lmstudio`, selecting a
llama.cpp endpoint/model and removing `auto_load`. Old LM Studio fields are
rejected with migration guidance, including when inference is disabled. Flower
never starts models or processes. The operator owns the endpoint, model loading,
context allocation, GPU, slots and remote autoload policy. A healthy server and
a ready selected model are separate prerequisites.

Start normally with the owned profile, or an explicit YAML:

```sh
.venv/bin/flower-mcp serve --config /absolute/private/operator.yaml --transport stdio
```

The environment/interpreter path must match the client registration. Restart
only the Flower instance that owns this profile to load a changed configuration;
never reset its ledger or bindings as part of the migration.

See [advanced configuration](ADVANCED-CONFIGURATION.md) for supported semantic
roles, external provider routes, association receipts and the complete explicit
prepare/execute/validate/adopt workflow.

## Execution and evidence boundaries

Use `fow_semantic` inventory and prepare to inspect the bounded role contract.
`execute_internal` is explicit; host assignments remain available without this
backend. Internal output passes the same local role validator as host output;
it is not human acceptance. Noncompleted, invalid or stale results cannot be
adopted as successful semantic authority.

Flower preserves per-call usage when reported and leaves unknown counters
unknown. Reasoning remains separate from visible output. Timeout, cancellation,
runaway and backend failures retain their terminal reason in durable role
results. Cooperative cancellation exists at the gateway boundary; Flower does
not add a public cancellation operation or claim remote GPU work has stopped.
Bounded thinking diagnostics are opt-in per call and are not implicitly saved
in lifecycle evidence. Structured tool calls are data and are never executed.

Adapters are reused by semantic role and owned by the Flower runtime. Shutdown
drains workers, then adapters, then releases ledger ownership. Model availability
and execution failures do not authorize automatic fallback to another provider.

The upstream library also provides distributed embedding budgets and exact
embedding preparation APIs. The generation contract used here is unchanged.
The upstream library supports embedding discovery. Flower currently has no
application embedding consumer, so this release does not configure or qualify
replica pools, vector stores, retrieval quality or embedding identity.
