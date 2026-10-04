# Flower MCP

<p align="center">
  <img src="assets/flower-mcp-logo.png" alt="Flower MCP: Require, Plan, Build, Verify, Deploy, Operate" width="380">
</p>

**Persistent software lifecycle management for coding agents.**

Flower connects requirements, milestones and implementation plans to evidence,
verification, acceptance and handover. It stores project state in a SQLite ledger
and exposes it through the Model Context Protocol (MCP), while your coding agent
investigates repositories, writes code and runs checks.

Version: `0.1.1` · **In testing** · Python: `3.11+` · [Apache-2.0](LICENSE)

[Quick start](#quick-start) · [English walkthrough](docs/presentation/eng/README.md) · [Presentazione italiana](docs/presentation/ita/README.md) · [Development method](docs/presentation/eng/method.md)

## Why Flower exists

An agent can finish a patch while the requested behavior remains unverified.
A later session needs to know which decisions still apply, which results are
current and what remains open before delivery.

Flower checks declared plan dependencies and verification obligations, applies
lifecycle gates, and preserves result provenance and revisions. A handover
recovers current work and the next gate. Exported Markdown plans support
authorized offline work and reconciliation when Flower returns.

**The model is not the system of record.** Persistence supports the lifecycle;
the purpose is to keep agreed intent, delegated work and evidence connected.

You can start with a scenario: what should the software do and show? Using
Flower's bootstrap guidance, the agent investigates technical gaps and asks
progressive questions about your intent. It records requirements and decisions
in Flower and proposes a roadmap for your confirmation before implementation.
You do not need to define the architecture up front.

## Who does what?

| Participant | Responsibility |
| --- | --- |
| **Person / project authority** | Clarifies intent, confirms scope and makes the acceptance and delivery decisions assigned to them. |
| **Coding agent and its host** | Investigates the repository, chooses the technical implementation, edits code, runs checks and reports outcomes. |
| **Flower MCP** | Maintains lifecycle records, applies its operation gates, tracks evidence provenance and returns durable state. |

The core works without CodingCastle, LM Studio or an internal model. Optional
providers can connect lifecycle records to technical evidence and execution;
see [integration boundaries](docs/presentation/eng/advanced.md).

### Implemented ≠ verified ≠ accepted

| State | What it means |
| --- | --- |
| **Implemented** | The material work is declared produced. |
| **Verified** | The required checks have passed for the declared scope and relevant current revision, with supporting evidence. |
| **Accepted** | The competent authority has made the required decision. |

Local checks, deferred campaigns and acceptance stay distinct. Results from an
older revision do not automatically satisfy current work.
[Plans, evidence and gates](docs/presentation/eng/concepts.md).

## Example: two people book the same room

*Illustrative scenario from the presentation, not an executed demo or benchmark.*

The requirement: two concurrent requests for the same room and time slot must
produce one confirmation and one explicit conflict. The agent records the requirement and
scenario in Flower, plans bounded work with dependencies and checks, and reports
results against the relevant revision. The implementation remains its job.

Two confirmations would be a defect; recurring bookings would be a new request.
Flower preserves that distinction and the work still awaiting verification.

The walkthrough follows **Require → Plan → Build → Verify → Deploy → Operate**.
These are lifecycle perspectives, not mandatory sequential commands or built-in
deployment and monitoring. Follow the story in
[English](docs/presentation/eng/README.md) or [Italiano](docs/presentation/ita/README.md).

## Quick start

Choose one installation route. Use a writable user directory and have a
**Codex, Claude Code or Cursor** client installed. Downloads require Internet
access and trusted HTTPS certificates. Check the
[prerequisites](docs/INSTALLATION.md#prerequisites) first.

### macOS / Linux

Requires Bash, `curl`, `awk`, `sha256sum` or `shasum`, and standard shell utilities.
Review the [release installer](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.sh) before execution:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.sh | bash
```

The installer prepares an isolated Python environment, obtaining Python if
needed, checks backend and wheel checksums, and offers optional client registration.

### Windows

Requires Windows PowerShell 5.1+. Download the launcher, inspect it, then run the
second command only after the download succeeds:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Platform codex
```

Use `-Platform claude-code`, `-Platform cursor` or `-NoRegister` as appropriate.
The launcher reuses or prepares Python and installs the checked release wheel.
The execution-policy option applies only to that process.

**Manual alternatives:** [source](docs/INSTALLATION.md#manual-installation-from-source)
or [release wheel with checksum verification](docs/INSTALLATION.md#manual-installation-from-a-release-wheel).
Both require Python 3.11+ with SSL, `venv` and `ensurepip`; cloning also requires
Git. The [installation guide](docs/INSTALLATION.md) covers downloads, upgrades,
profiles, removal and recovery.

### Glama and containers

The repository includes maintainer metadata and a core-only Dockerfile for
Glama's build workflow. See the [Glama and container guide](docs/GLAMA.md) for
startup arguments, persistent SQLite storage and client setup. Glama account
claim, hosted deployment and platform release are separate steps; the existing
GitHub `v0.1.1` tag predates these container files.

### Connect an agent and start a project

1. **Reload the registered client and approve its MCP connection.** The client
   starts Flower. If you installed without registration, configure the client
   first. Do not start another server process against the same ledger.
2. **Give your agent this request** while working in the project you intend to
   develop. Replace "the installed Flower MCP command" with the executable path
   returned by the installer:

> Run the installed Flower MCP command with `bootstrap` and follow its output
> to update this project's `AGENTS.md`, preserving its existing rules. Verify
> the MCP connection, discover the lifecycle projects and select the intended
> project explicitly. If the ledger is empty, I authorize creating a lifecycle
> project for this repository. Report an ambiguous project choice or a missing
> connection instead of guessing. Read the durable project snapshot and follow
> Flower's current recipes. Help me describe the first scenario, clarify its
> intent progressively and present a roadmap for my confirmation before coding.

The bootstrap command prints instructions; the agent merges them into
`AGENTS.md`. Ensure your host loads those instructions through its supported
mechanism. Project selection and state recovery use Flower's public tools;
the agent follows their current recipes.

For a manual source installation, the bootstrap command is
`.venv/bin/flower-mcp bootstrap` on macOS/Linux or
`& .\.venv\Scripts\flower-mcp.exe bootstrap` in PowerShell, **from the Flower
checkout**. From your application project, use the absolute path to that
executable. A bare `flower-mcp` command works only when it is on `PATH`.

**First-use check:** the agent can see Flower's tools, select the intended
project and retrieve its current snapshot and next gate. `doctor` checks
configuration files; it does not prove the MCP connection. The
[bootstrap guide](docs/BOOTSTRAP.md) includes a ready-to-use agent request.

## Documentation

| Topic | English | Italiano |
| --- | --- | --- |
| Scenario-led walkthrough | [Start here](docs/presentation/eng/README.md) | [Inizia qui](docs/presentation/ita/README.md) |
| Concepts, packet validation and evidence | [Concepts](docs/presentation/eng/concepts.md) | [Concetti](docs/presentation/ita/concepts.md) |
| Public MCP tools | [Tool map](docs/presentation/eng/tools.md) | [Mappa dei tool](docs/presentation/ita/tools.md) |
| Optional providers and technical execution | [Integrations](docs/presentation/eng/advanced.md) | [Integrazioni](docs/presentation/ita/advanced.md) |
| Comparison with related projects | [Comparison](docs/presentation/eng/comparison.md) | [Confronto](docs/presentation/ita/comparison.md) |
| Sources, provenance and limits | [Sources](docs/presentation/eng/sources.md) | [Fonti](docs/presentation/ita/sources.md) |

The [presentation index](docs/presentation/README.md) also links the offline readers.

## Development method

Flower is a personal project by **Davide Mele**, developed outside his
professional work. He designed the system, defined requirements and constraints,
guided verification and made acceptance decisions; coding agents, primarily
**Codex**, carried out repository investigation, technical planning,
implementation, tests and document updates. The work first used a documentary
framework; Flower moves part of that discipline into a persistent server.
Read the method in [English](docs/presentation/eng/method.md) or
[Italiano](docs/presentation/ita/method.md).

## Status and operating limits

Flower `0.1.1` is in testing. The [release notes](docs/RELEASE-NOTES-0.1.1.md) and
[installation status](docs/INSTALLATION.md#testing-status-and-release-access)
distinguish installed-package and CI checks from end-to-end installer and
target-client qualification.

Flower's gates govern its server operations, not every action available to the
agent's host. Host-declared evidence is not an independent source audit;
correctness depends on the implementation, checks and oracles behind it.
Optional CodingCastle adapters need compatible services; their presence alone
does not establish that a runtime pairing has been qualified.

To report an issue, include the Flower version, operating system, client,
operation and error in the [issue tracker](https://github.com/Damel91/flower-mcp/issues),
without credentials or private project data.

## License and compatibility

Licensed under [Apache-2.0](LICENSE), with attribution in [NOTICE](NOTICE).
The public command is `flower-mcp`; the Python distribution `flow-of-work-mcp`,
import package `flow_of_work_mcp` and MCP prefix `fow_*` retain their existing names.
