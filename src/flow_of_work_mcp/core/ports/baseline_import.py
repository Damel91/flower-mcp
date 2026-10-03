"""Transactional port for initial canonical SRS baseline materialization."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.baseline import BaselineImportPlan


class BaselineImportRepository(Protocol):
    def import_baseline(
        self,
        plan: BaselineImportPlan,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def revise_baseline(
        self,
        plan: BaselineImportPlan,
        *,
        previous_baseline_id: str,
        actor: str,
        governed_approval_reference: str = "",
        request_id: str = "",
    ) -> Mapping[str, object]: ...
