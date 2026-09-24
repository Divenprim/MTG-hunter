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

-- Во сколько коллекция оценивалась в такой-то день. Одна строка на день, а не
-- на каждый пересчёт: коллекция меняется реже, чем открывается страница, и
-- история из сотни одинаковых строк за вторник ничего не показывает. За день
-- строка переписывается последним значением.
--
-- Цены здесь -- это снимок на тот день, а не обещание: долларовая берётся из
-- локальной базы (она есть у всех карт), рублёвая -- из кеша topdeck, то есть
-- только по тем картам, цену которых вы спрашивали.
CREATE TABLE IF NOT EXISTS collection_value (
    at       TEXT PRIMARY KEY,
    cards    INTEGER NOT NULL DEFAULT 0,
    copies   INTEGER NOT NULL DEFAULT 0,
    usd      REAL    NOT NULL DEFAULT 0,
    rub      INTEGER NOT NULL DEFAULT 0,
    priced   INTEGER NOT NULL DEFAULT 0,
    recorded TEXT
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


def add(entries: dict[str, int]) -> dict[str, Any]:
    """Прибавить копии к тому, что уже есть.

    Сканеру нужно именно это: он приносит карты по одной, а не список целиком.
    Замена всей коллекции тут была бы разрушительной -- первая же
    отсканированная карта стёрла бы остальное.

    Снимок делается один на вызов, а не на карту: иначе после пачки в сотню
    карт история состояла бы из ста одинаковых строк.
    """
    conn = _conn()
    before = load()
    clean: dict[str, int] = {}
    for name, count in (entries or {}).items():
        key = str(name or "").strip()
        try:
            n = int(count or 0)
        except (TypeError, ValueError):
            continue
        if not key or n <= 0:
            continue
        clean[key] = clean.get(key, 0) + n
    if not clean:
        return {"added": 0, "collection": before}

    snapshot(conn, SNAPSHOT_KIND, before, "пополнение коллекции")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lower = {k.lower(): k for k in before}
    with conn:
        for name, n in clean.items():
            # Та же карта, записанная иначе, -- это та же карта: счёт идёт по
            # нормализованному имени, а показывается то, что уже лежало.
            known = lower.get(name.lower())
            display = known or name
            total = before.get(known or "", 0) + n
            conn.execute(
                "INSERT OR REPLACE INTO collection (name_norm, name, count, updated) "
                "VALUES (?,?,?,?)",
                (display.lower(), display, total, now),
            )
    return {"added": sum(clean.values()), "collection": load()}


def summary() -> dict[str, Any]:
    row = _conn().execute(
        "SELECT COUNT(*) AS distinct_cards, COALESCE(SUM(count),0) AS copies "
        "FROM collection WHERE count > 0"
    ).fetchone()
    return {"distinct": row["distinct_cards"], "copies": row["copies"]}


def record_value(cards: int, copies: int, usd: float, rub: int,
                 priced: int = 0) -> None:
    """Запомнить, во сколько коллекция оценивается сегодня.

    Пишется при каждом пересчёте учёта, но строка в день одна: за сегодня она
    переписывается. Так история получается кривой по дням, а не журналом
    открытий страницы.
    """
    conn = _conn()
    with conn:
        conn.execute(
            "INSERT INTO collection_value (at, cards, copies, usd, rub, priced, "
            "recorded) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(at) DO UPDATE SET cards = excluded.cards, "
            "copies = excluded.copies, usd = excluded.usd, rub = excluded.rub, "
            "priced = excluded.priced, recorded = excluded.recorded",
            (time.strftime("%Y-%m-%d"), int(cards), int(copies), float(usd),
             int(rub), int(priced), time.strftime("%Y-%m-%d %H:%M:%S")),
        )


def value_history(limit: int = 400) -> list[dict[str, Any]]:
    """Как менялась оценка -- по дням, от старых к новым."""
    rows = _conn().execute(
        "SELECT at, cards, copies, usd, rub, priced FROM collection_value "
        "ORDER BY at DESC LIMIT ?", (int(limit),)).fetchall()
    return [dict(r) for r in reversed(rows)]


def backups() -> list[dict[str, Any]]:
    return list_snapshots(_conn(), SNAPSHOT_KIND)


def restore(snapshot_id: int) -> dict[str, int]:
    payload = read_snapshot(_conn(), int(snapshot_id))
    if payload is None:
        raise RuntimeError("Такой резервной копии нет")
    return replace(payload if isinstance(payload, dict) else {})
