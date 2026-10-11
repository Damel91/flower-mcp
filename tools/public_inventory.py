"""Exact public catalog generations used by installed-package qualifiers."""

BASELINE_TOOL_NAMES = frozenset({
    "fow_accept_milestone", "fow_assurance", "fow_audit_phase", "fow_bindings",
    "fow_bootstrap", "fow_campaign_advance", "fow_campaign_author", "fow_campaign_inspect",
    "fow_capabilities", "fow_change", "fow_create_project", "fow_external_work",
    "fow_generate_artifacts", "fow_get_artifacts", "fow_get_job", "fow_get_requirement",
    "fow_goal", "fow_ground_intent", "fow_handover", "fow_import_srs", "fow_interaction",
    "fow_list_jobs", "fow_packet_advance", "fow_packet_author", "fow_packet_inspect",
    "fow_promote_milestone", "fow_record_verification", "fow_register_requirement",
    "fow_revise_requirement", "fow_revise_srs_baseline", "fow_run", "fow_semantic",
    "fow_set_requirement_lifecycle", "fow_traceability", "fow_validate_srs", "fow_what_next",
})
CURRENT_TOOL_NAMES = BASELINE_TOOL_NAMES | {"fow_architecture"}


def require_tool_inventory(tools, *, baseline: bool = False) -> None:
    """Keep the immutable predecessor and current additive API inventories exact."""
    expected = BASELINE_TOOL_NAMES if baseline else CURRENT_TOOL_NAMES
    names = [tool.name for tool in tools]
    if len(names) != len(expected) or set(names) != expected:
        raise RuntimeError("Public tool inventory differs from the exact "
                           + ("published baseline" if baseline else "current") + " contract")
