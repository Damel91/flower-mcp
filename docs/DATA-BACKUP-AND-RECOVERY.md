# Back up Flower data or move a project

Use **Backup** in the local dashboard to create and manage saved database
backups. Download a copy and keep it somewhere private, preferably on a
different disk. Use **Esporta progetto** on a project overview when you want
to transfer that project alone. An archive contains Flower's SQLite data,
including retained evidence and history. It can contain sensitive information.

A full backup includes all projects and SQLite ledger state. A project export
includes the selected project's lifecycle records, including original IDs,
revision history, evidence and receipts. Project transfer omits chat
selections and lens state. Neither archive copies profile
settings, credentials, client registrations, repository files, local import
files or provider storage. Recorded external links can require reconciliation
on the destination.

## Import a project into the current database

Send the ZIP from **Esporta progetto** to the recipient. In their Flower
dashboard, open **Progetti → Importa progetto** and select that ZIP. Flower
adds the project to the database already open in the dashboard and opens
the imported project. If its ID is taken, Flower picks the first available
suffix such as `-2` or `-3`. A new successful upload can create another
copy. After an interrupted response, check the project list before retrying.

Flower maps internal IDs to keep evidence and history linked in the
destination and preserves the original receipt material and provenance.
Use a trusted archive. The ZIP digest detects damage; the recipient decides
whether to trust the sender. External resources and a sender's live
execution authority do not move with the project. A full backup uses the
separate recovery action.

If a project archive still carries unfinished execution or packet/test
provider dispatch records, use separate-database recovery. Adding that
archive to a running database would require reconciling its external work.

## Restore from the dashboard

Open **Backup → Ripristina in un altro database**. Choose a Flower backup or
single-project export from your device and enter the name of the new database.
Flower validates the archive and places the recovered data in the installation's
profiles directory with a separate startup configuration. It refuses an
existing name and leaves the recovered database inactive.

## Terminal workflow

For a profile that is stopped, the CLI can also create an archive directly.
Choose a new filename in an existing private directory:

```sh
flower-mcp data backup --config /path/to/flower.yaml --output /private/backups/flower.flower.zip
flower-mcp data export --config /path/to/flower.yaml --project-id my-project --output /private/backups/my-project.flower.zip
```

Inspect the archive and restore it to an unused directory under an existing
private parent. These commands accept archives in the Flower archive v1 format
with supported schema 55 or 56. Use archives from a trusted source;
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
