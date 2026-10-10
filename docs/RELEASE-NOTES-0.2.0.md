# Flower MCP 0.2.0

This release migrates optional internal semantic inference to runtime-llama
0.3.0.dev0 and an operator-managed llama.cpp endpoint. Core installation and
external-agent planning remain independent of inference. MCP tool names,
Python import/distribution names and the Apache-2.0 license remain unchanged.

## Compatibility and installation

Historical `backend: lmstudio` and `auto_load` configurations require explicit
migration. No automatic process/model loading or fallback is added. Follow
[INFERENCE.md](INFERENCE.md) to install the exact optional wheel and configure
the selected loaded model. Core installers continue to install only Flower.

The release contains eight assets, including the unchanged MIT-licensed runtime
wheel and SHA256 manifest. Runtime license/notices/provenance are retained in
the source archive. The core Flower wheel and core container exclude inference.
This release also includes the Dockerfile/Glama integration introduced after
v0.1.1; Glama ownership and hosted deployment remain separate platform actions.

## Behavior

Role adapters are reused and closed with the runtime. Per-call usage, separate
reasoning, JSON output and terminal reasons are preserved. Failed/noncompleted
semantic results remain unadoptable. Thinking diagnostics are bounded and opt-in;
structured tool calls are never executed by Flower.

## Qualification

Deterministic gateway, configuration, lifecycle and semantic-role tests passed.
Fresh core and optional package installs passed on macOS Python 3.11. Through
public MCP, the configured loaded model produced a complete validated JSON
result. A separate live `length_cap` result retained its usage/transport evidence
and was refused adoption. Reasoning/visible-token counters remained unknown
when the backend did not report them.

The release workflow requires Ubuntu Python 3.11–3.14, Windows PowerShell 5.1
and installed public MCP checks, plus the network-disabled Linux amd64 core
container and durable restart workflow. These checks do not certify native
coding-client trust/setup or other target workstations. Deterministic mechanics,
live consumer behavior and human acceptance remain distinct. No embedding pool
or new agent-client usability qualification is claimed.
