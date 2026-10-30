# Flower architecture retrospective source audit v1

**Status:** bounded development/owner-recovery contract, not an MCP operation
**Scope:** explicit owner recovery of a retained malformed070 architecture proposal; no replay

Inputs match the existing packet-start assessor CLI: --wheel, --package-root,
--request-json (retained original {tool,arguments}), --expected-request-sha256,
--project-id, --request-id, --database, --association-reference. The owner binds
the retained original invocation to the original package/ledger; this association
is explicitly owner_declared, not independently observed historical execution.

Supported producer only070/ae96517e34f8c0b622249f22667f8f3471128dc4,
wheelSHA60d48ddc702b662e53115698bbf2c603b124461980571e2f9251abeb950ee0d0.
Compare complete package source/resource inventory against the wheel, excluding
bytecode. Never import/execute Flower. Original tool=fow_architecture,
operation=propose, canonical project/request and nonempty actor; payload has exactly
definition/expected_revision, nonnegative SQLite integer expected_revision;
definition has exactly components/interfaces/decisions arrays. At least one
component object has a boundaries value of string type. This pinned pure validator
always rejects before _transaction. Other malformed/supported inputs are not
automatically certifiable. Reject duplicate/nonfinite JSON and mismatched digests.

Open existing SQLite mode=ro/query_only in one coherent read transaction. Require
schema55 and existing project. Count architecture_requests and requirement_events
with exact request ID or colon-derived identity in that project. Any matching
history refuses certification, even if unrelated payload reused the ID. Absence
only corroborates pinned source proof. No WAL-unsafe file hash is a snapshot proof.

Success schema: contract_version=flow.architecture-source-audit.v1, status=assessed,
basis=retrospective_source_audit, original_request={tool,operation,project_id,
request_id,arguments_sha256}, retained_request_sha256, original_effect_state=unknown,
historical_result_rewritten=false, recovery_resolution={effect_state:none,
mutation_started:false}, producer={distribution_version:0.7.0,source_commit,
wheel_sha256,package_files_sha256}, ledger={project_id,database_locator_sha256,
architecture_request_matches:0,requirement_event_request_matches:0,read_only:true},
provenance={original_execution_association:owner_declared,association_reference},
limits=[retrospective assessment, owner-declared association, absence corroborative
only, no other requests/transport outcomes covered]. Never emit effect_receipt.

Refusal: contract_version, status=refused, effect_state=unknown, bounded reason;
no recovery_resolution/effect_receipt; CLI exits2 (success0). Missing/wrong input,
artifact/inventory/project/schema/history or provenance refuses. Consumer checks
all pins, exact request/arguments digests and explicit owner linkage before its
separate recovery record; original unknown/transcript remain immutable. This
assessment authorizes neither execution nor a different request.

## Running the local assessment

Use the two helper files from the same tagged source archive, not files from
an unrelated checkout: `tools/audit_architecture_rejection.py` and its sibling
`tools/audit_packet_start_rejection.py`. The helpers are source-archive tools,
not a new MCP route or wheel entry point. Retain the original070 package and
wheel; verify their identity and the original invocation association yourself.
The consumer must pin both helpers before trusting the output.

```sh
python3 -I tools/audit_architecture_rejection.py \
  --wheel /absolute/flow_of_work_mcp-0.7.0-py3-none-any.whl \
  --package-root /absolute/original/flow_of_work_mcp \
  --request-json /absolute/retained-original-request.json \
  --expected-request-sha256 ORIGINAL_REQUEST_FILE_SHA256 \
  --project-id ORIGINAL_PROJECT --request-id ORIGINAL_REQUEST_ID \
  --database /absolute/original/ledger.sqlite3 \
  --association-reference owner:retained-invocation-and-original-install
```

Windows can use `py -3 -I` with the same arguments. The assessor opens the existing
ledger read-only; it does not launch Flower, infer acceptance, execute a validator
through a service, or submit either proposal. Refusal exits2 and keeps uncertainty.
A successful assessment remains a separate owner-attributed recovery observation;
review its exact correlation before recording it in your client. Never replace
an uncertain historical response with a newly fabricated no-effect receipt.
