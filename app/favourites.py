"""Favourites: cards set aside to buy later, organised in folders.

Deliberately separate from the collection. The collection answers "what do I
already own" and is subtracted from decks; favourites answer "what do I want to
order", so a row keeps a wanted quantity, a note, and optionally a specific
printing, and a whole folder can be sent to the hunt.

Stored in `user.sqlite` next to the decks, not in a loose JSON file. The JSON
file was easy to destroy -- and was in fact destroyed by a cleanup step -- while
this store is transactional, takes a snapshot before every mutation, and shares
one backup unit with everything else the user owns.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any

from .storage import data_dir, list_snapshots, read_snapshot, snapshot, user_db_path

DEFAULT_FOLDER_NAME = "Хочу купить"
SNAPSHOT_KIND = "favourites"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fav_folders (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    name_norm TEXT,
    created   TEXT,
    position  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fav_cards (
    id                TEXT PRIMARY KEY,
    folder_id         TEXT NOT NULL,
    name              TEXT NOT NULL,
    name_norm         TEXT,
    quantity          INTEGER NOT NULL DEFAULT 1,
    set_code          TEXT,
    collector_number  TEXT,
    note              TEXT DEFAULT '',
    image             TEXT,
    added             TEXT
);
CREATE INDEX IF NOT EXISTS idx_favcards_folder ON fav_cards(folder_id);
"""


class FavouritesError(RuntimeError):
    """Message is written for the user to read as-is."""


def _fold(text: str) -> str:
    """Case-insensitive key. Python's casefold handles Cyrillic; sqlite's
    LOWER() does not, which is what let «Дубль» and «дубль» coexist."""
    return (text or "").strip().casefold()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Thread-local connection: FastAPI serves sync handlers from a pool and
    sqlite connections are bound to their creating thread."""
    existing = getattr(_local, "conn", None)
    path = user_db_path()
    if existing is not None and getattr(_local, "path", None) == path:
        return existing
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    _local.conn = conn
    _local.path = path
    _migrate_json(conn)
    _ensure_folder(conn)
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring an older database up to the current schema."""
    for table, column in (("fav_folders", "name_norm"), ("fav_cards", "name_norm")):
        have = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if column not in have:
            conn.execute("ALTER TABLE %s ADD COLUMN %s TEXT" % (table, column))
    with conn:
        for table in ("fav_folders", "fav_cards"):
            rows = conn.execute(
                "SELECT id, name FROM %s WHERE name_norm IS NULL OR name_norm = ''" % table
            ).fetchall()
            conn.executemany(
                "UPDATE %s SET name_norm = ? WHERE id = ?" % table,
                [(_fold(r["name"]), r["id"]) for r in rows],
            )


def reset_connection() -> None:
    """Drop the cached connection. Used by tests after moving MTGH_DATA_DIR."""
    existing = getattr(_local, "conn", None)
    if existing is not None:
        try:
            existing.close()
        except sqlite3.Error:
            pass
    _local.conn = None
    _local.path = None


# --------------------------------------------------------------------------- #
# Bootstrapping
# --------------------------------------------------------------------------- #

def _migrate_json(conn: sqlite3.Connection) -> None:
    """Import a legacy favourites.json exactly once, then rename it.

    Renamed rather than deleted: if the import gets something wrong, the
    original is still on disk to look at.
    """
    legacy = os.path.join(data_dir(), "favourites.json")
    if not os.path.exists(legacy):
        return
    have = conn.execute("SELECT COUNT(*) AS n FROM fav_folders").fetchone()["n"]
    try:
        with open(legacy, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return

    folders = doc.get("folders") if isinstance(doc, dict) else None
    if not isinstance(folders, list):
        return

    with conn:
        for position, folder in enumerate(folders):
            fid = folder.get("id") or _new_id()
            name = (folder.get("name") or "").strip() or DEFAULT_FOLDER_NAME
            existing = conn.execute(
                "SELECT id FROM fav_folders WHERE name_norm = ?", (_fold(name),)
            ).fetchone()
            if existing:
                fid = existing["id"]
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO fav_folders "
                    "(id, name, name_norm, created, position) VALUES (?,?,?,?,?)",
                    (fid, name, _fold(name), folder.get("created") or _now(), position),
                )
            for card in folder.get("cards") or []:
                if not (card.get("name") or "").strip():
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO fav_cards "
                    "(id, folder_id, name, name_norm, quantity, set_code, "
                    " collector_number, note, image, added) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (card.get("id") or _new_id(), fid, card["name"],
                     _fold(card["name"]), max(1, int(card.get("quantity") or 1)),
                     card.get("set_code"), card.get("collector_number"),
                     card.get("note") or "", card.get("image"),
                     card.get("added") or _now()),
                )
    os.replace(legacy, legacy + ".imported")


