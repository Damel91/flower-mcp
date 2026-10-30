# Flower packet revision retrospective source audit v1

**Status:** bounded local owner-recovery contract, not an MCP operation
**Scope:** owner reconciliation of the supported retained 0.7.1 packet revision; no replay

## 1. Supported source conclusion
Pin only official071/f77be7f699eae4a89598f36c86711232d6dbf558 and wheelSHA
36151d37b67fc5b10d1325b7c1f42496ae1bdac90a5b54b689f27970e1348ff5.
071 packet author can repair lifecycle BEFORE rejecting malformed refs in
ImplementationPacketDraft. The requested semantic refinement is never dispatched
for supported malformed {id,kind} refs, but ancillary writes cannot be ruled out
by absent request events. Construction refresh can write without those events;
refresh and readiness can also be no-ops. No universal applied/none theorem.

## 2. Inputs and owner association
Required CLI: --wheel, --package-root, --request-json, --expected-request-sha256,
--project-id, --change-id, --packet-id, --request-id, --database,
--before-snapshot-json, --expected-before-snapshot-sha256, --association-reference.
Original request is retained {tool,arguments}; require fow_packet_author,
operation=revise_packet, expected canonical project/packet/request, nonempty actor,
optional matching change_id, allowed revision fields and malformed refs where at
least one object has exactly {id,kind} with supported kind/nonempty id. Other
arguments must be in the original public revise contract and pass basic shape;
unknown/ambiguous/nonfinite JSON or unsupported paths refuse. No validator or
Flower mutation is imported or executed. Compare entire package inventory to
pinned wheel using the shared sibling verifier. Consumer pins both helper files.

Before snapshot is the retained owner full preservation JSON with ledger table
arrays. Its exact file digest binds it; only the five supported tables below are
read/endorsed. Additional tables/metadata are ignored by this assessor, not
certified. Check schema55 table column layout against frozen source hashes and
same project/change/packet present before and currently. Association of retained
input, snapshot, original executable and current ledger remains owner_declared.

## 3. Coherent read-only ledger and bounded witness
Open existing SQLite mode=ro/query_only in one read transaction. Allow only
schema_migrations, projects, implementation_packets, implementation_packet_revisions,
change_events. Verify schema55 and exact column layouts; no migration/init/writes.
Any original/colon-derived packet_revised in project refuses the not-applied
assessment. Correlated changes for foreign change/packet/actor refuse association.
Current packet full-row canonical SHA and spec/state/current revisions are observed,
not acceptance or a claim that current intent is verified.

A maintenance witness is optional. Only an exact single packet_readiness_evaluated
with request_id ORIGINAL:repair:readiness, matching project/change/packet and actor,
absent in before snapshot, can support ancillary_effect_state=applied. Require a
unique implementation_packet_revisions row for that packet with same actor and
created_at=event.occurred_at, absent before, lifecycle revision newer than before
packet current_revision. Exact event payload fields readiness_state,target_policy,
readiness_blockers,navigation_audit_ids,target_binding_ids must equal the joined
row (JSON lists decoded); no semantic revision event may exist. Hash event payload
and joined full revision row. Missing/ambiguous/mismatched witness refuses when a
candidate is present; no candidate yields ancillary_effect_state=unknown. Never
infer none. This proves at least one recorded maintenance effect, not complete
attribution of all ancillary work. It is not U6/global/provider quiescence.

## 4. Result schema
contract_version=flow.packet-revision-source-audit.v1; status=assessed;
basis=retrospective_source_audit; original_request={tool,operation,project_id,
change_id,packet_id,request_id,arguments_sha256}; retained_request_sha256;
before_snapshot_sha256; original_effect_state=unknown; historical_result_rewritten=false;
requested_revision_applied=false; ancillary_effect_state=applied|unknown;
ancillary_effects_complete=false; maintenance_witness=null or {event_id,request_id,
actor,occurred_at,lifecycle_revision,payload_sha256,revision_row_sha256};
current_packet={spec_revision,state_revision,current_revision,packet_row_sha256};
producer={distribution_version:0.7.1,source_commit,wheel_sha256,package_files_sha256};
ledger={project_id,change_id,packet_id,database_locator_sha256,read_only:true,
requested_revision_event_matches:0}; provenance={original_execution_association:
owner_declared,association_reference}; limits explicitly retain narrow scope and
uncertainty. NO effect_receipt, NO recovery_resolution, NO invocation-wide none.
Refusal: contract_version,status=refused,effect_state=unknown,reason; no positive
conclusion/witness. Exit0 assessed,2 refused.

