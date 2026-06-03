from __future__ import annotations

import fnmatch
import mimetypes
import os
import time
from datetime import datetime, timezone
from queue import Queue
from threading import Lock, Thread
from typing import Any

try:
    from PIL import Image
except ImportError:
    Image = None

from src.database import Database, utc_now_iso


class FileProcessor:
    """Strategy interface for extracting searchable file metadata."""

    def can_process(self, extension: str | None, mime_type: str | None) -> bool:
        raise NotImplementedError

    def process(self, path: str, extension: str | None, mime_type: str | None) -> dict[str, object]:
        raise NotImplementedError


class TextFileProcessor(FileProcessor):
    def __init__(self, engine: "IndexingEngine") -> None:
        self.engine = engine

    def can_process(self, extension: str | None, mime_type: str | None) -> bool:
        return self.engine._is_likely_text(extension, mime_type)

    def process(self, path: str, extension: str | None, mime_type: str | None) -> dict[str, object]:
        content_text, preview_text, is_text = self.engine._extract_text(path, extension, mime_type)
        return {
            "content_text": content_text,
            "preview_text": preview_text,
            "is_text": is_text,
            "status": "indexed" if is_text else "metadata_only",
            "file_type": "text" if is_text else "other",
            "dominant_color": None,
        }


class ImageFileProcessor(FileProcessor):
    IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
    COLOR_PALETTE = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "gray": (128, 128, 128),
        "red": (220, 40, 40),
        "orange": (230, 130, 30),
        "yellow": (235, 220, 60),
        "green": (45, 150, 75),
        "blue": (45, 95, 210),
        "purple": (130, 75, 190),
        "pink": (220, 100, 170),
        "brown": (120, 75, 35),
    }

    def can_process(self, extension: str | None, mime_type: str | None) -> bool:
        return bool(
            (extension and extension.lower() in self.IMAGE_EXTENSIONS)
            or (mime_type and mime_type.startswith("image/"))
        )

    def process(self, path: str, extension: str | None, mime_type: str | None) -> dict[str, object]:
        dominant_color = self._dominant_color(path)
        preview = f"Image file. Dominant color: {dominant_color or 'unknown'}."
        return {
            "content_text": None,
            "preview_text": preview,
            "is_text": False,
            "status": "metadata_only",
            "file_type": "image",
            "dominant_color": dominant_color,
        }

    def _dominant_color(self, path: str) -> str | None:
        if Image is None:
            return None

        try:
            with Image.open(path) as image:
                image.thumbnail((80, 80))
                pixels = image.convert("RGB").getdata()
                counts: dict[str, int] = {}
                for pixel in pixels:
                    color = self._nearest_color(pixel)
                    counts[color] = counts.get(color, 0) + 1
        except Exception:
            return None
        return max(counts, key=counts.get) if counts else None

    def _nearest_color(self, pixel: tuple[int, int, int]) -> str:
        red, green, blue = pixel
        return min(
            self.COLOR_PALETTE,
            key=lambda name: (
                (red - self.COLOR_PALETTE[name][0]) ** 2
                + (green - self.COLOR_PALETTE[name][1]) ** 2
                + (blue - self.COLOR_PALETTE[name][2]) ** 2
            ),
        )


