# Flower MCP 0.9.0

Flower now includes a local browser dashboard alongside its streamable HTTP MCP
server. Inspect registered projects, requirements, roadmap, packets, campaigns,
Oracles, adopted architecture and retained evidence in the same selected profile.
Browser navigation does not change a chat's project context or capability lens.
Reported implementation, verification and human acceptance remain separate.

## Local dashboard and document reading

Start the existing profile with streamable HTTP and open the one-time local
operator link printed by Flower. Access is limited to the same computer, with
independent Host/Origin/session checks and CSRF protection for administration.
The activation link expires after ten minutes; a session lasts up to24 hours
and is revoked by restart. Stdio connections continue to expose MCP without a
dashboard. Do not start two owners of the same profile. See the
[dashboard guide](DASHBOARD.md).

Choose system, light or dark appearance. The initial choice follows the OS; a
manual preference remains local to that browser. Retained Markdown opens in a
native reader with an outline, formatted tables and code, original source view
and unchanged download. Stored HTML is inert and images are not fetched. Only
explicit safe link navigation is enabled.

The browser evidence limit is2MiB. The formatted reader additionally limits its
source to256KiB and its projection to25,000 nodes; exceeding presentation limits
shows an explanation while preserving the valid original/source/download. No
repository file loading, document editor, Markdown authority store or CDN is added.

## Guarded project deletion

Prepare deletion explicitly to enter instance-wide maintenance, inspect the
inventory, then confirm the exact project ID and declare the actual host-stop
evidence you possess. Local admissions drain and idle jobs remain fenced while
the runtime retains its ownership lease. Busy jobs, unsupported platforms and
existing native purge guards block the operation.

Cancellation retains the prepared journal. An uncertain destructive outcome
requires inspection/reconciliation of the same intent; normal service resumes
only after verified cleanup. The UI does not claim to stop external workers,
erase repository files/backups/chats or synthesize host-cleanup acknowledgment.
See [native deletion boundaries](NATIVE-PROJECT-DELETION.md).

## Semantic currentness correction

Packet fingerprints now use normalized adopted architecture and current indirect
Oracle dependencies. Relevant revision or retirement changes invalidate current
pins; unrelated history does not silently rewrite old reports or evidence.
Existing affected packets may need ordinary read/review/repair rather than blind
mutation replay. See [currentness and recovery](CONTINUOUS-RECOVERY.md).

## Upgrade with the existing SQLite ledger

Use the [same-profile upgrade](UPGRADING.md#preparing-a-090-upgrade). Keep the same
environment, database/profile paths, YAML and client configuration. Stop the
Flower owner; the existing installer refuses active ownership and creates a
consistent SQLite/YAML backup before pip. Keep the backup: a failed pip operation
does not provide an atomic rollback. Never reset or recreate the database.

SQLite stays at schema55 and the catalog stays at37 MCP tools. This release adds
markdown-it-py as a core dependency for document presentation; optional inference
remains optional and no model/provider endpoint is required for the dashboard.
The installer algorithm, AGENTS bootstrap and client registrations are unchanged.
No queued work, provider execution or pipeline is resumed automatically.

## Qualification boundary

The existing focused dashboard/reader and fingerprint verification is reused.
Actual source and isolated installed-package browser/MCP checks cover themes,
reading and explicit maintenance. Authorized synthetic deletion was checked on
the source instance; the installed instance checked preparation, restart,
inspection and cancellation without deleting a project.
The Release workflow checks its exact public commit/packages before publication,
including installed Linux dashboard regressions and dashboard-resource parity.

This is not a claim of native browser qualification on every OS, external-host
quiescence, provider execution, model usability or completed witness/cross-server
acceptance. Current platform and integration guards retain their declared meaning.
