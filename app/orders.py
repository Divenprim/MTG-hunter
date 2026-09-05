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
    fingerprint  TEXT NOT NULL
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


def _conn() -> sqlite3.Connection:
    existing = getattr(_local, "conn", None)
    path = user_db_path()
    if existing is not None and getattr(_local, "path", None) == path:
        return existing
    conn = connect_user_db(SCHEMA, path)
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
            "UPDATE purchase_orders SET status = 'received' WHERE id = ?", (order_id,)
        )
    collection_store.reset_connection()
    return True


def state() -> dict[str, Any]:
    return {"orders": list_pending(), "ordered": ordered_counts()}


__all__ = [
    "create", "list_pending", "ordered_counts", "receive", "remove",
    "reset_connection", "state",
]
