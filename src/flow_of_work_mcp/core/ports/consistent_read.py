"""Read-snapshot boundary for composing coherent projections."""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class ConsistentReadScope(Protocol):
    """Provides one read-only revision across nested repository calls."""

    def consistent_read(self) -> AbstractContextManager[object]: ...
