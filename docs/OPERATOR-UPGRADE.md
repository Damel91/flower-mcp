# Upgrade a manually started Flower installation

Use this command from the Flower environment created by the official release
installer. Choose the exact published stable version, without a leading
`v`. Start with the preview:

```sh
flower-mcp upgrade --version X.Y.Z --profile default --dry-run
```

For a different standard profile, pass its name and, if applicable,
`--profile-root /absolute/path`. Use the same selection for preview and apply.
The preview checks the existing installation and reports the selected
configuration, SQLite and backup paths. It downloads and checks the official
installer, without changing the installed package or the selected profile.

Stop all clients and servers that use the installation, then repeat the
same command without `--dry-run`. The official installer verifies the
versioned assets, takes a consistent backup of SQLite and the existing YAML
before changing the package, and reports the backup path and outcome.
It keeps client registration in place. Restart the manually started
Flower connection when the command succeeds.

The command refuses source checkouts, environments without a matching
official installation receipt, and unsupported profile layouts. If the
installer reports a partial package update, keep the original data and
backup, and inspect the outcome before retrying. For independent data
recovery, see [Back up Flower data or move a project](DATA-BACKUP-AND-RECOVERY.md).

## Automatic upgrade for a dedicated macOS service

Use an installer-owned Flower 0.10.0 environment or a newer compatible release
with an initialized standard profile. Stop Flower servers in that environment.
Before registering the service, enroll its selected profile and endpoint, then
install and start it with these commands.

```sh
flower-mcp service enroll-upgrade --profile my-profile --profile-root /absolute/flower-data
flower-mcp service install --profile my-profile --profile-root /absolute/flower-data
flower-mcp service start --profile my-profile --profile-root /absolute/flower-data
```

Use the same host and port for all commands if you override the defaults.
Enrollment dedicates the Python environment to that profile. Use another
environment for other profiles. An existing installation receipt alone does
not enable automatic upgrades.

Open **Impostazioni Flower → Aggiornamento del servizio** in the local
dashboard. Review an exact newer stable version that supports managed upgrades
and confirm the request with your local password. Flower verifies the release
before stopping the service. A separate macOS job
blocks new starts, backs up SQLite and YAML, installs the package, and restarts
the same service. Sign in again after it returns to see the retained result.
If the connection drops, consult the receipt before trying again. The browser
does not submit the request again.

The local account owner can also submit or inspect the same operation from
the terminal:

```sh
flower-mcp service upgrade --profile my-profile --profile-root /absolute/flower-data --version X.Y.Z
flower-mcp service upgrade-status --profile my-profile --profile-root /absolute/flower-data
```

A failure before stop leaves the existing service running. A failure after
stop keeps the installation fenced and records the last phase and any verified
backup. Inspect that receipt and the retained backup before taking recovery
action. Flower does not force-stop another process, retry the operation or
restore the backup automatically. Use the manual upgrade procedure on
platforms without a qualified managed updater.
