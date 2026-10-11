# Flower MCP 0.3.0

This update adds Antigravity and Gemini CLI to the existing client installation
workflow and pins optional runtime-llama to 0.4.0. Existing MCP tool names,
Python namespaces, lifecycle data and Apache-2.0 licensing remain unchanged.

## Installation

Use `--platform antigravity` or `--platform gemini-cli` with the Python/Bash
installer; PowerShell accepts the same names with `-Platform`. Existing Codex,
Claude Code and Cursor choices remain supported. Registration reuses dry-run,
backup, idempotent ownership, explicit replace and safe uninstall. See
[Google client setup](GOOGLE-CLIENTS.md) for current paths and connection steps.
No client trust policy or existing lifecycle database is migrated.

## Optional inference

The unchanged delivered runtime 0.4.0 wheel replaces the previous optional
artifact in this release. Its MIT attribution and exact provenance are included
in the source archive. Flower's generation bridge remains compatible; upstream
embedding improvements add no embedding consumer or retrieval dependency to
Flower. Core installation and host execution remain independent of inference.
See [inference setup](INFERENCE.md) for exact two-wheel installation.

## Qualification

The bounded consumer suite passed 120 deterministic tests with the exact 0.4.0
runtime, and client/profile regression suites passed 93 tests in each repository.
Release inventory checks passed 25 tests; installer forwarding checks passed two.
A fresh core installation has no runtime-llama dependency, while the optional
installation uses the delivered, checksum-verified 0.4.0 wheel.

Both generated Google registrations launched the installed Flower server through
public stdio MCP: 19 calls per client, including restart recovery, verified
multiline Markdown and structured results. These tests also covered idempotent
registration/removal and preservation of foreign configuration and project data.
The configured inference gateway completed public MCP preparation, generation,
validation and adoption on an isolated project; replay preserved the result.

Native CI separately gates release publication on Linux Python 3.11–3.14,
Windows and container qualification. Native Google client usability and human
acceptance remain separate: Antigravity and Gemini CLI are not installed in the
local qualification environment. No Google model access, trust policy or native
client approval behavior is certified by the generated-entry tests.
