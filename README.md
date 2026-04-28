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
- Re-index cleanup for deleted files
- Per-file error handling with run/error logging
- Browser UI on top of the same indexing/query engine
- Integration tests for indexing and search behavior

## Project Structure
```text
src/
  main.py                # CLI
  indexing_engine.py     # indexing pipeline
  query_engine.py        # query + ranking + snippets
  database.py            # schema + database operations
  ui_server.py           # local HTTP server for the browser UI
  ui/                    # HTML/CSS/JS assets
tests/
  test_iteration1.py     # iteration 1 integration tests
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

3. Launch the browser UI:
```powershell
python -m src.main serve --open-browser
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
- `serve --port 8765 --db .local_search.db --root .`

## Verification
Run the integration suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```