class MetadataFileProcessor(FileProcessor):
    def can_process(self, extension: str | None, mime_type: str | None) -> bool:
        return True

    def process(self, path: str, extension: str | None, mime_type: str | None) -> dict[str, object]:
        return {
            "content_text": None,
            "preview_text": None,
            "is_text": False,
            "status": "metadata_only",
            "file_type": "other",
            "dominant_color": None,
        }


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
        self.processors: list[FileProcessor] = [
            TextFileProcessor(self),
            ImageFileProcessor(),
            MetadataFileProcessor(),
        ]

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
        report_lock = Lock()
        task_queue: Queue[tuple[str, int] | None] = Queue()
        result_queue: Queue[dict[str, Any] | None] = Queue()

        def print_progress(force: bool = False) -> None:
            nonlocal last_progress_seen
            if progress_every == 0:
                return
            with report_lock:
                files_seen = int(report["files_seen"])
                files_indexed = int(report["files_indexed"])
                files_skipped = int(report["files_skipped"])
                errors_count = int(report["errors_count"])
            if not force and files_seen % progress_every != 0:
                return
            if files_seen == last_progress_seen:
                return
            elapsed = max(time.monotonic() - started, 0.001)
            rate = files_seen / elapsed
            print(
                "[progress] "
                f"seen={files_seen} "
                f"indexed={files_indexed} "
                f"skipped={files_skipped} "
                f"errors={errors_count} "
                f"elapsed={elapsed:.1f}s "
                f"rate={rate:.1f} files/s",
                flush=True,
            )
            last_progress_seen = files_seen

        def reader_worker() -> None:
            while True:
                task = task_queue.get()
                try:
                    if task is None:
                        return
                    path, size_bytes = task
                    result_queue.put({"kind": "file", "row": self._build_file_row(path, size_bytes=size_bytes)})
                except Exception as exc:
                    result_queue.put(
                        {
                            "kind": "error",
                            "path": task[0] if task else root,
                            "error_type": type(exc).__name__,
                            "message": str(exc) or repr(exc),
                        }
                    )
                finally:
                    task_queue.task_done()

        def writer_worker() -> None:
            while True:
                result = result_queue.get()
                try:
                    if result is None:
                        return
                    if result["kind"] == "file":
                        self.database.upsert_file(result["row"])
                        with report_lock:
                            report["files_indexed"] += 1
                    else:
                        with report_lock:
                            report["errors_count"] += 1
                        self.database.log_error(
                            run_id,
                            str(result["path"]),
                            str(result["error_type"]),
                            str(result["message"]),
                        )
                    print_progress()
                finally:
                    result_queue.task_done()

        worker_count = 4
        readers = [Thread(target=reader_worker, daemon=True) for _ in range(worker_count)]
        writer = Thread(target=writer_worker, daemon=True)
        writer.start()
        for reader in readers:
            reader.start()

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
                with report_lock:
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
                        with report_lock:
                            report["files_skipped"] += 1
                        continue

                    indexed_paths.add(os.path.abspath(full_path))
                    task_queue.put((full_path, size_bytes))
                except Exception as exc:
                    result_queue.put(
                        {
                            "kind": "error",
                            "path": full_path,
                            "error_type": type(exc).__name__,
                            "message": str(exc) or repr(exc),
                        }
                    )
                finally:
                    print_progress()

        for _ in readers:
            task_queue.put(None)
        task_queue.join()
        for reader in readers:
            reader.join()

        result_queue.put(None)
        result_queue.join()
        writer.join()

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

        extracted = self._process_file(path, extension, mime_type)
        path_score = self._compute_path_score(path, size_bytes, extension)

        return {
            "path": os.path.abspath(path),
            "filename": filename,
            "extension": extension,
            "size_bytes": int(size_bytes),
            "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "mime_type": mime_type,
            "is_text": bool(extracted["is_text"]),
            "content_text": extracted["content_text"],
            "preview_text": extracted["preview_text"],
            "indexed_at": utc_now_iso(),
            "status": extracted["status"],
            "path_score": path_score,
            "file_type": extracted["file_type"],
            "dominant_color": extracted["dominant_color"],
        }

    def _process_file(self, path: str, extension: str | None, mime_type: str | None) -> dict[str, object]:
        for processor in self.processors:
            if processor.can_process(extension, mime_type):
                return processor.process(path, extension, mime_type)
        return MetadataFileProcessor().process(path, extension, mime_type)

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
    def _compute_path_score(path: str, size_bytes: int, extension: str | None) -> float:
        normalized = path.replace("\\", "/")
        depth = normalized.count("/")
        score = max(0.0, 20.0 - depth * 0.5)

        preferred_extensions = {
            ".py",
            ".js",
            ".ts",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".md",
            ".txt",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".html",
            ".css",
        }
        if extension and extension.lower() in preferred_extensions:
            score += 10.0

        size_kb = size_bytes / 1024
        if 1 <= size_kb <= 10240:
            score += 5.0
        elif size_kb > 10240:
            score -= 2.0

        return round(score, 2)

    @staticmethod
    def _decode(raw: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
