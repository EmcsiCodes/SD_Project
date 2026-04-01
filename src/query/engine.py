from __future__ import annotations

import re

from src.persistence.db import Database


class QueryEngine:
    def __init__(self, database: Database) -> None:
        self.database = database

    def search(
        self,
        query_text: str,
        limit: int = 10,
        filename_only: bool = False,
        content_only: bool = False,
    ) -> list[dict[str, object]]:
        terms = self._parse_terms(query_text)
        if not terms:
            return []

        use_filename = not content_only
        use_content = not filename_only
        pool_size = max(limit * 5, 20)
        candidates: dict[str, dict[str, object]] = {}

        if use_filename:
            for row in self.database.search_filename(terms, pool_size):
                path = str(row["path"])
                candidate = candidates.setdefault(path, {"row": row, "filename_score": 0.0, "bm25_rank": None})
                candidate["row"] = row
                candidate["filename_score"] = max(
                    float(candidate["filename_score"]),
                    self._filename_score(str(row["filename"]), terms),
                )

        if use_content:
            for row in self.database.search_content(terms, pool_size):
                path = str(row["path"])
                candidate = candidates.setdefault(path, {"row": row, "filename_score": 0.0, "bm25_rank": None})
                candidate["row"] = row
                bm25_rank = float(row.get("bm25_rank", 0.0))
                if candidate["bm25_rank"] is None or bm25_rank < float(candidate["bm25_rank"]):
                    candidate["bm25_rank"] = bm25_rank

        results: list[dict[str, object]] = []
        for candidate in candidates.values():
            row = dict(candidate["row"])
            score = self._combine_score(
                filename_score=float(candidate["filename_score"]),
                bm25_rank=candidate["bm25_rank"],
            )
            snippet = self._build_snippet(
                content_text=row.get("content_text"),
                terms=terms,
                fallback=row.get("preview_text"),
            )
            results.append(
                {
                    "path": str(row["path"]),
                    "filename": str(row["filename"]),
                    "score": score,
                    "snippet": snippet,
                    "metadata": (
                        f"ext={row.get('extension') or '-'}, "
                        f"size={row.get('size_bytes') or 0} bytes, "
                        f"modified={row.get('modified_at') or '-'}"
                    ),
                }
            )

        results.sort(key=lambda item: (-float(item["score"]), str(item["filename"]).lower()))
        return results[:limit]

    @staticmethod
    def format_results(results: list[dict[str, object]]) -> str:
        if not results:
            return "No results found."
        lines: list[str] = []
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. {result['filename']}  score={float(result['score']):.2f}")
            lines.append(f"   path: {result['path']}")
            lines.append(f"   meta: {result['metadata']}")
            if result["snippet"]:
                lines.append(f"   snippet: {result['snippet']}")
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
    def _combine_score(filename_score: float, bm25_rank: object) -> float:
        content_score = 0.0
        if bm25_rank is not None:
            adjusted = max(float(bm25_rank), 0.0)
            content_score = 40.0 / (1.0 + adjusted)
        return round(filename_score + content_score, 2)

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
