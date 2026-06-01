# Changelog

All notable changes to this project are documented in this file.

## [0.3.0] - 2026-06-01

### Added
- Iteration 3 image indexing with dominant color extraction for `color:<name>` queries.
- File processor strategy classes for text, image, and metadata-only files.
- Producer-consumer indexing pipeline with reader worker threads and a single database writer.
- Decorator-based query preprocessor pipeline for sanitization and simple image synonyms.
- Context-aware widgets for gallery, log analysis, and color matches.
- Tracked pre-commit hook under `.githooks/pre-commit`.

### Changed
- Search results now include `file_type` and `dominant_color` metadata.
- Browser UI displays active widgets and image color swatches.

## [0.2.0] - 2026-06-01

### Added
- Qualified query support, ranking strategies, search history, popularity ranking, and browser UI.
