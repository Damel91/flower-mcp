# Optional internal inference

Flower core and host-executed semantic assignments run without a model or
inference dependency. Only an explicitly requested internal semantic execution
uses this integration. Flower generates bounded semantic output; it does not
execute returned tool calls or provide an embedding/retrieval consumer.

## Install the optional runtime

Release 0.2.0 replaces the historical LM Studio dependency with
`runtime-llama==0.3.0.dev0`, import `runtime_llama`. Upstream has not published a
PyPI package or Git remote. Flower redistributes the delivered wheel unchanged:

- File: `runtime_llama-0.3.0.dev0-py3-none-any.whl`
- SHA256: `6a24fc89318fc27f4bcf6e007d6e81e749a2ebef353a1c55ddcdf45a2c160b2e`
- Upstream revision: `9538540e4e9fc285068fa18bc011650642636e97`
- MIT license, notices and vendored attribution: [third_party/runtime-llama](../third_party/runtime-llama/).

Download both wheels and `SHA256SUMS` from the
[0.2.0 release](https://github.com/Damel91/flower-mcp/releases/tag/v0.2.0).
Compare each wheel's digest with its exact manifest entry before installing;
stop on mismatch. Use `sha256sum` on Linux, `shasum -a 256` on macOS or
`Get-FileHash -Algorithm SHA256` in PowerShell, as in the
[manual core instructions](INSTALLATION.md#manual-installation-from-a-release-wheel).
Install into the dedicated Flower environment, while its server is stopped.
The `.venv` paths below refer to the manual installation example. For an
automatic installation, use its returned environment/interpreter path instead:

```sh
.venv/bin/python -m pip install './flow_of_work_mcp-0.2.0-py3-none-any.whl[inference]' ./runtime_llama-0.3.0.dev0-py3-none-any.whl
.venv/bin/python -m pip check
```

Windows, using that same directory and environment:

```powershell
& .\.venv\Scripts\python.exe -m pip install './flow_of_work_mcp-0.2.0-py3-none-any.whl[inference]' ./runtime_llama-0.3.0.dev0-py3-none-any.whl
& .\.venv\Scripts\python.exe -m pip check
```

For a source checkout or extracted source archive, use
`python -m pip install '.[inference]' third_party/runtime-llama/runtime_llama-0.3.0.dev0-py3-none-any.whl`
with the chosen environment's interpreter. Passing the wheel explicitly selects
the inspected delivered artifact. Dependencies such as `requests` still
need their normal package source. Merely enabling YAML does not install the wheel.
Core installers intentionally omit this extra. Do not use a wildcard to install
all release wheels when you intend to install only core.

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

The upstream library also supports embedding discovery. Flower currently has no
application embedding consumer, so this release does not configure or qualify
replica pools, vector stores, retrieval quality or embedding identity.
