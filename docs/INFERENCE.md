# Optional internal inference

Flower core and host-executed semantic assignments run without a model or
inference dependency. Only explicit internal semantic execution uses this
integration. Returned tool calls remain data; Flower has no embedding or model
catalog consumer.

## Install the optional runtime

Select the Flower artifact and the optional SDK separately:

| Flower source/build | Its `inference` extra selects |
| --- | --- |
| Flower 0.7.5 and matching source | Independently published `runtime-llama` `0.5.0` |
| Historical published Flower 0.6.2 and matching source | Independently published `runtime-llama` `0.5.0` |
| Historical published Flower `0.6.1` wheel | Independently published `runtime-llama` `0.5.0` |
| Historical published Flower `0.6.0` wheel | Independently published `runtime-llama` `0.5.0` |
| Immutable published Flower `0.5.0`, `0.5.1` and `0.5.2` wheels | `runtime-llama` `0.4.1` |
| Historical published Flower `0.4.1` wheel | `runtime-llama` `0.4.0` |

The current source dependency is:

```text
runtime-llama @ https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/runtime_llama-0.5.0-py3-none-any.whl#sha256=dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13
```

- [Upstream release](https://github.com/Damel91/llama-runtime/releases/tag/v0.5.0).
- [Upstream wheel](https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/runtime_llama-0.5.0-py3-none-any.whl).
- SHA256: `dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13`.
- Python 3.11+ and `requests>=2.31,<3`; Apache-2.0 `LICENSE`/`NOTICE` and the
  retained llamatelemetry MIT attribution remain in the upstream wheel.

[Flower 0.6.2](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.2) is published at commit
`12ad69317dab92bdba06ae113ac22d107d259236` with the same optional pin. Its official
wheel SHA256 is `0e2a37013bcfcce0476edf1324e6a660bd5ac3c8ea783d62cf7cf8a3148df182`.
Historical [Flower 0.6.1](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.1) remains published
at commit `8de41beb1368ef772755b068b7404a91d3197f49` with this optional pin.
Its historical wheel SHA256 is
`7f510b27e63824d42c1644f4931dde404044229343ba0c1942043bca8d1ba982`.
[Flower 0.6.0](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.0) used the
same runtime 0.5.0 pin and remains a separate preserved release. Historical
[Flower 0.5.2 assets](https://github.com/Damel91/flower-mcp/releases/tag/v0.5.2) remain immutable.
Earlier source builds could carry version `0.5.2` with this newer optional pin;
those were distinct from the immutable released wheel. Retain the selected
artifact's exact commit, version and SHA256. Matching a version alone does not
make it the released wheel or an installer receipt's artifact.
Flower releases contain seven Flower assets and no runtime wheel; historical
Flower 0.4.1 retains its eight immutable assets and older runtime.

### Fresh source or candidate installation

Use a separate fresh/manual environment and the selected current source:

```sh
.venv/bin/python -m pip install '.[inference]'
.venv/bin/python -m pip check
```

Windows:

```powershell
& .\.venv\Scripts\python.exe -m pip install '.[inference]'
& .\.venv\Scripts\python.exe -m pip check
```

For a reviewed local 0.7.5 source/candidate wheel, replace `'.[inference]'` with
`'./dist/flow_of_work_mcp-0.7.5-py3-none-any.whl[inference]'` in a fresh/manual
environment. This remains a local-build example, separate from any official
release artifact. For a fresh/manual official installation, acquire the selected
release's wheel and `SHA256SUMS` through the
[release-wheel procedure](INSTALLATION.md#manual-installation-from-a-release-wheel),
then use that verified wheel path with `[inference]`. The older 0.6.2 wheel digest
recorded above is historical and does not identify a 0.7.5 artifact.
A rebuilt same-version wheel remains a different artifact. Historical **0.5.2** still selects
runtime `0.4.1`. Core installers remain core-only.
The extra fetches the exact upstream URL/hash and its normal dependency closure;
it requires no Flower-bundled runtime or upstream PyPI publication.

For an installer-owned environment, preserve the Flower wheel/build named in
its private `.flower-release-install.json`, including its recorded `sha256`.
Never replace it through pip with a rebuilt same-version Flower wheel, install
an editable checkout over it, or edit its receipt to hide a mismatch. Use the
[owned core upgrade](UPGRADING.md) when changing Flower itself. To change only an
already installed SDK, use the targeted procedure below. Core installers omit
inference; enabling YAML does not install the SDK.

### Verified download and offline installation

Acquire a complete compatible wheelhouse on a connected machine. Use the target
Python/OS/architecture, or select compatible target wheels explicitly. This
example downloads the selected local Flower wheel's core dependency closure and
explicitly selects the independent runtime 0.5.0:

```sh
python -m pip download --only-binary=:all: --dest wheelhouse './dist/flow_of_work_mcp-0.7.5-py3-none-any.whl' 'runtime-llama @ https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/runtime_llama-0.5.0-py3-none-any.whl#sha256=dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13'
sha256sum wheelhouse/runtime_llama-0.5.0-py3-none-any.whl
# macOS alternative:
shasum -a 256 wheelhouse/runtime_llama-0.5.0-py3-none-any.whl
```

Windows checksum:

```powershell
Get-FileHash .\wheelhouse\runtime_llama-0.5.0-py3-none-any.whl -Algorithm SHA256
```

The runtime digest must equal
`dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13`.
Verify the Flower wheel against its selected release/build's checksums. Retain
and verify a checksum inventory for the entire wheelhouse before and after
transfer. Do not mix several Flower or runtime versions in that directory.

For a fresh/manual offline environment, save this beside `wheelhouse` and run it
with that environment's Python:

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

Do not request the extra again offline: its direct HTTPS reference can require
network access. An installer-owned Flower wheel must still match its existing
receipt, not just its version. This is not an offline replacement for the owned
core upgrade, backup and lease workflow. Exported plans/readers do not contain
package dependencies.

### Upgrading the optional runtime

A [core/profile upgrade](UPGRADING.md) does not request inference or change the
model endpoint. For an **existing optional SDK installation**, runtime 0.5.0 can
be adopted independently while preserving the installed Flower package,
installation receipt, profile, SQLite ledger, YAML and client registration.
Do not add inference to a core-only environment merely to update Flower.

Stop every service/client sharing the selected interpreter before pip changes
its SDK files. Preserve a private backup of the previous SDK and package
inventory; retain the original Flower/profile paths. The existing SDK already
requires `requests>=2.31,<3`: verify its dependencies with `pip check` first.
Use the Python from the original registration, replacing `.venv/bin/python`
below when necessary. Preview this **SDK-only** change:

```sh
.venv/bin/python -m pip check
.venv/bin/python -m pip install --dry-run --no-deps --upgrade 'https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/runtime_llama-0.5.0-py3-none-any.whl#sha256=dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13'
```

Inspect the plan, then apply that exact SDK-only update:

```sh
.venv/bin/python -m pip install --no-deps --upgrade 'https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/runtime_llama-0.5.0-py3-none-any.whl#sha256=dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13'
.venv/bin/python -m pip check
.venv/bin/python -c 'from importlib.metadata import version; import runtime_llama; print(version("runtime-llama"), runtime_llama.__version__)'
```

Windows uses the same arguments with `& .\.venv\Scripts\python.exe`.
Both versions must report `0.5.0`; retain direct-URL/digest provenance and upstream
attribution. Keep the original Flower package and its receipt unchanged. This
operation does not back up or migrate SQLite and is not an atomic rollback
mechanism. If Flower core also needs an update, use its owned upgrade procedure
separately before changing the SDK.

Reinstalling an immutable older Flower wheel's `[inference]` extra can select its
older runtime again; it is not the SDK-only 0.5.0 update. Restart only each
owner's stopped services with their original profiles and verify public MCP
state. Gateway/package tests and connection-refusal recovery do not establish
successful model generation, model readiness or hosted deployment. Flower does
not expose the SDK's new model-discovery API.

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
