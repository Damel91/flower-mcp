"""Errors whose meaning is independent of SQLite, MCP or an LLM backend."""

from typing import Mapping


class LifecycleError(RuntimeError):
    """Base error raised by a canonical lifecycle operation."""


class InputValidationError(ValueError):
    """Typed invalid input that can be projected without parsing prose."""

    def __init__(
        self,
        message: str,
        *,
        field: str,
        received_value: object,
        accepted_values: tuple[str, ...] = (),
    ) -> None:
        self.field = str(field or "").strip()
        self.received_value = received_value
        self.accepted_values = tuple(str(item) for item in accepted_values)
        super().__init__(message)


class ProjectNotFoundError(LifecycleError):
    """Raised when a project-scoped operation has no project authority."""


class RequirementNotFoundError(LifecycleError):
    """Raised when a project does not own the requested requirement."""


class GoalNodeNotFoundError(LifecycleError):
    """Raised when a project does not own the requested Goal Graph node."""


class JobNotFoundError(LifecycleError):
    """Raised when a project does not own the requested durable job."""


class RequirementConflictError(LifecycleError):
    """Raised for deterministic duplicate or conflicting requirement input."""


class BootstrapStartConflictError(RequirementConflictError):
    """Known rejected start with safe facts for explicit public recovery."""

    def __init__(self, reason: str, message: str, *, context: Mapping[str, object]) -> None:
        self.reason = reason
        self.context = dict(context)
        super().__init__(f"{reason}: {message}")


class RequirementMutationBlockedError(LifecycleError):
    """Raised when a governed requirement transition lacks required authority."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "").strip() or "requirement_mutation_blocked"
        super().__init__(self.reason)


class BootstrapBlockedError(LifecycleError):
    """Raised when a resumable bootstrap requires an explicit next action."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "").strip() or "bootstrap_blocked"
        super().__init__(self.reason)


class ChangeControlBlockedError(LifecycleError):
    """Raised when deterministic packet/change policy blocks a transition."""

    def __init__(self, reason: str, *, details: Mapping[str, object] | None = None) -> None:
        self.reason = str(reason or "").strip() or "change_control_blocked"
        self.details = dict(details or {})
        super().__init__(self.reason)


class AssuranceBlockedError(LifecycleError):
    """Raised when findings, campaigns or acceptance gates reject a transition."""

    def __init__(self, reason: str, *, details: Mapping[str, object] | None = None) -> None:
        self.reason = str(reason or "").strip() or "assurance_blocked"
        self.details = dict(details or {})
        super().__init__(self.reason)


class RunControlBlockedError(LifecycleError):
    """Raised when implementation-run continuity gates reject a transition."""

    def __init__(self, reason: str, *, details: Mapping[str, object] | None = None) -> None:
        self.reason = str(reason or "").strip() or "run_control_blocked"
        self.details = dict(details or {})
        super().__init__(self.reason)


class ModelGatewayError(LifecycleError):
    """Base error for a provider-neutral bounded model invocation."""


class ImplementationProviderError(LifecycleError):
    """Base error for a bounded external implementation-intelligence provider."""


class ImplementationProviderUnavailableError(ImplementationProviderError):
    """The optional provider cannot supply a verified snapshot at this time."""

    def __init__(self, terminal_reason: str = "implementation_provider_unavailable") -> None:
        self.terminal_reason = str(terminal_reason or "implementation_provider_unavailable").strip()
        super().__init__(self.terminal_reason)


class ImplementationProviderContractError(ImplementationProviderError):
    """The provider responded, but violated the closed snapshot contract."""

    terminal_reason = "implementation_provider_contract_invalid"


class PacketProviderRejectedError(ImplementationProviderError):
    """The packet provider rejected one valid transport command."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "packet_provider_rejected").strip()
        self.terminal_reason = self.reason
        super().__init__(self.reason)


class ModelBackendError(ModelGatewayError):
    """Raised when a configured model endpoint rejects or corrupts a response."""


class ModelIdleTimeoutError(ModelGatewayError, TimeoutError):
    """Raised when no new stream event arrives within the configured idle bound."""

    terminal_reason = "idle_timeout"


class ModelRunawayError(ModelGatewayError):
    """Raised when bounded stream analysis detects non-converging output."""

    terminal_reason = "runaway"

    def __init__(
        self,
        message: str = "Model generation entered a repeated-output loop",
        *,
        diagnostics: Mapping[str, int | str] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})
