# Flower MCP 0.7.1

Architecture proposals/adoptions rejected during pure structural validation now
carry an explicit, correlated proof that the invocation started no mutation.
The diagnostic names the invalid field and links its exact operation contract.
Errors during/after dispatch, rollback and lost responses remain uncertain;
a rejection never erases earlier effects under the same request identity.

A separate source-archive utility supports read-only owner assessment of the
retained0.7.0 malformed-boundaries proposal. It pins original artifact/input bytes,
requires explicit owner association and corroborating SQLite reads, preserves the
original unknown response, and never replays the failed or corrected proposal.
See [architecture recovery](ARCHITECTURE-RECOVERY.md).

## Upgrade

Use the [ordinary upgrade](UPGRADING.md#preparing-a-071-upgrade). Keep the existing
environment, profile, SQLite database, YAML and client configuration; the existing
installer creates a consistent backup before changing packages and rejects active
owners. SQLite remains schema55; no migration, dependency change or installer
behavior change is introduced. Installation does not itself recover an uncertain
client request. Older releases, evidence and human acceptance remain separate.

## Verification boundary

Focused rejection/replay/conflict/rollback tests, independent severe review and
public MCP checks cover the changed source and installed surface. Existing
release CI gates the exact packages; no new broad lifecycle or upgrade campaign
is claimed. Native client recovery/adoption belongs to its owner.
