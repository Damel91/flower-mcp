# Flower MCP 0.6.5

Guided bootstrap now returns an operational continuation instead of repeatedly
rendering complete answers and cumulative audit payloads. Ordinary guided
start/state/resume/answer/correspondence/confirmation/contradiction/continuation/
completion/cancellation responses show counts, the changed answer identity and
revision, the first blocker and the existing next-gate template.

## Complete authority remains accessible

Structured `result.bootstrap` is preserved. The additive
`result.operational_projection` uses `flow.guided-bootstrap-operational.v1`.
`state_details` explicitly returns full state and the recent ten-event audit
window; `guidance` and self-contained `roadmap` references remain complete.
Default operational Markdown is bounded for normal identities; unusually large
legacy actor values preserve exact detail calls and are an explicit limit.
A gate template still requires real inputs, current authority and prerequisites.
No new engineering gate, automatic questioning, coding or acceptance is added.

## Constructive diagnostics and exact help

Empty, malformed or duplicate roadmap milestone selections are rejected by a
pure validator before dispatch. The correlated `flow.operation-effect.v1`
receipt declares rejected/none and points to the milestone-planning recipe.
Roadmap does not create milestones. This proof covers that invocation's
selection validation only; service/output/transport failures and uncertain
mutations remain conservative. Never replay an uncertain historical request
just to obtain a new receipt.

Exact bootstrap operation help now separates workflow applicability from the
general multiplexer catalog. Guided engineering does not require code-import
behavior derivation or an internal model. Progress diagnostic codes remain
visible as the operational blocker's reason.

## Updating safely

Use the [same-profile upgrade](UPGRADING.md#preparing-a-065-upgrade), retaining the
existing environment, ledger, YAML and client configuration. The unchanged
installer offers `--upgrade --dry-run --backup-root`, refuses active owners and
backs up SQLite/YAML before pip. Schema55, dependencies and optional
runtime-llama 0.5.0 are unchanged. 37 tools / 445 input fields remain; one explicit
read route brings the operation catalog to 183 routes. Old tags/assets stay fixed.

## Qualification boundaries

Focused deterministic regressions and actual isolated public source/core-wheel
workflows verify both response channels, ten long answers, explicit details,
replay/read/rejection invariance, canonical authoring and roadmap confirmation,
restart and no internal model dependency. Severe review found and corrected the
progress-code blocker seam, then the output boundary for explicitly requested
complete details. Each correction received focused regressions and installed
public read verification; unchanged workflows were not replayed.
Exact Release CI separately qualifies the official package/platform/container
and upgrade mechanics. Noxi owns actual adapter/preview qualification and
preservation; that evidence and human acceptance remain separate. Witness/U6
and paused pipelines are outside this correction.
