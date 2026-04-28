# Architecture

## Purpose
Local File Search Engine indexes files from a local directory and supports fast search by filename, textual content, and metadata.

Iteration 1 scope:
- recursive traversal
- ignore rules
- metadata + text extraction
- DB persistence
- full-text search
- result snippets
- robust per-file error handling

## Design Principles
1. Separate indexing from querying.
2. Keep infrastructure replaceable (DB, extractors).
3. Prefer correctness and clear data model over early optimization.
4. Fail per file, not per run.
5. Leave extension points for incremental indexing and richer ranking.

## C4 - System Context
Primary actor:
- User: configures root path/ignore rules, starts indexing, runs searches, views results.

External systems:
- Local File System: files, folders, timestamps, permissions.
- DBMS: indexed records + full-text indexes.
- OS services (future): file change notifications.

Main interactions:
1. User interacts with Search Engine.
2. Search Engine reads from Local File System.
3. Search Engine writes/reads indexed data in DBMS.

## C4 - Container View
1. Presentation Layer (CLI + local Web UI): accepts commands or form input, shows progress/results/errors.
2. Indexing Engine: crawl -> filter -> inspect -> extract -> normalize -> store.
3. Query Engine: parse query -> search DB -> rank -> build snippets -> format.
4. Database: stores files/content/metadata/runs/errors; provides full-text search.
5. Local File System (external): source of files.

Main container flow:
1. User starts indexing in UI/CLI.
2. UI/CLI invokes Indexing Engine.
3. Indexing Engine reads file system and writes DB.
4. User submits query in UI/CLI.
5. UI/CLI invokes Query Engine.
6. Query Engine reads DB and returns ranked results.

## C4 - Component View
Indexing Engine components:
- FileCrawler: recursive walk and candidate discovery.
- IgnorePolicy: skip rules (path, extension, hidden, size, config).
- FileInspector: metadata collection.
- ContentExtractor: text extraction for supported files.
- DocumentNormalizer: unified internal document shape.
- IndexWriter: insert/update with transaction safety.
- IndexingReporter: progress and summary.
- ErrorHandler: classify/log/recover when possible.

Query Engine components:
- QueryParser: tokenize/normalize fields.
- SearchService: orchestrate DB queries and merge results.
- RankingStrategy: combine relevance signals.
- SnippetBuilder: generate preview around matches.
- ResultFormatter: output shape for UI/CLI.

Persistence components:
- FileRepository
- SearchRepository
- IndexStateRepository
- SchemaManager

## C4 - Code/Class View (Suggested Modules)
```text
src/
  main.py             CLI orchestration
  indexing_engine.py  indexing pipeline
  query_engine.py     search pipeline
  database.py         schema + persistence
  ui_server.py        browser UI server + HTTP endpoints
  ui/                 static browser assets
```

Core domain objects:
- IndexedDocument: path, filename, extension, size, timestamps, content_text, preview_text, mime_type.
- SearchQuery: raw text, normalized terms, search scope flags, limit.
- SearchResult: path, filename, score, snippet, metadata summary.

## Data Model (Iteration 1)
1. files
- id, path (unique), filename, extension, size_bytes
- created_at, modified_at, mime_type, is_text
- content_text, preview_text, indexed_at, status

2. indexing_runs
- id, started_at, finished_at
- files_seen, files_indexed, files_skipped, errors_count
- report_json

3. indexing_errors
- id, run_id, path, error_type, message, occurred_at

Notes:
- Use DB full-text index on content (and optionally filename).
- Keep metadata even if not immediately queried.
- Cache preview_text to reduce query-time work.

## Main Workflows
Indexing flow:
1. User selects root + settings.
2. Crawl files and apply ignore policy.
3. Collect metadata and extract text when supported.
4. Normalize document model.
5. Upsert into DB.
6. Track progress and show final report.

Search flow:
1. User submits query.
2. Parse + normalize query.
3. Run filename/content/metadata DB search.
4. Rank and build snippets.
5. Return formatted results.

## Error Handling
Policy: continue indexing whenever a single file fails.

Typical cases:
- permission denied -> log + skip
- unsupported/binary content -> metadata-only record
- decode/extraction failure -> mark error + continue
- symlink loop -> detect + skip
- transient DB write failure -> retry when safe; otherwise stop current batch with clear report

## Quality Attributes
- Modifiability: clear separation of concerns.
- Performance: DB full-text search + lean query path.
- Reliability: defensive processing + explicit run/error logs.
- Extensibility: hooks for incremental indexing, richer extractors, file watchers, improved ranking.

## Key Decisions
1. DBMS over custom index files.
2. Separate indexing pipeline from query pipeline.
3. Persist metadata even when not immediately needed.
4. Use native DB full-text search.
5. Always return snippets/previews with results.

## Future Evolution
1. Incremental indexing (mtime/hash based).
2. Additional extractors (PDF, DOCX, etc.).
3. Background indexing jobs.
4. Better ranking (filename/recency boosts).
5. File-system event driven updates.

## Requirement Mapping
- C4 levels covered: context, containers, components, code/class.
- Iteration 1 covered: crawl, filter, extract, store, search, preview, error handling.
- Forward-compatible structure for later iterations.
- **Future-proofing**: the design already leaves room for incremental indexing and richer search in later iterations.
