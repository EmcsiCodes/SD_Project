from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.database import Database, utc_now_iso
from src.query_preprocessor import QueryBuilder, build_default_query_builder


class RankingStrategy(str, Enum):
    """Available ranking algorithms."""
    TFIDF = "tfidf"
    PATH = "path"
    DATE = "date"
    POPULARITY = "popularity"


@dataclass(slots=True)
class ParsedQuery:
    """Parsed query with separated qualifier terms and implicit terms."""
    path_terms: list[str] = field(default_factory=list)
    content_terms: list[str] = field(default_factory=list)
    color_terms: list[str] = field(default_factory=list)
    implicit_terms: list[str] = field(default_factory=list)

    def has_qualifiers(self) -> bool:
        return bool(self.path_terms or self.content_terms or self.color_terms)

    def all_terms(self) -> list[str]:
        return self.path_terms + self.content_terms + self.color_terms + self.implicit_terms


class QueryParser:
    """Parse queries with path:, content:, and color: qualifiers."""
    VALID_QUALIFIERS = {"path", "content", "color"}

    @classmethod
    def parse(cls, query_text: str) -> ParsedQuery:
        text = (query_text or "").strip()
        if not text:
            return ParsedQuery()

        parsed = ParsedQuery()
        consumed_spans: list[tuple[int, int]] = []

        pattern = re.compile(
            r'(?P<key>\w+):(?:(?P<quoted>"[^"]*"|\'[^\']*\')|(?P<value>\S+))',
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            key = match.group("key").lower()
            if key not in cls.VALID_QUALIFIERS:
                continue

            raw_value = match.group("quoted") or match.group("value") or ""
            value = raw_value.strip().strip('"').strip("'")
            if not value:
                continue

            terms = cls._split_terms(value)
            if key == "path":
                parsed.path_terms.extend(terms)
            elif key == "content":
                parsed.content_terms.extend(terms)
            else:
                parsed.color_terms.extend(terms)
            consumed_spans.append(match.span())

        # Remaining text becomes implicit terms
        stripped = cls._remove_spans(text, consumed_spans)
        parsed.implicit_terms.extend(cls._split_terms(stripped))

        # Deduplicate all term lists
        parsed.path_terms = cls._deduplicate(parsed.path_terms)
        parsed.content_terms = cls._deduplicate(parsed.content_terms)
        parsed.color_terms = cls._deduplicate(parsed.color_terms)
        parsed.implicit_terms = cls._deduplicate(parsed.implicit_terms)
        return parsed

    @staticmethod
    def _split_terms(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    @staticmethod
    def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
        if not spans:
            return text
        pieces: list[str] = []
        cursor = 0
        for start, end in sorted(spans):
            if cursor < start:
                pieces.append(text[cursor:start])
            cursor = end
        if cursor < len(text):
            pieces.append(text[cursor:])
        return " ".join(pieces)

    @staticmethod
    def _deduplicate(terms: list[str]) -> list[str]:
        seen: set[str] = set()
        deduplicated: list[str] = []
        for term in terms:
            if term not in seen:
                seen.add(term)
                deduplicated.append(term)
        return deduplicated


class BaseRanker:
    """Base class for ranking strategies."""
    def rank(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError


class TfidfRanker(BaseRanker):
    """Rank by FTS BM25 score plus filename match."""
    def rank(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for candidate in candidates:
            filename_score = float(candidate.get("filename_score", 0.0))
            bm25_rank = candidate.get("bm25_rank")
            content_score = 0.0
            if bm25_rank is not None:
                content_score = min(max(-float(bm25_rank), 0.0) * 10_000_000, 40.0)
            candidate["score"] = round(filename_score + content_score, 2)
        return sorted(candidates, key=lambda x: (-float(x.get("score", 0.0)), str(x.get("filename", "")).lower()))


class PathRanker(BaseRanker):
    """Rank by path location (prefer shallower paths) + filename."""
    def rank(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for candidate in candidates:
            score = float(candidate.get("path_score", 0.0))
            filename_score = float(candidate.get("filename_score", 0.0))
            depth = int(candidate.get("path_depth", 0))
            score += max(0.0, 20.0 - depth * 0.4)
            score += filename_score * 0.3
            candidate["score"] = round(score, 2)
        return sorted(candidates, key=lambda x: (-float(x.get("score", 0.0)), str(x.get("filename", "")).lower()))


class DateRanker(BaseRanker):
    """Rank newest modified files first, with filename matches as a tie-breaker."""
    def rank(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for candidate in candidates:
            filename_score = float(candidate.get("filename_score", 0.0))
            candidate["score"] = round(10.0 + filename_score * 0.2, 2)
        return sorted(
            candidates,
            key=lambda x: (
                str(x.get("modified_at") or ""),
                float(x.get("filename_score", 0.0)),
                str(x.get("filename", "")).lower(),
            ),
            reverse=True,
        )


class PopularityRanker(BaseRanker):
    """Rank by popularity (click frequency) + filename."""
    def rank(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for candidate in candidates:
            popularity = float(candidate.get("popularity_score", 0.0))
            filename_score = float(candidate.get("filename_score", 0.0))
            candidate["score"] = round(popularity * 2.0 + filename_score * 0.4, 2)
        return sorted(candidates, key=lambda x: (-float(x.get("score", 0.0)), str(x.get("filename", "")).lower()))


def get_ranker(strategy: RankingStrategy | str) -> BaseRanker:
    """Get a ranker instance for the given strategy."""
    if not isinstance(strategy, RankingStrategy):
        try:
            strategy = RankingStrategy(str(strategy).lower())
        except ValueError:
            strategy = RankingStrategy.TFIDF
    
    rankers: dict[RankingStrategy, type[BaseRanker]] = {
        RankingStrategy.TFIDF: TfidfRanker,
        RankingStrategy.PATH: PathRanker,
        RankingStrategy.DATE: DateRanker,
        RankingStrategy.POPULARITY: PopularityRanker,
    }
    return rankers[strategy]()


class QueryEngine:
    """Search engine with qualified query parsing and pluggable ranking."""
    def __init__(
        self,
        database: Database,
        ranking_strategy: RankingStrategy | str = RankingStrategy.TFIDF,
        query_builder: QueryBuilder | None = None,
    ) -> None:
        self.database = database
        self.ranking_strategy = ranking_strategy
        self.ranker = get_ranker(ranking_strategy)
        self.query_builder = query_builder or build_default_query_builder()

    def set_ranking_strategy(self, ranking_strategy: RankingStrategy | str) -> None:
        self.ranking_strategy = ranking_strategy
        self.ranker = get_ranker(ranking_strategy)

    def search(
        self,
        query_text: str,
        limit: int = 10,
        filename_only: bool = False,
        content_only: bool = False,
    ) -> list[dict[str, object]]:
        """Parse the query, run the selected search path, and record history."""
        processed_query = self.query_builder.build(query_text)
        parsed = QueryParser.parse(processed_query)
        if not parsed.has_qualifiers():
            results = self._legacy_search(processed_query, limit, filename_only, content_only)
        else:
            results = self._qualified_search(parsed, limit, filename_only, content_only)

        # Record search in history
        self.database.add_search_history(query_text, utc_now_iso(), len(results))

        return results

    def _qualified_search(
        self,
        parsed: ParsedQuery,
        limit: int,
        filename_only: bool,
        content_only: bool,
    ) -> list[dict[str, object]]:
        pool_size = max(limit * 5, 20)
        candidates: dict[str, dict[str, Any]] = {}

        path_rows = []
        if parsed.path_terms and not content_only:
            path_rows = self.database.search_paths(parsed.path_terms, pool_size)
        content_terms = parsed.content_terms + parsed.implicit_terms
        content_rows = []
        if content_terms and not filename_only:
            content_rows = self.database.search_content(content_terms, pool_size)
        color_rows = []
        if parsed.color_terms and not content_only:
            color_rows = self.database.search_color(parsed.color_terms, pool_size)

        for row in path_rows:
            path = str(row["path"])
            candidate = candidates.setdefault(path, self._candidate_template(row))
            candidate["matched_path"] = True
            candidate["filename_score"] = max(
                float(candidate["filename_score"]),
                self._filename_score(str(row["filename"]), parsed.path_terms),
            )
            candidate["path_score"] = max(float(candidate["path_score"]), float(row.get("path_score", 0.0)))

        for row in content_rows:
            path = str(row["path"])
            candidate = candidates.setdefault(path, self._candidate_template(row))
            candidate["matched_content"] = True
            candidate["filename_score"] = max(
                float(candidate["filename_score"]),
                self._filename_score(str(row["filename"]), content_terms),
            )
            bm25_rank = row.get("bm25_rank")
            if bm25_rank is not None:
                current = candidate["bm25_rank"]
                if current is None or float(bm25_rank) < float(current):
                    candidate["bm25_rank"] = float(bm25_rank)
            candidate["path_score"] = max(float(candidate["path_score"]), float(row.get("path_score", 0.0)))

        for row in color_rows:
            path = str(row["path"])
            candidate = candidates.setdefault(path, self._candidate_template(row))
            candidate["matched_color"] = True
            candidate["filename_score"] = max(
                float(candidate["filename_score"]),
                self._filename_score(str(row["filename"]), parsed.color_terms),
            )
            candidate["path_score"] = max(float(candidate["path_score"]), float(row.get("path_score", 0.0)))

        required_path = bool(parsed.path_terms and not content_only)
        required_content = bool(content_terms and not filename_only)
        required_color = bool(parsed.color_terms and not content_only)
        results = self._build_results(candidates, parsed.all_terms())
        results = [
            result
            for result in results
            if (
                (not required_path or result["matched_path"])
                and (not required_content or result["matched_content"])
                and (not required_color or result["matched_color"])
            )
        ]
        return self.ranker.rank(results)[:limit]

    def _legacy_search(
        self,
        query_text: str,
        limit: int,
        filename_only: bool,
        content_only: bool,
    ) -> list[dict[str, object]]:
        terms = self._parse_terms(query_text)
        if not terms:
            return []

        pool_size = max(limit * 5, 20)
        candidates: dict[str, dict[str, Any]] = {}

        if not content_only:
            for row in self.database.search_filename(terms, pool_size):
                path = str(row["path"])
                candidate = candidates.setdefault(path, self._candidate_template(row))
                candidate["matched_path"] = True
                candidate["filename_score"] = max(
                    float(candidate["filename_score"]),
                    self._filename_score(str(row["filename"]), terms),
                )

        if not filename_only:
            for row in self.database.search_content(terms, pool_size):
                path = str(row["path"])
                candidate = candidates.setdefault(path, self._candidate_template(row))
                candidate["matched_content"] = True
                candidate["filename_score"] = max(
                    float(candidate["filename_score"]),
                    self._filename_score(str(row["filename"]), terms),
                )
                bm25_rank = row.get("bm25_rank")
                if bm25_rank is not None:
                    current = candidate["bm25_rank"]
                    if current is None or float(bm25_rank) < float(current):
                        candidate["bm25_rank"] = float(bm25_rank)

        results = self._build_results(candidates, terms)
        return self.ranker.rank(results)[:limit]

    def _candidate_template(self, row: dict[str, Any]) -> dict[str, Any]:
        path = str(row["path"])
        return {
            "row": dict(row),
            "filename_score": 0.0,
            "bm25_rank": None,
            "path_score": float(row.get("path_score", 0.0)),
            "path_depth": path.count("/") + path.count("\\"),
            "matched_path": False,
            "matched_content": False,
            "matched_color": False,
        }

    def _build_results(self, candidates: dict[str, dict[str, Any]], search_terms: list[str]) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for candidate in candidates.values():
            row = candidate["row"]
            results.append(
                {
                    "path": str(row["path"]),
                    "filename": str(row["filename"]),
                    "extension": row.get("extension"),
                    "size_bytes": row.get("size_bytes"),
                    "modified_at": row.get("modified_at"),
                    "preview_text": row.get("preview_text"),
                    "content_text": row.get("content_text"),
                    "path_score": float(candidate.get("path_score", 0.0)),
                    "path_depth": int(candidate.get("path_depth", 0)),
                    "filename_score": float(candidate.get("filename_score", 0.0)),
                    "bm25_rank": candidate.get("bm25_rank"),
                    "popularity_score": float(row.get("popularity_score", 0.0)),
                    "file_type": row.get("file_type") or "other",
                    "dominant_color": row.get("dominant_color"),
                    "matched_path": bool(candidate.get("matched_path")),
                    "matched_content": bool(candidate.get("matched_content")),
                    "matched_color": bool(candidate.get("matched_color")),
                    "snippet": self._build_snippet(row.get("content_text"), search_terms, row.get("preview_text")),
                    "metadata": (
                        f"ext={row.get('extension') or '-'}, "
                        f"size={row.get('size_bytes') or 0} bytes, "
                        f"modified={row.get('modified_at') or '-'}, "
                        f"type={row.get('file_type') or 'other'}, "
                        f"color={row.get('dominant_color') or '-'}"
                    ),
                }
            )
        return results

    @staticmethod
    def format_results(results: list[dict[str, object]]) -> str:
        if not results:
            return "No results found."
        lines: list[str] = []
        for index, result in enumerate(results, start=1):
            score = float(result.get("score", 0.0))
            lines.append(f"{index}. {result['filename']}  score={score:.2f}")
            lines.append(f"   path: {result['path']}")
            lines.append(f"   meta: {result['metadata']}")
            snippet = result.get("snippet")
            if snippet:
                lines.append(f"   snippet: {snippet}")
        return "\n".join(lines)

    @staticmethod
    def _parse_terms(query_text: str) -> list[str]:
        terms = re.findall(r"[A-Za-z0-9_]+", query_text.lower())
        return list(dict.fromkeys(terms))

    @staticmethod
    def _filename_score(filename: str, terms: list[str]) -> float:
        lowered = filename.lower()
        score = 0.0
        for term in terms:
            if lowered == term:
                score += 20.0
            elif lowered.startswith(term):
                score += 12.0
            elif term in lowered:
                score += 8.0
        return score

    @staticmethod
    def _build_snippet(content_text: object, terms: list[str], fallback: object) -> str:
        text = str(content_text) if content_text else ""
        if not text:
            return str(fallback) if fallback else ""

        lowered = text.lower()
        match_pos = -1
        for term in terms:
            idx = lowered.find(term)
            if idx >= 0:
                match_pos = idx
                break

        radius = 70
        if match_pos < 0:
            return " ".join(text[: 2 * radius].split())

        start = max(0, match_pos - radius)
        end = min(len(text), match_pos + radius)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = f"... {snippet}"
        if end < len(text):
            snippet = f"{snippet} ..."
        return " ".join(snippet.split())
