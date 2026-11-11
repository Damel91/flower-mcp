"""Construct an isolated predecessor fixture from the additive migration."""

from contextlib import closing
import sqlite3

from flow_of_work_mcp.native_purge_schema import PROJECT_IMPORT_TABLE_HASHES


def retain_schema55(path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN")
        for table in reversed(tuple(PROJECT_IMPORT_TABLE_HASHES)):
            connection.execute(f'DROP TABLE "{table}"')
        connection.execute("DELETE FROM schema_migrations WHERE version = 56")