def _ensure_folder(conn: sqlite3.Connection) -> None:
    """Always keep one folder, so the UI has somewhere to put a card."""
    row = conn.execute("SELECT COUNT(*) AS n FROM fav_folders").fetchone()
    if row["n"] == 0:
        with conn:
            conn.execute(
                "INSERT INTO fav_folders (id, name, name_norm, created, position) "
                "VALUES (?,?,?,?,0)",
                (_new_id(), DEFAULT_FOLDER_NAME, _fold(DEFAULT_FOLDER_NAME), _now()),
            )


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def load() -> dict[str, Any]:
    conn = _conn()
    folders = []
    for row in conn.execute(
        "SELECT * FROM fav_folders ORDER BY position, created, name"
    ):
        cards = [
            dict(c)
            for c in conn.execute(
                "SELECT * FROM fav_cards WHERE folder_id = ? ORDER BY added, name",
                (row["id"],),
            )
        ]
        for card in cards:
            card.pop("folder_id", None)
            card.pop("name_norm", None)
        folders.append({
            "id": row["id"],
            "name": row["name"],
            "created": row["created"],
            "cards": cards,
        })
    return {"folders": folders}


def summary(doc: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = doc or load()
    return {
        "folders": len(doc["folders"]),
        "cards": sum(len(f["cards"]) for f in doc["folders"]),
        "copies": sum(
            int(c.get("quantity", 1)) for f in doc["folders"] for c in f["cards"]
        ),
    }


def _take_snapshot(reason: str) -> None:
    snapshot(_conn(), SNAPSHOT_KIND, load(), reason)


def backups() -> list[dict[str, Any]]:
    return list_snapshots(_conn(), SNAPSHOT_KIND)


def restore(snapshot_id: int) -> dict[str, Any]:
    """Put a snapshot back. Snapshots the current state first."""
    payload = read_snapshot(_conn(), int(snapshot_id))
    if payload is None:
        raise FavouritesError("Такой резервной копии нет")
    _take_snapshot("перед восстановлением")

    conn = _conn()
    with conn:
        conn.execute("DELETE FROM fav_cards")
        conn.execute("DELETE FROM fav_folders")
        for position, folder in enumerate(payload.get("folders") or []):
            fid = folder.get("id") or _new_id()
            name = folder.get("name") or DEFAULT_FOLDER_NAME
            conn.execute(
                "INSERT INTO fav_folders (id, name, name_norm, created, position) "
                "VALUES (?,?,?,?,?)",
                (fid, name, _fold(name), folder.get("created") or _now(), position),
            )
            for card in folder.get("cards") or []:
                conn.execute(
                    "INSERT INTO fav_cards "
                    "(id, folder_id, name, name_norm, quantity, set_code, "
                    " collector_number, note, image, added) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (card.get("id") or _new_id(), fid, card["name"],
                     _fold(card["name"]), max(1, int(card.get("quantity") or 1)),
                     card.get("set_code"), card.get("collector_number"),
                     card.get("note") or "", card.get("image"),
                     card.get("added") or _now()),
                )
    _ensure_folder(conn)
    return load()


