from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.database import Database
from src.indexing_engine import IndexingEngine
from src.query_engine import QueryEngine, QueryParser
from src.query_preprocessor import build_default_query_builder
from src.widgets import WidgetFactory


class Iteration3Tests(unittest.TestCase):
    def test_color_query_finds_indexed_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "red_square.png"
            Image.new("RGB", (24, 24), (230, 20, 20)).save(image_path)

            database = Database(str(root / "search.db"))
            report = IndexingEngine(database).index(str(root), progress_every=0)
            results = QueryEngine(database).search("color:red", limit=5)

        self.assertGreaterEqual(report["files_indexed"], 1)
        self.assertEqual(results[0]["filename"], "red_square.png")
        self.assertEqual(results[0]["file_type"], "image")
        self.assertEqual(results[0]["dominant_color"], "red")

    def test_query_preprocessor_pipeline_sanitizes_and_expands(self) -> None:
        processed = build_default_query_builder().build("img!!! color:red")

        self.assertIn("img image photo", processed)
        self.assertIn("color:red", processed)
        self.assertNotIn("!", processed)

    def test_parser_supports_color_qualifier(self) -> None:
        parsed = QueryParser.parse("color:blue path:assets")

        self.assertEqual(parsed.color_terms, ["blue"])
        self.assertEqual(parsed.path_terms, ["assets"])

    def test_widget_factory_activates_gallery_for_images(self) -> None:
        widgets = WidgetFactory().build_widgets(
            "color:red",
            [{"file_type": "image", "dominant_color": "red", "extension": ".png"}],
        )

        self.assertEqual({widget["key"] for widget in widgets}, {"gallery", "color_filter"})


if __name__ == "__main__":
    unittest.main()
