"""Pending purchases: ordered from a seller, but not owned yet.

An order is deliberately separate from the collection.  It remains visible in
the hunt and deck while in transit; only the explicit "received" action moves
its cards into the collection.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from . import collection as collection_store
from .storage import connect_user_db, snapshot, user_db_path

SNAPSHOT_KIND = "orders"

SCHEMA = """
CREATE TABLE IF NOT EXISTS purchase_orders (
    id           TEXT PRIMARY KEY,
    seller_name  TEXT NOT NULL,
    seller_kind  TEXT NOT NULL DEFAULT 'user',
    total        INTEGER NOT NULL DEFAULT 0,
    created      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    fingerprint  TEXT NOT NULL,
    received     TEXT
);
CREATE TABLE IF NOT EXISTS purchase_order_items (
    order_id     TEXT NOT NULL,
    name_norm    TEXT NOT NULL,
    name         TEXT NOT NULL,
    quantity     INTEGER NOT NULL,
    unit_price   INTEGER NOT NULL DEFAULT 0,
    subtotal     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, name_norm)
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON purchase_order_items(order_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_order_fingerprint
    ON purchase_orders(fingerprint) WHERE status = 'pending';
"""

_local = threading.local()
_MUTATION_LOCK = threading.RLock()


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring a database made by an earlier version up to this schema.

    `received` arrived with the purchase history: orders marked received before
    it existed have no date, and are shown without one rather than with a
    made-up one.
    """
    have = {r["name"] for r in conn.execute("PRAGMA table_info(purchase_orders)")}
    if "received" not in have:
        with conn:
            conn.execute("ALTER TABLE purchase_orders ADD COLUMN received TEXT")
    # Created here rather than in SCHEMA: that script runs before this
    # migration, and an index over `received` cannot be built on a database
    # that has not got the column yet.
    with conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_status "
            "ON purchase_orders(status, received)"
        )


def _conn() -> sqlite3.Connection:
    existing = getattr(_local, "conn", None)
    path = user_db_path()
    if existing is not None and getattr(_local, "path", None) == path:
        return existing
    conn = connect_user_db(SCHEMA, path)
    _add_missing_columns(conn)
    _local.conn = conn
    _local.path = path
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


def _clean_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in items:
        name = str(raw.get("name") or "").strip()
        quantity = max(0, int(raw.get("quantity") or 0))
        if not name or quantity <= 0:
            continue
        key = name.lower()
        unit_price = max(0, int(raw.get("unit_price") or 0))
        if key in merged:
            merged[key]["quantity"] += quantity
            merged[key]["subtotal"] += quantity * unit_price
            merged[key]["unit_price"] = round(
                merged[key]["subtotal"] / merged[key]["quantity"]
            )
        else:
            merged[key] = {
                "name_norm": key,
                "name": name,
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": quantity * unit_price,
            }
    return sorted(merged.values(), key=lambda item: item["name_norm"])


def _fingerprint(seller_name: str, items: list[dict[str, Any]]) -> str:
    payload = [seller_name.strip().lower(), [
        [item["name_norm"], item["quantity"], item["unit_price"]]
        for item in items
    ]]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def list_pending() -> list[dict[str, Any]]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM purchase_orders WHERE status = 'pending' ORDER BY created DESC, id DESC"
    ).fetchall()
    out = []
    for row in rows:
        order = dict(row)
        order["items"] = [
            dict(item) for item in conn.execute(
                "SELECT name, name_norm, quantity, unit_price, subtotal "
                "FROM purchase_order_items WHERE order_id = ? ORDER BY name_norm",
                (row["id"],),
            )
        ]
        out.append(order)
    return out


def ordered_counts() -> dict[str, int]:
    return {
        row["name_norm"]: int(row["copies"])
        for row in _conn().execute(
            "SELECT i.name_norm, SUM(i.quantity) AS copies "
            "FROM purchase_order_items i JOIN purchase_orders o ON o.id = i.order_id "
            "WHERE o.status = 'pending' GROUP BY i.name_norm"
        )
    }


def create(
    seller_name: str,
    seller_kind: str,
    items: list[dict[str, Any]],
) -> str:
    with _MUTATION_LOCK:
        return _create(seller_name, seller_kind, items)