def _find_folder(conn: sqlite3.Connection, folder_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM fav_folders WHERE id = ?", (folder_id,)).fetchone()
    if row is None:
        raise FavouritesError("Папка не найдена — возможно, её удалили в другом окне")
    return row


# --------------------------------------------------------------------------- #
# Folders
# --------------------------------------------------------------------------- #

def create_folder(name: str) -> dict[str, Any]:
    clean = (name or "").strip()
    if not clean:
        raise FavouritesError("Дайте папке название")
    conn = _conn()
    if conn.execute(
        "SELECT id FROM fav_folders WHERE name_norm = ?", (_fold(clean),)
    ).fetchone():
        raise FavouritesError("Папка «%s» уже есть" % clean)
    _take_snapshot("создание папки")
    with conn:
        conn.execute(
            "INSERT INTO fav_folders (id, name, name_norm, created, position) "
            "VALUES (?,?,?,?,(SELECT COALESCE(MAX(position),0)+1 FROM fav_folders))",
            (_new_id(), clean, _fold(clean), _now()),
        )
    return load()


def rename_folder(folder_id: str, name: str) -> dict[str, Any]:
    clean = (name or "").strip()
    if not clean:
        raise FavouritesError("Название не может быть пустым")
    conn = _conn()
    _find_folder(conn, folder_id)
    clash = conn.execute(
        "SELECT id FROM fav_folders WHERE name_norm = ? AND id <> ?",
        (_fold(clean), folder_id),
    ).fetchone()
    if clash:
        raise FavouritesError("Папка «%s» уже есть" % clean)
    _take_snapshot("переименование папки")
    with conn:
        conn.execute(
            "UPDATE fav_folders SET name = ?, name_norm = ? WHERE id = ?",
            (clean, _fold(clean), folder_id),
        )
    return load()


def delete_folder(folder_id: str) -> dict[str, Any]:
    conn = _conn()
    _find_folder(conn, folder_id)
    total = conn.execute("SELECT COUNT(*) AS n FROM fav_folders").fetchone()["n"]
    if total == 1:
        raise FavouritesError("Это последняя папка — её нельзя удалить, только переименовать")
    _take_snapshot("удаление папки")
    with conn:
        conn.execute("DELETE FROM fav_cards WHERE folder_id = ?", (folder_id,))
        conn.execute("DELETE FROM fav_folders WHERE id = ?", (folder_id,))
    return load()


# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #

def _same_card(conn: sqlite3.Connection, folder_id: str, name: str,
               set_code: str | None, number: str | None) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM fav_cards WHERE folder_id = ? AND name_norm = ? "
        "AND IFNULL(set_code,'') = ? AND IFNULL(collector_number,'') = ?",
        (folder_id, _fold(name), set_code or "", number or ""),
    ).fetchone()


def add_card(
    folder_id: str,
    name: str,
    quantity: int = 1,
    set_code: str | None = None,
    collector_number: str | None = None,
    note: str = "",
    image: str | None = None,
) -> dict[str, Any]:
    clean = (name or "").strip()
    if not clean:
        raise FavouritesError("Не указано имя карты")
    quantity = max(1, int(quantity or 1))

    conn = _conn()
    _find_folder(conn, folder_id)
    _take_snapshot("добавление карты")

    # Same card AND same requested printing -> bump the quantity. A different
    # printing is a genuinely different want.
    existing = _same_card(conn, folder_id, clean, set_code, collector_number)
    with conn:
        if existing:
            conn.execute(
                "UPDATE fav_cards SET quantity = ?, note = ? WHERE id = ?",
                (existing["quantity"] + quantity, note or existing["note"],
                 existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO fav_cards "
                "(id, folder_id, name, name_norm, quantity, set_code, "
                " collector_number, note, image, added) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (_new_id(), folder_id, clean, _fold(clean), quantity, set_code,
                 collector_number, note or "", image, _now()),
            )
    return load()


