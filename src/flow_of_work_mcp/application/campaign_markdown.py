"""Model-facing working views of the campaign contract."""

from collections.abc import Mapping, Sequence
from typing import Any

from flow_of_work_mcp.markdown_adapter import safe_inline


_VIEWS = {
    "cases": ("Cases", "case_id", ("title", "revision", "test_type", "execution_lane", "expected_outcome", "result")),
    "obligations": ("Proof obligations", "obligation_id", ("currentness", "statement", "decision", "subject_ref", "source_kind", "source_ref", "source_revision", "expected_behavior", "prohibited_behavior", "rationale")),
    "oracles": ("Behavioral Oracles", "oracle_id", ("revision", "status", "current")),
    "oracle_ir": ("Deterministic Oracle IR", "case_id", ("oracle_id", "state", "constructible", "refinement_applicable")),
    "attestation": ("Source attestations", "attestation_id", ("case_id", "state", "oracle_id", "oracle_revision", "materialization_mode", "source_manifest_digest")),
    "evidence": ("Observed evidence", "evidence_id", ("case_id", "operation", "provider_kind", "authority", "provenance", "outcome", "technical_state", "acceptance_disposition", "authoritative", "source_revision", "evidence_reference", "current")),
    "host_attempts": ("Issued host checks", "attempt_id", ("case_id", "source_revision", "execution_profile", "check_reference", "current")),
    "residuals": ("Residuals", "kind", ("case_id", "obligation_id", "subject_ref", "missing_fact", "reason", "message", "status")),
    "history": ("Recent revisions", "revision", ("reason", "created_at", "actor")),
}
_SHEET_VIEWS = ("obligations", "cases", "oracles", "attestation", "host_attempts", "evidence", "residuals")
_RESULT_KEYS = {"attestation": "attestations"}


def _plain(value: object, limit: int = 180) -> str:
    raw = str(value)
    clipped = raw if len(raw) <= limit else raw[: limit - 1] + "…"
    return safe_inline(clipped).replace("`", "\\`")


def _scalars(values: object, limit: int = 12) -> str:
    if not isinstance(values, (list, tuple)):
        return ""
    visible = [_plain(item, 100) for item in values[:limit] if isinstance(item, (str, int))]
    return ", ".join(visible) + (", …" if len(values) > limit else "") if visible else ""


def _fields(row: Mapping[str, Any], names: Sequence[str]) -> str:
    selected = []
    for name in names:
        value = row.get(name)
        if isinstance(value, (str, int)) and value != "":
            shown = _plain(value, 260 if name in {"statement", "message"} else 140)
        else:
            shown = _scalars(value, limit=4)
        if shown:
            selected.append(f"{name.replace('_', ' ')}: {shown}")
    return " · ".join(selected)


def _rows(view: str, rows: object, maximum: int) -> list[str]:
    heading, identity, fields = _VIEWS[view]
    lines = ["", f"## {heading}", ""]
    if not isinstance(rows, (list, tuple)) or not rows:
        return [*lines, "No rows in this selection."]
    for row in rows[:maximum]:
        if isinstance(row, Mapping):
            label = row.get(identity) or row.get("receipt_id") or row.get("kind") or row.get("reason") or heading
            if view == "obligations" and "fresh" in row:
                row = {**row, "currentness": "current" if row["fresh"] else "historical"}
            detail = _fields(row, fields)
            lines.append(f"- **{_plain(label)}**" + (f" · {detail}" if detail else ""))
            if view == "oracles":
                pending = [question.get("question_id", "") for question in row.get("questions", ())
                           if not question.get("answer_authority")]
                if pending:
                    lines.append("  - Pending source questions: " + _scalars(pending))
        elif isinstance(row, str):
            lines.append(f"- {_plain(row)}")
    return lines


