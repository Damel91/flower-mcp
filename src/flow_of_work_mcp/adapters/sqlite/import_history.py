"""Resolve source references and immutable cells of imported projects."""
from __future__ import annotations

import sqlite3


def local_identity(connection: sqlite3.Connection, project_id: str, kind: str, identity: int) -> int:
    """Resolve an old numeric identity within its destination project and type."""
    rows = connection.execute(
        """SELECT DISTINCT local_id FROM project_import_identities
           WHERE project_id = ? AND identity_kind = ? AND source_id = ? LIMIT 2""",
        (project_id, kind, identity),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("the imported source identity is ambiguous")
    return int(rows[0][0]) if rows else identity


def original_integer_keyed_cells(
    connection: sqlite3.Connection, project_id: str, table: str, identity: int, column: str,
) -> tuple[str, ...]:
    """Read immutable originals of a global integer-keyed cell across origins."""
    return tuple(row[0] for row in connection.execute(
        """SELECT cell.original_value
           FROM project_import_identities AS identity
           JOIN project_import_originals AS cell
             ON cell.project_id = identity.project_id AND cell.origin_digest = identity.origin_digest
            AND cell.table_name = identity.identity_kind AND cell.row_key = json_array(identity.source_id)
           WHERE identity.project_id = ? AND identity.identity_kind = ? AND identity.local_id = ?
             AND cell.column_name = ?
           ORDER BY identity.origin_digest, identity.source_id""",
        (project_id, table, identity, column),
    ))
