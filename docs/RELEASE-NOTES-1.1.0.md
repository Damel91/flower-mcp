# Flower MCP 1.1.0

## Share a project

Export a project from its overview and send the ZIP to another Flower owner.
The recipient opens **Progetti → Importa progetto** and selects the ZIP.
Flower adds the project to the current database, retains its history and
evidence and preserves the original receipt material. If the project ID is
already in use, Flower chooses the first available suffix, such as `-2`.
A full backup still has a separate recovery action. [Backup and recovery](DATA-BACKUP-AND-RECOVERY.md)

The dashboard sidebar shows the version of the Flower server it is connected to.

## Update when ready

The dashboard update action is available to the owner of a supported official
installation on macOS, including when Flower is started manually. It reviews
the selected release and uses the existing backed-up installer. After a
manual update, reopen Flower with your usual launcher. The optional managed
service retains its own restart path. [Dashboard guide](DASHBOARD.md)

## Install or upgrade

The first start of 1.1.0 adds three import metadata tables and advances the
SQLite schema from 55 to 56. The existing installer backs up SQLite and the
profile YAML before pip. Keep the same selected database, configuration and
client settings. Flower 1.1.0 can read project archives made by 1.0.0.
[Upgrade guide](UPGRADING.md)