def campaign_detail_lines(result: Mapping[str, Any], view: str) -> list[str]:
    """Describe one bounded working view and its exact continuation."""
    campaign = result.get("campaign") or {}
    if not campaign or view == "summary":
        return []
    lines = []
    if (fingerprint := campaign.get("fingerprint")) and view in {"working_sheet", "oracles", "obligations"}:
        lines.append(f"- **Current revision pin:** `{_plain(fingerprint)}` (revision {campaign['revision']}).")
    if view == "working_sheet":
        for name in _SHEET_VIEWS:
            rows = campaign.get(_RESULT_KEYS.get(name, name))
            if rows:
                lines.extend(_rows(name, rows, 2))
        lines.extend(["", "Read one section with `fow_campaign_inspect` and its view: "
                      + ", ".join(f"`{name}`" for name in _SHEET_VIEWS) + "."])
        return lines
    if view == "constructibility":
        result_view = result["constructibility"]
        lines.append(f"- **Constructibility:** {_plain(result_view['state'] or 'unassessed')}")
        return [*lines, *_rows("residuals", result_view.get("residuals"), 6)]
    if view not in _VIEWS:
        return lines
    page = result.get("page")
    rows = result.get(_RESULT_KEYS.get(view, view))
    maximum = 8
    lines.extend(_rows(view, rows, maximum))
    if isinstance(page, Mapping):
        start, total = page["offset"], page["total"]
        count = min(len(rows or ()), maximum)
        lines.extend(["", f"Showing {count} of {total} rows (offset {start})."])
        if count and start + count < total:
            lines.append(f"Continue with `fow_campaign_inspect` and `view={view}`, "
                         f"`offset={start + count}`, `limit={min(page['limit'], maximum)}`.")
    elif len(rows or ()) > maximum:
        lines.extend(["", f"Showing the first {maximum} rows. Use the structured `{view}` view for its full projection."])
    return lines


def campaign_error_markdown(
    tool: str, payload: Mapping[str, Any], arguments: Mapping[str, Any],
) -> str:
    result = payload.get("result") or {}
    request = result.get("original_request") or arguments
    diagnostics = result.get("diagnostics") or []
    first = diagnostics[0] if diagnostics else {}
    reason = payload.get("reason") or "campaign_operation_failed"
    lines = [f"# Campaign {payload['status']}", ""]
    if scope := _fields(request, ("project_id", "campaign_id", "operation", "request_id")):
        lines.append(f"- **Scope:** {scope}")
    cause = first.get("message") or result.get("detail") or str(reason).replace("_", " ")
    lines.append(f"- **Cause:** {_plain(cause, 500)} (`{_plain(reason)}`)")
    if field := first.get("field"):
        lines.append(f"- **Input to correct:** `{_plain(field)}`")
    if effect_resolution := first.get("resolution"):
        lines.append(f"- **Recovery:** {_plain(effect_resolution, 500)}")
    if choices := _scalars(first.get("accepted_values"), limit=20):
        lines.append(f"- **Accepted values:** {choices}")
    if first.get("current") and isinstance(first["current"], Mapping):
        if current := _fields(first["current"], ("oracle_id", "question_id", "oracle_revision")):
            lines.append(f"- **Current Oracle question:** {current}")
    effect = result.get("effect_state")
    if effect == "none":
        lines.append("- **Effect:** Validation stopped the request before mutation.")
    elif effect == "unknown":
        lines.append("- **Effect:** Unconfirmed. Inspect current authority before retrying a write.")
    elif result.get("read_only"):
        lines.append("- **Effect:** This call was a read.")
    call = result.get("next_tool_call") or {}
    if target := call.get("tool"):
        inputs = call.get("arguments") or {}
        exact = _fields(inputs, ("project_id", "campaign_id", "change_id", "view", "operation", "operation_tool", "operation_name"))
        lines.append(f"- **Next step:** Call `{_plain(target)}`" + (f" with {exact}." if exact else "."))
    elif reason == "project_not_found":
        lines.append("- **Next step:** Confirm the project ID with `fow_interaction` / `discover` and retry the read.")
    else:
        view = arguments.get("view") if tool == "fow_campaign_inspect" else "summary"
        lines.append(f"- **Next step:** Inspect the current campaign with `fow_campaign_inspect`, `view={_plain(view or 'summary')}`.")
    return "\n".join(lines) + "\n"


def campaign_receipt_lines(result: Mapping[str, Any]) -> list[str]:
    lines = []
    for key, label, fields in (
        ("host_attempt", "Host check", ("attempt_id", "case_id", "source_revision", "execution_profile", "check_reference")),
        ("host_receipt", "Host result", ("attempt_id", "outcome", "evidence_reference", "source_revision")),
    ):
        receipt = result.get(key)
        if isinstance(receipt, Mapping) and (shown := _fields(receipt, fields)):
            lines.append(f"- **{label}:** {shown}")
    if isinstance(batch := result.get("authoring_receipt"), Mapping):
        items = batch.get("items") or []
        applied = sum(item.get("outcome") == "applied" for item in items)
        lines.append(f"- **Obligation batch:** {applied} applied, {len(items) - applied} already current.")
    return lines


def campaign_check_lines(check: Mapping[str, Any]) -> list[str]:
    lines = []
    for key in ("setup", "action", "observation_point", "expected_outcome", "prohibited_outcome", "cleanup"):
        value = check.get(key)
        shown = _plain(value, 300) if isinstance(value, str) and value else _scalars(value, limit=3)
        if shown:
            lines.append(f"- **Check {key.replace('_', ' ')}:** {shown}")
    return lines
