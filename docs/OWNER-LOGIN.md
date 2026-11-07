# Local owner login and optional startup

Flower 0.14.0 uses native account verification for its local dashboard. The
operating system account that owns the selected profile signs in with its local
password. The optional per-user startup commands select the same profile.

Native verification and the LaunchAgent lifecycle were exercised on an isolated
macOS 26.6.2 arm64 fixture. Linux and Windows have separate account and policy
prerequisites, and their native authentication and startup qualification remain
pending.

## Which account can sign in

Use the local operating-system account that owns **both** the selected Flower
YAML configuration and SQLite database. Flower must run normally under that same
account. A Flower profile, such as `management`, selects configuration and data;
it is not another user account. Another valid local user is not authorized to
open that profile.

Flower checks stable OS identity and file ownership, not just the displayed
username. Changed, mismatched, unsafe or unsupported ownership blocks dashboard
access. Do not change ownership, run Flower as root/Administrator or disable an
OS account policy to make a login succeed. Browser authentication does not change
permissions on SQLite or isolate data from the owning OS account's existing file
access.

The first supported account scope is:

| System | Native verification and prerequisites | Scope boundaries |
| --- | --- | --- |
| Linux | System Linux-PAM, an explicitly installed and reviewed `flower-mcp` PAM policy, and a matching local account record | The native distro/policy/helper combination needs its own qualification; no arbitrary fallback policy or shadow-file access |
| macOS | System Open Directory/CoreFoundation and a local user record matching the data owner's UID | Use the local account password; Apple ID/network-directory authentication, Touch ID and password changes are not provided |
| Windows | System local-account APIs, local SAM account and matching owner/token user SID | Use a normal non-elevated local password account; domain/cloud-linked accounts, domain controllers, Windows Hello PIN and biometrics are outside this increment |

A missing policy/library, unsupported account type, denied OS restriction or
native timeout is an unavailable or denied login, never anonymous access.
Core/stdio operation and existing MCP authentication remain independent of the
browser verifier.

## Open the dashboard manually

Keep the same selected environment and configuration. Stop its current owner
before changing transport; a second process cannot share the same runtime lease.
Use the installed command:

```sh
flower-mcp serve --config "/absolute/path/flower.yaml" --transport streamable-http --host 127.0.0.1 --port 8010
```

Open `http://127.0.0.1:8010/dashboard`, or the stable local address printed by your
chosen instance. Enter your local username and password into the browser form.
Enter passwords **only** in that form: do not put them in CLI arguments, chat,
configuration, scripts, environment variables or diagnostic receipts. Flower does
not persist them in SQLite, files or browser storage. The input clears after a
completed attempt; a failed attempt is not resubmitted automatically.

