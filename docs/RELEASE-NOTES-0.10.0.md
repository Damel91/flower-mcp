# Flower MCP 0.10.0

Flower 0.10.0 adds native owner sign-in, project creation, profile settings,
backup and project transfer to the local dashboard. Dedicated macOS services can
also verify and install a compatible future Flower release, then restart on the
same profile.

## Local dashboard and data management

- Sign in at the local `/dashboard` address with the OS account that owns the
  selected YAML and SQLite database. Project deletion requires a fresh password
  check alongside the inventory, project ID and host-stop reference. See the
  [owner-login guide](OWNER-LOGIN.md).
- Create projects and prepare profile settings in the dashboard. Apply the
  validated settings draft from the terminal with the selected Flower instance
  stopped. See the [dashboard guide](DASHBOARD.md).
- Retain a consistent full SQLite backup or export a single project. Inspect
  archives and restore to a separate profile using the native CLI. See the
  [backup and recovery guide](DATA-BACKUP-AND-RECOVERY.md).

## Upgrade an existing installation

For the move from 0.9.1, stop Flower and use the 0.10.0 installer with
`--upgrade` and your existing profile selection. It backs up SQLite and YAML
before replacing the package. Keep the backup and start the same profile.
The ledger uses schema 55. See [upgrading](UPGRADING.md#preparing-a-0100-upgrade).

For later upgrades, use the new manual `flower-mcp upgrade` command or enroll
a dedicated macOS service before registering it. On an enrolled service,
Flower checks the exact compatible release, fences concurrent starts, stops
the service, backs up SQLite and YAML, installs the package, and verifies
the restarted instance. The operation receipt is available in the dashboard
and from the terminal. See the [operator upgrade guide](OPERATOR-UPGRADE.md).

## Platform verification

The complete managed upgrade ran on an isolated macOS arm64 service using two
locally built wheels and the release installer transaction. The run exercised
concurrent start refusal, backup integrity, package replacement and supervised
restart. Native owner login and the LaunchAgent lifecycle were also exercised
on an isolated macOS fixture. Linux and Windows use the manual upgrade route
and have separate native account and startup qualification.
