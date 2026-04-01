# SD_Project

Simple local file search engine implementation based on `ARCHITECTURE.md`.

This project keeps the assignment rule in place:
- `ARCHITECTURE.md` is tracked in the main project and describes the C4 design.

## Features (Iteration 1)
- Recursive file traversal
- Ignore rules (hidden files, extension, path pattern, max size)
- Metadata + text extraction for common text file types
- SQLite persistence
- Full-text search (SQLite FTS5) + filename search
- Result snippets
- Per-file error handling with run/error logging

## Project Structure
```text
src/
  main.py                # CLI
  indexing_engine.py     # indexing pipeline
  query_engine.py        # query + ranking + snippets
  database.py            # schema + database operations
```

## Usage
Run from repository root.

1. Index a folder:
```powershell
python -m src.main index . --db .local_search.db
```

2. Search:
```powershell
python -m src.main search "architecture" --db .local_search.db --limit 10
```

`--limit` can also be used without a value and defaults to 10:
```powershell
python -m src.main search "architecture" --db .local_search.db --limit
```

## Useful Options
- `index --ignore-ext ".png,.jpg" --ignore-path "*node_modules*"`
- `index --max-file-size-mb 5`
- `index --include-hidden`
- `index --progress-every 100` (print indexing progress every 100 seen files, use `0` to disable)
- `search --filename-only`
- `search --content-only`
