"""Shared packet-provider delivery fingerprint lineage."""

from __future__ import annotations

from hashlib import sha256
from string import hexdigits

from flow_of_work_mcp.core.domain.identifiers import required_text


_RETRY_SEPARATOR = ":retry:"
_SHA256_HEX_LENGTH = 64
_MAX_DELIVERY_FINGERPRINT_LENGTH = 256


def semantic_delivery_root(delivery_fingerprint: str) -> str:
    """Return the stable semantic identity beneath any supported retry attempt."""

    value = str(delivery_fingerprint or "").strip()
    while True:
        root, separator, digest = value.rpartition(_RETRY_SEPARATOR)
        if not separator or not _is_sha256(digest):
            return value
        value = root


def rejection_retry_fingerprint(
    delivery_fingerprint: str, occurrence_ref: str
) -> str:
    """Derive one distinct retry attempt while retaining semantic currentness."""

    original = required_text(delivery_fingerprint, "delivery_fingerprint")
    occurrence = required_text(occurrence_ref, "occurrence_ref")
    root = semantic_delivery_root(original)
    digest = sha256(f"{original}\x1f{occurrence}".encode("utf-8")).hexdigest()
    retry = f"{root}{_RETRY_SEPARATOR}{digest}"
    if len(retry) > _MAX_DELIVERY_FINGERPRINT_LENGTH:
        raise ValueError("packet provider retry fingerprint exceeds the supported bound")
    return retry


def _is_sha256(value: str) -> bool:
    return len(value) == _SHA256_HEX_LENGTH and all(
        character in hexdigits for character in value
    )


__all__ = ["rejection_retry_fingerprint", "semantic_delivery_root"]
