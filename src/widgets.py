from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Widget:
    key: str
    title: str
    description: str


class WidgetRule(Protocol):
    def matches(self, query: str, results: list[dict[str, object]]) -> bool:
        ...

    def build(self) -> Widget:
        ...


class GalleryWidgetRule:
    def matches(self, query: str, results: list[dict[str, object]]) -> bool:
        image_count = sum(1 for result in results if result.get("file_type") == "image")
        query_mentions_images = any(term in query.lower() for term in ("image", "img", "photo", "color:"))
        return image_count >= 2 or (image_count >= 1 and query_mentions_images)

    def build(self) -> Widget:
        return Widget(
            key="gallery",
            title="View as Gallery",
            description="Image-heavy results can be reviewed visually.",
        )


class LogAnalyzerWidgetRule:
    def matches(self, query: str, results: list[dict[str, object]]) -> bool:
        if not results:
            return False
        log_count = sum(1 for result in results if result.get("extension") == ".log")
        return log_count >= max(1, len(results) // 2)

    def build(self) -> Widget:
        return Widget(
            key="analyze_logs",
            title="Analyze Logs",
            description="Most results are log files, so error summaries may be useful.",
        )


class ColorWidgetRule:
    def matches(self, query: str, results: list[dict[str, object]]) -> bool:
        return "color:" in query.lower() and any(result.get("dominant_color") for result in results)

    def build(self) -> Widget:
        return Widget(
            key="color_filter",
            title="Color Match",
            description="These image results match the requested dominant color.",
        )


class WidgetFactory:
    def __init__(self) -> None:
        self.rules: list[WidgetRule] = [
            GalleryWidgetRule(),
            LogAnalyzerWidgetRule(),
            ColorWidgetRule(),
        ]

    def build_widgets(self, query: str, results: list[dict[str, object]]) -> list[dict[str, str]]:
        return [
            widget.__dict__
            for rule in self.rules
            if rule.matches(query, results)
            for widget in [rule.build()]
        ]
