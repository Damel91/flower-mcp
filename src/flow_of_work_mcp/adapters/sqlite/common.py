"""Shared helpers for the SQLite ledger adapter."""
from __future__ import annotations

from datetime import datetime, timezone
import re


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


_GOAL_NODE_ID_RE = re.compile(r"^GOAL-[0-9]{6}$")
