# Flower MCP 0.6.4

This patch makes packet-start validation failures explicit. When `fow_packet_author`
with `operation=start_packet` rejects a malformed packet identity/draft, or an
exact parent lookup proves the change does not exist before creation, Flower
returns a correlated `flow.operation-effect.v1` receipt. Both Markdown and the
structured channel explain the invalid field, its rule and a safe exact-help route.
No packet, event, revision or sequence is allocated by a certified rejection.

The receipt binds tool, operation, project and request identity, with
`basis=pre_effect_validation` and `mutation_started=false`. It describes that
invocation. It does not erase earlier work under a reused request ID. A failure
after creation dispatch, queueing, commit or continuation remains `unknown`,
including an error shaped like an input rejection. A timeout, lost response or
current absence query is never permission to replay blindly. Corrected input
requires an explicit new submission after resolving the actual state.

An older uncertain result is not retroactively turned into an originally
emitted receipt. Native recovery must retain the original response and evidence;
a separately attributed, exact-source audit may support its own bounded recovery
resolution. This release does not add a generic historical effect-query API or
clear a consumer's pending state automatically.

## Compatibility and scope

Flower retains 37 public tools, 445 input fields, 182 operation routes, SQLite
schema55 and unchanged dependencies. Successful creation/replay and the
transactional provider queue remain supported. The optional inference extra
still selects independently published llama-runtime 0.5.0; see
[advanced configuration](ADVANCED-CONFIGURATION.md). Core remains model-free.
No witness/U6, pipeline resumption, runtime-llama update, new model tool, native
consumer UI fix or automatic client restart is included. Historical releases
and artifacts remain immutable. Flower remains in testing.

## Upgrade while preserving SQLite

Use the [same-profile upgrade guide](UPGRADING.md#preparing-a-064-upgrade).
Verify the official 0.6.4 asset checksums and use its installer with the original
environment, profile root and data paths:

```sh
python3 -I ./install_flower.py --version 0.6.4 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Stop owners/clients sharing the selected environment and ledger, inspect the
plan and then execute without `--dry-run`. Windows uses `py -3 -I` and actual
Windows paths. The unchanged installer refuses an active owner and makes a
consistent SQLite backup plus exact YAML copy before pip. Keep SQLite, YAML,
bindings, receipts, evidence, handovers and client configuration in their existing
locations. Manual pip environments use the separate backup procedure in the
guide; do not bypass installer ownership receipts. Failed pip does not promise
automatic restoration or atomic code/database rollback. Schema55 has no new
migration; the existing schema52-to55 route remains a separate supported path.

## Qualification boundaries

The producer has 64 focused and adjacent source checks and an actual isolated
public MCP workflow covering malformed/absent changes, whole-ledger logical
invariance on certified rejection and replay, corrected creation and truthful
conflict uncertainty in both channels. A separate development-only historical
audit utility has 26 checks and an owned exact 0.6.3 artifact fixture; this does not
qualify a user's real recovery. Existing exact-commit Release CI qualifies the
installed wheel and published assets separately. An owner's actual update,
retained-chat recovery, local UI and human acceptance remain separate evidence.

## Published delivery record

This record preserves the package-verification checkpoint previously included
in the project README. Client adoption and user acceptance have their own
verification records.

Flower `0.6.4` is published at commit `76b3fbd666f027a8c2007819e5ae589828cdf731`
([release 418844855](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.4)).
The [Release workflow](https://github.com/Damel91/flower-mcp/actions/runs/39490419031)
passed all eight jobs, including installed Python 3.11–3.14, Windows and the core container.
Seven anonymous official assets match SHA256SUMS; the wheel SHA256 is
`572baa55357ffe35b31d6dfb9c4229f1495b814bb72f22d4c46b22a4f8e83d67`. The qualified packet-start source matches the released wheel and
source archive. SQLite remains at schema 55 and optional runtime-llama remains 0.5.0.
Actual retained-chat recovery and module update belong to the consuming host;
publication does not clear its historical unknown results. Witness/U6 stays deferred.
