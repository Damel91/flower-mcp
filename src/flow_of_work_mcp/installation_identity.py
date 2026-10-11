"""Installed Flower identity, independent of MCP SDK and runtime configuration."""

from __future__ import annotations

from importlib import metadata


def installed_distribution_identity() -> dict[str, object]:
    """Report installed metadata without claiming a source checkout is a release."""
    distribution_name = "flow-of-work-mcp"
    try:
        version = metadata.version(distribution_name)
    except metadata.PackageNotFoundError:
        version = None
    return {
        "product": "Flower MCP",
        "distribution_name": distribution_name,
        "distribution_version": version,
        "version_available": version is not None,
        "version_source": "importlib.metadata",
    }
