from __future__ import annotations

import argparse

from src.database import Database
from src.indexing_engine import IndexingEngine
from src.query_engine import QueryEngine


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
    return parser


def parse_extensions(raw_values: list[str]) -> set[str]:
    extensions: set[str] = set()
    for value in raw_values:
        for part in value.split(","):
            ext = part.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = f".{ext}"
            extensions.add(ext)
    return extensions


def run_index(args: argparse.Namespace) -> int:
    database = Database(args.db)
    engine = IndexingEngine(database)
    report = engine.index(
        root_path=args.root,
        ignore_extensions=parse_extensions(args.ignore_ext),
        ignore_patterns=args.ignore_path,
        include_hidden=args.include_hidden,
        max_file_size_mb=args.max_file_size_mb,
    )

    print("Indexing complete.")
    print(f"Files seen:    {report['files_seen']}")
    print(f"Files indexed: {report['files_indexed']}")
    print(f"Files skipped: {report['files_skipped']}")
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "index":
        return run_index(args)
    if args.command == "search":
        return run_search(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
