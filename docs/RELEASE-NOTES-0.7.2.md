# Flower MCP 0.7.2

Packet architecture references now expose their exact nested shape:
`revision`, `kind` and `entity_id`. Malformed references are rejected with a
correlated no-mutation proof before packet lifecycle repair can start. Omitted
references retain their meaning; an empty list clears them. Errors after repair
or dispatch remain uncertain and never erase earlier effects.

Read-only external-work views preserve roadmap confirmation gates without
misreporting them as uncertain mutations. Unexpected read failures have a bounded
read diagnostic and exact-operation guidance. No gate is bypassed.

A separate [packet revision recovery guide](PACKET-REVISION-RECOVERY.md) and
source-archive assessor support owner investigation of the retained malformed
0.7.1 revision. The requested revision was not dispatched on that supported path,
but earlier lifecycle repair may have written maintenance state. A strictly joined
readiness record can attest that maintenance occurred; it never proves complete
attribution or invocation-wide absence of effects. The original unknown response
is retained. Client reconciliation remains an explicit owner action.

## Upgrade

Use the [ordinary upgrade](UPGRADING.md#preparing-a-072-upgrade), retaining the
existing environment, profile, SQLite database, YAML and client configuration.
The installer backs up SQLite and YAML before pip and rejects active owners.
Schema 55, dependencies and installer behavior are unchanged; no data migration
or project reset is needed. Updating code does not replay or recover an uncertain
historical operation automatically.

## Verification boundary

Focused schema, preflight, prior-effect, read-gate and historical-assessment
regressions, independent severe review and public MCP verification cover the
changed source and installed surface. Release CI gates the exact packages.
Historical fixture mechanics and native owner reconciliation remain distinct;
no new upgrade campaign, model usability, witness U6 or human acceptance is claimed.
