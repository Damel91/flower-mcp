# Flower MCP 0.9.1

The local dashboard now opens directly at its stable `/dashboard` address while
Flower is running. There is no activation link, access-code form, login, session
cookie or time-based access expiry. A desktop launcher is optional convenience,
not a prerequisite for using the dashboard. See the [dashboard guide](DASHBOARD.md).

## Direct local access

Streamable HTTP startup prints `Flower dashboard: <local-url>`. Use that address
in any local browser, return later, or reopen it after a server restart without
an activation exchange. Connection failures provide retry rather than an unlock
screen. Stdio continues to serve MCP without a browser dashboard.

Loopback-peer, Host and Origin checks remain. Administrative requests retain
automatic CSRF protection: the browser obtains its current request token from
server status, with no operator action. This token is not a login or evidence of
host quiescence. No remote access or API-key scheme is introduced.

## Existing project and document safeguards

Project deletion still requires explicit instance-wide maintenance, inventory
review, the exact project-ID confirmation and actual host-stop evidence. Native
purge blockers, currentness checks and unknown-outcome recovery are unchanged.
No destructive command is replayed automatically. The retained Markdown reader,
original/source download, themes and lifecycle-state projections are unchanged.

## Upgrade without recreating SQLite

Use the [ordinary same-profile upgrade](UPGRADING.md#preparing-a-091-upgrade).
Stop the Flower owner; retain the same environment, profile/database paths,
YAML and client settings. The verified installer refuses active ownership and
creates a consistent SQLite backup and exact YAML copy before pip. Keep that
backup: a failed package install does not provide an atomic rollback.

SQLite stays at schema55 and the catalog stays at37 MCP tools. There is no new
migration, dependency change from0.9.0, AGENTS edit or client re-registration.
The installer does not start Flower. Start the same connection when ready; the
upgrade neither resumes queued work nor changes historical acceptance.

## Qualification boundary

Focused verification covers the changed direct-entry/request-protection surface,
connection recovery and the stable startup address. Existing0.9.0 reader, native
purge, package-resource and upgrade qualification is reused where unchanged.
The Release workflow gates publication on its exact source and package checks.
This does not claim native browser qualification on every OS, external-host
quiescence, model usability or completed witness/cross-server acceptance.
