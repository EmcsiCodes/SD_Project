from __future__ import annotations

import fnmatch
import mimetypes
import os
import time
from datetime import datetime, timezone

from src.database import Database, utc_now_iso


class IndexingEngine:
    TEXT_EXTENSIONS = {
        ".c",
        ".cpp",
        ".css",
        ".csv",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".log",
        ".md",
        ".py",
        ".sql",
        ".toml",
        ".ts",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }

    def __init__(self, database: Database) -> None:
        self.database = database

    def index(
        self,
        root_path: str,
        ignore_extensions: set[str] | None = None,
        ignore_patterns: list[str] | None = None,
        include_hidden: bool = False,
        max_file_size_mb: int = 2,
        progress_every: int = 250,
    ) -> dict[str, int | float]:
        ignore_extensions = {ext.lower() for ext in (ignore_extensions or set())}
        ignore_patterns = ignore_patterns or []
        max_file_size_bytes = max(1, max_file_size_mb) * 1024 * 1024
        root = os.path.abspath(root_path)

        self.database.init_schema()
        run_id = self.database.start_run()

        started = time.monotonic()
        report = {
            "files_seen": 0,
            "files_indexed": 0,
            "files_skipped": 0,
            "files_deleted": 0,
            "errors_count": 0,
            "duration_seconds": 0.0,
        }
        progress_every = max(0, progress_every)
        last_progress_seen = -1
        indexed_paths: set[str] = set()

        def print_progress(force: bool = False) -> None:
            nonlocal last_progress_seen
            if progress_every == 0:
                return
            if not force and report["files_seen"] % progress_every != 0:
                return
            if report["files_seen"] == last_progress_seen:
                return
            elapsed = max(time.monotonic() - started, 0.001)
            rate = report["files_seen"] / elapsed
            print(
                "[progress] "
                f"seen={report['files_seen']} "
                f"indexed={report['files_indexed']} "
                f"skipped={report['files_skipped']} "
                f"errors={report['errors_count']} "
                f"elapsed={elapsed:.1f}s "
                f"rate={rate:.1f} files/s",
                flush=True,
            )
            last_progress_seen = report["files_seen"]

        for current_dir, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            filtered_dirs: list[str] = []
            for dirname in dirnames:
                full_dir = os.path.join(current_dir, dirname)
                if os.path.islink(full_dir):
                    continue
                if self._should_ignore(full_dir, is_dir=True, include_hidden=include_hidden, ignore_patterns=ignore_patterns):
                    continue
                filtered_dirs.append(dirname)
            dirnames[:] = filtered_dirs

            for filename in filenames:
                full_path = os.path.join(current_dir, filename)
                report["files_seen"] += 1
                try:
                    size_bytes = os.path.getsize(full_path)
                    if self._should_ignore(
                        full_path,
                        is_dir=False,
                        include_hidden=include_hidden,
                        ignore_patterns=ignore_patterns,
                        ignore_extensions=ignore_extensions,
                        size_bytes=size_bytes,
                        max_file_size_bytes=max_file_size_bytes,
                    ):
                        report["files_skipped"] += 1
                        continue

                    indexed_paths.add(os.path.abspath(full_path))
                    file_row = self._build_file_row(full_path, size_bytes=size_bytes)
                    self.database.upsert_file(file_row)
                    report["files_indexed"] += 1
                except Exception as exc:
                    report["errors_count"] += 1
                    self.database.log_error(
                        run_id,
                        full_path,
                        type(exc).__name__,
                        str(exc) or repr(exc),
                    )
                finally:
                    print_progress()

        stale_paths = [
            path
            for path in self.database.list_paths_under_root(root)
            if path not in indexed_paths
        ]
        report["files_deleted"] = self.database.delete_files(stale_paths)
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        print_progress(force=True)
        self.database.finish_run(run_id, report)
        return report

    def _build_file_row(self, path: str, size_bytes: int) -> dict[str, object]:
        stat = os.stat(path)
        filename = os.path.basename(path)
        extension = os.path.splitext(filename)[1].lower() or None
        mime_type, _ = mimetypes.guess_type(path)

        content_text, preview_text, is_text = self._extract_text(path, extension, mime_type)
        status = "indexed" if is_text else "metadata_only"

        return {
            "path": os.path.abspath(path),
            "filename": filename,
            "extension": extension,
            "size_bytes": int(size_bytes),
            "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "mime_type": mime_type,
            "is_text": is_text,
            "content_text": content_text,
            "preview_text": preview_text,
            "indexed_at": utc_now_iso(),
            "status": status,
        }

    def _extract_text(
        self,
        path: str,
        extension: str | None,
        mime_type: str | None,
    ) -> tuple[str | None, str | None, bool]:
        if not self._is_likely_text(extension, mime_type):
            return None, None, False

        with open(path, "rb") as file:
            raw = file.read(1_000_000)

        if b"\x00" in raw:
            return None, None, False

        text = self._decode(raw)
        preview = " ".join(text.split())[:240] if text else None
        return text, preview, True

    def _should_ignore(
        self,
        path: str,
        is_dir: bool,
        include_hidden: bool,
        ignore_patterns: list[str],
        ignore_extensions: set[str] | None = None,
        size_bytes: int | None = None,
        max_file_size_bytes: int | None = None,
    ) -> bool:
        normalized = path.replace("\\", "/")
        name = os.path.basename(path)

        if not include_hidden:
            parts = [part for part in os.path.normpath(path).split(os.sep) if part]
            if any(part.startswith(".") for part in parts):
                return True

        for pattern in ignore_patterns:
            if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(name, pattern):
                return True

        if not is_dir and ignore_extensions:
            extension = os.path.splitext(name)[1].lower()
            if extension in ignore_extensions:
                return True

        if (
            not is_dir
            and size_bytes is not None
            and max_file_size_bytes is not None
            and size_bytes > max_file_size_bytes
        ):
            return True

        return False

    def _is_likely_text(self, extension: str | None, mime_type: str | None) -> bool:
        if extension and extension in self.TEXT_EXTENSIONS:
            return True
        if mime_type and mime_type.startswith("text/"):
            return True
        return False

    @staticmethod
    def _decode(raw: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
