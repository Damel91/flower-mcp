"""Canonical surface vocabulary for the current CodingCastle provider."""
from __future__ import annotations

from collections.abc import Iterable


CODINGCASTLE_PROVIDER_SURFACES = (
    "repo",
    "workspace",
    "docs",
    "test_repo",
    "cc_test",
)
CODINGCASTLE_PROVIDER_SURFACE_SET = frozenset(CODINGCASTLE_PROVIDER_SURFACES)
CODINGCASTLE_BOOTSTRAP_SURFACES = ("repo", "test_repo", "docs")


def codingcastle_provider_surface(value: object) -> str:
    """Validate one provider-owned surface without aliases or inference."""

    surface = str(value or "").strip()
    if surface not in CODINGCASTLE_PROVIDER_SURFACE_SET:
        raise ValueError(
            "surface must be repo, workspace, docs, test_repo or cc_test"
        )
    return surface


def codingcastle_provider_surfaces(
    values: Iterable[object],
    *,
    require_repo: bool = False,
) -> tuple[str, ...]:
    """Validate an ordered provider surface set and preserve caller order."""

    surfaces = tuple(codingcastle_provider_surface(value) for value in values)
    if not surfaces:
        raise ValueError("provider surfaces must be non-empty")
    if len(surfaces) != len(set(surfaces)):
        raise ValueError("provider surfaces must be unique")
    if require_repo and "repo" not in surfaces:
        raise ValueError("provider surfaces require repo")
    return surfaces
