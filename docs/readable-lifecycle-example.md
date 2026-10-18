# Reading Flower lifecycle references

Flower returns human-readable Markdown alongside the structured application
envelope. The structured channel retains machine types and canonical references.
The Markdown channel presents the same supplied facts as sections, records, lists
and shallow tables. An executable tool call remains explicit JSON so a host can
copy its arguments without guessing.

The readable-reference correction is source work after the immutable 0.6.1
release. It does not change existing release assets, update an installation or
rewrite previously generated artifacts.

## A roadmap the stakeholder can inspect

Use `fow_capabilities(view="operation", operation_tool="fow_bootstrap",
operation_name="roadmap")` for the current operation contract. Read the roadmap
for the selected milestone IDs, in their intended order. Its reference includes:

- Scenario details and relations, including ordered sequence steps.
- Complete supplied requirements and their revisions.
- Milestones with requirements realized by that work, prerequisite requirements,
  declared producers, entry/exit policies and recorded checks.
- Scoped stakeholder answers, correspondence and declared provenance.
- Draft intake outside the selected scope and unresolved obligations.
- The semantic fingerprint and the question asking the stakeholder to confirm
  that the roadmap represents the intended software.

An empty field is shown explicitly. Missing declarations remain gaps; readable
formatting does not resolve them. Scope confirmation, agent completion,
verification and human acceptance are separate events. A roadmap includes the
criteria actually supplied in its snapshot; packet-specific PVP declarations
belong to the packet's external plan.

## Record correspondence without dropping empty reference lists

This is a schema-shaped example, **not a receipt or an instruction to execute
placeholder IDs**. Replace the project/bootstrap/requirement IDs with values
returned by your Flower instance, and use the current recorded answer revision.
First inspect `record_correspondence` operation help.

```json
{
  "tool": "fow_bootstrap",
  "arguments": {
    "project_id": "replace-with-project-id",
    "operation": "record_correspondence",
    "actor": "external-engineer",
    "bootstrap_id": "replace-with-bootstrap-id",
    "request_id": "replace-with-unique-request-id",
    "correspondence": {
      "answer_key": "export-scenario",
      "answer_revision": 1,
      "canonical_references": {
        "requirement_ids": ["replace-with-current-requirement-id"],
        "goal_node_ids": [],
        "milestone_ids": []
      },
      "disposition": "consistent",
      "rationale": "The referenced requirement expresses this recorded scenario."
    }
  }
}
```

All three reference lists are required, including empty lists. At least one list
must contain a current canonical reference. A successful call records the
engineer's declared correspondence; it does not independently certify that
judgment. Replaying a mutation uses the same request identity, actor and contents.

## Keep the complete reference outside Flower

Generated SRS, use-case and sequence artifacts contain readable scenario blocks
and physical Markdown paragraphs. Retrieve the actual generated artifact rather
than reconstructing it from a tool preview. A new generation receives its normal
content digest; an earlier artifact or replay remains historical evidence.

For implementation, export the external-agent plan through the existing
`fow_external_work` `export_plan` operation. Save its complete returned Markdown
with the host's file tools. That plan carries packet authority, producer/consumer
contracts, unit-local checks, deferred verification and the exact offline report
contract. It remains readable while Flower is offline. Retain outcomes and
evidence locally, then explicitly reconcile them when Flower returns; editing
the exported document never mutates lifecycle authority.
