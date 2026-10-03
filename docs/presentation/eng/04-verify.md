# 4. Verify: green against which question?

[Previous: Build](03-build.md) · [Index](README.md) · [Next: Deploy](05-deploy.md)

> "All tests pass. Can we say double bookings are solved?"

## The happy path is not concurrency

One request succeeds. A second request, arriving later, is rejected. That test
is useful, but it does not check two simultaneous requests. A service test also
does not demonstrate that the interface displays the right outcome when the
connection drops after confirmation.

The agent must create and run checks that address the agreed behaviors. Flower
preserves obligations, results and links; it does not make an irrelevant test
appropriate just because its exit code is zero.

## An honest view of progress

| Dimension | Example in the story | What it does not imply |
| --- | --- | --- |
| Implementation | Service and interface are declared produced. | That they are correct or accepted. |
| Local verification | The unit's available checks have declared outcomes and references. | That a campaign on the real system was executed. |
| Deferred verification | A complete check in the target environment remains open. | An implicit failure or automatic promotion to pass. |
| Acceptance | The competent authority makes the required decision with appropriate evidence. | That a completion percentage was enough. |

Derived progress concerns selected criteria and scope. A missing denominator
does not become "100%." Evidence from an older plan is not used as though it
unconditionally verifies the current one.

## A campaign, not just a test command

The agent can structure cases, obligations, expected responses and oracle
sources: simultaneous requests, cancellation, permissions and lost responses.
Flower provides campaign authoring, advancement and inspection; technical
execution and attestation depend on the available path and prerequisites.

Optional semantic analysis can help: `fow_semantic` prepares bounded SRS or
grounding assignments, including host-executed ones. A structurally valid
response is not universal proof. Adoption records an audit with provenance,
not automatic product acceptance.

## The problem behind the mechanism

"Verified," "completed" and "accepted" are too convenient unless we say by
whom, with which data and at which revision. Keeping them distinct preserves
what we know and makes what we do not know visible.

## On the public surface

`fow_campaign_author`, `fow_campaign_advance` and `fow_campaign_inspect` manage
campaigns; `fow_record_verification`, `fow_traceability` and `fow_assurance`
record evidence and decisions. Operations requiring a provider or model are
not presented as available when those prerequisites are missing.

**Question for the audience:** if we read "100%," can we also identify which
questions have not been verified yet?

[More: three meanings of done](concepts.md#three-meanings-of-done) · [Chapter sources](sources.md#verify)

[Previous: Build](03-build.md) · [Index](README.md) · [Next: Deploy](05-deploy.md)
