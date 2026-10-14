"""Provider-neutral implementation-intelligence adapter over public MCP.

The lifecycle core defines the desired evidence, not the provider.  Any system
that can return the versioned ``implementation-graph-snapshot-v1`` contract may
back grounding: CodingCastle, Code Review Graph, or a future local service.
No provider Python package, database, runtime object or private API is imported.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import errno
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from threading import Event, Thread
import time
from typing import Protocol

from .mcp_transport_worker import (
    ERROR_REASONS,
    PROTOCOL_VERSION,
    TIMEOUT_REASON,
    TRANSPORT_UNAVAILABLE_REASON,
    strict_json_loads,
)

from flow_of_work_mcp.core.domain.grounding import (
    ImplementationAnchor,
    ImplementationGraphSnapshot,
    ImplementationSnapshotRequest,
)
from flow_of_work_mcp.core.domain.bootstrap import (
    BootstrapBehaviorAnchor,
    BootstrapBehaviorSnapshot,
    BootstrapBehaviorSnapshotRequest,
)
from flow_of_work_mcp.core.domain.packet_reconciliation import (
    PACKET_EVIDENCE_CONTRACT_VERSION,
    PacketEvidenceClaimDraft,
    PacketEvidenceClaimType,
    PacketEvidenceSnapshotDraft,
    PacketEvidenceSnapshotRequest,
)
from flow_of_work_mcp.core.domain.provider_binding import (
    ImplementationProviderKind,
    ProviderProjectBinding,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError,
    ImplementationProviderUnavailableError,
)


_TRANSPORT_WORKER = Path(__file__).with_name("mcp_transport_worker.py").resolve()
_CONTRACT_VERSION = "implementation-graph-snapshot-v1"
_BOOTSTRAP_CONTRACT_VERSION = "bootstrap-behavior-snapshot-v1"
_PROVIDER_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class McpToolClient(Protocol):
    """Minimal synchronous MCP client boundary needed by this adapter."""

    def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        meta: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        """Return a decoded tool result or raise a typed provider error."""


class ProviderProjectBindingResolver(Protocol):
    """Resolve the current ledger-owned binding for one provider family."""

    def resolve_provider_binding(
        self,
        project_id: str,
        provider_kind: ImplementationProviderKind | str,
    ) -> ProviderProjectBinding | None: ...


@dataclass(frozen=True)
class ImplementationProviderProjectBinding:
    """Explicit Flow-project to external-provider scope binding."""

    project_id: str
    scope_id: str
    surfaces: tuple[str, ...] = ("repo",)
    provider_context_id: str = ""

    def __post_init__(self) -> None:
        project_id = str(self.project_id or "").strip()
        scope_id = str(self.scope_id or "").strip()
        surfaces = tuple(str(value or "").strip() for value in self.surfaces if str(value or "").strip())
        if not project_id:
            raise ValueError("implementation provider binding project_id must be non-empty")
        if not scope_id:
            raise ValueError("implementation provider binding scope_id must be non-empty")
        if not surfaces:
            raise ValueError("implementation provider binding requires at least one surface")
        if len(set(surfaces)) != len(surfaces):
            raise ValueError("implementation provider binding surfaces must be unique")
        provider_context_id = str(self.provider_context_id or "").strip()
        if len(provider_context_id) > 256:
            raise ValueError("implementation provider binding context exceeds the supported bound")
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in provider_context_id
        ):
            raise ValueError("implementation provider binding context contains control characters")
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "scope_id", scope_id)
        object.__setattr__(self, "surfaces", surfaces)
        object.__setattr__(self, "provider_context_id", provider_context_id)


@dataclass(frozen=True)
class StreamableHttpMcpClientConfig:
    """Connection settings for a standalone implementation-intelligence server."""

    endpoint: str
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        endpoint = str(self.endpoint or "").strip()
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("implementation provider MCP endpoint must be an HTTP(S) URL")
        if (isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds)
                or self.timeout_seconds <= 0):
            raise ValueError("implementation provider MCP timeout_seconds must be finite and positive")
        object.__setattr__(self, "endpoint", endpoint)


class StreamableHttpMcpClient:
    """One contained, network-only MCP process per synchronous provider RPC."""

    def __init__(self, config: StreamableHttpMcpClientConfig) -> None:
        self._config = config

    def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        meta: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        deadline = time.monotonic() + self._config.timeout_seconds
        expired = Event()
        try:
            payload = json.dumps({
                "version": PROTOCOL_VERSION,
                "endpoint": self._config.endpoint,
                "timeout_seconds": self._config.timeout_seconds,
                "deadline_monotonic": deadline,
                "tool_name": tool_name,
                "arguments": dict(arguments),
                "meta": dict(meta) if meta is not None else None,
            }, ensure_ascii=False, allow_nan=False).encode("utf-8")
            exit_code, output = _invoke_transport_worker(payload, deadline, expired)
            if expired.is_set() or time.monotonic() >= deadline:
                raise ImplementationProviderUnavailableError(TIMEOUT_REASON)
            if exit_code != 0:
                raise ImplementationProviderUnavailableError(TRANSPORT_UNAVAILABLE_REASON)
            response = strict_json_loads(output)
            if not isinstance(response, dict) or response.get("version") != PROTOCOL_VERSION:
                raise ValueError("invalid private provider response")
            status = response.get("status")
            if status == "ok":
                if set(response) != {"version", "status", "result"} or not isinstance(response["result"], dict):
                    raise ValueError("invalid private provider result")
                if time.monotonic() >= deadline:
                    raise ImplementationProviderUnavailableError(TIMEOUT_REASON)
                return response["result"]
            if (set(response) != {"version", "status", "reason"}
                    or not isinstance(status, str) or status not in ERROR_REASONS
                    or response.get("reason") not in ERROR_REASONS[status]):
                raise ValueError("invalid private provider error")
            if time.monotonic() >= deadline:
                raise ImplementationProviderUnavailableError(TIMEOUT_REASON)
            if status == "contract":
                raise ImplementationProviderContractError(response["reason"])
            raise ImplementationProviderUnavailableError(response["reason"])
        except subprocess.TimeoutExpired as exc:
            raise ImplementationProviderUnavailableError(TIMEOUT_REASON) from exc
        except (ImplementationProviderUnavailableError, ImplementationProviderContractError):
            raise
        except Exception as exc:  # noqa: BLE001 - never expose private process/SDK details
            raise ImplementationProviderUnavailableError(
                TIMEOUT_REASON if expired.is_set() or time.monotonic() >= deadline
                else TRANSPORT_UNAVAILABLE_REASON
            ) from exc


def _invoke_transport_worker(payload: bytes, deadline: float, expired: Event) -> tuple[int, bytes]:
    command = [sys.executable]
    if sys.flags.isolated:
        command.append("-I")
    command.extend(["-B", str(_TRANSPORT_WORKER)])
    stop_watchdog = Event()
    child = None
    watchdog = None
    communicated = False
    caller_cancellation = None
    try:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, shell=False, close_fds=True)
        def enforce_deadline() -> None:
            # Windows can block inside communicate's stdin write, before its
            # timeout applies. This owner only kills this RPC's child.
            if not stop_watchdog.wait(max(0.0, deadline - time.monotonic())):
                expired.set()
                _kill_transport_child(child)

        watchdog = Thread(target=enforce_deadline, name="fow-provider-deadline", daemon=False)
        watchdog.start()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, 0)
        output, _ = child.communicate(input=payload, timeout=remaining)
        communicated = True
    except BaseException as exc:
        if not isinstance(exc, Exception):
            caller_cancellation = exc
        raise
    finally:
        try:
            # Never expose a result/exception while owned I/O can continue.
            if child is not None:
                _kill_transport_child(child)
                if not communicated:
                    child.communicate()  # Drain/close pipes and join Windows reader threads.
                child.wait()
                # Retrying communicate(None) can leave a partially written
                # stdin open after TimeoutExpired. The child is reaped now.
                close_error = None
                for pipe in (child.stdin, child.stdout, child.stderr):
                    if pipe is not None:
                        try:
                            pipe.close()
                        except OSError as exc:
                            # Match subprocess's dead-reader handling on Windows.
                            if exc.errno != errno.EPIPE and not (sys.platform == "win32" and exc.errno == errno.EINVAL):
                                close_error = close_error or exc
                if close_error is not None:
                    if caller_cancellation is None:
                        raise close_error
                    caller_cancellation.add_note("Provider transport pipe cleanup failed after the owned child was reaped.")
        finally:
            stop_watchdog.set()
            if watchdog is not None and watchdog.ident is not None:
                watchdog.join()
    return child.returncode, output


def _kill_transport_child(child: subprocess.Popen) -> None:
    if child.poll() is None:
        try:
            child.kill()
        except ProcessLookupError:
            pass  # The owned process exited between poll and kill.


@dataclass(frozen=True)
class McpProviderInvocationRoute:
    """Configured public MCP route for one implementation-intelligence provider.

    The direct form is the original v1 transport.  The advanced form is for a
    provider that intentionally keeps its contract endpoint behind a typed MCP
    gateway, such as CodingCastle's ``codingcastle_advanced``.  This type stays
    at the adapter edge: Flow's domain never learns provider tool names.
    """

    tool_name: str
    mode: str = "direct"
    session_id: str = ""
    domain: str = ""
    operation: str = ""

    def __post_init__(self) -> None:
        tool_name = str(self.tool_name or "").strip()
        mode = str(self.mode or "").strip().lower()
        session_id = str(self.session_id or "").strip()
        domain = str(self.domain or "").strip()
        operation = str(self.operation or "").strip()
        if not tool_name:
            raise ValueError("implementation provider tool_name must be non-empty")
        if mode not in {"direct", "advanced"}:
            raise ValueError("implementation provider invocation mode must be direct or advanced")
        if mode == "advanced" and (not session_id or not domain or not operation):
            raise ValueError(
                "advanced implementation provider route requires session_id, domain and operation"
            )
        if mode == "direct" and any((session_id, domain, operation)):
            raise ValueError("direct implementation provider route cannot include advanced fields")
        object.__setattr__(self, "tool_name", tool_name)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "operation", operation)

    def call(
        self,
        client: McpToolClient,
        contract_request: Mapping[str, object],
        *,
        provider_context_id: str = "",
    ) -> Mapping[str, object]:
        """Invoke one public route without changing the nested v1 request."""
        request = dict(contract_request)
        if self.mode == "direct":
            if provider_context_id:
                raise ImplementationProviderContractError(
                    "direct provider route cannot use a provider invocation context"
                )
            return client.call_tool(self.tool_name, request)
        return client.call_tool(
            self.tool_name,
            {
                "session_id": provider_context_id or self.session_id,
                "domain": self.domain,
                "operation": self.operation,
                "arguments": request,
            },
        )


class McpImplementationGraphProvider:
    """Translate a closed Flow grounding scope into a provider-neutral snapshot."""

    def __init__(
        self,
        *,
        client: McpToolClient,
        bindings: tuple[ImplementationProviderProjectBinding, ...],
        tool_name: str = "",
        route: McpProviderInvocationRoute | None = None,
        binding_resolver: ProviderProjectBindingResolver | None = None,
    ) -> None:
        by_project = {binding.project_id: binding for binding in bindings}
        if not by_project and binding_resolver is None:
            raise ValueError("implementation provider requires at least one project binding")
        if len(by_project) != len(bindings):
            raise ValueError("implementation provider project bindings must be unique")
        if route is None:
            route = McpProviderInvocationRoute(tool_name=tool_name, mode="direct")
        elif tool_name and str(tool_name).strip() != route.tool_name:
            raise ValueError("implementation provider tool_name conflicts with invocation route")
        self._client = client
        self._route = route
        self._bindings = by_project
        self._binding_resolver = binding_resolver

    def snapshot(self, request: ImplementationSnapshotRequest) -> ImplementationGraphSnapshot:
        binding = _resolved_binding(
            request.project_id,
            ImplementationProviderKind.IMPLEMENTATION_GRAPH,
            self._bindings,
            self._binding_resolver,
        )
        if binding is None:
            raise ImplementationProviderUnavailableError("implementation_provider_project_unbound")

        contract_request = {
            "contract_version": _CONTRACT_VERSION,
            "project_id": request.project_id,
            "scope_id": binding.scope_id,
            "goal_scope": [
                {
                    "goal_node_id": goal.goal_node_id,
                    "node_type": goal.node_type,
                    "title": goal.title,
                    "payload": dict(goal.payload),
                }
                for goal in request.goals
            ],
            "source_revision": request.source_revision,
            "surfaces": list(binding.surfaces),
            "max_anchors": request.max_anchors,
        }
        result = _validated_result(
            self._route.call(
                self._client,
                contract_request,
                provider_context_id=binding.provider_context_id,
            )
        )
        self._validate_binding(result, request, binding)
        truncated = result.get("truncated", False)
        if not isinstance(truncated, bool):
            raise ImplementationProviderContractError("provider snapshot truncated must be boolean")
        try:
            return ImplementationGraphSnapshot(
                project_id=request.project_id,
                provider_id=str(result.get("provider_id") or ""),
                source_revision=str(result.get("source_revision") or ""),
                anchors=_anchors_from_result(result, max_anchors=request.max_anchors),
                truncated=truncated,
            )
        except ValueError as exc:
            raise ImplementationProviderContractError("provider snapshot is not closed or valid") from exc

    @staticmethod
    def _validate_binding(
        result: Mapping[str, object],
        request: ImplementationSnapshotRequest,
        binding: ImplementationProviderProjectBinding,
    ) -> None:
        if str(result.get("contract_version") or "") != _CONTRACT_VERSION:
            raise ImplementationProviderContractError("provider snapshot contract version mismatch")
        if str(result.get("project_id") or "") != request.project_id:
            raise ImplementationProviderContractError("provider snapshot project binding mismatch")
        if str(result.get("scope_id") or "") != binding.scope_id:
            raise ImplementationProviderContractError("provider snapshot scope binding mismatch")
        source_revision = str(result.get("source_revision") or "").strip()
        if not source_revision or len(source_revision) > 512:
            raise ImplementationProviderContractError("provider snapshot source revision is missing")
        if request.source_revision and source_revision != request.source_revision:
            raise ImplementationProviderContractError("provider snapshot source revision mismatch")
        surfaces = _string_tuple(result.get("surfaces"), "provider snapshot surfaces")
        if surfaces != binding.surfaces:
            raise ImplementationProviderContractError("provider snapshot surfaces mismatch")
        provider_id = str(result.get("provider_id") or "").strip()
        if not provider_id or len(provider_id) > 512:
            raise ImplementationProviderContractError("provider snapshot provider_id is missing")


class McpBootstrapBehaviorProvider:
    """Consume code-first evidence through a public provider contract."""

    def __init__(
        self,
        *,
        client: McpToolClient,
        bindings: tuple[ImplementationProviderProjectBinding, ...],
        tool_name: str = "",
        route: McpProviderInvocationRoute | None = None,
        binding_resolver: ProviderProjectBindingResolver | None = None,
    ) -> None:
        by_project = {binding.project_id: binding for binding in bindings}
        if not by_project and binding_resolver is None:
            raise ValueError("bootstrap behavior provider requires at least one project binding")
        if len(by_project) != len(bindings):
            raise ValueError("bootstrap behavior provider project bindings must be unique")
        if route is None:
            route = McpProviderInvocationRoute(tool_name=tool_name, mode="direct")
        elif tool_name and str(tool_name).strip() != route.tool_name:
            raise ValueError("bootstrap behavior provider tool_name conflicts with invocation route")
        self._client = client
        self._route = route
        self._bindings = by_project
        self._binding_resolver = binding_resolver

    def snapshot(
        self, request: BootstrapBehaviorSnapshotRequest
    ) -> BootstrapBehaviorSnapshot:
        binding = _resolved_binding(
            request.project_id,
            ImplementationProviderKind.BOOTSTRAP_BEHAVIOR,
            self._bindings,
            self._binding_resolver,
        )
        if binding is None:
            raise ImplementationProviderUnavailableError("bootstrap_behavior_provider_project_unbound")
        if binding.surfaces != request.surfaces:
            raise ImplementationProviderUnavailableError("bootstrap_behavior_provider_surfaces_unbound")
        result = _validated_result(
            self._route.call(
                self._client,
                {
                    "contract_version": _BOOTSTRAP_CONTRACT_VERSION,
                    "project_id": request.project_id,
                    "scope_id": binding.scope_id,
                    "source_revision": request.source_revision,
                    "surfaces": list(request.surfaces),
                    "max_anchors": request.max_anchors,
                },
                provider_context_id=binding.provider_context_id,
            )
        )
        self._validate_binding(result, request, binding)
        truncated = result.get("truncated", False)
        if not isinstance(truncated, bool):
            raise ImplementationProviderContractError("bootstrap snapshot truncated must be boolean")
        try:
            return BootstrapBehaviorSnapshot(
                project_id=request.project_id,
                provider_id=str(result.get("provider_id") or ""),
                scope_id=binding.scope_id,
                source_revision=str(result.get("source_revision") or ""),
                surfaces=request.surfaces,
                anchors=_bootstrap_anchors_from_result(result, max_anchors=request.max_anchors),
                truncated=truncated,
            )
        except ValueError as exc:
            raise ImplementationProviderContractError("bootstrap snapshot is not closed or valid") from exc

    @staticmethod
    def _validate_binding(
        result: Mapping[str, object],
        request: BootstrapBehaviorSnapshotRequest,
        binding: ImplementationProviderProjectBinding,
    ) -> None:
        if str(result.get("contract_version") or "") != _BOOTSTRAP_CONTRACT_VERSION:
            raise ImplementationProviderContractError("bootstrap snapshot contract version mismatch")
        if str(result.get("project_id") or "") != request.project_id:
            raise ImplementationProviderContractError("bootstrap snapshot project binding mismatch")
        if str(result.get("scope_id") or "") != binding.scope_id:
            raise ImplementationProviderContractError("bootstrap snapshot scope binding mismatch")
        source_revision = str(result.get("source_revision") or "").strip()
        if not source_revision or source_revision != request.source_revision:
            raise ImplementationProviderContractError("bootstrap snapshot source revision mismatch")
        if _string_tuple(result.get("surfaces"), "bootstrap snapshot surfaces") != request.surfaces:
            raise ImplementationProviderContractError("bootstrap snapshot surfaces mismatch")
        provider_id = str(result.get("provider_id") or "").strip()
        if not provider_id or len(provider_id) > 512:
            raise ImplementationProviderContractError("bootstrap snapshot provider_id is missing")


class McpPacketEvidenceProvider:
    """Transport-only adapter for the packet evidence snapshot contract."""

    def __init__(
        self,
        *,
        client: McpToolClient,
        bindings: tuple[ImplementationProviderProjectBinding, ...],
        tool_name: str = "",
        route: McpProviderInvocationRoute | None = None,
        binding_resolver: ProviderProjectBindingResolver | None = None,
    ) -> None:
        by_project = {binding.project_id: binding for binding in bindings}
        if (not by_project and binding_resolver is None) or len(by_project) != len(bindings):
            raise ValueError("packet evidence provider bindings require a resolver or unique defaults")
        if route is None:
            route = McpProviderInvocationRoute(tool_name=tool_name, mode="direct")
        elif tool_name and str(tool_name).strip() != route.tool_name:
            raise ValueError("packet evidence provider tool_name conflicts with invocation route")
        self._client = client
        self._route = route
        self._bindings = by_project
        self._binding_resolver = binding_resolver

    def snapshot(self, request: PacketEvidenceSnapshotRequest) -> PacketEvidenceSnapshotDraft:
        binding = _resolved_binding(
            request.project_id,
            ImplementationProviderKind.PACKET_EVIDENCE,
            self._bindings,
            self._binding_resolver,
        )
        if binding is None:
            raise ImplementationProviderUnavailableError("packet_evidence_provider_project_unbound")
        if not set(request.surfaces).issubset(binding.surfaces):
            raise ImplementationProviderUnavailableError(
                "packet_evidence_provider_surfaces_unbound"
            )
        if binding.scope_id != request.provider_scope_id:
            raise ImplementationProviderContractError("packet evidence provider scope binding mismatch")
        contract_request = {
            "contract_version": PACKET_EVIDENCE_CONTRACT_VERSION,
            "project_id": request.project_id,
            "scope_id": request.provider_scope_id,
            "packet_id": request.packet_id,
            "workspace_revision": request.workspace_revision,
            "surfaces": list(request.surfaces),
            "claim_types": [value.value for value in request.claim_types],
            "bounds": {"max_claims": request.max_claims, "max_depth": request.max_depth},
        }
        if request.selection_refs:
            contract_request["selection_refs"] = list(request.selection_refs)
            contract_request["target_handles"] = list(request.target_handles)
        else:
            contract_request["selection_ref"] = request.selection_ref
            contract_request["source_revision"] = request.source_revision
        result = _validated_result(
            self._route.call(
                self._client,
                contract_request,
                provider_context_id=binding.provider_context_id,
            )
        )
        self._validate_result(result, request, binding)
        forbidden = {
            "readiness", "readiness_state", "execution_ready", "acceptance",
            "accepted", "milestone_status", "packet_status",
        }
        if forbidden.intersection(result):
            raise ImplementationProviderContractError("provider returned Flow lifecycle authority")
        raw_claims = result.get("claims")
        if not isinstance(raw_claims, list) or len(raw_claims) > request.max_claims:
            raise ImplementationProviderContractError("packet evidence claims exceed the requested bound")
        claims: list[PacketEvidenceClaimDraft] = []
        try:
            for raw in raw_claims:
                if not isinstance(raw, Mapping):
                    raise ValueError("claim is not an object")
                claims.append(
                    PacketEvidenceClaimDraft(
                        claim_type=PacketEvidenceClaimType(str(raw.get("claim_type") or "")),
                        claim_key=str(raw.get("claim_key") or ""),
                        subject_ref=str(raw.get("subject_ref") or ""),
                        predicate=str(raw.get("predicate") or ""),
                        object_ref=str(raw.get("object_ref") or ""),
                        assertion=_mapping_value(raw.get("assertion"), "claim assertion"),
                        evidence_refs=_string_tuple(
                            raw.get("evidence_refs"), "claim evidence_refs", max_items=256,
                        ),
                        required=_bool_value(raw.get("required"), "claim required"),
                        dynamic=_bool_value(raw.get("dynamic"), "claim dynamic"),
                        contradicted=_bool_value(raw.get("contradicted"), "claim contradicted"),
                    )
                )
            completeness = _mapping_value(result.get("completeness"), "snapshot completeness")
            diagnostics = _string_tuple(
                result.get("diagnostics"), "snapshot diagnostics", max_items=512,
            )
            return PacketEvidenceSnapshotDraft(
                reconciliation_scope_id=request.reconciliation_scope_id,
                packet_id=request.packet_id,
                provider_id=str(result.get("provider_id") or ""),
                provider_scope_id=str(result.get("scope_id") or ""),
                provider_snapshot_id=str(result.get("provider_snapshot_id") or ""),
                selection_ref=str(result.get("selection_ref") or ""),
                source_revision=str(result.get("source_revision") or ""),
                workspace_revision=str(result.get("workspace_revision") or ""),
                surfaces=_string_tuple(result.get("surfaces"), "snapshot surfaces"),
                fingerprint=str(result.get("fingerprint") or ""),
                completeness={str(key): str(value) for key, value in completeness.items()},
                claims=tuple(claims),
                contract_version=str(result.get("contract_version") or ""),
                truncated=_bool_value(result.get("truncated"), "snapshot truncated"),
                diagnostics=diagnostics,
            )
        except (TypeError, ValueError) as exc:
            raise ImplementationProviderContractError("packet evidence snapshot is not closed or valid") from exc

    def residual_action(
        self,
        *,
        project_id: str,
        residual: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Translate graph-backed residuals to CodingCastle's public graph tool."""

        next_action = residual.get("next_action")
        capability = str(
            next_action.get("capability")
            if isinstance(next_action, Mapping)
            else ""
        )
        if capability not in {
            "graph.investigate_claim",
            "runtime.investigate_dynamic_claim",
        }:
            return {}
        binding = _resolved_binding(
            project_id,
            ImplementationProviderKind.PACKET_EVIDENCE,
            self._bindings,
            self._binding_resolver,
        )
        if binding is None:
            return {}
        target = str(
            residual.get("subject_ref") or residual.get("claim_key") or ""
        ).strip()
        if not target:
            return {}
        return {
            "tool": "codingcastle_graph",
            "operation": "nearby_evidence",
            "arguments": {
                "session_id": binding.provider_context_id or "default",
                "operation": "nearby_evidence",
                "target": target,
                "depth": 2,
                "detail_level": "standard",
                "surfaces": list(binding.surfaces),
            },
            "required_inputs": [],
        }

    @staticmethod
    def _validate_result(
        result: Mapping[str, object],
        request: PacketEvidenceSnapshotRequest,
        binding: ImplementationProviderProjectBinding,
    ) -> None:
        expected = {
            "contract_version": PACKET_EVIDENCE_CONTRACT_VERSION,
            "project_id": request.project_id,
            "scope_id": binding.scope_id,
            "packet_id": request.packet_id,
            "provider_id": request.provider_id,
            "workspace_revision": request.workspace_revision,
        }
        for field, value in expected.items():
            if str(result.get(field) or "") != value:
                raise ImplementationProviderContractError(
                    f"packet evidence snapshot {field} mismatch"
                )
        if request.selection_refs:
            if _string_tuple(
                result.get("source_selection_refs"),
                "snapshot source_selection_refs",
                max_items=128,
            ) != request.selection_refs:
                raise ImplementationProviderContractError(
                    "packet evidence snapshot source selections mismatch"
                )
            if _string_tuple(
                result.get("target_handles"),
                "snapshot target_handles",
                max_items=2_048,
            ) != request.target_handles:
                raise ImplementationProviderContractError(
                    "packet evidence snapshot target handles mismatch"
                )
            if not str(result.get("selection_ref") or "").strip():
                raise ImplementationProviderContractError(
                    "packet evidence snapshot aggregate selection is missing"
                )
            if not str(result.get("source_revision") or "").strip():
                raise ImplementationProviderContractError(
                    "packet evidence snapshot current revision is missing"
                )
        else:
            if str(result.get("selection_ref") or "") != request.selection_ref:
                raise ImplementationProviderContractError(
                    "packet evidence snapshot selection_ref mismatch"
                )
            if str(result.get("source_revision") or "") != request.source_revision:
                raise ImplementationProviderContractError(
                    "packet evidence snapshot source_revision mismatch"
                )
        if _string_tuple(result.get("surfaces"), "snapshot surfaces") != request.surfaces:
            raise ImplementationProviderContractError("packet evidence snapshot surfaces mismatch")
        if not str(result.get("provider_snapshot_id") or "").strip():
            raise ImplementationProviderContractError("provider snapshot id is missing")
        if not str(result.get("fingerprint") or "").strip():
            raise ImplementationProviderContractError("provider snapshot fingerprint is missing")


