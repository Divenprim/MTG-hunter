"""Deck storage, editing, and the rouble price cache.

Kept in its own SQLite file (`data/user.sqlite`), deliberately NOT in
cards.sqlite: that one is a disposable local mirror of Scryfall and gets
rebuilt, while decks and cached prices are the user's own data and must survive
a rebuild.

The price cache exists because the whole point of this builder is showing what
a deck costs **in roubles**, and every topdeck query is a polite 1.5s request.
So prices are stored with a timestamp and refreshed on demand, never silently
on every edit.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Iterable

from .storage import snapshot, user_db_path

# Resolved through storage.user_db_path() so MTGH_DATA_DIR can send tests
# somewhere else: nothing here may write to real user data during a test run.
USER_DB_PATH = user_db_path()

SECTIONS = ("commander", "main", "side", "maybe")

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    format      TEXT DEFAULT 'commander',
    notes       TEXT DEFAULT '',
    created     TEXT,
    updated     TEXT
);

CREATE TABLE IF NOT EXISTS deck_cards (
    id                TEXT PRIMARY KEY,
    deck_id           TEXT NOT NULL,
    name              TEXT NOT NULL,
    quantity          INTEGER NOT NULL DEFAULT 1,
    section           TEXT NOT NULL DEFAULT 'main',
    category          TEXT DEFAULT '',
    set_code          TEXT,
    collector_number  TEXT,
    note              TEXT DEFAULT '',
    added             TEXT
);
CREATE INDEX IF NOT EXISTS idx_deckcards_deck ON deck_cards(deck_id);

CREATE TABLE IF NOT EXISTS deck_versions (
    id        TEXT PRIMARY KEY,
    deck_id   TEXT NOT NULL,
    label     TEXT DEFAULT '',
    created   TEXT,
    snapshot  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deckversions_deck ON deck_versions(deck_id);

-- Cached topdeck prices, in roubles, per card name.
CREATE TABLE IF NOT EXISTS price_cache (
    name_norm        TEXT PRIMARY KEY,
    display_name     TEXT,
    rub_min          INTEGER,
    rub_median       INTEGER,
    offers           INTEGER DEFAULT 0,
    cheapest_seller  TEXT,
    cheapest_line    TEXT,
    cheapest_url     TEXT,
    checked_at       TEXT
);
"""


class DeckError(RuntimeError):
    """Message is written for the user to read as-is."""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or user_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


