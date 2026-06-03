from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            with conn:
                yield conn
        finally:
            conn.close()

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
                    status TEXT NOT NULL,
                    path_score REAL NOT NULL DEFAULT 0.0,
                    access_time TEXT,
                    popularity_score INTEGER NOT NULL DEFAULT 0,
                    file_type TEXT NOT NULL DEFAULT 'other',
                    dominant_color TEXT
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    searched_at TEXT NOT NULL,
                    results_count INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS click_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    rank INTEGER,
                    score REAL,
                    clicked_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_search_history_query ON search_history(query);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_click_history_query ON click_history(query);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_click_history_path ON click_history(file_path);")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS files_fts
                USING fts5(path UNINDEXED, filename, content_text, tokenize='unicode61');
                """
            )

            self._ensure_column(conn, "files", "path_score", "REAL NOT NULL DEFAULT 0.0")
            self._ensure_column(conn, "files", "access_time", "TEXT")
            self._ensure_column(conn, "files", "popularity_score", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "files", "file_type", "TEXT NOT NULL DEFAULT 'other'")
            self._ensure_column(conn, "files", "dominant_color", "TEXT")
            self._ensure_column(conn, "search_history", "results_count", "INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_definition: str) -> None:
        existing = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table});").fetchall()
        }
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_definition};")

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
                    mime_type, is_text, content_text, preview_text, indexed_at, status,
                    path_score, access_time, popularity_score, file_type, dominant_color
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    status = excluded.status,
                    path_score = excluded.path_score,
                    access_time = COALESCE(files.access_time, excluded.access_time),
                    popularity_score = files.popularity_score,
                    file_type = excluded.file_type,
                    dominant_color = excluded.dominant_color;
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
                    float(file_row.get("path_score", 0.0)),
                    file_row.get("access_time"),
                    int(file_row.get("popularity_score", 0)),
                    str(file_row.get("file_type") or "other"),
                    file_row.get("dominant_color"),
                ),
            )

            conn.execute("DELETE FROM files_fts WHERE path = ?;", (file_row["path"],))
            if file_row["is_text"] and file_row["content_text"]:
                conn.execute(
                    "INSERT INTO files_fts(path, filename, content_text) VALUES (?, ?, ?);",
                    (file_row["path"], file_row["filename"], file_row["content_text"]),
                )

    def list_paths_under_root(self, root_path: str) -> list[str]:
        like_pattern = f"{root_path}{os.sep}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT path
                FROM files
                WHERE path = ? OR path LIKE ?;
                """,
                (root_path, like_pattern),
            ).fetchall()
        return [str(row["path"]) for row in rows]

    def delete_files(self, paths: list[str]) -> int:
        if not paths:
            return 0

        with self._connect() as conn:
            conn.executemany("DELETE FROM files_fts WHERE path = ?;", ((path,) for path in paths))
            conn.executemany("DELETE FROM files WHERE path = ?;", ((path,) for path in paths))
        return len(paths)

    def search_filename(self, terms: list[str], limit: int) -> list[dict[str, Any]]:
        if not terms:
            return []
        conditions = " AND ".join("lower(filename) LIKE ?" for _ in terms)
        params: list[Any] = [f"%{term.lower()}%" for term in terms] + [limit]
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT path, filename, extension, size_bytes, modified_at, preview_text, content_text,
                       path_score, access_time, popularity_score, file_type, dominant_color
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
        fts_terms = self._normalize_fts_terms(terms)
        if not fts_terms:
            return []
        fts_query = " AND ".join(f"{term}*" for term in fts_terms)
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
                    f.path_score,
                    f.access_time,
                    f.popularity_score,
                    f.file_type,
                    f.dominant_color,
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

    @staticmethod
    def _normalize_fts_terms(terms: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for term in terms:
            for part in re.findall(r"[A-Za-z0-9_]+", str(term).lower()):
                if part not in seen:
                    seen.add(part)
                    normalized.append(part)
        return normalized

    def search_paths(self, terms: list[str], limit: int) -> list[dict[str, Any]]:
        if not terms:
            return []
        conditions = " AND ".join("lower(path) LIKE ?" for _ in terms)
        params: list[Any] = [f"%{term.lower()}%" for term in terms] + [limit]
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT path, filename, extension, size_bytes, modified_at, preview_text, content_text,
                       path_score, access_time, popularity_score, file_type, dominant_color
                FROM files
                WHERE status IN ('indexed', 'metadata_only')
                  AND {conditions}
                ORDER BY path_score DESC, modified_at DESC
                LIMIT ?;
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def search_color(self, colors: list[str], limit: int) -> list[dict[str, Any]]:
        normalized = [color.lower() for color in colors if color]
        if not normalized:
            return []
        placeholders = ", ".join("?" for _ in normalized)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT path, filename, extension, size_bytes, modified_at, preview_text, content_text,
                       path_score, access_time, popularity_score, file_type, dominant_color
                FROM files
                WHERE file_type = 'image'
                  AND lower(dominant_color) IN ({placeholders})
                ORDER BY modified_at DESC
                LIMIT ?;
                """,
                [*normalized, limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def get_color_summary(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT dominant_color AS color, COUNT(*) AS count
                FROM files
                WHERE file_type = 'image'
                  AND dominant_color IS NOT NULL
                GROUP BY dominant_color
                ORDER BY count DESC, dominant_color ASC;
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def is_indexed_image(self, path: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM files
                WHERE path = ?
                  AND file_type = 'image'
                LIMIT 1;
                """,
                (path,),
            ).fetchone()
        return row is not None

    def add_search_history(self, query: str, searched_at: str, results_count: int = 0) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO search_history(query, searched_at, results_count) VALUES (?, ?, ?);",
                (query, searched_at, int(results_count)),
            )

    def add_click_history(
        self,
        query: str,
        file_path: str,
        rank: int,
        score: float,
        clicked_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO click_history(query, file_path, rank, score, clicked_at) VALUES (?, ?, ?, ?, ?);",
                (query, file_path, rank, score, clicked_at),
            )

    def get_recent_searches(self, limit: int = 10) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT query
                FROM search_history
                ORDER BY searched_at DESC, id DESC
                LIMIT ?;
                """,
                (limit,),
            ).fetchall()
        return [str(row["query"]) for row in rows]

    def get_query_suggestions(self, prefix: str, limit: int = 5) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT query
                FROM search_history
                WHERE lower(query) LIKE lower(?)
                ORDER BY searched_at DESC, id DESC
                LIMIT ?;
                """,
                (f"{prefix}%", limit),
            ).fetchall()
        return [str(row["query"]) for row in rows]

    def increment_popularity(self, path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE files
                SET popularity_score = COALESCE(popularity_score, 0) + 1,
                    access_time = ?
                WHERE path = ?;
                """,
                (utc_now_iso(), path),
            )