def add_many(
    cards: list[dict[str, Any]],
    folder_id: str | None = None,
    folder_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add a batch, optionally creating the folder. One call, because the real
    action is "these twelve cards go into a new list"."""
    if not cards:
        raise FavouritesError("Не выбрано ни одной карты")

    conn = _conn()
    _take_snapshot("массовое добавление")

    if folder_id:
        folder = _find_folder(conn, folder_id)
        target_id, target_name = folder["id"], folder["name"]
    elif folder_name and folder_name.strip():
        clean = folder_name.strip()
        row = conn.execute(
            "SELECT * FROM fav_folders WHERE name_norm = ?", (_fold(clean),)
        ).fetchone()
        if row:
            target_id, target_name = row["id"], row["name"]
        else:
            target_id, target_name = _new_id(), clean
            with conn:
                conn.execute(
                    "INSERT INTO fav_folders (id, name, name_norm, created, position) "
                    "VALUES (?,?,?,?,(SELECT COALESCE(MAX(position),0)+1 FROM fav_folders))",
                    (target_id, clean, _fold(clean), _now()),
                )
    else:
        raise FavouritesError("Не указана папка")

    added = 0
    stacked = 0
    with conn:
        for raw in cards:
            name = (raw.get("name") or "").strip()
            if not name:
                continue
            quantity = max(1, int(raw.get("quantity") or 1))
            set_code = raw.get("set_code") or None
            number = raw.get("collector_number") or None
            existing = _same_card(conn, target_id, name, set_code, number)
            if existing:
                conn.execute(
                    "UPDATE fav_cards SET quantity = ? WHERE id = ?",
                    (existing["quantity"] + quantity, existing["id"]),
                )
                stacked += 1
            else:
                conn.execute(
                    "INSERT INTO fav_cards "
                    "(id, folder_id, name, name_norm, quantity, set_code, "
                    " collector_number, note, image, added) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (_new_id(), target_id, name, _fold(name), quantity, set_code,
                     number, raw.get("note") or "", raw.get("image"), _now()),
                )
                added += 1

    return load(), {
        "folder_id": target_id,
        "folder_name": target_name,
        "added": added,
        "stacked": stacked,
    }


def update_card(folder_id: str, card_id: str, **changes: Any) -> dict[str, Any]:
    conn = _conn()
    _find_folder(conn, folder_id)
    row = conn.execute(
        "SELECT * FROM fav_cards WHERE id = ? AND folder_id = ?", (card_id, folder_id)
    ).fetchone()
    if row is None:
        raise FavouritesError("Карта не найдена в этой папке")

    sets, params = [], []
    if changes.get("quantity") is not None:
        sets.append("quantity = ?")
        params.append(max(1, int(changes["quantity"])))
    if changes.get("note") is not None:
        sets.append("note = ?")
        params.append(str(changes["note"]))
    if not sets:
        return load()

    _take_snapshot("изменение карты")
    params.append(card_id)
    with conn:
        conn.execute("UPDATE fav_cards SET %s WHERE id = ?" % ", ".join(sets), params)
    return load()


def remove_card(folder_id: str, card_id: str) -> dict[str, Any]:
    conn = _conn()
    _find_folder(conn, folder_id)
    row = conn.execute(
        "SELECT id FROM fav_cards WHERE id = ? AND folder_id = ?", (card_id, folder_id)
    ).fetchone()
    if row is None:
        raise FavouritesError("Карта не найдена в этой папке")
    _take_snapshot("удаление карты")
    with conn:
        conn.execute("DELETE FROM fav_cards WHERE id = ?", (card_id,))
    return load()


def move_card(folder_id: str, card_id: str, target_folder_id: str) -> dict[str, Any]:
    if folder_id == target_folder_id:
        return load()
    conn = _conn()
    _find_folder(conn, folder_id)
    _find_folder(conn, target_folder_id)
    moving = conn.execute(
        "SELECT * FROM fav_cards WHERE id = ? AND folder_id = ?", (card_id, folder_id)
    ).fetchone()
    if moving is None:
        raise FavouritesError("Карта не найдена в этой папке")

    _take_snapshot("перемещение карты")
    existing = _same_card(
        conn, target_folder_id, moving["name"], moving["set_code"],
        moving["collector_number"],
    )
    with conn:
        if existing:
            conn.execute(
                "UPDATE fav_cards SET quantity = ? WHERE id = ?",
                (existing["quantity"] + moving["quantity"], existing["id"]),
            )
            conn.execute("DELETE FROM fav_cards WHERE id = ?", (card_id,))
        else:
            conn.execute(
                "UPDATE fav_cards SET folder_id = ? WHERE id = ?",
                (target_folder_id, card_id),
            )
    return load()


def folder_as_wants(folder_id: str) -> list[dict[str, Any]]:
    """A folder, in the shape the hunt endpoint expects."""
    conn = _conn()
    _find_folder(conn, folder_id)
    rows = conn.execute(
        "SELECT name, quantity, set_code FROM fav_cards WHERE folder_id = ? "
        "ORDER BY added, name",
        (folder_id,),
    ).fetchall()
    return [
        {
            "name": r["name"],
            "quantity": int(r["quantity"] or 1),
            "set_code": r["set_code"],
            "section": "main",
        }
        for r in rows
    ]