def _resolved_binding(
    project_id: str,
    provider_kind: ImplementationProviderKind,
    defaults: Mapping[str, ImplementationProviderProjectBinding],
    resolver: ProviderProjectBindingResolver | None,
) -> ImplementationProviderProjectBinding | None:
    if resolver is not None:
        durable = resolver.resolve_provider_binding(project_id, provider_kind)
        if durable is not None:
            return ImplementationProviderProjectBinding(
                project_id=durable.project_id,
                scope_id=durable.scope_id,
                surfaces=durable.surfaces,
                provider_context_id=durable.provider_context_id,
            )
    return defaults.get(project_id)


def _validated_result(payload: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise ImplementationProviderContractError("provider MCP result is not an object")
    # FastMCP's structured result may add ``{"result": <tool-envelope>}``
    # around a provider's own success envelope. Unwrap only these two bounded,
    # public envelope layers; the final object must still be the exact v1 shape.
    current: object = payload
    for _ in range(3):
        if not isinstance(current, Mapping):
            raise ImplementationProviderContractError("provider snapshot result is not an object")
        if "contract_version" in current:
            return current
        status = str(current.get("status") or "")
        if status:
            if status not in {"ok", "success"}:
                raise ImplementationProviderUnavailableError(
                    _provider_terminal_reason(current)
                )
            current = current.get("result")
            continue
        nested = current.get("result")
        if isinstance(nested, Mapping):
            current = nested
            continue
        break
    raise ImplementationProviderContractError("provider snapshot contract payload is missing")


def _validated_named_contract(
    payload: Mapping[str, object], contract_key: str,
) -> Mapping[str, object]:
    """Unwrap one public provider result key before strict contract validation."""
    current: object = payload
    for _ in range(3):
        if not isinstance(current, Mapping):
            break
        named = current.get(contract_key)
        if isinstance(named, Mapping):
            return _validated_result(named)
        if "contract_version" in current:
            return _validated_result(current)
        status = str(current.get("status") or "")
        if status and status not in {"ok", "success"}:
            return _validated_result(current)
        nested = current.get("result")
        if isinstance(nested, Mapping):
            current = nested
            continue
        break
    return _validated_result(payload)


def _provider_terminal_reason(payload: Mapping[str, object]) -> str:
    """Return one safe machine reason without exposing arbitrary provider text."""

    candidates: list[object] = [payload.get("reason"), payload.get("terminal_reason")]
    nested = payload.get("result")
    if isinstance(nested, Mapping):
        candidates.extend((nested.get("reason"), nested.get("terminal_reason")))
    for candidate in candidates:
        value = str(candidate or "").strip()
        if _PROVIDER_REASON_RE.fullmatch(value):
            return value
    return "implementation_snapshot_capability_unavailable"


def _anchors_from_result(
    result: Mapping[str, object],
    *,
    max_anchors: int,
) -> tuple[ImplementationAnchor, ...]:
    raw_anchors = result.get("anchors")
    if not isinstance(raw_anchors, list):
        raise ImplementationProviderContractError("provider snapshot anchors must be a list")
    if len(raw_anchors) > max_anchors:
        raise ImplementationProviderContractError("provider snapshot exceeds requested anchor bound")
    anchors: list[ImplementationAnchor] = []
    for raw in raw_anchors:
        if not isinstance(raw, Mapping):
            raise ImplementationProviderContractError("provider snapshot anchor is not an object")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in metadata.items()
        ):
            raise ImplementationProviderContractError("provider snapshot anchor metadata is invalid")
        try:
            anchors.append(
                ImplementationAnchor(
                    anchor_id=str(raw.get("anchor_id") or ""),
                    kind=str(raw.get("kind") or ""),
                    label=str(raw.get("label") or ""),
                    summary=str(raw.get("summary") or ""),
                    source_path=str(raw.get("source_path") or ""),
                    evidence_ids=_string_tuple(
                        raw.get("evidence_ids"), "anchor evidence_ids", max_items=128
                    ),
                    dependency_anchor_ids=_string_tuple(
                        raw.get("dependency_anchor_ids"), "anchor dependency_anchor_ids", max_items=128
                    ),
                    test_evidence_ids=_string_tuple(
                        raw.get("test_evidence_ids"), "anchor test_evidence_ids", max_items=128
                    ),
                    metadata=dict(metadata),
                )
            )
        except ValueError as exc:
            raise ImplementationProviderContractError("provider snapshot anchor is invalid") from exc
    return tuple(anchors)


