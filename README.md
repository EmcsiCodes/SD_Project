# SD_Project

Simple local file search engine implementation based on `ARCHITECTURE.md`.

Iteration 3 is merged into the same codebase, so the project has one search engine with indexing, advanced queries, image color search, and a browser UI.

This project keeps the assignment rule in place:
- `ARCHITECTURE.md` is tracked in the main project and describes the C4 design.

## Features (Iteration 1)
- Recursive file traversal
- Ignore rules (hidden files, extension, path pattern, max size)
- Metadata + text extraction for common text file types
- SQLite persistence
- Qualified queries like `path:src content:error`
- Image queries like `color:red`
- Path scoring computed at index time
- Swappable ranking strategies (`tfidf`, `path`, `date`, `popularity`)
- Search history and query suggestions
- Popularity counters for popularity ranking
- Browser UI for indexing and searching
- Context-aware widgets for image-heavy, log-heavy, and color-search results
- Producer-consumer indexing with worker readers and one database writer
- Decorator-based query preprocessing

## Project Structure
```text
src/
  main.py                # CLI
  indexing_engine.py     # indexing pipeline + path scoring
  query_engine.py        # query parsing + ranking + snippets
  query_preprocessor.py  # decorator-based query rewriting
  widgets.py             # context-aware widget factory
  database.py            # schema + database operations
  ui_server.py           # local HTTP server for the browser UI
  ui/                    # HTML/CSS/JS assets
tests/
  test_iteration3.py     # Iteration 3 parser, image, and widget tests
```

## Usage

Install the only external dependency used for image color extraction:

```powershell
pip install -r requirements.txt
```

1. Index a folder:
```powershell
python -m src.main index . --db .local_search.db
```

2. Search:
```powershell
python -m src.main search "architecture" --db .local_search.db --limit 10
```

Optional ranking strategy:
```powershell
python -m src.main search "architecture" --db .local_search.db --ranking date
```

Color search:
```powershell
python -m src.main search "color:red" --db .local_search.db
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

Enable the tracked pre-commit hook once per clone:

```powershell
git config core.hooksPath .githooks
```

Suggested final tag for Iteration 3:

```powershell
git tag v0.3.0
```
