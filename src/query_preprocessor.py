from __future__ import annotations

import re
from abc import ABC, abstractmethod


class QueryBuilder(ABC):
    """Build the query string that is passed to the search engine."""

    @abstractmethod
    def build(self, raw_query: str) -> str:
        raise NotImplementedError


class BaseQueryBuilder(QueryBuilder):
    def build(self, raw_query: str) -> str:
        return (raw_query or "").strip()


class QueryBuilderDecorator(QueryBuilder):
    def __init__(self, wrapped: QueryBuilder) -> None:
        self.wrapped = wrapped

    def build(self, raw_query: str) -> str:
        return self.wrapped.build(raw_query)


class SanitizationDecorator(QueryBuilderDecorator):
    """Remove characters that commonly break FTS syntax."""

    def build(self, raw_query: str) -> str:
        query = super().build(raw_query)
        query = re.sub(r"[^\w\s:.'\"/\\-]", " ", query)
        return " ".join(query.split())


class SynonymDecorator(QueryBuilderDecorator):
    """Expand a few common image terms without changing qualified queries."""

    SYNONYMS = {
        "img": ["image", "photo"],
        "image": ["photo", "picture"],
        "photo": ["image", "picture"],
    }

    def build(self, raw_query: str) -> str:
        query = super().build(raw_query)
        expanded: list[str] = []
        for token in query.split():
            expanded.append(token)
            lowered = token.lower()
            if ":" not in token and lowered in self.SYNONYMS:
                expanded.extend(self.SYNONYMS[lowered])
        return " ".join(expanded)


class LogicDecorator(QueryBuilderDecorator):
    """Reserved wrapper for prefix-search policy.

    SQLite FTS prefix matching is already applied in Database.search_content,
    so this decorator intentionally keeps the string stable while documenting
    where that behavior belongs in the pipeline.
    """


def build_default_query_builder() -> QueryBuilder:
    return LogicDecorator(SynonymDecorator(SanitizationDecorator(BaseQueryBuilder())))
