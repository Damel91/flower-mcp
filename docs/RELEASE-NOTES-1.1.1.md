# Flower MCP 1.1.1

## Deferred milestone verification

When a milestone's applicable packets use external-agent execution, Flower
reconciles explicitly linked, current campaign proof with the corresponding
deferred verification. A missing, stale or ineligible result leaves the
obligation pending. Proof requirements and the separate stakeholder acceptance
decision still apply. Historical receipts keep their original source and
provenance. [Engineering cycle](ENGINEERING-CYCLE.md)

## Install or upgrade

For a 1.1.0 installation, use the same environment and profile. The installer
backs up SQLite and the profile YAML before updating the package. Both releases
use schema 56. After restarting Flower, reopen the existing project and inspect
its current milestone. [Upgrade guide](UPGRADING.md#preparing-a-111-upgrade)
