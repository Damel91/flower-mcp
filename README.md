# Flower MCP

<p align="center">
  <img src="assets/flower-mcp-logo.png" alt="Flower MCP: Require, Plan, Build, Verify, Deploy, Operate" width="380">
</p>

**Persistent software lifecycle management for coding agents.**

Building software with an AI agent takes more than a good prompt. You need to
keep track of what you asked for, which decisions you made, what is ready to
build and what still needs checking.

Flower gives your agent a lasting project memory and a structured way to move
from an idea to verified work. It keeps requirements, plans, decisions and
evidence connected, even when the conversation changes.

**In testing** · Python **3.11+** · [Latest release](https://github.com/Damel91/flower-mcp/releases/latest) · [Apache-2.0](LICENSE)

[Quick start](#quick-start) · [First project](#start-your-first-project) · [English walkthrough](docs/presentation/eng/README.md) · [Presentazione italiana](docs/presentation/ita/README.md)

## What you gain

- **Pick up where you left off.** Recover the selected project's context,
  decisions, open work and next step in another session or compatible agent.
- **Start with the behavior you want.** Describe what the software should do
  and show. Your agent investigates technical choices, asks focused questions
  and proposes a roadmap for you to confirm.
- **Give the agent work it can act on.** Plans carry scope, ordered tasks,
  dependencies and checks. Flower exposes missing declarations and lifecycle
  gates before admitting the next operation.
- **See what “done” means.** Work reported as implemented, evidence of
  verification and a decision to accept the result remain distinct.
- **Keep progress when plans change.** Requirements, decisions and results
  retain their revisions and history, so earlier work stays understandable.
- **Hand work over, including offline.** Export a self-contained Markdown
  plan, carry out its authorized work and reconcile outcomes when Flower is
  available again.

Project state lives in a SQLite ledger under your chosen Flower profile.
The core works without an internal model or CodingCastle. You can use a local
or cloud coding agent through a compatible MCP client.

## How it works

You explain the outcome. Your coding agent investigates the repository, chooses
an implementation, writes code and runs builds and tests. Flower maintains the
project's requirements, roadmap, work plans, findings, evidence and handovers.
You keep the scope and acceptance decisions assigned to you.

For example, you might ask:

> I want a room-booking service for our association. Two people must not be
> able to reserve the same room at the same time.

The agent can clarify what a booking means, record the agreed behavior and
propose bounded work. The plan identifies what must be implemented and checked.
If overlapping bookings are confirmed for the same room, that is a defect to
investigate; adding recurring bookings changes the requested scope. Flower
keeps those discussions and their resulting work connected.

This is an illustrative scenario, not a benchmark. Follow the complete story in
[English](docs/presentation/eng/README.md) or [Italiano](docs/presentation/ita/README.md).

Governing architecture stays in Flower alongside the work it explains. At a
bounded work boundary, the agent reconciles repository facts and original
evidence with current authority before dependent work advances. Read the
[engineering cycle](docs/ENGINEERING-CYCLE.md) for the practical workflow.

## Quick start

Have a supported client installed: **Codex, Claude Code, Cursor, Antigravity or
Gemini CLI**. Choose a writable user directory and check the
[installation prerequisites](docs/INSTALLATION.md#prerequisites).

**OpenCode V2:** integration is available in the development source. Follow the
[OpenCode setup guide](docs/OPENCODE.md) for a local candidate; the published
0.7.6 installers do not include this adapter yet.

### macOS and Linux

You need a terminal with `curl`, Internet access and trusted HTTPS certificates.
The launcher finds or prepares a supported Python environment.
See prerequisite setup for [macOS](docs/INSTALLATION.md#macos-prerequisite-setup)
or [Linux](docs/INSTALLATION.md#linux-prerequisite-setup) if a command is missing.

Review the [installer](https://github.com/Damel91/flower-mcp/releases/download/v0.7.6/install.sh), then run:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.7.6/install.sh | bash
```

Choose your client when prompted, or choose installation without registration.

### Windows

Use **Windows PowerShell 5.1+** or **PowerShell 7**, with Internet access and
trusted HTTPS certificates. This route uses `Invoke-WebRequest`; curl is not
required. See the [Windows prerequisites](docs/INSTALLATION.md#windows-prerequisite-setup).

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.7.6/install.ps1" -OutFile ".\install.ps1"
# Review install.ps1, then run:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

The execution-policy override applies only to that process. Follow the prompts
to select your client or install without registration.

### Other installation options

- **Manual installation:** use a [verified release wheel](docs/INSTALLATION.md#manual-installation-from-a-release-wheel)
  or [install from source](docs/INSTALLATION.md#manual-installation-from-source).
  These routes require Python 3.11+ with SSL, `venv` and `ensurepip`; cloning
  the repository also requires Git.
- **Google clients:** see [Antigravity and Gemini CLI setup](docs/GOOGLE-CLIENTS.md).
- **Containers:** see [container and Glama setup](docs/GLAMA.md) for server
  startup and persistent storage.
- **Already installed?** Use the [SQLite-preserving upgrade guide](docs/UPGRADING.md)
  with your existing environment, profile and data paths. The installer offers
  `--upgrade --dry-run` and backs up SQLite and YAML before changing packages.

## Start your first project

Reload the registered client and approve its MCP connection. The registered
client starts Flower; a manual installation needs its client connection configured
first. Then open the repository you want to work on and give your agent this request:

> Set up Flower MCP for this repository. Run the bootstrap_command returned by
> the installer and follow its output to integrate Flower's instructions into
> this project's AGENTS.md, preserving its existing rules. Verify the MCP
> connection and explicitly select the intended lifecycle project; ask me if
> the choice is ambiguous. If Flower has no projects yet, I authorize creating
> one for this repository. Help me describe the first scenario and present a
> roadmap for my confirmation before coding.

**The AGENTS.md step is already part of the guided setup.** A fresh installation
returns `bootstrap_command` with the installed executable's absolute path and
`bootstrap` argument. The command prints the bundled engineering template; your
agent creates or merges its Flower section in the intended project's `AGENTS.md`.
The installer itself does not edit project files. Make sure your client loads
those project instructions.

For a manual installation, ask the agent to run the installed `flower-mcp`
executable with `bootstrap`, using its absolute path. The
[bootstrap guide](docs/BOOTSTRAP.md) provides detailed prompts and examples.
An upgrade preserves the existing profile and guides the agent to recover its
project; it does not repeat first-project setup.

## Optional LLMs and providers

Your coding agent can use Flower's core without installing an internal model.
For additional assistance, Flower supports bounded internal semantic roles,
host-executed semantic assignments and optional technical providers. Each route
has its own prerequisites and evidence provenance.

See [advanced configuration](docs/ADVANCED-CONFIGURATION.md) and
[internal inference setup](docs/INFERENCE.md) to choose the integration you need.

## Learn more

| What you want to do | Where to go |
| --- | --- |
| Follow a complete project scenario | [English walkthrough](docs/presentation/eng/README.md) · [Italiano](docs/presentation/ita/README.md) |
| Understand plans, verification and handovers | [Essential concepts](docs/presentation/eng/concepts.md) |
| Explore the public tools | [Tool map](docs/presentation/eng/tools.md) |
| Resume work or reconcile offline results | [Continuous work and recovery](docs/CONTINUOUS-RECOVERY.md) |
| Connect project architecture and technical providers | [Integration guide](docs/NOXI-INTEGRATION.md) |
| Install, update or recover a profile | [Installation](docs/INSTALLATION.md) · [Upgrading](docs/UPGRADING.md) |
| See changes and compatibility notes | [Releases](https://github.com/Damel91/flower-mcp/releases) |
| Read the walkthrough offline | [Local readers](docs/presentation/README.md) |

## About the project

Flower is a personal project by **Davide Mele**, developed outside his
professional work. He designed the system, defined requirements and guided
verification; coding agents, primarily **Codex**, carried out repository
investigation, implementation, tests and documentation. Read about the
[development method](docs/presentation/eng/method.md).

A real project managed with Flower is
[llama-runtime](https://github.com/Damel91/llama-runtime). Its requirements,
milestones, implementation plans, verification evidence and handovers are
maintained in Flower's project ledger.

Flower remains in testing. Its gates govern lifecycle operations; the coding
agent and its host remain responsible for code, execution and reporting.
Host-declared evidence keeps that provenance and is not an independent source
audit. See the [sources and limits](docs/presentation/eng/sources.md).
Report problems in the [issue tracker](https://github.com/Damel91/flower-mcp/issues),
including your version, operating system, client and the affected operation.
Keep credentials and private project data out of reports.

## License and compatibility

[Apache-2.0](LICENSE), with attribution in [NOTICE](NOTICE).
The public command is `flower-mcp`; the Python distribution `flow-of-work-mcp`,
import package `flow_of_work_mcp` and MCP prefix `fow_*` retain their existing names.