def _create(
    seller_name: str,
    seller_kind: str,
    items: list[dict[str, Any]],
) -> str:
    seller = seller_name.strip()
    clean = _clean_items(items)
    if not seller or not clean:
        raise ValueError("в заказе нет продавца или карт")
    fingerprint = _fingerprint(seller, clean)
    conn = _conn()
    existing = conn.execute(
        "SELECT id FROM purchase_orders WHERE status = 'pending' AND fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    if existing:
        return str(existing["id"])

    snapshot(conn, SNAPSHOT_KIND, list_pending(), "отмечен новый заказ")
    order_id = uuid.uuid4().hex[:12]
    total = sum(item["subtotal"] for item in clean)
    with conn:
        conn.execute(
            "INSERT INTO purchase_orders "
            "(id, seller_name, seller_kind, total, created, status, fingerprint) "
            "VALUES (?,?,?,?,?,'pending',?)",
            (order_id, seller, seller_kind or "user", total,
             time.strftime("%Y-%m-%d %H:%M:%S"), fingerprint),
        )
        conn.executemany(
            "INSERT INTO purchase_order_items "
            "(order_id, name_norm, name, quantity, unit_price, subtotal) "
            "VALUES (?,?,?,?,?,?)",
            [
                (order_id, item["name_norm"], item["name"], item["quantity"],
                 item["unit_price"], item["subtotal"])
                for item in clean
            ],
        )
    return order_id


def remove(order_id: str) -> bool:
    with _MUTATION_LOCK:
        return _remove(order_id)


def _remove(order_id: str) -> bool:
    conn = _conn()
    row = conn.execute(
        "SELECT id FROM purchase_orders WHERE id = ? AND status = 'pending'",
        (order_id,),
    ).fetchone()
    if row is None:
        return False
    snapshot(conn, SNAPSHOT_KIND, list_pending(), "снята отметка заказа")
    with conn:
        conn.execute("DELETE FROM purchase_order_items WHERE order_id = ?", (order_id,))
        conn.execute("DELETE FROM purchase_orders WHERE id = ?", (order_id,))
    return True


def receive(order_id: str) -> bool:
    """Move a pending order into the collection exactly once."""
    with _MUTATION_LOCK:
        return _receive(order_id)


def _receive(order_id: str) -> bool:
    conn = _conn()
    row = conn.execute(
        "SELECT id FROM purchase_orders WHERE id = ? AND status = 'pending'",
        (order_id,),
    ).fetchone()
    if row is None:
        return False
    items = conn.execute(
        "SELECT name_norm, name, quantity FROM purchase_order_items WHERE order_id = ?",
        (order_id,),
    ).fetchall()
    conn.executescript(collection_store.SCHEMA)
    current = {
        r["name"]: int(r["count"])
        for r in conn.execute("SELECT name, count FROM collection WHERE count > 0")
    }
    snapshot(conn, collection_store.SNAPSHOT_KIND, current, "получен заказ")
    snapshot(conn, SNAPSHOT_KIND, list_pending(), "заказ перенесён в коллекцию")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        for item in items:
            conn.execute(
                "INSERT INTO collection (name_norm, name, count, updated) VALUES (?,?,?,?) "
                "ON CONFLICT(name_norm) DO UPDATE SET "
                "count = collection.count + excluded.count, name = excluded.name, updated = excluded.updated",
                (item["name_norm"], item["name"], item["quantity"], now),
            )
        conn.execute(
            "UPDATE purchase_orders SET status = 'received', received = ? "
            "WHERE id = ?",
            (now, order_id),
        )
    collection_store.reset_connection()
    return True


HISTORY_LIMIT = 60


def history(limit: int = HISTORY_LIMIT) -> list[dict[str, Any]]:
    """Orders already received, newest first, with what was in them.

    The rows were being kept and never read. They are the only place the
    program knows what a card actually cost you -- topdeck prices move, and a
    cached price from March is not what you paid in March.
    """
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM purchase_orders WHERE status = 'received' "
        "ORDER BY COALESCE(received, created) DESC, id DESC LIMIT ?",
        (max(1, int(limit or HISTORY_LIMIT)),),
    ).fetchall()
    out = []
    for row in rows:
        order = dict(row)
        order["items"] = [
            dict(item) for item in conn.execute(
                "SELECT name, name_norm, quantity, unit_price, subtotal "
                "FROM purchase_order_items WHERE order_id = ? ORDER BY name_norm",
                (row["id"],),
            )
        ]
        order["cards"] = sum(int(i["quantity"]) for i in order["items"])
        out.append(order)
    return out


def spent() -> dict[str, Any]:
    """What the history adds up to: money, cards, sellers, first and last."""
    row = _conn().execute(
        "SELECT COUNT(*) AS orders, COALESCE(SUM(total), 0) AS total, "
        "COUNT(DISTINCT LOWER(seller_name)) AS sellers, "
        "MIN(COALESCE(received, created)) AS first, "
        "MAX(COALESCE(received, created)) AS last "
        "FROM purchase_orders WHERE status = 'received'"
    ).fetchone()
    cards = _conn().execute(
        "SELECT COALESCE(SUM(i.quantity), 0) AS cards "
        "FROM purchase_order_items i JOIN purchase_orders o ON o.id = i.order_id "
        "WHERE o.status = 'received'"
    ).fetchone()
    return {
        "orders": int(row["orders"] or 0),
        "total": int(row["total"] or 0),
        "sellers": int(row["sellers"] or 0),
        "cards": int(cards["cards"] or 0),
        "first": row["first"],
        "last": row["last"],
    }


def purchases_of(name: str) -> list[dict[str, Any]]:
    """Every time this card was actually bought, and for how much.

    Answers the question a price cache cannot: not "what does it cost now" but
    "what did I pay, and to whom".
    """
    key = str(name or "").strip().lower()
    if not key:
        return []
    return [
        dict(row) for row in _conn().execute(
            "SELECT o.id, o.seller_name, o.seller_kind, "
            "COALESCE(o.received, o.created) AS when_received, "
            "i.name, i.quantity, i.unit_price, i.subtotal "
            "FROM purchase_order_items i JOIN purchase_orders o ON o.id = i.order_id "
            "WHERE o.status = 'received' AND i.name_norm = ? "
            "ORDER BY when_received DESC",
            (key,),
        )
    ]


def state(with_history: bool = True) -> dict[str, Any]:
    """Everything the interface shows about orders.

    History rides along with the pending list: it is a local read of a small
    table, and it means the panel is right the moment an order is received
    rather than after a second request.
    """
    out = {"orders": list_pending(), "ordered": ordered_counts()}
    if with_history:
        out["history"] = history()
        out["spent"] = spent()
    return out


__all__ = [
    "create", "history", "list_pending", "ordered_counts", "purchases_of",
    "receive", "remove", "reset_connection", "spent", "state",
]
