from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    extension TEXT,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL,
                    mime_type TEXT,
                    is_text INTEGER NOT NULL DEFAULT 0,
                    content_text TEXT,
                    preview_text TEXT,
                    indexed_at TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indexing_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    files_seen INTEGER NOT NULL DEFAULT 0,
                    files_indexed INTEGER NOT NULL DEFAULT 0,
                    files_skipped INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    report_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indexing_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES indexing_runs(id) ON DELETE CASCADE
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename);")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS files_fts
                USING fts5(path UNINDEXED, filename, content_text, tokenize='unicode61');
                """
            )

    def start_run(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO indexing_runs (
                    started_at, finished_at, files_seen, files_indexed,
                    files_skipped, errors_count, report_json
                ) VALUES (?, NULL, 0, 0, 0, 0, '{}');
                """,
                (utc_now_iso(),),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, report: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE indexing_runs
                SET
                    finished_at = ?,
                    files_seen = ?,
                    files_indexed = ?,
                    files_skipped = ?,
                    errors_count = ?,
                    report_json = ?
                WHERE id = ?;
                """,
                (
                    utc_now_iso(),
                    int(report["files_seen"]),
                    int(report["files_indexed"]),
                    int(report["files_skipped"]),
                    int(report["errors_count"]),
                    json.dumps(report, ensure_ascii=True),
                    run_id,
                ),
            )

    def log_error(self, run_id: int, path: str, error_type: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO indexing_errors (
                    run_id, path, error_type, message, occurred_at
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (run_id, path, error_type, message[:2000], utc_now_iso()),
            )

    def upsert_file(self, file_row: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO files (
                    path, filename, extension, size_bytes, created_at, modified_at,
                    mime_type, is_text, content_text, preview_text, indexed_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    filename = excluded.filename,
                    extension = excluded.extension,
                    size_bytes = excluded.size_bytes,
                    created_at = excluded.created_at,
                    modified_at = excluded.modified_at,
                    mime_type = excluded.mime_type,
                    is_text = excluded.is_text,
                    content_text = excluded.content_text,
                    preview_text = excluded.preview_text,
                    indexed_at = excluded.indexed_at,
                    status = excluded.status;
                """,
                (
                    file_row["path"],
                    file_row["filename"],
                    file_row["extension"],
                    file_row["size_bytes"],
                    file_row["created_at"],
                    file_row["modified_at"],
                    file_row["mime_type"],
                    1 if file_row["is_text"] else 0,
                    file_row["content_text"],
                    file_row["preview_text"],
                    file_row["indexed_at"],
                    file_row["status"],
                ),
            )

            conn.execute("DELETE FROM files_fts WHERE path = ?;", (file_row["path"],))
            if file_row["is_text"] and file_row["content_text"]:
                conn.execute(
                    "INSERT INTO files_fts(path, filename, content_text) VALUES (?, ?, ?);",
                    (file_row["path"], file_row["filename"], file_row["content_text"]),
                )

    def search_filename(self, terms: list[str], limit: int) -> list[dict[str, Any]]:
        if not terms:
            return []
        conditions = " AND ".join("lower(filename) LIKE ?" for _ in terms)
        params: list[Any] = [f"%{term.lower()}%" for term in terms] + [limit]
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT path, filename, extension, size_bytes, modified_at, preview_text, content_text
                FROM files
                WHERE status IN ('indexed', 'metadata_only')
                  AND {conditions}
                ORDER BY modified_at DESC
                LIMIT ?;
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def search_content(self, terms: list[str], limit: int) -> list[dict[str, Any]]:
        if not terms:
            return []
        fts_query = " AND ".join(f"{term}*" for term in terms)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    f.path,
                    f.filename,
                    f.extension,
                    f.size_bytes,
                    f.modified_at,
                    f.preview_text,
                    f.content_text,
                    bm25(files_fts) AS bm25_rank
                FROM files_fts
                JOIN files f ON f.path = files_fts.path
                WHERE files_fts MATCH ?
                ORDER BY bm25_rank
                LIMIT ?;
                """,
                (fts_query, limit),
            ).fetchall()
        return [dict(row) for row in rows]
