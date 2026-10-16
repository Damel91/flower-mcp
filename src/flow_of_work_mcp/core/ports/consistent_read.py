"""Read-snapshot boundary for composing coherent projections."""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Callable, Protocol, TypeVar


_T = TypeVar("_T")


class ConsistentReadScope(Protocol):
    """Provides one read-only revision across nested repository calls."""

    def consistent_read(self) -> AbstractContextManager[object]: ...

    def read_projection(
        self, namespace: str, key: tuple[str, ...], producer: Callable[[], _T]
    ) -> _T: ...
