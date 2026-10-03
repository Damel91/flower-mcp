"""Provider-neutral adapter and runtime composition from validated config."""

from __future__ import annotations

from flow_of_work_mcp.adapters.implementation_intelligence import (
    CodingCastlePacketProjectBinding,
    CodingCastleTestProjectBinding,
    ImplementationProviderProjectBinding,
    McpBootstrapBehaviorProvider,
    McpImplementationGraphProvider,
    McpPacketEvidenceProvider,
    McpProviderInvocationRoute,
    McpCodingCastlePacketProvider,
    McpCodingCastleTestProvider,
    McpCodingCastleInteractionProvider,
    StreamableHttpMcpClient,
    StreamableHttpMcpClientConfig,
)
from flow_of_work_mcp.adapters.sqlite import SQLiteRequirementLedger
from flow_of_work_mcp.application import (
    ProviderBindingAuthorization,
    ProviderBindingService,
)
from flow_of_work_mcp.config import (
    FlowConfig,
    ModelConfig,
    PacketProviderConfig,
    ProviderConfig,
    TestProviderConfig,
    FlowConfigError,
)
from flow_of_work_mcp.core.domain import ImplementationProviderKind
from flow_of_work_mcp.core.ports import ModelGateway
from flow_of_work_mcp.mcp_runtime import McpRuntime, build_runtime
from flow_of_work_mcp.runtime_ownership import RuntimeOwnership, acquire_runtime_ownership


