"""Stable domain vocabulary for the canonical lifecycle ledger."""
from __future__ import annotations

from enum import StrEnum


class LifecycleStatus(StrEnum):
    """Current implementation state of a requirement.

    Verification remains independent: an implemented requirement can still be
    untested, and a removed requirement retains its historical evidence.
    """

    PLANNED = "planned"
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    REMOVED = "removed"


class VerificationKind(StrEnum):
    """Evidence classes exposed by the traceability view."""

    DETERMINISTIC = "tested_deterministically"
    LIVE = "tested_live"


class VerificationOutcome(StrEnum):
    """Outcome of a particular evidence record, not a lifecycle transition."""

    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
