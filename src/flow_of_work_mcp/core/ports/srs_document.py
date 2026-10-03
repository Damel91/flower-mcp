"""Port for importing a source document into a structured SRS representation."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from flow_of_work_mcp.core.domain.srs import ParsedSrs


class SrsDocumentParser(Protocol):
    def parse(self, source_path: str | Path) -> ParsedSrs:
        """Parse a permitted source file without applying lifecycle policy."""
