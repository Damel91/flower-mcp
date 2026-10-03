"""SQLite implementation of the canonical requirement-ledger port.

The ledger is intentionally independent of MCP transport, document parsing and
LLM invocation. Those layers consume and append auditable state through this
boundary; they do not allocate requirement identities or rewrite history.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import sqlite3
from typing import Iterator

from flow_of_work_mcp.adapters.sqlite.artifacts import ArtifactStoreMixin
from flow_of_work_mcp.adapters.sqlite.associations import AssociationStoreMixin
from flow_of_work_mcp.adapters.sqlite.external_work import ExternalWorkStoreMixin
from flow_of_work_mcp.adapters.sqlite.semantic_assignments import SemanticAssignmentStoreMixin
from flow_of_work_mcp.adapters.sqlite.assurance_store import AssuranceStoreMixin
from flow_of_work_mcp.adapters.sqlite.baseline import BaselineStoreMixin
from flow_of_work_mcp.adapters.sqlite.bootstrap import BootstrapStoreMixin
from flow_of_work_mcp.adapters.sqlite.campaign_authority_store import (
    CampaignAuthorityStoreMixin,
)
from flow_of_work_mcp.adapters.sqlite.changes import ChangeStoreMixin
from flow_of_work_mcp.adapters.sqlite.goals import GoalStoreMixin
from flow_of_work_mcp.adapters.sqlite.jobs import JobStoreMixin
from flow_of_work_mcp.adapters.sqlite.lifecycle import LifecycleStoreMixin
from flow_of_work_mcp.adapters.sqlite.navigation_audit import NavigationAuditStoreMixin
from flow_of_work_mcp.adapters.sqlite.packet_construction import PacketConstructionStoreMixin
from flow_of_work_mcp.adapters.sqlite.packet_pressure import PacketPressureStoreMixin
from flow_of_work_mcp.adapters.sqlite.packet_provider_socket import (
    PacketProviderSocketStoreMixin,
)
from flow_of_work_mcp.adapters.sqlite.packet_review import PacketReviewStoreMixin
from flow_of_work_mcp.adapters.sqlite.packet_reconciliation import PacketReconciliationStoreMixin
from flow_of_work_mcp.adapters.sqlite.packet_work_plan import PacketWorkPlanStoreMixin
from flow_of_work_mcp.adapters.sqlite.provider_bindings import ProviderBindingStoreMixin
from flow_of_work_mcp.adapters.sqlite.project_context import ProjectContextStoreMixin
from flow_of_work_mcp.adapters.sqlite.requirements import RequirementStoreMixin
from flow_of_work_mcp.adapters.sqlite.runs import RunStoreMixin
from flow_of_work_mcp.adapters.sqlite.schema import SchemaMixin
from flow_of_work_mcp.adapters.sqlite.serialization import SerializationMixin
from flow_of_work_mcp.adapters.sqlite.test_provider_socket import (
    TestProviderSocketStoreMixin,
)


class SQLiteRequirementLedger(
    SchemaMixin,
    SerializationMixin,
    RequirementStoreMixin,
    BaselineStoreMixin,
    BootstrapStoreMixin,
    ChangeStoreMixin,
    AssuranceStoreMixin,
    CampaignAuthorityStoreMixin,
    RunStoreMixin,
    GoalStoreMixin,
    LifecycleStoreMixin,
    NavigationAuditStoreMixin,
    PacketConstructionStoreMixin,
    PacketWorkPlanStoreMixin,
    PacketReconciliationStoreMixin,
    PacketPressureStoreMixin,
    PacketProviderSocketStoreMixin,
    TestProviderSocketStoreMixin,
    PacketReviewStoreMixin,
    ProjectContextStoreMixin,
    ProviderBindingStoreMixin,
    ArtifactStoreMixin,
    AssociationStoreMixin,
    ExternalWorkStoreMixin,
    SemanticAssignmentStoreMixin,
    JobStoreMixin,
):
    """Project-isolated SQLite persistence for requirements and evidence."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._transaction_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"flow_ledger_transaction_{id(self)}", default=None
        )
        self._migrate()
        self.migrate_associations()
        self.migrate_external_work()
        self.migrate_semantic_assignments()
        self.migrate_grounding_provenance()
        self.recover_interrupted_runs()
        self.recover_interrupted_packet_provider_commands()
        self.recover_interrupted_test_provider_commands()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        active = self._transaction_connection.get()
        if active is not None:
            yield active
            return
        connection = self._connect()
        token = self._transaction_connection.set(connection)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._transaction_connection.reset(token)
            connection.close()

    def atomic(self) -> Iterator[sqlite3.Connection]:
        """Compose multiple ledger mutations into one durable transaction."""
        return self._transaction()

    @contextmanager
    def consistent_read(self) -> Iterator[sqlite3.Connection]:
        """Share one read-only SQLite snapshot across nested repository reads."""

        active = self._transaction_connection.get()
        if active is not None:
            yield active
            return
        connection = self._connect()
        token = self._transaction_connection.set(connection)
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            yield connection
        finally:
            connection.rollback()
            self._transaction_connection.reset(token)
            connection.close()

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        active = self._transaction_connection.get()
        if active is not None:
            yield active
            return
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()