def _bootstrap_anchors_from_result(
    result: Mapping[str, object], *, max_anchors: int
) -> tuple[BootstrapBehaviorAnchor, ...]:
    raw_anchors = result.get("anchors")
    if not isinstance(raw_anchors, list) or len(raw_anchors) > max_anchors:
        raise ImplementationProviderContractError("bootstrap snapshot anchors are invalid")
    anchors: list[BootstrapBehaviorAnchor] = []
    for raw in raw_anchors:
        if not isinstance(raw, Mapping):
            raise ImplementationProviderContractError("bootstrap snapshot anchor is not an object")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in metadata.items()
        ):
            raise ImplementationProviderContractError("bootstrap snapshot anchor metadata is invalid")
        try:
            anchors.append(
                BootstrapBehaviorAnchor(
                    anchor_id=str(raw.get("anchor_id") or ""),
                    kind=str(raw.get("kind") or ""),
                    label=str(raw.get("label") or ""),
                    summary=str(raw.get("summary") or ""),
                    source_path=str(raw.get("source_path") or ""),
                    evidence_ids=_string_tuple(
                        raw.get("evidence_ids"), "anchor evidence_ids", max_items=128
                    ),
                    dependency_anchor_ids=_string_tuple(
                        raw.get("dependency_anchor_ids"),
                        "anchor dependency_anchor_ids",
                        max_items=128,
                    ),
                    test_evidence_ids=_string_tuple(
                        raw.get("test_evidence_ids"), "anchor test_evidence_ids", max_items=128
                    ),
                    metadata=dict(metadata),
                )
            )
        except ValueError as exc:
            raise ImplementationProviderContractError("bootstrap snapshot anchor is invalid") from exc
    return tuple(anchors)


def _string_tuple(value: object, field: str, *, max_items: int = 32) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ImplementationProviderContractError(f"{field} must be a list")
    values = tuple(str(item or "").strip() for item in value)
    if (
        len(values) > max_items
        or any(not item or len(item) > 2_048 for item in values)
        or len(set(values)) != len(values)
    ):
        raise ImplementationProviderContractError(f"{field} must contain unique non-empty strings")
    return values


def _mapping_value(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImplementationProviderContractError(f"{field} must be an object")
    return dict(value)


def _bool_value(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ImplementationProviderContractError(f"{field} must be boolean")
    return value
