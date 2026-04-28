from __future__ import annotations

import argparse
import os

from src.database import Database
from src.input_parsing import parse_extensions
from src.indexing_engine import IndexingEngine
from src.query_engine import QueryEngine
from src.ui_server import ServerConfig, serve_ui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-search",
        description="Simple local file search engine.",
    )
    subparsers = parser.add_subparsers(dest="command")

    index_parser = subparsers.add_parser("index", help="Index a local directory.")
    index_parser.add_argument("root", nargs="?", default=".", help="Folder to index.")
    index_parser.add_argument("--db", default=".local_search.db", help="SQLite DB file.")
    index_parser.add_argument(
        "--ignore-ext",
        action="append",
        default=[],
        help="Extensions to skip (repeat or comma-separated, e.g. .png,.jpg).",
    )
    index_parser.add_argument(
        "--ignore-path",
        action="append",
        default=[],
        help="Glob path patterns to skip (repeatable).",
    )
    index_parser.add_argument("--include-hidden", action="store_true", help="Include hidden files/folders.")
    index_parser.add_argument("--max-file-size-mb", type=int, default=2, help="Skip files bigger than this size.")
    index_parser.add_argument(
        "--progress-every",
        type=int,
        default=250,
        help="Print progress every N seen files (0 disables).",
    )

    search_parser = subparsers.add_parser("search", help="Search indexed files.")
    search_parser.add_argument("query", help="Text to search for.")
    search_parser.add_argument("--db", default=".local_search.db", help="SQLite DB file.")
    search_parser.add_argument(
        "--limit",
        type=int,
        nargs="?",
        const=10,
        default=10,
        help="Max number of results (optional value, default 10).",
    )
    search_parser.add_argument("--filename-only", action="store_true", help="Search only in file names.")
    search_parser.add_argument("--content-only", action="store_true", help="Search only in file content.")

    serve_parser = subparsers.add_parser("serve", help="Launch the browser UI.")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    serve_parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    serve_parser.add_argument("--db", default=".local_search.db", help="Default SQLite DB file.")
    serve_parser.add_argument("--root", default=".", help="Default folder shown in the UI.")
    serve_parser.add_argument("--open-browser", action="store_true", help="Open the UI in the browser.")
    return parser


def run_index(args: argparse.Namespace) -> int:
    database = Database(args.db)
    engine = IndexingEngine(database)
    if args.progress_every > 0:
        print(
            f"Indexing '{args.root}' -> '{args.db}' "
            f"(progress every {args.progress_every} files)",
            flush=True,
        )
    report = engine.index(
        root_path=args.root,
        ignore_extensions=parse_extensions(args.ignore_ext),
        ignore_patterns=args.ignore_path,
        include_hidden=args.include_hidden,
        max_file_size_mb=args.max_file_size_mb,
        progress_every=args.progress_every,
    )

    print("Indexing complete.")
    print(f"Files seen:    {report['files_seen']}")
    print(f"Files indexed: {report['files_indexed']}")
    print(f"Files skipped: {report['files_skipped']}")
    print(f"Files deleted: {report.get('files_deleted', 0)}")
    print(f"Errors:        {report['errors_count']}")
    print(f"Duration:      {report['duration_seconds']} s")
    return 0


def run_search(args: argparse.Namespace) -> int:
    if args.filename_only and args.content_only:
        print("Choose only one of --filename-only or --content-only.")
        return 2

    database = Database(args.db)
    database.init_schema()
    engine = QueryEngine(database)
    results = engine.search(
        query_text=args.query,
        limit=max(1, args.limit),
        filename_only=args.filename_only,
        content_only=args.content_only,
    )
    print(engine.format_results(results))
    return 0


def run_serve(args: argparse.Namespace) -> int:
    config = ServerConfig(
        host=args.host,
        port=args.port,
        default_root=os.path.abspath(args.root),
        default_db=os.path.abspath(args.db),
        open_browser=args.open_browser,
    )
    serve_ui(config)
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "index":
        return run_index(args)
    if args.command == "search":
        return run_search(args)
    if args.command == "serve":
        return run_serve(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
