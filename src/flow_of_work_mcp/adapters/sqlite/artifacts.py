"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

from dataclasses import replace
import sqlite3
from typing import Mapping

from flow_of_work_mcp.core.domain import (
    ArtifactDraft,
    ArtifactGeneration,
    ArtifactKind,
    ArtifactMapping,
)
from flow_of_work_mcp.core.domain.identifiers import (
    required_text,
)




class ArtifactStoreMixin:
    def record_artifact_generation(
        self,
        generation: ArtifactGeneration,
        *,
        actor: str,
        request_id: str = "",
    ) -> ArtifactGeneration:
        """Persist a versioned read-only generation batch and canonical mappings."""

        if generation.generation_id is not None:
            raise ValueError("only a new artifact generation can be recorded")
        actor = required_text(actor, "actor")
        with self._transaction() as connection:
            self._ensure_project(connection, generation.project_id)
            if request_id:
                existing = connection.execute(
                    """
                    SELECT generation_id FROM artifact_generations
                    WHERE project_id = ? AND request_id = ?
                    """,
                    (generation.project_id, str(request_id)),
                ).fetchone()
                if existing is not None:
                    return self._artifact_generation_to_domain(
                        self._artifact_generation_value(connection, int(existing["generation_id"]))
                    )
            cursor = connection.execute(
                """
                INSERT INTO artifact_generations(
                    project_id, profile_id, profile_version, source_ledger_version,
                    generated_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation.project_id,
                    generation.profile_id,
                    generation.profile_version,
                    generation.source_ledger_version,
                    generation.generated_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            generation_id = int(cursor.lastrowid)
            artifact_ids: list[int] = []
            for artifact in generation.artifacts:
                artifact_cursor = connection.execute(
                    """
                    INSERT INTO generated_artifacts(
                        generation_id, artifact_kind, content_sha256, content
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        generation_id,
                        artifact.kind.value,
                        artifact.content_sha256,
                        artifact.content,
                    ),
                )
                artifact_id = int(artifact_cursor.lastrowid)
                artifact_ids.append(artifact_id)
                for mapping in artifact.mappings:
                    connection.execute(
                        """
                        INSERT INTO artifact_mappings(
                            artifact_id, canonical_kind, canonical_id, source_anchor
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            artifact_id,
                            mapping.canonical_kind,
                            mapping.canonical_id,
                            mapping.source_anchor,
                        ),
                    )
            self._append_event(
                connection,
                project_id=generation.project_id,
                requirement_id=None,
                event_type="artifact_generation_recorded",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "generation_id": generation_id,
                    "profile_id": generation.profile_id,
                    "profile_version": generation.profile_version,
                    "source_ledger_version": generation.source_ledger_version,
                    "artifact_ids": artifact_ids,
                    "artifact_kinds": [artifact.kind.value for artifact in generation.artifacts],
                },
                occurred_at=generation.generated_at,
            )
        return replace(generation, generation_id=generation_id)

    def artifact_generations(self, project_id: str) -> list[Mapping[str, object]]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            records = connection.execute(
                """
                SELECT generation_id FROM artifact_generations
                WHERE project_id = ?
                ORDER BY generation_id
                """,
                (project_id,),
            ).fetchall()
            return [self._artifact_generation_value(connection, int(row["generation_id"])) for row in records]

    @staticmethod
    def _artifact_generation_value(
        connection: sqlite3.Connection,
        generation_id: int,
    ) -> Mapping[str, object]:
        row = connection.execute(
            """
            SELECT generation_id, project_id, profile_id, profile_version,
                   source_ledger_version, generated_at, created_by, request_id
            FROM artifact_generations
            WHERE generation_id = ?
            """,
            (generation_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown artifact generation: {generation_id}")
        value: dict[str, object] = dict(row)
        artifacts = []
        for artifact_row in connection.execute(
            """
            SELECT artifact_id, artifact_kind, content_sha256, content
            FROM generated_artifacts
            WHERE generation_id = ?
            ORDER BY artifact_id
            """,
            (generation_id,),
        ).fetchall():
            artifact = dict(artifact_row)
            mappings = [
                dict(mapping_row)
                for mapping_row in connection.execute(
                    """
                    SELECT canonical_kind, canonical_id, source_anchor
                    FROM artifact_mappings
                    WHERE artifact_id = ?
                    ORDER BY canonical_kind, canonical_id
                    """,
                    (int(artifact["artifact_id"]),),
                ).fetchall()
            ]
            artifact["mappings"] = mappings
            artifacts.append(artifact)
        value["artifacts"] = artifacts
        return value

    @staticmethod
    def _artifact_generation_to_domain(value: Mapping[str, object]) -> ArtifactGeneration:
        artifacts = tuple(
            ArtifactDraft(
                kind=ArtifactKind(str(item["artifact_kind"])),
                content=str(item["content"]),
                mappings=tuple(
                    ArtifactMapping(
                        canonical_kind=str(mapping["canonical_kind"]),
                        canonical_id=str(mapping["canonical_id"]),
                        source_anchor=str(mapping["source_anchor"]),
                    )
                    for mapping in item["mappings"]
                ),
            )
            for item in value["artifacts"]
        )
        return ArtifactGeneration(
            project_id=str(value["project_id"]),
            profile_id=str(value["profile_id"]),
            profile_version=str(value["profile_version"]),
            source_ledger_version=int(value["source_ledger_version"]),
            generated_at=str(value["generated_at"]),
            artifacts=artifacts,
            generation_id=int(value["generation_id"]),
        )
