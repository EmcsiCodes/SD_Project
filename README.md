# SD_Project

Simple local file search engine implementation based on `ARCHITECTURE.md`.

Iteration 2 is now merged into the same codebase as Iteration 1, so the project has one search engine with optional advanced parsing, ranking, and history tracking.

This project keeps the assignment rule in place:
- `ARCHITECTURE.md` is tracked in the main project and describes the C4 design.

## Features (Iteration 1)
- Recursive file traversal
- Ignore rules (hidden files, extension, path pattern, max size)
- Metadata + text extraction for common text file types
- SQLite persistence
- Qualified queries like `path:src content:error`
- Path scoring computed at index time
- Swappable ranking strategies (`tfidf`, `path`, `date`, `popularity`)
- Search history and query suggestions
- Observer-based click tracking for popularity ranking
- Separate Iteration 2 test coverage, while keeping Iteration 1 intact

## Project Structure
```text
src/
  main.py                # CLI
  indexing_engine.py     # indexing pipeline + path scoring
  query_engine.py        # query parsing + ranking + snippets
  query_parser.py        # Iteration 2 qualified query parser
  ranking_strategies.py  # Iteration 2 ranking strategies
  search_history.py      # Iteration 2 history + observers
  database.py            # schema + database operations
  ui_server.py           # local HTTP server for the browser UI
  ui/                    # HTML/CSS/JS assets
tests/
  test_iteration1.py     # iteration 1 integration tests

1. Index a folder:
```powershell
python -m src.main index . --db .local_search.db
```

2. Search:
```powershell
python -m src.main search "architecture" --db .local_search.db --limit 10
```

Optional ranking strategy:
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
