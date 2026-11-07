# Back up Flower data or move a project

Use **Backup** in the local dashboard to create and manage saved database
backups. Download a copy and keep it somewhere private, preferably on a
different disk. Use **Esporta progetto** on a project overview when you want
to transfer that project alone. An archive contains Flower's SQLite data,
including retained evidence and history. It can contain sensitive information.

A full backup includes all projects and SQLite ledger state. A project export
includes the selected project's lifecycle records, including existing IDs,
revision history, evidence and receipts. The new profile does not inherit chat
selections or lens state from a project export. Neither archive copies profile
settings, credentials, client registrations, repository files, local import
files or provider storage. Recorded external links can require reconciliation
on the destination.

## Restore from the dashboard

Open **Backup → Ripristina archivio**. Choose a Flower backup or
single-project export from your device and enter the name of a new profile.
Flower validates the archive and places the recovered data in the installation's
profiles directory. It refuses an existing name and leaves the new profile
inactive. Use a trusted archive. Its digest detects damage, while the source
of the file remains your responsibility.

## Terminal workflow

For a profile that is stopped, the CLI can also create an archive directly.
Choose a new filename in an existing private directory:

```sh
flower-mcp data backup --config /path/to/flower.yaml --output /private/backups/flower.flower.zip
flower-mcp data export --config /path/to/flower.yaml --project-id my-project --output /private/backups/my-project.flower.zip
```

Inspect the archive and restore it to an unused directory under an existing
private parent. These commands accept archives in the Flower archive v1 format
with the supported schema55 ledger. Use archives from a trusted source;
the digest detects corruption and does not authenticate the sender.

```sh
flower-mcp data inspect --archive /private/backups/my-project.flower.zip
flower-mcp data restore --archive /private/backups/my-project.flower.zip --restore-dir /private/profiles/recovered-project
```

Flower creates a new core configuration and keeps the original profile
untouched. An existing destination, even an empty one, is refused. The command
does not start Flower or register a client. Choose a free port when opening the
recovered profile beside a running instance:

```sh
flower-mcp serve --config /private/profiles/recovered-project/flower.yaml --transport streamable-http --port 8011
```

If you want the installed upgrade command to select the new profile by name,
choose its unused directory under the standard profile root’s `profiles` folder.

Review any interrupted work and external provider references in the recovered
profile before configuring integrations. A backup does not transfer ownership
of work running in another system. If restoration is interrupted during
publication, inspect the new directory and use another unused destination for
a retry. Dashboard deletion affects only the selected retained backup; copies
you downloaded are independent.