The browser offers the same system/light/dark appearance as the workspace. A
successful login opens the selected profile's projects. Dashboard deletion
requires the exact project ID and fresh confirmation with the local owner's
password. See the
[dashboard guide](DASHBOARD.md#delete-a-project).

Use **Esci** to revoke the session. Flower requires both the session cookie and
the current page's sign-in proof. Opening, reloading or restoring a tab requires
a fresh sign-in even when the browser restores the cookie. The latest successful
sign-in on the same origin replaces the prior cookie. The bounded session store
can revoke its oldest entry and reports that fact.

The LAN dashboard uses HTTPS and the same owner verification. Enable LAN
access in **Impostazioni Flower** and restart the selected profile. Use the
hostname link or one of the IPv4 links that Flower prints.
[LAN access guide](REMOTE-DASHBOARD.md)

## Recover a connection or an interrupted action

If Flower is unavailable, restore the selected process and use the connection
retry control. After a restart or revoked session, sign in again. Request-CSRF
state refreshes automatically; it is not a password or a user-entered access key.

Logout and connection loss do not cancel or undo an admitted deletion. Flower
retains the nonsecret intent reference. After signing in again, inspect the
existing intent and its current maintenance state before any destructive retry.
Use explicit inspection or reconciliation; do not create a new deletion merely
because the previous response was missing. The browser never replays a password
or destructive POST for you.

Too many attempts or an already active native verification produces retry
guidance. Honor that guidance and OS lockout policies. Do not test repeated bad
passwords against the operator's real account to diagnose an installation.

## Prepare native authentication

### Linux

An administrator must explicitly install a reviewed, distro-appropriate policy
named `/etc/pam.d/flower-mcp`. The policy and its directory must be trusted,
root-owned and not writable by other users; it must define both authentication
and account checks. Use the target distribution's normal local password/account
policy, including its restrictions and expiry behavior. There is no universally
qualified policy template for every Linux distribution in this increment.

Pip, normal startup and `doctor` do not install or rewrite PAM policy. Flower does
not fall back to `login`, `sudo` or `other`, read `/etc/shadow`, call the distro
password helper directly or install its own privileged helper. A policy path
that is missing, unsafe or changes during verification cannot authorize access.

The distro's `pam_unix` helper must work in the actual launch context. Inherited
`no_new_privs`, a `nosuid` mount or container restrictions can prevent it from
working. Report that restriction as unavailable; do not remove the restriction
or grant shadow-group access as an automatic repair. Native qualification must
name the exact distro, policy, account type and any managed-service restrictions.

### macOS

Use a local Open Directory user account and a process running under that same
normal owner identity. The system frameworks are loaded only when needed.
Configuration and database ownership must agree. Password verification and
account-policy checks use the native record; an available framework alone is not
proof of successful password authentication.

No `sudo`/`dscl` password command, copied Keychain password or privileged daemon
is needed by this implementation. If the local record or native account policy
is unavailable, use normal OS account management and the documented qualification
recipe; do not put an operator's password into diagnostics.

### Windows

Run from a normal, non-elevated owner session using a local password account.
The selected configuration and database require coherent owner user SIDs and
native security metadata access. File owner groups or system/service identities
are not user authorization. The verifier checks local-account classification,
password logon and the returned token's user SID.

Native account restrictions remain effective, including denied network-logon
rights, disabled/locked accounts and password-change requirements. A desktop PIN
is not the account password. Unsupported domain, cloud-linked or domain-controller
identity must be reported explicitly; a matching SID alone is insufficient.
Actual Windows account and policy qualification remains pending with its owner.

## Optional managed startup

Manual `serve` remains available and is independent of login. Service management
is an explicit opt-in, per-user HTTP startup path; installing the package or
opening the dashboard does not enable it.

Use the same configuration, executable environment, loopback host and port on
**every** service operation. These values identify the owned registration. The
examples below retain the illustrative port8010; use your existing endpoint when
managing an existing instance. Profile selection can instead use the existing
`--profile` and `--profile-root`. Do not combine explicit `--config` with
`--profile-root`.

```sh
flower-mcp service plan --config "/absolute/path/flower.yaml" --host 127.0.0.1 --port 8010
flower-mcp service install --config "/absolute/path/flower.yaml" --host 127.0.0.1 --port 8010
flower-mcp service start --config "/absolute/path/flower.yaml" --host 127.0.0.1 --port 8010
flower-mcp service status --config "/absolute/path/flower.yaml" --host 127.0.0.1 --port 8010
```

| Operation | Effect |
| --- | --- |
| `plan` | Read-only selection and command preview; no start or registration |
| `install` | Write/register only owned, disabled management artifacts; do not start Flower |
| `start` | Explicitly start this owned instance, preserving the same data and OS lease |
| `enable` | Enable later owner-sign-in startup; do not start the current process |
| `disable` | Disable later owner-sign-in startup; do not stop an already running process |
| `stop` | Persistently pause the managed runner and request graceful shutdown; retain registration |
| `status` | Report selected registration, pause, process and readiness facts |
| `remove` | Gracefully stop and remove only owned registration/definition; retain profile, SQLite, evidence and logs |

For later owner-sign-in startup, choose it explicitly:

```sh
flower-mcp service enable --config "/absolute/path/flower.yaml" --host 127.0.0.1 --port 8010
```

Use the same command with `disable`, `stop` or `remove` for those actions. A stopped
registration can retain `autostart_enabled: true` while `paused: true`; the pause
prevents its runner from starting Flower. Explicit `start` clears that pause.
Explicit `enable` also clears it so a later sign-in can start Flower. Ordinary
package upgrade does not make either choice for you.

The native forms are a systemd **user** service on Linux, a user LaunchAgent on
macOS and an owner sign-in task on Windows. The Windows task uses the owner's
interactive token, requires that account to be signed in and stores no task
password. It is not a pre-login SCM service. Automatic systemd linger, root/
LocalSystem execution and socket activation are outside this increment. No client
configuration is silently changed from stdio to HTTP.

Stop pauses the owned runner before requesting shutdown through its protected
local control state. It waits for the owned process, runner and ledger lease to
settle for up to 30 seconds. A timeout remains blocked/paused; Flower does not force
Task Scheduler termination or report an uncertain stop as success. Inspect the
same registration before retrying or upgrading. Unknown or user-edited native
service definitions are not overwritten.

## Upgrade or return to manual startup

Stop the managed instance before running an ordinary backup-first installer
upgrade. Use `service status` to inspect its state and retain the same profile,
database, YAML and client configuration. After the upgrade, choose explicit
`service start` or use `service remove` and continue with manual `serve` against
the same data.

The [operator upgrade guide](OPERATOR-UPGRADE.md) describes both the manual
command and automatic upgrades for dedicated, enrolled macOS services.
