# Flower MCP 0.14.0

- Dashboard project deletion asks for the project ID and the local owner's
  password. Flower handles SQLite maintenance during the request. The browser
  path skips external run checks and creates no deletion journal or archive.
  [Dashboard guide](DASHBOARD.md#delete-a-project)
- **Backup → Ripristina archivio** restores either a full Flower backup or a
  single-project archive from the browser. Select a ZIP and choose a new
  profile name. The recovered profile is left inactive and the current profile
  stays intact. [Backup and recovery guide](DATA-BACKUP-AND-RECOVERY.md#restore-from-the-dashboard)
- Stop the running instance before upgrading with the release installer.
  Schema 55 is unchanged and the installer backs up SQLite and the profile
  configuration before changing the package. [Upgrade guide](UPGRADING.md)
