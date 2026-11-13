from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class MetadataStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    title TEXT,
                    size_bytes INTEGER NOT NULL,
                    pages INTEGER NOT NULL,
                    chunks INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    file_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    document_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_job(self, job_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (id, status, progress, stage, created_at, updated_at)
                VALUES (?, 'queued', 0, '等待处理', ?, ?)
                """,
                (job_id, now, now),
            )

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        stage: str | None = None,
        document_id: str | None = None,
        error: str | None = None,
    ) -> None:
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [datetime.now(UTC).isoformat()]
        for column, value in (
            ("status", status),
            ("progress", progress),
            ("stage", stage),
            ("document_id", document_id),
            ("error", error),
        ):
            if value is not None:
                updates.append(f"{column} = ?")
                values.append(value)
        values.append(job_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                values,
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return dict(row) if row else None

    def add_document(self, document: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents
                    (id, filename, title, size_bytes, pages, chunks, status,
                     summary, file_path, sha256, created_at)
                VALUES
                    (:id, :filename, :title, :size_bytes, :pages, :chunks,
                     :status, :summary, :file_path, :sha256, :created_at)
                """,
                document,
            )

    def list_documents(self, document_ids: list[str] | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM documents ORDER BY created_at DESC"
        params: tuple[Any, ...] = ()
        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            query = (
                f"SELECT * FROM documents WHERE id IN ({placeholders}) "
                "ORDER BY created_at DESC"
            )
            params = tuple(document_ids)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_document(self, document_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "DELETE FROM documents WHERE id = ?", (document_id,)
            )
            return dict(row)

    def count(self) -> tuple[int, int]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS docs, COALESCE(SUM(chunks), 0) AS chunks "
                "FROM documents"
            ).fetchone()
            return int(row["docs"]), int(row["chunks"])
