# Flower MCP 0.6.3

This patch
corrects HTTP process shutdown after SIGTERM. Previously Uvicorn could complete
its own shutdown and re-raise the signal before Flower reached its outer runtime
cleanup. Flower now keeps that existing cleanup reachable: join owned workers,
close the runtime, release ownership and close logging in their established order.

The HTTP CLI temporarily installs a restorable termination handler after runtime
construction, with main-thread and restoration guards. Repeated SIGTERM while
closing does not interrupt cleanup. The previous handler is restored, and real
application or cleanup failures retain their failure outcome. This is not a
force-stop mechanism or a promise that an arbitrary legacy process has shut down.

## Compatibility and scope

Stdio behavior is unchanged. Flower retains 37 public tools, 445 input fields,
182 operation routes, SQLite schema 55 and its existing dependencies. No lifecycle,
receipt, provider or model contract changes. Historical artifacts and request
replays are not rewritten. The optional extra still selects independently
published [llama-runtime 0.5.0](https://github.com/Damel91/llama-runtime/releases/tag/v0.5.0);
see [advanced configuration](ADVANCED-CONFIGURATION.md). Core remains model-free.
No witness/U6, pipeline resumption, native deletion or external-provider feature
is included. Historical releases and assets remain immutable.

## Upgrade without losing SQLite

Follow the [same-profile upgrade guide](UPGRADING.md#preparing-a-063-upgrade).
Verify the official 0.6.3 asset checksums and use
the new installer with the original environment, profile and database paths:

```sh
python3 -I ./install_flower.py --version 0.6.3 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Stop all Flower owners/clients sharing the environment, inspect the plan, then
execute it without `--dry-run`. Windows uses `py -3 -I` with actual Windows paths.
The installer refuses an active selected-ledger owner and backs up SQLite plus
the exact YAML before pip. Preserve client configuration, imports, logs,
revisions, receipts, evidence and handovers. Do not reset a project, replace its
bindings, move its ledger or bypass an owned artifact receipt with manual pip.
Failed pip does not promise automatic restore or atomic package/database rollback.
Manual pip environments use the separate backup procedure in the upgrade guide.

Reconnect using the intended transport and same profile; inspect the existing
project through public MCP after restart. An actual coding-client stdio connection
requires its own restart and readback. It is not established by an HTTP process
check. The retained 0.3.1/schema 52-to55 migration route is separate from a
same-schema update.

## Qualification boundaries

The unchanged source correction already has focused and independent review,
107 focused source tests and 12 independent tests, and real owned public HTTP
termination, worker-join, state-preservation, restart and SIGINT evidence across
the selected SDK scopes. These are corrected-source results, not blanket
installed 0.6.3, actual-owner, named-client or unknown-OS qualification.

The exact versioned package, existing Release CI, official assets and preserved
upgrade have separate delivery checkpoints. Source qualification alone does not establish those deployment results. No duplicate historical campaign or automatic client
restart is required by these notes. Source pushes do not publish a release.
Flower remains in testing.
