# Flower MCP on Glama

The repository provides `glama.json` for maintainer identification and a
`Dockerfile` that installs Flower's core and starts its existing MCP stdio server.
It needs no API key, internal model or CodingCastle service.
This prepares the source for Glama's build process; claiming a listing, deploying
and publishing a Glama release are separate account actions.

## Configure Glama

1. Sign in to Glama with the GitHub account authorized to maintain this repository.
   Claim the server's listing when available. Root
   [glama.json](../glama.json) names `Damel91` under Glama's
   [maintainer schema](https://glama.ai/mcp/schemas/server.json).
2. Connect `Damel91/flower-mcp` using Glama's GitHub integration and select its
   root [Dockerfile](../Dockerfile). The image installs the source's current
   `flow-of-work-mcp` package with its core dependencies. Select a source revision
   deliberately; GitHub `v0.2.0` includes these container files, while the
   historical `v0.1.1` tag predates them.
3. If the dashboard asks for the startup command, use these executable arguments:

   ```json
   ["flower-mcp", "serve", "--profile", "default", "--profile-root", "/data", "--transport", "stdio"]
   ```

   The Dockerfile sets `FLOWER_HOME=/data`. No credential or placeholder
   environment variable is required for core use. Keep the stdio process in the
   foreground without a TTY; Glama supplies its Streamable HTTP gateway.
4. Enable a persistent volume at `/data` before keeping project records.
   Glama documents volumes as optional: the image's `VOLUME` declaration alone
   does not enable durable storage on the platform. The mount must be writable
   by UID/GID `10001:10001`, the image's runtime user.
5. Run Glama's build/deployment test, then inspect the handshake, tools and a
   synthetic project's recovery after recreation. If the build test succeeds,
   choose whether to create and publish a Glama release in your account.

Follow the current [Glama hosting guide](https://glama.ai/mcp/hosting) and
[release procedure](https://glama.ai/blog/2026-03-15-how-to-make-a-release).
Glama's release is a platform build and publication; it is separate from the
GitHub release and its downloadable Python installers. Hosting is a separately
billed service. Repository CI does not perform any account-side deployment.

## State and agent setup

Keep the whole `/data/profiles/default` directory: it contains `flower.yaml`,
`ledger.sqlite3` and its companion files, the runtime lock sidecar, `imports/`
and `logs/`. A single server process owns a ledger. Do not start another process
against the same volume or remove its lock file to bypass ownership.
Before replacing an instance, stop its server and retain or back up the profile.

Connect the coding client to the gateway endpoint returned by Glama, using the
platform's connection credentials. The coding agent works on its own repository
checkout and reports outcomes through Flower's public tools. Hosting the lifecycle
server does not mount the agent's source repository or execute coding tasks.
Optional integrations still require their explicitly configured prerequisites;
their absence does not block the core lifecycle.

Give the agent the canonical [bootstrap instructions](../src/flow_of_work_mcp/resources/agent-bootstrap.md)
and follow the [bootstrap guide](BOOTSTRAP.md). It should verify the connection,
discover the current capabilities, select a lifecycle project explicitly and
recover its snapshot. An empty new volume starts without a lifecycle project.
Exported Markdown plans support authorized offline work and explicit outcome
reconciliation when the server returns.

## Build and run the image yourself

Prerequisites: Git to clone the source, Docker with a running Linux container
engine, Internet access and trusted HTTPS for the Python image and build
dependencies. The host does not need Python, curl or an inference runtime to run
this image. Docker installation may need administrator permission; see
[Docker's installation instructions](https://docs.docker.com/engine/install/).
On Windows and macOS, use a running Linux container engine such as Docker Desktop.

Run each command separately, stopping on failure:

```sh
git clone https://github.com/Damel91/flower-mcp.git
cd flower-mcp
docker build --tag flower-mcp:local .
docker volume create flower-state
docker run --rm -i --network none --mount type=volume,src=flower-state,dst=/data flower-mcp:local
```

The last command waits for an MCP client on stdin; it is not an interactive shell.
Do not add `-t`. An MCP client that supports command-based stdio servers can use:

```json
{
  "mcpServers": {
    "flower-mcp": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "--network", "none", "--mount", "type=volume,src=flower-state,dst=/data", "flower-mcp:local"]
    }
  }
}
```

Use the client's supported configuration location. Only one client-owned server
process may use that volume at a time. Reuse `flower-state` on later launches;
`--rm` removes the container, not the named volume. A new named volume inherits
the image's `/data` ownership. Existing volumes or host bind mounts must already
have permissions for UID/GID10001; Flower does not change ownership of mounted
host files. `--network none` suits core stdio operation; optional remote providers
require an explicitly selected network and compatible configuration.

To print the agent instructions without starting a server:

```sh
docker run --rm --network none flower-mcp:local flower-mcp bootstrap
```

The image uses an installed package in `/opt/flower-venv`, not checkout imports.
Its allowlisted build context excludes development authorities, runtime data,
credentials and Git history. The Python base is pinned by image digest.
Dependencies follow the core package's version constraints; this does not promise
byte-identical rebuilds against changing package indexes.

## Verification status

The [CI workflow](https://github.com/Damel91/flower-mcp/actions/workflows/ci.yml)
builds the actual image from the current source archive. Its container job checks
installed identity/resources, core-only dependencies, nonroot execution and the
public MCP workflow with networking disabled, then recreates the container over
the same dedicated test volume and checks durable state. Receipts include
model-facing multiline Markdown and structured results. No existing user volume
is used by the qualifier.

Local OCI verification is blocked when no container daemon is available.
Linux amd64 CI mechanics, native ARM/container-host behavior, actual Glama
deployment and human acceptance are separate checkpoints. Glama indexing,
quality scores, hosted persistence and publication cannot be inferred from the
presence of these repository files.
