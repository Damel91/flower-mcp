# Flower MCP 0.6.2

This patch makes lifecycle responses, guided roadmaps and generated references
readable as complete Markdown. Nested records become associated sections and
lists; shallow single-line scalar values can use tables. Multiline paragraphs,
ordered steps, empty fields and all supplied facts remain visible. Explicit
executable tool-call references retain JSON arguments. The complete roadmap
appears once alongside its summary and gates, while the structured application
envelope remains available to the coding host. See the
[readable lifecycle guide](readable-lifecycle-example.md).

Roadmaps include the supplied scenarios, requirements, milestone prerequisites
and declared producers, policies, answers, correspondence, draft context and
gaps. Rendering does not resolve missing declarations or certify intent.
Canonical authority, fingerprints, readiness and acceptance gates are unchanged.
Newly generated Markdown receives its normal digest; historical artifacts and
request replays keep their original content. An exported external-agent plan
remains a self-contained offline reference with explicit outcome reconciliation.

The public catalog remains 37 direct tools, 445 input fields and 182 operation
routes, with the existing nine work-area memberships. No database migration,
provider request, internal model or optional inference dependency is required.
SQLite stays at schema 55. The optional inference extra retains independently
published [llama-runtime 0.5.0](https://github.com/Damel91/llama-runtime/releases/tag/v0.5.0);
settings and external-provider contracts remain in the
[advanced configuration guide](ADVANCED-CONFIGURATION.md).

## Preserve an existing installation

Use the [upgrade procedure](UPGRADING.md) with the original owned environment,
profile, database, YAML and client paths. Download the official 0.6.2 installer
and SHA256SUMS, verify its checksum, then preview before updating:

```sh
python3 -I ./install_flower.py --version 0.6.2 --upgrade --dry-run --venv '/absolute/flower-venv' --profile default --profile-root '/absolute/private/flower-state' --backup-root '/absolute/private/flower-backups'
```

Stop every Flower owner/client sharing that environment before executing the
inspected plan without --dry-run. The backend refuses an active selected-ledger
owner and makes a consistent SQLite backup and exact YAML copy before pip.
Keep the private backup. Do not reset SQLite, replace projects or bindings, move
configuration, or bypass an installer-owned artifact receipt with manual pip.
Windows uses `py -3 -I` and the same options with its actual paths. Manual pip
installations have a separate backup/upgrade procedure. Package downgrade is
not database rollback, and failed pip does not promise automatic restoration.

For Flower integrated in Noxi, use its existing native updater and inspect the
components it proposes. Updating Flower does not authorize updating Noxi,
CodingCastle or another module. The owner preserves chats, project, SQLite,
configuration and auxiliary state, then verifies reopening and restart. Its
managed-generation path changes, if any, retain their own provenance; this is
separate from an installer-owned same-path upgrade.

The supported 0.3.1/schema52 to55 migration route remains distinct from a
same-schema 0.6.1 to0.6.2 update. Refresh the host schemas and inspect existing
project state through public MCP after restart. Older pre0.6.0 clients must
observe the retained [milestone compatibility change](RELEASE-NOTES-0.6.0.md).
Previous release tags/assets are preserved. No witness/U6, pipeline resumption
or native deletion is included.

## Qualification boundaries

The unchanged product correction was independently reviewed and qualified in
its source and earlier source-built candidate scopes: 159 source tests, 141
installed tests, separate real public MCP workflows, offline/restart/history
checks and rendered Markdown inspection. Those are prior component evidence,
not proof of this final versioned package or a real installation update.

Final0.6.2 package/source/resource/guide checks, actual installed workflows,
populated candidate upgrade, exact CI, all eight Release results, seven anonymous
assets and official HTTPS upgrade are separate recorded delivery checkpoints.
Actual Noxi adoption retains owner provenance and a separate preservation audit.
This guide defines the intended release and upgrade procedure; it does not assert
that a later checkpoint has already executed. Version-pinned download commands
require the corresponding published assets. Human/local-model usability,
unknown workstation compatibility and physical/cross-provider/U6 acceptance
remain separate. Flower remains in testing.
