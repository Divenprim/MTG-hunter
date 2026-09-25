"""Коллекция: что у вас уже есть -- и какими именно печатями.

Переехала из `collection.json` по той же причине, что и избранное: россыпь
JSON уничтожается одним неудачным сохранением, и однажды так и вышло. Теперь
живёт в `user.sqlite`, снимок делается перед каждой записью, восстановить
можно из интерфейса.

Хранится по печатям, а не по именам. Раньше строка была «имя -- сколько», и
печать терялась ровно в тот момент, когда сканер её узнал: он различает
Ashaya из DSC и из CMM, а коллекция обе писала одной строкой. Для колод и
охоты хватало имени, а для учёта имущества -- нет: печати стоят по-разному.

Печать может быть и неизвестна -- когда коллекцию вводят списком без сетов.
Это честное состояние, а не ошибка: такие строки так и подписаны.

`collection` осталась как сводка по именам. Ею пользуется всё остальное
(колоды, охота, учёт), и переписывать их ради печатей незачем -- там вопрос
всегда про имя. Правда одна: строки печатей; сводка из них пересчитывается
той же транзакцией.
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
-- Сводка по именам: сколько всего копий карты, безразлично какой печати.
-- Пересчитывается из collection_item и наружу отдаётся всем, кому важно имя.
CREATE TABLE IF NOT EXISTS collection (
    name_norm  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    updated    TEXT
);

-- Сами копии: по печатям. Пустой сет означает «печать неизвестна» -- так
-- попадают карты, введённые списком без сетов.
CREATE TABLE IF NOT EXISTS collection_item (
    name_norm         TEXT NOT NULL,
    name              TEXT NOT NULL,
    set_code          TEXT NOT NULL DEFAULT '',
    collector_number  TEXT NOT NULL DEFAULT '',
    finish            TEXT NOT NULL DEFAULT 'nonfoil',
    count             INTEGER NOT NULL DEFAULT 0,
    updated           TEXT,
    PRIMARY KEY (name_norm, set_code, collector_number, finish)
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
    _migrate_items(conn)
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


def _item_key(entry: dict[str, Any]) -> tuple[str, str, str, str]:
    name = str(entry.get("name") or "").strip()
    return (
        name.lower(),
        str(entry.get("set_code") or "").strip().lower(),
        str(entry.get("collector_number") or "").strip(),
        str(entry.get("finish") or "nonfoil").strip().lower() or "nonfoil",
    )


def _resum(conn: sqlite3.Connection) -> None:
    """Пересчитать сводку по именам из строк печатей.

    Делается той же транзакцией, что и запись: сводка -- не вторая правда, а
    отражение первой, и разъехаться они не должны даже на мгновение.
    """
    conn.execute("DELETE FROM collection")
    conn.execute(
        "INSERT INTO collection (name_norm, name, count, updated) "
        "SELECT name_norm, MIN(name), SUM(count), MAX(updated) "
        "FROM collection_item WHERE count > 0 GROUP BY name_norm"
    )


def _migrate_items(conn: sqlite3.Connection) -> None:
    """Перенести старые строки «имя -- сколько» в строки печатей.

    Печать у них неизвестна, и так они и записываются: выдумывать сет за
    пользователя нельзя -- он потом увидит цену чужой печати.
    """
    have = conn.execute("SELECT COUNT(*) AS n FROM collection_item").fetchone()["n"]
    if have:
        return
    rows = conn.execute("SELECT name_norm, name, count, updated FROM collection "
                        "WHERE count > 0").fetchall()
    if not rows:
        return
    with conn:
        for r in rows:
            conn.execute(
                "INSERT OR REPLACE INTO collection_item (name_norm, name, set_code, "
                "collector_number, finish, count, updated) VALUES (?,?,'','',"
                "'nonfoil',?,?)",
                (r["name_norm"], r["name"], int(r["count"]),
                 r["updated"] or time.strftime("%Y-%m-%d %H:%M:%S")))


def items() -> list[dict[str, Any]]:
    """Все копии по печатям, от больших стопок к меньшим."""
    return [dict(r) for r in _conn().execute(
        "SELECT name, name_norm, set_code, collector_number, finish, count, "
        "updated FROM collection_item WHERE count > 0 "
        "ORDER BY name COLLATE NOCASE, count DESC, set_code")]


def load() -> dict[str, int]:
    """Имя -> сколько всего. В этом виде коллекцию ждёт всё остальное."""
    return {
        r["name"]: int(r["count"])
        for r in _conn().execute("SELECT name, count FROM collection WHERE count > 0")
    }


def replace(entries: dict[str, int]) -> dict[str, int]:
    """Переписать коллекцию списком «имя -- сколько».

    Печати в таком списке нет, и она честно становится неизвестной. Если
    печати известны, звать надо replace_items.
    """
    return replace_items([{"name": name, "quantity": count}
                          for name, count in (entries or {}).items()])


def replace_items(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Переписать коллекцию целиком -- строками печатей.

    Так её сохраняет ввод списком: в строке «4 Lightning Bolt (MSC) 806» сет и
    номер есть, и терять их незачем.
    """
    conn = _conn()
    snapshot(conn, SNAPSHOT_KIND, items(), "замена коллекции")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows or []:
        name = str(row.get("name") or "").strip()
        try:
            n = int(row.get("quantity") or row.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if not name or n <= 0:
            continue
        key = _item_key(row)
        got = merged.setdefault(key, {"name": name, "count": 0})
        got["count"] += n
    with conn:
        conn.execute("DELETE FROM collection_item")
        for (norm, set_code, number, finish), got in merged.items():
            conn.execute(
                "INSERT INTO collection_item (name_norm, name, set_code, "
                "collector_number, finish, count, updated) VALUES (?,?,?,?,?,?,?)",
                (norm, got["name"], set_code, number, finish, got["count"], now))
        _resum(conn)
    return load()


def add_items(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Прибавить копии -- с печатью, если она известна.

    Так кладёт сканер: он печать знает и обязан её сохранить. Строка с той же
    печатью прибавляется к существующей, с другой -- заводит свою.
    """
    conn = _conn()
    before = items()
    clean: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows or []:
        name = str(row.get("name") or "").strip()
        try:
            n = int(row.get("quantity") or row.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if not name or n <= 0:
            continue
        key = _item_key(row)
        got = clean.setdefault(key, {"name": name, "count": 0})
        got["count"] += n
    if not clean:
        return {"added": 0, "collection": load()}

    snapshot(conn, SNAPSHOT_KIND, before, "пополнение коллекции")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        for (norm, set_code, number, finish), got in clean.items():
            # Имя показывается то, которым карта уже записана: человек мог
            # ввести её по-русски, и переписывать это на английское незачем.
            known = conn.execute(
                "SELECT name FROM collection_item WHERE name_norm = ? LIMIT 1",
                (norm,)).fetchone()
            conn.execute(
                "INSERT INTO collection_item (name_norm, name, set_code, "
                "collector_number, finish, count, updated) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(name_norm, set_code, collector_number, finish) "
                "DO UPDATE SET count = count + excluded.count, "
                "updated = excluded.updated",
                (norm, (known["name"] if known else got["name"]), set_code,
                 number, finish, got["count"], now))
        _resum(conn)
    return {"added": sum(g["count"] for g in clean.values()),
            "collection": load()}


def add(entries: dict[str, int]) -> dict[str, Any]:
    """Прибавить копии к тому, что уже есть.

    Сканеру нужно именно это: он приносит карты по одной, а не список целиком.
    Замена всей коллекции тут была бы разрушительной -- первая же
    отсканированная карта стёрла бы остальное.

    Снимок делается один на вызов, а не на карту: иначе после пачки в сотню
    карт история состояла бы из ста одинаковых строк.
    """
    return add_items([{"name": name, "quantity": count}
                      for name, count in (entries or {}).items()])


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
    """Вернуть коллекцию из снимка.

    Снимки бывают двух видов: старые -- словарь «имя -- сколько», новые --
    строки печатей. Читаются оба: снимок, сделанный до перехода, обязан
    восстанавливаться и после.
    """
    payload = read_snapshot(_conn(), int(snapshot_id))
    if payload is None:
        raise RuntimeError("Такой резервной копии нет")
    if isinstance(payload, list):
        return replace_items(payload)
    return replace(payload if isinstance(payload, dict) else {})
