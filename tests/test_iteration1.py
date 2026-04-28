from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
import gc
from pathlib import Path
import shutil

from src.database import Database
from src.indexing_engine import IndexingEngine
from src.query_engine import QueryEngine


class Iteration1IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_path = Path(tempfile.mkdtemp())
        self.root = self.temp_path / "fixture"
        self.root.mkdir()
        self.db_path = self.temp_path / "search.db"
        self.database = Database(str(self.db_path))
        self.indexing = IndexingEngine(self.database)
        self.query = QueryEngine(self.database)

    def tearDown(self) -> None:
        self.query = None
        self.indexing = None
        self.database = None
        gc.collect()

        for _ in range(10):
            try:
                shutil.rmtree(self.temp_path)
                break
            except PermissionError:
                time.sleep(0.1)
        else:
            shutil.rmtree(self.temp_path)

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_bytes(self, relative_path: str, content: bytes) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_index(self, **overrides: object) -> dict[str, int | float]:
        options = {
            "root_path": str(self.root),
            "ignore_extensions": set(),
            "ignore_patterns": [],
            "include_hidden": False,
            "max_file_size_mb": 2,
            "progress_every": 0,
        }
        options.update(overrides)
        return self.indexing.index(**options)

    def list_indexed_files(self) -> list[tuple[str, str]]:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT filename, status FROM files ORDER BY filename"
            ).fetchall()

    def test_indexing_respects_hidden_binary_and_file_size_rules(self) -> None:
        self.write_text("readme.txt", "Architecture notes and search engine design.")
        self.write_text("docs/report.md", "The indexing engine stores metadata snippets.")
        self.write_text(".hidden/secret.txt", "hidden content should stay out of the index")
        self.write_bytes("image.bin", bytes(range(16)))
        self.write_text("large.txt", "a" * (3 * 1024 * 1024))

        report = self.run_index()

        self.assertEqual(report["files_seen"], 4)
        self.assertEqual(report["files_indexed"], 3)
        self.assertEqual(report["files_skipped"], 1)
        self.assertEqual(report["errors_count"], 0)
        self.assertEqual(
            self.list_indexed_files(),
            [
                ("image.bin", "metadata_only"),
                ("readme.txt", "indexed"),
                ("report.md", "indexed"),
            ],
        )
        self.assertEqual(self.query.search("hidden"), [])
        self.assertEqual(
            [result["filename"] for result in self.query.search("image", filename_only=True)],
            ["image.bin"],
        )

    def test_content_ranking_preserves_fts_order(self) -> None:
        self.write_text("alpha.txt", "architecture search engine")
        self.write_text("zeta.txt", "architecture architecture architecture search engine design")

        self.run_index()
        results = self.query.search("architecture", content_only=True)

        self.assertGreaterEqual(len(results), 2)
        self.assertEqual(results[0]["filename"], "zeta.txt")
        self.assertGreater(float(results[0]["score"]), float(results[1]["score"]))

    def test_reindex_removes_deleted_files(self) -> None:
        removable = self.write_text("remove-me.txt", "stale records should disappear")
        self.write_text("keep-me.txt", "fresh content stays searchable")

        self.run_index()
        removable.unlink()

        report = self.run_index()

        self.assertEqual(report["files_deleted"], 1)
        self.assertEqual(self.query.search("remove", filename_only=True), [])
        self.assertEqual(
            [result["filename"] for result in self.query.search("keep", filename_only=True)],
            ["keep-me.txt"],
        )


if __name__ == "__main__":
    unittest.main()
