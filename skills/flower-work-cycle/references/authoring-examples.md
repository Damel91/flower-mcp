# Authoring examples

## Classify and verify two criteria

- Criterion 1, implementation. Returning the next integer is the job of the
  `increment` unit. In one plan revision give that unit `implements: [1]` and
  a `unit_check` in `verifies` for criterion 1. Use
  `unit_checks_from_verifies: true` on the supported external authoring route.
- Criterion 2, verification only. A real client must observe the same result.
  Target criterion 1. Give the verifier a dependency on `increment` and a
  `live_campaign` verification for criterion 2. Preserve that later obligation
  when the implementation becomes executable.
- Classify the current criterion numbers after the plan is drafted, review the
  scoped PVP result, then use the current gate and revisions.

## OpenCode CodeMode

Prefer Flower's native Markdown when the host exposes it. If a CodeMode wrapper
exposes the structured result instead, its envelope is at `reply.result` and
the result body is at `reply.result.result`. Return a short Markdown summary to
the model. For example, after an exact architecture-help call:

```javascript
const reply = await tools.flower.fow_capabilities({
  view: "operation", operation_tool: "fow_architecture", operation_name: "propose",
});
const contract = reply.result.result.operation_contract;
const kinds = contract.accepted_values["payload.definition.interfaces[].kind"];
return "### Interface kinds\n" + kinds.map(kind => "- " + kind).join("\n");
```

On a rejection, keep the scoped field, received and expected values, original
request, effect state and continuation in that Markdown. Preserve the full
machine receipt where the host can retain it.