class DeckStore:
    """Thread-local connections, for the same reason CardDB uses them: FastAPI
    serves sync handlers from a thread pool and sqlite connections are bound to
    their creating thread."""

    def __init__(self, path: str | None = None) -> None:
        import threading

        self.path = path or user_db_path()
        self._local = threading.local()
        self._local.conn = connect(path)

    @property
    def conn(self) -> sqlite3.Connection:
        existing = getattr(self._local, "conn", None)
        if existing is None:
            existing = connect(self.path)
            self._local.conn = existing
        return existing

    # ------------------------------------------------------------- decks --
    def list_decks(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT d.*,
                   (SELECT COALESCE(SUM(quantity), 0) FROM deck_cards c
                     WHERE c.deck_id = d.id AND c.section IN ('main','commander')) AS cards,
                   (SELECT COUNT(*) FROM deck_versions v WHERE v.deck_id = d.id) AS versions
            FROM decks d ORDER BY updated DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def create_deck(self, name: str, fmt: str = "commander") -> str:
        clean = (name or "").strip()
        if not clean:
            raise DeckError("Дайте колоде название")
        deck_id = _new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO decks (id, name, format, notes, created, updated) "
                "VALUES (?,?,?,'',?,?)",
                (deck_id, clean, fmt or "commander", _now(), _now()),
            )
        return deck_id

    def rename_deck(self, deck_id: str, name: str | None, fmt: str | None = None) -> None:
        self._require_deck(deck_id)
        sets, params = [], []
        if name is not None:
            clean = name.strip()
            if not clean:
                raise DeckError("Название не может быть пустым")
            sets.append("name = ?")
            params.append(clean)
        if fmt is not None:
            sets.append("format = ?")
            params.append(fmt)
        if not sets:
            return
        sets.append("updated = ?")
        params.append(_now())
        params.append(deck_id)
        with self.conn:
            self.conn.execute("UPDATE decks SET %s WHERE id = ?" % ", ".join(sets), params)

    def delete_deck(self, deck_id: str) -> None:
        deck = self.get_deck(deck_id)
        # Deleting a deck is the one irreversible action here, so it leaves a
        # snapshot behind.
        snapshot(self.conn, "deck:" + deck_id, deck, "удаление колоды «%s»" % deck["name"])
        with self.conn:
            self.conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
            self.conn.execute("DELETE FROM deck_versions WHERE deck_id = ?", (deck_id,))
            self.conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))

    def _require_deck(self, deck_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
        if row is None:
            raise DeckError("Колода не найдена")
        return dict(row)

    def _touch(self, deck_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE decks SET updated = ? WHERE id = ?", (_now(), deck_id)
            )

    def get_deck(self, deck_id: str) -> dict[str, Any]:
        deck = self._require_deck(deck_id)
        rows = self.conn.execute(
            "SELECT * FROM deck_cards WHERE deck_id = ? ORDER BY section, category, name",
            (deck_id,),
        ).fetchall()
        deck["cards"] = [dict(r) for r in rows]
        return deck

    # ------------------------------------------------------------- cards --
    def add_card(
        self,
        deck_id: str,
        name: str,
        quantity: int = 1,
        section: str = "main",
        category: str = "",
        set_code: str | None = None,
        collector_number: str | None = None,
    ) -> str:
        self._require_deck(deck_id)
        clean = (name or "").strip()
        if not clean:
            raise DeckError("Не указано имя карты")
        if section not in SECTIONS:
            section = "main"
        quantity = max(1, int(quantity or 1))

        existing = self.conn.execute(
            "SELECT id, quantity FROM deck_cards "
            "WHERE deck_id = ? AND LOWER(name) = ? AND section = ? AND category = ?",
            (deck_id, clean.lower(), section, category or ""),
        ).fetchone()
        if existing:
            with self.conn:
                self.conn.execute(
                    "UPDATE deck_cards SET quantity = ? WHERE id = ?",
                    (existing["quantity"] + quantity, existing["id"]),
                )
            self._touch(deck_id)
            return existing["id"]

        row_id = _new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO deck_cards "
                "(id, deck_id, name, quantity, section, category, set_code, "
                " collector_number, note, added) VALUES (?,?,?,?,?,?,?,?,'',?)",
                (row_id, deck_id, clean, quantity, section, category or "",
                 set_code, collector_number, _now()),
            )
        self._touch(deck_id)
        return row_id

    def add_many(self, deck_id: str, cards: Iterable[dict[str, Any]]) -> int:
        n = 0
        for card in cards:
            name = (card.get("name") or "").strip()
            if not name:
                continue
            self.add_card(
                deck_id,
                name,
                quantity=card.get("quantity") or 1,
                section=card.get("section") or "main",
                category=card.get("category") or "",
                set_code=card.get("set_code"),
                collector_number=card.get("collector_number"),
            )
            n += 1
        return n

    def update_card(self, deck_id: str, card_id: str, **changes: Any) -> None:
        self._require_deck(deck_id)
        row = self.conn.execute(
            "SELECT * FROM deck_cards WHERE id = ? AND deck_id = ?", (card_id, deck_id)
        ).fetchone()
        if row is None:
            raise DeckError("Карта не найдена в этой колоде")

        sets, params = [], []
        if changes.get("quantity") is not None:
            sets.append("quantity = ?")
            params.append(max(1, int(changes["quantity"])))
        if changes.get("section") is not None:
            section = changes["section"]
            sets.append("section = ?")
            params.append(section if section in SECTIONS else "main")
        if changes.get("category") is not None:
            sets.append("category = ?")
            params.append(str(changes["category"]))
        if changes.get("note") is not None:
            sets.append("note = ?")
            params.append(str(changes["note"]))
        if not sets:
            return
        params.append(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE deck_cards SET %s WHERE id = ?" % ", ".join(sets), params
            )
        self._touch(deck_id)

    def remove_card(self, deck_id: str, card_id: str) -> None:
        self._require_deck(deck_id)
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM deck_cards WHERE id = ? AND deck_id = ?", (card_id, deck_id)
            )
        if cur.rowcount == 0:
            raise DeckError("Карта не найдена в этой колоде")
        self._touch(deck_id)

    # ---------------------------------------------------------- versions --
    def save_version(self, deck_id: str, label: str = "") -> str:
        deck = self.get_deck(deck_id)
        version_id = _new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO deck_versions (id, deck_id, label, created, snapshot) "
                "VALUES (?,?,?,?,?)",
                (version_id, deck_id, (label or "").strip(), _now(),
                 json.dumps(deck, ensure_ascii=False)),
            )
        return version_id

    def list_versions(self, deck_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, label, created FROM deck_versions WHERE deck_id = ? "
            "ORDER BY created DESC",
            (deck_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def restore_version(self, deck_id: str, version_id: str) -> None:
        row = self.conn.execute(
            "SELECT snapshot FROM deck_versions WHERE id = ? AND deck_id = ?",
            (version_id, deck_id),
        ).fetchone()
        if row is None:
            raise DeckError("Версия не найдена")
        snapshot = json.loads(row["snapshot"])

        # Keep the current state as a version first: restoring must never be
        # the action that loses work.
        self.save_version(deck_id, "перед откатом")
        with self.conn:
            self.conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
            for card in snapshot.get("cards", []):
                self.conn.execute(
                    "INSERT INTO deck_cards "
                    "(id, deck_id, name, quantity, section, category, set_code, "
                    " collector_number, note, added) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (_new_id(), deck_id, card["name"], card.get("quantity", 1),
                     card.get("section", "main"), card.get("category", ""),
                     card.get("set_code"), card.get("collector_number"),
                     card.get("note", ""), card.get("added") or _now()),
                )
        self._touch(deck_id)

    def delete_version(self, deck_id: str, version_id: str) -> None:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM deck_versions WHERE id = ? AND deck_id = ?",
                (version_id, deck_id),
            )
        if cur.rowcount == 0:
            raise DeckError("Версия не найдена")

    # ------------------------------------------------------- price cache --
    def get_prices(self, names: Iterable[str]) -> dict[str, dict[str, Any]]:
        wanted = [n.strip().lower() for n in names if n and n.strip()]
        if not wanted:
            return {}
        out: dict[str, dict[str, Any]] = {}
        # Chunk the IN clause: sqlite caps bound parameters at 999 by default.
        for i in range(0, len(wanted), 500):
            chunk = wanted[i : i + 500]
            rows = self.conn.execute(
                "SELECT * FROM price_cache WHERE name_norm IN (%s)"
                % ",".join("?" * len(chunk)),
                chunk,
            ).fetchall()
            for row in rows:
                out[row["name_norm"]] = dict(row)
        return out

    def store_price(
        self,
        name: str,
        rub_min: int | None,
        rub_median: int | None,
        offers: int,
        cheapest_seller: str = "",
        cheapest_line: str = "",
        cheapest_url: str = "",
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(name_norm, display_name, rub_min, rub_median, offers, "
                " cheapest_seller, cheapest_line, cheapest_url, checked_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (name.strip().lower(), name.strip(), rub_min, rub_median, offers,
                 cheapest_seller, cheapest_line, cheapest_url, _now()),
            )

    def price_stats(self) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, MAX(checked_at) AS newest, MIN(checked_at) AS oldest "
            "FROM price_cache"
        ).fetchone()
        return dict(row) if row else {"n": 0}
