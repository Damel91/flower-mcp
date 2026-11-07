# Flower MCP 0.13.0

Flower makes the next recovery action explicit when an issued unit has a
retained outcome on an earlier authority fingerprint.

- MCP and the dashboard surface historical outcome recovery before further
  execution on the same issued work. Original reports retain their pin.
  [Dashboard guide](DASHBOARD.md)
- Replaying an external outcome distinguishes the original receipt from
  applicability to current authority. Repeated delivery preserves the
  report identity. [Dashboard and recovery guide](DASHBOARD.md)
- The dashboard separates campaign, direct requirement, unit report and
  repository review evidence. Failed verification actions expose the retained
  proof and explicitly linked exception scope. [Inspect a project](DASHBOARD.md#inspect-a-project)
- Upgrade the stopped instance with the existing installer. SQLite stays on
  schema 55 and the installer retains the selected profile and settings.
  [Upgrade guide](UPGRADING.md#preparing-a-0130-upgrade)
