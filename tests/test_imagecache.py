from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import imagecache


class FakeDB:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE cards (id TEXT PRIMARY KEY, name TEXT, image_small TEXT, image_normal TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE card_faces (card_id TEXT, face_index INTEGER, name TEXT, "
            "image_small TEXT, image_normal TEXT)"
        )
        self.conn.execute(
            "INSERT INTO cards VALUES (?,?,?,?,?)",
            ("card-1", "Test Card", "https://example.invalid/small.jpg",
             "https://example.invalid/normal.jpg"),
        )
        self.conn.commit()


class ImageCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cache = imagecache.CACHE_DIR
        imagecache.CACHE_DIR = Path(self.tmp.name)
        self.db = FakeDB()

    def tearDown(self) -> None:
        imagecache.CACHE_DIR = self.old_cache
        self.db.conn.close()
        self.tmp.cleanup()

    def test_network_image_is_cached(self) -> None:
        payload = b"x" * 2048
        with patch("app.imagecache._download", return_value=(payload, "image/jpeg")) as fetch:
            data, media, source = imagecache.get_image(self.db, "card-1", "small")
        self.assertEqual(payload, data)
        self.assertEqual("image/jpeg", media)
        self.assertEqual("network", source)
        self.assertTrue(fetch.called)

        with patch("app.imagecache._download", side_effect=AssertionError("network used")):
            data2, media2, source2 = imagecache.get_image(self.db, "card-1", "small")
        self.assertEqual(payload, data2)
        self.assertEqual("image/jpeg", media2)
        self.assertEqual("cache", source2)

    def test_total_network_failure_returns_svg_placeholder(self) -> None:
        with patch("app.imagecache._download", return_value=None):
            data, media, source = imagecache.get_image(self.db, "card-1", "normal")
        self.assertEqual("image/svg+xml", media)
        self.assertEqual("placeholder", source)
        self.assertIn(b"Test Card", data)
        self.assertIn(b"<svg", data)

    def test_unknown_card_still_returns_placeholder(self) -> None:
        with patch("app.imagecache._download", return_value=None):
            data, media, source = imagecache.get_image(self.db, "missing", "small")
        self.assertEqual("image/svg+xml", media)
        self.assertEqual("placeholder", source)
        self.assertIn(b"<svg", data)


if __name__ == "__main__":
    unittest.main()
