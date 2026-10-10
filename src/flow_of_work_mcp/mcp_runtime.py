"""Runtime composition for the Flow of Work MCP transport."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from flow_of_work_mcp.adapters.documents import MarkdownSrsParser
from flow_of_work_mcp.adapters.sqlite import SQLiteRequirementLedger
from flow_of_work_mcp.application import (
    ArtifactGenerationService,
    AssuranceService,
    CampaignAuthorityService,
    BaselineImportService,
    BootstrapService,
    ChangeControlService,
    CoveragePropagationService,
    DurableJobService,
    ExecutionRunService,
    GoalGraphService,
    HandoverService,
    IntentionGroundingService,
    InteractionProjectionService,
    LifecycleControlService,
    MilestoneTraceabilityProjectionService,
    NavigationAuditService,
    PacketLifecycleService,
    PacketUnitAuthoringService,
    PacketConstructionService,
    PacketGuardService,
    PacketAdvancementCoordinator,
    PacketLifecycleProjectionService,
    PacketPressureService,
    PacketProviderProjectionService,
    PacketProviderOverlayService,
    PacketProviderSocketService,
    TestProviderSocketService,
    PacketNextActionProjectionService,
    PacketWorkPlanService,
    PacketReconciliationService,
    PacketReviewService,
    ProviderBindingService,
    ProjectStateSnapshotService,
    RequirementService,
    SrsSemanticValidationService,
    SrsValidationService,
)
from flow_of_work_mcp.core.ports import (
    BootstrapBehaviorProvider,
    ImplementationGraphProvider,
    ModelGateway,
    PacketEvidenceProvider,
    PacketProvider,
    TestProvider,
    InteractionProvider,
)
from flow_of_work_mcp.core.standards import StandardProfileRegistry
from flow_of_work_mcp.application.association_receipts import AssociationReceiptService
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.engineer_gate import EngineerGateService
from flow_of_work_mcp.application.guided_bootstrap import GuidedBootstrapService
from flow_of_work_mcp.application.semantic_assignments import SemanticAssignmentService
from flow_of_work_mcp.runtime_ownership import RuntimeOwnership


class RuntimeCompositionCleanupError(RuntimeError):
    """Construction failed and owned resources could not finish cleanup.

    The chained errors retain both failures. Runtime ownership must remain held
    until explicit cleanup or process exit, rather than admit unsafe recovery.
    """


@dataclass
class McpRuntime:
    ledger: SQLiteRequirementLedger
    requirements: RequirementService
    assurance: AssuranceService
    campaign_authority: CampaignAuthorityService
    test_provider_socket: TestProviderSocketService
    coverage_propagation: CoveragePropagationService
    goals: GoalGraphService
    lifecycle: LifecycleControlService
    milestone_traceability: MilestoneTraceabilityProjectionService
    changes: ChangeControlService
    navigation: NavigationAuditService
    packet_factory: PacketLifecycleService
    packet_construction: PacketConstructionService
    packet_guards: PacketGuardService
    packet_advancement: PacketAdvancementCoordinator
    packet_lifecycle: PacketLifecycleProjectionService
    packet_pressure: PacketPressureService
    packet_provider_projection: PacketProviderProjectionService
    packet_provider_overlay: PacketProviderOverlayService
    packet_provider_socket: PacketProviderSocketService
    packet_next_action: PacketNextActionProjectionService
    packet_work_plan: PacketWorkPlanService
    packet_unit_authoring: PacketUnitAuthoringService
    packet_reconciliation: PacketReconciliationService
    packet_review: PacketReviewService
    project_state_snapshot: ProjectStateSnapshotService
    provider_bindings: ProviderBindingService
    association_receipts: AssociationReceiptService
    semantic_assignments: SemanticAssignmentService
    external_work: ExternalWorkService
    engineer_gate: EngineerGateService
    project_context: object
    interaction_projection: InteractionProjectionService
    execution_runs: ExecutionRunService
    handover: HandoverService
    artifacts: ArtifactGenerationService
    structural_validation: SrsValidationService
    baseline_import: BaselineImportService
    bootstrap: BootstrapService
    guided_bootstrap: GuidedBootstrapService
    jobs: DurableJobService
    bootstrap_behavior_provider: BootstrapBehaviorProvider | None = None
    packet_evidence_provider: PacketEvidenceProvider | None = None
    packet_provider: PacketProvider | None = None
    packet_provider_mode: str = "agnostic"
    test_provider: TestProvider | None = None
    test_provider_mode: str = "agnostic"
    semantic_validation: SrsSemanticValidationService | None = None
    grounding: IntentionGroundingService | None = None
    runtime_ownership: RuntimeOwnership | None = None
    owned_model_gateway: ModelGateway | None = None

    def close(self) -> None:
        # A failed shutdown does not prove workers have stopped. Keep ownership
        # until cleanup succeeds or the process exits rather than admit recovery
        # over work that may still be alive.
        self.jobs.shutdown()
        close = getattr(self.owned_model_gateway, "close", None)
        if callable(close):
            close()
        self.owned_model_gateway = None
        if self.runtime_ownership is not None:
            self.runtime_ownership.close()


def build_runtime(
    *,
    database_path: str | Path,
    import_root: str | Path,
    model_gateway: ModelGateway | None = None,
    implementation_provider: ImplementationGraphProvider | None = None,
    bootstrap_behavior_provider: BootstrapBehaviorProvider | None = None,
    packet_evidence_provider: PacketEvidenceProvider | None = None,
    packet_provider: PacketProvider | None = None,
    packet_provider_mode: str = "agnostic",
    test_provider: TestProvider | None = None,
    test_provider_mode: str = "agnostic",
    interaction_provider: InteractionProvider | None = None,
    ledger: SQLiteRequirementLedger | None = None,
    provider_bindings: ProviderBindingService | None = None,
    job_workers: int = 1,
    runtime_ownership: RuntimeOwnership | None = None,
    owned_model_gateway: ModelGateway | None = None,
) -> McpRuntime:
    """Compose the standalone runtime without an external-provider runtime import."""

    profiles = StandardProfileRegistry()
    ledger = ledger or SQLiteRequirementLedger(database_path)
    engineer_gate = EngineerGateService(ledger)
    def external_execution_guard(project_id, packet_id):
        engineer_gate.execution_guard(project_id, packet_id)
        guided_bootstrap.execution_guard(project_id, packet_id)
    external_work = ExternalWorkService(ledger, execution_guard=external_execution_guard,
                                       engineer_projection=engineer_gate.projection)
    provider_bindings = provider_bindings or ProviderBindingService(ledger)
    association_receipts = AssociationReceiptService(ledger, provider_bindings)
    from flow_of_work_mcp.application.project_context import ProjectContextService

    project_context = ProjectContextService(
        ledger,
        provider_context_resolver=(
            getattr(packet_provider, "session_for_project", None)
            if packet_provider is not None
            else None
        ),
    )
    requirements = RequirementService(ledger)
    assurance = AssuranceService(assurance=ledger, changes=ledger, engineer_gate=engineer_gate)
    test_provider_socket = TestProviderSocketService(
        ledger, mode=test_provider_mode, provider=test_provider
    )
    coverage_propagation = CoveragePropagationService(
        assurance=ledger,
        requirements=ledger,
        grounding_audits=ledger,
    )
    campaign_authority = CampaignAuthorityService(
        ledger,
        test_provider_socket=test_provider_socket,
        coverage_propagation=coverage_propagation,
    )
    execution_runs = ExecutionRunService(ledger)
    handover = HandoverService(ledger)
    goals = GoalGraphService(ledger)
    def external_milestone_progress(project_id: str, milestone_id: str):
        packets = [packet for change in ledger.list_changes(project_id)
                   if change.get('milestone_id') == milestone_id for packet in change.get('packets', [])
                   if packet['status'] not in {'cancelled', 'superseded'}]
        if not packets or any(external_work.mode_for_packet(project_id, packet['packet_id']) != 'external_agent' for packet in packets):
            return None
        return milestone_traceability.progress(project_id, milestone_ids=(milestone_id,))

    lifecycle = LifecycleControlService(
        requirements=ledger,
        goals=ledger,
        grounding_audits=ledger,
        control=ledger,
        change_control=ledger,
        assurance=ledger,
        campaign_authority=campaign_authority,
        execution_runs=ledger,
        external_milestone_progress=external_milestone_progress,
    )
    changes = ChangeControlService(ledger, external_packet_closure=lambda project_id, change_id, packet_id: external_work.implementation_closure(project_id, change_id, packet_id))
    navigation = NavigationAuditService(ledger, work_plans=ledger)
    packet_construction = PacketConstructionService(ledger)
    packet_reconciliation = PacketReconciliationService(
        ledger, provider=packet_evidence_provider
    )
    packet_pressure = PacketPressureService(ledger)
    packet_provider_projection = PacketProviderProjectionService(
        mode=packet_provider_mode,
        provider=packet_provider,
    )
    packet_provider_socket = PacketProviderSocketService(
        ledger,
        mode=packet_provider_mode,
        provider=packet_provider,
    )
    packet_provider_overlay = PacketProviderOverlayService(
        ledger,
        socket=packet_provider_socket,
        projection=packet_provider_projection,
        external_work=external_work,
    )
    packet_next_action = PacketNextActionProjectionService()
    packet_work_plan = PacketWorkPlanService(
        ledger,
        changes=ledger,
        navigation=ledger,
    )
    packet_unit_authoring = PacketUnitAuthoringService(
        ledger=ledger,
        repository=ledger,
        changes=ledger,
        navigation=navigation,
        work_plans=packet_work_plan,
        provider_managed_targets=packet_provider_overlay.provider_managed_targets,
    )
    packet_factory = PacketLifecycleService(
        ledger=ledger,
        changes=changes,
        assurance=assurance,
        navigation=navigation,
        construction=packet_construction,
        reconciliation=packet_reconciliation,
        packet_provider_overlay=packet_provider_overlay,
    )
    packet_review = PacketReviewService(
        ledger=ledger,
        assurance=assurance,
        provider_kind=packet_provider_socket.provider_kind,
    )
    packet_guards = PacketGuardService(
        changes=ledger,
        work_plans=ledger,
        construction=ledger,
        pressure=ledger,
        reviews=ledger,
        reconciliation=ledger,
        campaigns=ledger,
        packet_provider_overlay=packet_provider_overlay,
        external_work=external_work,
        consistent_reads=ledger,
    )
    packet_advancement = PacketAdvancementCoordinator(
        ledger=ledger,
        guards=packet_guards,
        next_actions=packet_next_action,
        changes=changes,
        construction=packet_construction,
        pressure=packet_pressure,
        work_plans=packet_work_plan,
        reviews=packet_review,
        reconciliation=packet_reconciliation,
        campaigns=ledger,
        packet_provider_overlay=packet_provider_overlay,
    )
    packet_lifecycle = PacketLifecycleProjectionService(
        changes=ledger,
        assurance=ledger,
        work_plans=packet_work_plan,
        construction=packet_construction,
        guards=packet_guards,
        next_actions=packet_next_action,
        reviews=ledger,
        reconciliation=ledger,
        packet_provider_overlay=packet_provider_overlay,
        external_work=external_work,
        consistent_reads=ledger,
    )
    milestone_traceability = MilestoneTraceabilityProjectionService(
        requirements=ledger,
        lifecycle=ledger,
        changes=ledger,
        navigation=ledger,
        assurance=ledger,
        execution_runs=ledger,
        ledger_versions=ledger,
        grounding_audits=ledger,
        construction=ledger,
        pressure=ledger,
        external_work=external_work,
    )
    project_state_snapshot = ProjectStateSnapshotService(
        consistent_reads=ledger,
        goals=ledger,
        grounding_audits=ledger,
        changes=ledger,
        assurance=ledger,
        campaign_authority=campaign_authority,
        work_plans=ledger,
        provider_bindings=ledger,
        lifecycle=lifecycle,
        traceability=milestone_traceability,
        packet_guards=packet_guards,
        packet_next_actions=packet_next_action,
        packet_lifecycle=packet_lifecycle,
        provider_enabled=packet_provider is not None,
    )
    interaction_projection = InteractionProjectionService(
        repository=ledger,
        project_context=project_context,
        project_state_snapshot=project_state_snapshot,
        interaction_provider=interaction_provider,
    )
    artifacts = ArtifactGenerationService(
        profiles=profiles,
        requirements=ledger,
        goals=ledger,
        control=ledger,
        ledger_versions=ledger,
        artifacts=ledger,
    )
    parser = MarkdownSrsParser(import_root)
    structural_validation = SrsValidationService(parser, profiles)
    semantic_validation = (
        SrsSemanticValidationService(model_gateway, profiles)
        if model_gateway is not None
        else None
    )
    grounding = IntentionGroundingService(
            goals=ledger,
            requirements=ledger,
            audits=ledger,
            provider=implementation_provider,
            gateway=model_gateway,
        )
    baseline_import = BaselineImportService(
        structural_validation=structural_validation,
        repository=ledger,
        lifecycle=lifecycle,
    )
    bootstrap = BootstrapService(
        repository=ledger,
        baseline_repository=ledger,
        lifecycle=lifecycle,
        import_root=import_root,
        behavior_provider=bootstrap_behavior_provider,
        model_gateway=model_gateway,
    )
    guided_bootstrap = GuidedBootstrapService(ledger, external_work=external_work, traceability=milestone_traceability)
    semantic_assignments = SemanticAssignmentService(
        repository=ledger,
        structural_validation=structural_validation,
        profiles=profiles,
        lifecycle=lifecycle,
        gateway=model_gateway,
        grounding=grounding,
        observed_behavior_available=model_gateway is not None and bootstrap_behavior_provider is not None,
    )
    # The executor is lazy: no work is submitted during composition. Keep it
    # last, and close it if construction fails before ownership reaches runtime.
    jobs = DurableJobService(ledger, max_workers=job_workers)
    try:
        return McpRuntime(
            ledger=ledger,
            requirements=requirements,
            assurance=assurance,
            campaign_authority=campaign_authority,
            test_provider_socket=test_provider_socket,
            coverage_propagation=coverage_propagation,
            goals=goals,
            lifecycle=lifecycle,
            milestone_traceability=milestone_traceability,
            changes=changes,
            navigation=navigation,
            packet_factory=packet_factory,
            packet_construction=packet_construction,
            packet_guards=packet_guards,
            packet_advancement=packet_advancement,
            packet_lifecycle=packet_lifecycle,
            packet_pressure=packet_pressure,
            packet_provider_projection=packet_provider_projection,
            packet_provider_overlay=packet_provider_overlay,
            packet_provider_socket=packet_provider_socket,
            packet_next_action=packet_next_action,
            packet_work_plan=packet_work_plan,
            packet_unit_authoring=packet_unit_authoring,
            packet_reconciliation=packet_reconciliation,
            packet_review=packet_review,
            project_state_snapshot=project_state_snapshot,
            provider_bindings=provider_bindings,
            association_receipts=association_receipts,
            semantic_assignments=semantic_assignments,
            external_work=external_work,
            engineer_gate=engineer_gate,
            project_context=project_context,
            interaction_projection=interaction_projection,
            execution_runs=execution_runs,
            handover=handover,
            artifacts=artifacts,
            structural_validation=structural_validation,
            baseline_import=baseline_import,
            bootstrap=bootstrap,
            guided_bootstrap=guided_bootstrap,
            semantic_validation=semantic_validation,
            grounding=grounding,
            jobs=jobs,
            bootstrap_behavior_provider=bootstrap_behavior_provider,
            packet_evidence_provider=packet_evidence_provider,
            packet_provider=packet_provider,
            packet_provider_mode=str(packet_provider_mode or "agnostic"),
            test_provider=test_provider,
            test_provider_mode=str(test_provider_mode or "agnostic"),
            runtime_ownership=runtime_ownership,
            owned_model_gateway=owned_model_gateway,
        )
    except BaseException:
        try:
            jobs.shutdown()
        except BaseException as cleanup_error:
            raise RuntimeCompositionCleanupError(
                "runtime construction failed and worker cleanup is incomplete; runtime ownership remains held"
            ) from cleanup_error
        raise
