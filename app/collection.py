"""The collection: what you already own.

Moved out of `collection.json` for the same reason favourites were: a loose
JSON file is trivially destroyed, and this one was. It now lives in
`user.sqlite`, takes a snapshot before every write, and can be restored.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

from .storage import (
    connect_user_db, data_dir, list_snapshots, read_snapshot, snapshot, user_db_path,
)

SNAPSHOT_KIND = "collection"

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection (
    name_norm  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    updated    TEXT
);
"""

_local = threading.local()


def _conn() -> sqlite3.Connection:
    existing = getattr(_local, "conn", None)
    path = user_db_path()
    if existing is not None and getattr(_local, "path", None) == path:
        return existing
    conn = connect_user_db(SCHEMA, path)
    _local.conn = conn
    _local.path = path
    _migrate_json(conn)
    return conn


def reset_connection() -> None:
    existing = getattr(_local, "conn", None)
    if existing is not None:
        try:
            existing.close()
        except sqlite3.Error:
            pass
    _local.conn = None
    _local.path = None


def _migrate_json(conn: sqlite3.Connection) -> None:
    """Import a legacy collection.json once, then rename it aside."""
    legacy = os.path.join(data_dir(), "collection.json")
    if not os.path.exists(legacy):
        return
    try:
        with open(legacy, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(doc, dict):
        return
    with conn:
        for name, count in doc.items():
            try:
                n = int(count or 0)
            except (TypeError, ValueError):
                continue
            if n <= 0 or not str(name).strip():
                continue
            conn.execute(
                "INSERT OR REPLACE INTO collection (name_norm, name, count, updated) "
                "VALUES (?,?,?,?)",
                (str(name).strip().lower(), str(name).strip(), n,
                 time.strftime("%Y-%m-%d %H:%M:%S")),
            )
    os.replace(legacy, legacy + ".imported")


def load() -> dict[str, int]:
    """Name -> count, in the shape the rest of the app already expects."""
    return {
        r["name"]: int(r["count"])
        for r in _conn().execute("SELECT name, count FROM collection WHERE count > 0")
    }


def replace(entries: dict[str, int]) -> dict[str, int]:
    """Overwrite the whole collection, snapshotting the old one first."""
    conn = _conn()
    snapshot(conn, SNAPSHOT_KIND, load(), "замена коллекции")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute("DELETE FROM collection")
        for name, count in entries.items():
            clean = str(name).strip()
            try:
                n = int(count or 0)
            except (TypeError, ValueError):
                continue
            if not clean or n <= 0:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO collection (name_norm, name, count, updated) "
                "VALUES (?,?,?,?)",
                (clean.lower(), clean, n, now),
            )
    return load()


def summary() -> dict[str, Any]:
    row = _conn().execute(
        "SELECT COUNT(*) AS distinct_cards, COALESCE(SUM(count),0) AS copies "
        "FROM collection WHERE count > 0"
    ).fetchone()
    return {"distinct": row["distinct_cards"], "copies": row["copies"]}


def backups() -> list[dict[str, Any]]:
    return list_snapshots(_conn(), SNAPSHOT_KIND)


def restore(snapshot_id: int) -> dict[str, int]:
    payload = read_snapshot(_conn(), int(snapshot_id))
    if payload is None:
        raise RuntimeError("Такой резервной копии нет")
    return replace(payload if isinstance(payload, dict) else {})
