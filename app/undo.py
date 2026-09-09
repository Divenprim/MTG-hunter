"""Отмена последнего действия.

Every store here already writes a snapshot of itself before it changes
anything -- that was for the backup lists in the interface. The same snapshots
make an undo possible, and an undo is worth far more than a backup list: it
turns "точно удалить?" dialogues into something you can simply take back.

So this module adds no new bookkeeping. It looks at the newest snapshot of a
kind and puts it back.

Two things it is careful about:

  * restoring takes its own snapshot first, so undo is itself undoable and a
    misplaced undo cannot lose anything;
  * receiving an order changes two things at once -- the pending list and the
    collection -- so undoing it restores both, in that order. Undoing half of
    that would leave the cards owned and the order gone.

What cannot be undone this way is said so rather than half-done: a topdeck
request, a message you already sent, a card database rebuild.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from . import collection as collection_store
from . import favourites, orders
from .storage import list_snapshots, read_snapshot, snapshot

# kind in the snapshots table -> what the interface calls it
KINDS = {
    "favourites": "избранное",
    "collection": "коллекция",
    "orders": "заказы",
}

# Undoing a received order has to put both halves back.
COMPOUND = {"receive": ("collection", "orders")}


class UndoError(RuntimeError):
    """Message is written for the user to read as-is."""


def _conn() -> sqlite3.Connection:
    """The connection the order store already keeps for this thread.

    Snapshots of every kind live in the one shared user database, so opening
    another connection here would be a second handle to the same file that
    nobody closes -- and on Windows an unclosed handle is a file that cannot
    be deleted.
    """
    return orders._conn()


def newest(kind: str) -> dict[str, Any] | None:
    rows = list_snapshots(_conn(), kind)
    return rows[0] if rows else None


def available() -> list[dict[str, Any]]:
    """What can be taken back right now, newest first."""
    out = []
    for kind, label in KINDS.items():
        row = newest(kind)
        if not row:
            continue
        out.append({
            "kind": kind,
            "label": label,
            "created": row.get("created"),
            "reason": row.get("reason") or "",
        })
    out.sort(key=lambda r: r["created"] or "", reverse=True)
    return out


def _restore_orders(snapshot_id: int) -> int:
    """Put the pending list back exactly as the snapshot has it."""
    payload = read_snapshot(_conn(), int(snapshot_id))
    if payload is None:
        raise UndoError("Такой резервной копии нет")
    if not isinstance(payload, list):
        raise UndoError("Резервная копия заказов испорчена")

    conn = orders._conn()
    snapshot(conn, orders.SNAPSHOT_KIND, orders.list_pending(),
             "перед отменой")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        pending = [
            row["id"] for row in conn.execute(
                "SELECT id FROM purchase_orders WHERE status = 'pending'")
        ]
        for order_id in pending:
            conn.execute(
                "DELETE FROM purchase_order_items WHERE order_id = ?", (order_id,))
            conn.execute("DELETE FROM purchase_orders WHERE id = ?", (order_id,))

        for order in payload:
            items = order.get("items") or []
            conn.execute(
                "INSERT OR REPLACE INTO purchase_orders "
                "(id, seller_name, seller_kind, total, created, status, "
                " fingerprint, received) "
                "VALUES (?,?,?,?,?,'pending',?,NULL)",
                (order.get("id") or ("undo-" + now),
                 order.get("seller_name") or "",
                 order.get("seller_kind") or "user",
                 int(order.get("total") or 0),
                 order.get("created") or now,
                 order.get("fingerprint") or ""),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO purchase_order_items "
                "(order_id, name_norm, name, quantity, unit_price, subtotal) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (order.get("id"), item.get("name_norm") or
                     str(item.get("name", "")).strip().lower(),
                     item.get("name") or "", int(item.get("quantity") or 0),
                     int(item.get("unit_price") or 0),
                     int(item.get("subtotal") or 0))
                    for item in items
                ],
            )
    return len(payload)


def undo(kind: str) -> dict[str, Any]:
    """Take back the last change of this kind."""
    if kind in COMPOUND:
        done = []
        for part in COMPOUND[kind]:
            done.append(undo(part)["kind"])
        return {"kind": kind, "undone": done,
                "label": "получение заказа"}

    if kind not in KINDS:
        raise UndoError("Это отменить нельзя: %s" % kind)

    row = newest(kind)
    if not row:
        raise UndoError("Отменять нечего — изменений %s не записано" % KINDS[kind])

    if kind == "favourites":
        favourites.restore(int(row["id"]))
    elif kind == "collection":
        collection_store.restore(int(row["id"]))
    elif kind == "orders":
        _restore_orders(int(row["id"]))

    return {
        "kind": kind,
        "label": KINDS[kind],
        "restored_from": row.get("created"),
        "reason": row.get("reason") or "",
    }


__all__ = ["COMPOUND", "KINDS", "UndoError", "available", "newest", "undo"]