def build_model_gateway(config: ModelConfig) -> ModelGateway | None:
    if not config.enabled:
        return None
    try:
        from flow_of_work_mcp.adapters.model_runtime import (
            LMStudioRuntimeGatewayConfig,
            LMStudioRuntimeModelGateway,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "lmstudio_agent_runtime":
            raise
        raise FlowConfigError(
            "internal inference requires the optional inference dependency; "
            "install flow-of-work-mcp[inference], configure an authorized model "
            "endpoint, or set model.enabled=false to use Flower core"
        ) from exc

    return LMStudioRuntimeModelGateway(
        LMStudioRuntimeGatewayConfig(
            model=config.model,
            base_url=config.base_url,
            context_length=config.context_length,
            auto_load=config.auto_load,
            stream_idle_timeout_sec=config.idle_timeout_sec,
            api_key_env=config.api_key_env,
        )
    )


def _provider_components(config: ProviderConfig):
    if not config.enabled:
        return None
    client = StreamableHttpMcpClient(StreamableHttpMcpClientConfig(endpoint=config.url))
    route = McpProviderInvocationRoute(
        tool_name=config.tool,
        mode=config.invocation,
        session_id=config.session_id,
        domain=config.domain,
        operation=config.operation,
    )
    bindings = tuple(
        ImplementationProviderProjectBinding(
            project_id=binding.project_id,
            scope_id=binding.scope_id,
            surfaces=binding.surfaces or config.surfaces,
            provider_context_id=binding.provider_context_id or config.session_id,
        )
        for binding in config.bindings
    )
    return client, route, bindings


def build_implementation_provider(config: ProviderConfig, *, binding_resolver=None):
    components = _provider_components(config)
    if components is None:
        return None
    client, route, bindings = components
    return McpImplementationGraphProvider(
        client=client,
        tool_name=config.tool,
        bindings=bindings,
        route=route,
        binding_resolver=binding_resolver,
    )


def build_bootstrap_provider(config: ProviderConfig, *, binding_resolver=None):
    components = _provider_components(config)
    if components is None:
        return None
    client, route, bindings = components
    return McpBootstrapBehaviorProvider(
        client=client,
        tool_name=config.tool,
        bindings=bindings,
        route=route,
        binding_resolver=binding_resolver,
    )


def build_packet_evidence_provider(config: ProviderConfig, *, binding_resolver=None):
    components = _provider_components(config)
    if components is None:
        return None
    client, route, bindings = components
    return McpPacketEvidenceProvider(
        client=client,
        tool_name=config.tool,
        bindings=bindings,
        route=route,
        binding_resolver=binding_resolver,
    )


def build_packet_provider(
    config: PacketProviderConfig, *, unit_correlation_resolver=None, binding_resolver=None
):
    if not config.configured or config.mode == "agnostic":
        return None
    client = StreamableHttpMcpClient(
        StreamableHttpMcpClientConfig(
            endpoint=config.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
    )
    return McpCodingCastlePacketProvider(
        client=client,
        tool_name=config.tool,
        bindings=tuple(
            CodingCastlePacketProjectBinding(
                project_id=item.project_id,
                provider_session_id=item.provider_session_id,
            )
            for item in config.bindings
        ),
        unit_correlation_resolver=unit_correlation_resolver,
        binding_resolver=binding_resolver,
    )


def build_test_provider(config: TestProviderConfig, *, binding_resolver=None):
    if not config.configured or config.mode == "agnostic":
        return None
    client = StreamableHttpMcpClient(
        StreamableHttpMcpClientConfig(
            endpoint=config.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
    )
    return McpCodingCastleTestProvider(
        client=client,
        tool_name=config.tool,
        bindings=tuple(
            CodingCastleTestProjectBinding(
                project_id=item.project_id,
                provider_session_id=item.provider_session_id,
                repository=item.repository,
            )
            for item in config.bindings
        ),
        binding_resolver=binding_resolver,
    )


def build_interaction_provider(config: PacketProviderConfig):
    if not config.configured or config.mode == "agnostic":
        return None
    client = StreamableHttpMcpClient(
        StreamableHttpMcpClientConfig(
            endpoint=config.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
    )
    return McpCodingCastleInteractionProvider(client=client)


def build_runtime_from_config(
    config: FlowConfig, *, ownership: RuntimeOwnership | None = None
) -> McpRuntime:
    """Own the ledger before composing adapters, migrations or recovery."""
    lease = (
        ownership
        if ownership is not None
        else acquire_runtime_ownership(config.runtime.database_path)
    )
    # A foreign lease has not transferred to this factory and must not be closed.
    try:
        lease.assert_resource(config.runtime.database_path)
    except BaseException:
        if ownership is None:
            lease.close()
        raise
    try:
        return _compose_runtime_from_config(config, ownership=lease)
    except BaseException:
        lease.close()
        raise


def _compose_runtime_from_config(
    config: FlowConfig, *, ownership: RuntimeOwnership
) -> McpRuntime:
    """Compose the existing runtime from one validated configuration."""

    model_gateway = build_model_gateway(config.model)
    ledger = SQLiteRequirementLedger(config.runtime.database_path)
    authorizations = tuple(
        ProviderBindingAuthorization(
            provider_kind=kind,
            provider_id=f"configured-mcp/{kind.value}",
            surfaces=provider_config.surfaces,
            supports_context_binding=provider_config.invocation == "advanced",
            default_provider_context_id=provider_config.session_id,
        )
        for kind, provider_config in (
            (
                ImplementationProviderKind.IMPLEMENTATION_GRAPH,
                config.implementation_graph_provider,
            ),
            (
                ImplementationProviderKind.BOOTSTRAP_BEHAVIOR,
                config.bootstrap_behavior_provider,
            ),
            (
                ImplementationProviderKind.PACKET_EVIDENCE,
                config.packet_evidence_provider,
            ),
        )
        if provider_config.enabled
    ) + tuple(
        ProviderBindingAuthorization(
            provider_kind=kind,
            provider_id=f"configured-mcp/{kind.value}",
            surfaces=(),
            supports_context_binding=True,
        )
        for kind, execution_config in (
            (ImplementationProviderKind.PACKET_EXECUTION, config.packet_provider),
            (ImplementationProviderKind.TEST_EXECUTION, config.test_provider),
        )
        if execution_config.configured and execution_config.mode != "agnostic"
    )
    provider_bindings = ProviderBindingService(ledger, authorizations)
    for kind, provider_config in (
        (
            ImplementationProviderKind.IMPLEMENTATION_GRAPH,
            config.implementation_graph_provider,
        ),
        (
            ImplementationProviderKind.BOOTSTRAP_BEHAVIOR,
            config.bootstrap_behavior_provider,
        ),
        (ImplementationProviderKind.PACKET_EVIDENCE, config.packet_evidence_provider),
    ):
        for binding in provider_config.bindings if provider_config.enabled else ():
            provider_bindings.import_default(
                binding.project_id,
                provider_kind=kind,
                scope_id=binding.scope_id,
                surfaces=binding.surfaces or provider_config.surfaces,
                provider_context_id=binding.provider_context_id
                or provider_config.session_id,
            )

    for kind, execution_config in (
        (ImplementationProviderKind.PACKET_EXECUTION, config.packet_provider),
        (ImplementationProviderKind.TEST_EXECUTION, config.test_provider),
    ):
        if execution_config.configured and execution_config.mode != "agnostic":
            for binding in execution_config.bindings:
                provider_bindings.import_default(
                    binding.project_id,
                    provider_kind=kind,
                    scope_id="",
                    surfaces=(),
                    provider_context_id=binding.provider_session_id,
                    repository=getattr(binding, "repository", None),
                )

    implementation_provider = build_implementation_provider(
        config.implementation_graph_provider, binding_resolver=ledger
    )
    bootstrap_provider = build_bootstrap_provider(
        config.bootstrap_behavior_provider, binding_resolver=ledger
    )
    packet_evidence_provider = build_packet_evidence_provider(
        config.packet_evidence_provider, binding_resolver=ledger
    )
    packet_provider = build_packet_provider(
        config.packet_provider,
        unit_correlation_resolver=ledger.packet_provider_unit_correlation,
        binding_resolver=ledger,
    )
    interaction_provider = build_interaction_provider(config.packet_provider)
    test_provider = build_test_provider(config.test_provider, binding_resolver=ledger)
    return build_runtime(
        database_path=config.runtime.database_path,
        import_root=config.runtime.import_root,
        model_gateway=model_gateway,
        implementation_provider=implementation_provider,
        bootstrap_behavior_provider=bootstrap_provider,
        packet_evidence_provider=packet_evidence_provider,
        packet_provider=packet_provider,
        packet_provider_mode=config.packet_provider.mode,
        interaction_provider=interaction_provider,
        test_provider=test_provider,
        test_provider_mode=config.test_provider.mode,
        ledger=ledger,
        provider_bindings=provider_bindings,
        job_workers=config.runtime.job_workers,
        runtime_ownership=ownership,
    )