## 5. Consumer adoption boundary
This is never ordinary flow.operation-effect.v1 no-effect evidence. Native owner
recovery requires original complete request/turn, retained before/current snapshots,
exact pins/digests and an explicit current-state reconciliation. An applied witness
may support failed/applied maintenance while requested_revision_applied remains
false and original unknown is retained as annotation. Unknown/no-witness cannot
be promoted to applied or none or silently clear pending-effect barriers. Preserve
all other operations, current authority gates and user work. No retry, confirmation,
human acceptance, repair deletion or original transcript rewrite is authorized.

## 6. Frozen layout and canonicalization
Column layout digest is SHA256 of canonical JSON ordered column-name array from
schema55 PRAGMA table_info, UTF-8/ensure_ascii=false/sort_keys=true/separators
comma-colon/no NaN. Original071 schemaDDL is unchanged from owned schema55.
Before arrays must have exactly that column count and are mapped by those frozen
names; current PRAGMA layout must match before reading rows. Row digests use the
same canonical JSON of a column-name/value object, including exact JSON-text
column bytes as strings (do not reformat inner JSON). Witness payload digest uses
the parsed five-field payload under the same canonicalization. List order stays
significant. Duplicate/nonfinite/malformed snapshot JSON, mismatched layouts/row
lengths or input hash refuse. Bound original request1MiB and before snapshot64MiB.

| Table | Ordered column-name SHA256 |
| --- | --- |
| schema_migrations | bc984f79f76fde4c00f58433a9a98d2b40d64547c5a2cef60dabb7df08c2a946 |
| projects | f4bd9bbb71deb24b5c2e3504f87b965f0feed113714b11d3d66b96c0ab9b735e |
| implementation_packets | 8ee6d2c582f51db839bab3e00948bfea9547984750c9de58b27c888ec3f489c5 |
| implementation_packet_revisions | 4df62187fbb6f62bcb84d3d93a936c91bd7f93f068e7a3e70e4ca8167e0c65a4 |
| change_events | 51899662e6a3c08831c76b626c50be13f27d52dd7603dfbf3e48434dbd7b7b8b |

## Running the local assessment

Extract the two helpers from the same tagged 0.7.2 source archive:
`tools/audit_packet_revision_rejection.py` and its unchanged sibling
`tools/audit_packet_start_rejection.py`. These are source-archive owner tools,
not wheel entry points or public MCP operations. Pin both files before consuming
their output. Retain the original 0.7.1 wheel, installed package, original request
and before snapshot. The owner must establish their association with the original
invocation; this association remains declared provenance.

```sh
python3 -I tools/audit_packet_revision_rejection.py \
  --wheel /absolute/flow_of_work_mcp-0.7.1-py3-none-any.whl \
  --package-root /absolute/original/flow_of_work_mcp \
  --request-json /absolute/retained-original-request.json \
  --expected-request-sha256 ORIGINAL_REQUEST_FILE_SHA256 \
  --project-id ORIGINAL_PROJECT --change-id ORIGINAL_CHANGE \
  --packet-id ORIGINAL_PACKET --request-id ORIGINAL_REQUEST_ID \
  --database /absolute/original/ledger.sqlite3 \
  --before-snapshot-json /absolute/retained-before-snapshot.json \
  --expected-before-snapshot-sha256 BEFORE_SNAPSHOT_FILE_SHA256 \
  --association-reference owner:retained-invocation-original-install-and-snapshot
```

Windows can use `py -3 -I` with the same arguments. The assessor only reads the
existing ledger. It does not initialize a database, import Flower, replay work,
change client recovery state or infer acceptance. A refusal exits 2.

The owner must explicitly reconcile the complete retained turn and current state
before a separate client recovery record. A witnessed maintenance effect is not
the requested semantic revision, and does not account for every possible repair.
Without a valid witness the ancillary state remains unknown. Preserve the original
unknown response, other operations, current gates and user work in either case.
