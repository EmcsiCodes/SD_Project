from __future__ import annotations

from collections.abc import Iterable


def parse_extensions(raw_values: Iterable[str]) -> set[str]:
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


def parse_patterns(raw_text: str) -> list[str]:
    patterns: list[str] = []
    for line in raw_text.splitlines():
        for part in line.split(","):
            pattern = part.strip()
            if pattern:
                patterns.append(pattern)
    return patterns
