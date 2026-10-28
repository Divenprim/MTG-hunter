"""Completion checks for interrupted card-database builds."""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import DB_PATH, SCHEMA, database_is_complete  # noqa: E402
from app.cardsbuild import build_database  # noqa: E402


def _base_is_built() -> bool:
    """Лежит ли рядом настоящая база карт, а не пустая заготовка."""
    if not os.path.exists(DB_PATH):
        return False
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] > 0
        finally:
            conn.close()
    except sqlite3.Error:
        return False


class TestDatabaseHealth(unittest.TestCase):
    def test_missing_database_is_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(database_is_complete(os.path.join(root, "missing.sqlite")))

    def test_completion_marker_alone_is_not_enough(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "cards.sqlite")
            conn = sqlite3.connect(path)
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT INTO cards (id, name, set_code) VALUES ('one', 'One', 'tst')"
            )
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                (("built_at", "now"), ("cards", "1")),
            )
            conn.commit()
            conn.close()
            self.assertFalse(database_is_complete(path))

    # Эта проверка -- про здоровье собранной базы, а не про код: там, где
    # базы нет вовсе (свежая копия репозитория, сборка main), спрашивать
    # не о чем, и молчание честнее красного креста.
    #
    # Наличия файла мало: sqlite заводит его сам при первом подключении,
    # и в чистой копии после любого теста на диске лежит пустышка. Спрос
    # идёт с того, есть ли в ней карты.
    @unittest.skipUnless(_base_is_built(), "офлайн-базы карт нет")
    def test_current_database_has_every_required_index(self):
        self.assertTrue(database_is_complete())

    def test_interrupted_rebuild_invalidates_an_old_completion_marker(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "cards.sqlite")
            conn = sqlite3.connect(path)
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT INTO cards (id, name, set_code) VALUES ('old', 'Old', 'tst')"
            )
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                (("built_at", "yesterday"), ("cards", "1")),
            )
            conn.commit()
            conn.close()

            with patch("app.cardsbuild._stream_bulk",
                       side_effect=RuntimeError("interrupted")):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    build_database(path, include_russian=False)

            conn = sqlite3.connect(path)
            meta = dict(conn.execute("SELECT key, value FROM meta"))
            old_cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            conn.close()
            self.assertNotIn("built_at", meta)
            self.assertNotIn("cards", meta)
            self.assertEqual(old_cards, 1)
            self.assertFalse(database_is_complete(path, require_russian=False))


if __name__ == "__main__":
    unittest.main()
