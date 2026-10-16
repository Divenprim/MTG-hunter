"""Перенос своего с одного устройства на другое.

Программа локальная: данные лежат в `data/user.sqlite` того компьютера, на
котором её запустили. Второй компьютер, ноутбук в поездке, переезд на новую
машину -- и всё приходится набирать заново. Скопировать сам `user.sqlite`
можно, но это «всё или ничего»: он затирает то, что уже нажито на той
стороне, вместе с заказами и историей цен.

Поэтому отдельный файл переноса -- JSON, который видно глазами:

* **коллекция** -- по печатям, а не по именам. Карта в коллекции это «Sol Ring
  из C21 №263, нефойл», и выгрузка по именам теряет ровно то, ради чего
  коллекция ведётся по печатям;
* **колоды** -- со всем, что у них есть: формат, заметки, разделы, категории,
  печати, семейство, отметка «собрана»;
* **избранное** -- папками, с количествами и печатями.

Чего здесь нет и почему: цены (их переспросит та сторона -- они стареют),
заказы (это история покупок именно этого человека на этом устройстве),
снимки (переносить чужую историю отмен бессмысленно).

**Как ложится на той стороне.** Два способа, и человек выбирает:

* `merge` -- добавить к тому, что есть. Коллекция складывается по печатям,
  колоды с тем же именем не трогаются, а новые создаются, папки избранного
  дополняются;
* `replace` -- заменить целиком. Коллекция перезаписывается, колоды с
  совпадающим именем заменяются новым составом.

Перед любой записью снимается снимок -- тот же, что у всех остальных правок:
импорт не должен быть единственным действием в программе, которое нельзя
отменить.
"""

from __future__ import annotations

import json
from typing import Any

from . import collection as collection_store
from . import favourites as fav_store
from .decks import DeckStore

# Версия формата. Меняется, когда меняется смысл полей: читатель должен
# отказаться от файла, которого не понимает, а не угадывать.
FORMAT = 1
KIND = "mtg-hunter-transfer"


class TransferError(Exception):
    """Файл переноса не подошёл. Текст виден человеку."""


# --------------------------------------------------------------- выгрузка

def export_all(store: DeckStore) -> dict[str, Any]:
    """Всё своё -- одним куском."""
    decks = []
    for row in store.list_decks():
        full = store.get_deck(row["id"])
        decks.append({
            "name": full.get("name") or "",
            "format": full.get("format") or "",
            "notes": full.get("notes") or "",
            "family": full.get("family") or "",
            "assembled": bool(full.get("assembled")),
            "cards": [{
                "name": c.get("name") or "",
                "quantity": int(c.get("quantity") or 0),
                "section": c.get("section") or "main",
                "category": c.get("category") or "",
                "set_code": c.get("set_code") or "",
                "collector_number": c.get("collector_number") or "",
                "note": c.get("note") or "",
            } for c in (full.get("cards") or [])],
        })

    doc = fav_store.load()
    folders = [{
        "name": f.get("name") or "",
        "cards": [{
            "name": c.get("name") or "",
            "quantity": int(c.get("quantity") or 1),
            "set_code": c.get("set_code") or "",
            "collector_number": c.get("collector_number") or "",
            "note": c.get("note") or "",
        } for c in (f.get("cards") or [])],
    } for f in (doc.get("folders") or [])]

    collection = [{
        "name": row.get("name") or "",
        "count": int(row.get("count") or 0),
        "set_code": row.get("set_code") or "",
        "collector_number": row.get("collector_number") or "",
        "finish": row.get("finish") or "nonfoil",
    } for row in collection_store.items() if int(row.get("count") or 0) > 0]

    return {
        "kind": KIND,
        "format": FORMAT,
        "collection": collection,
        "decks": decks,
        "favourites": folders,
        # Сводка -- не для программы, а для человека: открыв файл, он сразу
        # видит, то ли это, что он выгружал.
        "summary": {
            "collection_rows": len(collection),
            "collection_copies": sum(r["count"] for r in collection),
            "decks": len(decks),
            "deck_cards": sum(len(d["cards"]) for d in decks),
            "folders": len(folders),
        },
    }


# ----------------------------------------------------------------- чтение

def read_file(payload: bytes | str) -> dict[str, Any]:
    """Разобрать файл переноса и убедиться, что это он.

    Файл приходит от человека, то есть из любого места: с флешки, из почты,
    из чужих рук. Проверяем вид и версию, а внутри -- только то, что собираемся
    читать; на лишние поля не ругаемся, их может добавить будущая версия.
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise TransferError("это не файл переноса: не разбирается как JSON "
                            "(%s)" % exc) from exc
    if not isinstance(data, dict):
        raise TransferError("это не файл переноса: внутри не объект")
    if data.get("kind") != KIND:
        raise TransferError("это не файл переноса MTG Hunter")
    version = data.get("format")
    if not isinstance(version, int) or version > FORMAT:
        raise TransferError(
            "файл сделан более новой версией программы (формат %s, здесь "
            "понимают %s) — обновите программу на этом устройстве"
            % (version, FORMAT))

    out = {"collection": [], "decks": [], "favourites": []}
    for row in data.get("collection") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        count = int(row.get("count") or 0)
        if name and count > 0:
            out["collection"].append({
                "name": name,
                "count": count,
                "set_code": str(row.get("set_code") or ""),
                "collector_number": str(row.get("collector_number") or ""),
                "finish": str(row.get("finish") or "nonfoil"),
            })

    for deck in data.get("decks") or []:
        if not isinstance(deck, dict):
            continue
        name = str(deck.get("name") or "").strip()
        if not name:
            continue
        cards = []
        for card in deck.get("cards") or []:
            if not isinstance(card, dict):
                continue
            card_name = str(card.get("name") or "").strip()
            if not card_name:
                continue
            cards.append({
                "name": card_name,
                "quantity": max(1, int(card.get("quantity") or 1)),
                "section": str(card.get("section") or "main"),
                "category": str(card.get("category") or ""),
                "set_code": str(card.get("set_code") or ""),
                "collector_number": str(card.get("collector_number") or ""),
                "note": str(card.get("note") or ""),
            })
        out["decks"].append({
            "name": name,
            "format": str(deck.get("format") or ""),
            "notes": str(deck.get("notes") or ""),
            "family": str(deck.get("family") or ""),
            "cards": cards,
        })

    for folder in data.get("favourites") or []:
        if not isinstance(folder, dict):
            continue
        name = str(folder.get("name") or "").strip()
        if not name:
            continue
        cards = []
        for card in folder.get("cards") or []:
            if not isinstance(card, dict):
                continue
            card_name = str(card.get("name") or "").strip()
            if not card_name:
                continue
            cards.append({
                "name": card_name,
                "quantity": max(1, int(card.get("quantity") or 1)),
                "set_code": str(card.get("set_code") or ""),
                "collector_number": str(card.get("collector_number") or ""),
                "note": str(card.get("note") or ""),
            })
        out["favourites"].append({"name": name, "cards": cards})

    return out


# ----------------------------------------------------------------- приём

def _import_collection(rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "copies": 0}
    payload = [{
        "name": r["name"],
        "quantity": r["count"],
        "set_code": r["set_code"] or None,
        "collector_number": r["collector_number"] or None,
        "finish": r["finish"],
    } for r in rows]
    if mode == "replace":
        collection_store.replace_items(payload)
    else:
        collection_store.add_items(payload)
    return {"rows": len(rows), "copies": sum(r["count"] for r in rows)}


def _import_decks(decks: list[dict[str, Any]], store: DeckStore,
                  mode: str) -> dict[str, Any]:
    existing = {(d.get("name") or "").strip().lower(): d["id"]
                for d in store.list_decks()}
    added = replaced = skipped = 0
    for deck in decks:
        key = deck["name"].strip().lower()
        if key in existing:
            if mode != "replace":
                # Колода с таким именем уже есть: трогать её при слиянии
                # нельзя -- человек мог развивать её здесь.
                skipped += 1
                continue
            store.delete_deck(existing[key])
            replaced += 1
        else:
            added += 1
        deck_id = store.create_deck(deck["name"],
                                    deck["format"] or "commander",
                                    notes=deck.get("notes") or "")
        for card in deck["cards"]:
            # Заметку у карты колоды записать нечем: в хранилище её кладёт
            # отдельная правка, а не добавление. Переносим всё остальное и
            # не делаем вид, что перенесли заметку.
            store.add_card(
                deck_id, card["name"], card["quantity"],
                section=card["section"], category=card["category"],
                set_code=card["set_code"] or None,
                collector_number=card["collector_number"] or None)
        if deck.get("family"):
            store.rename_deck(deck_id, None, None,
                              family=deck.get("family"))
    return {"added": added, "replaced": replaced, "skipped": skipped}


def _import_favourites(folders: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    if not folders:
        return {"folders": 0, "cards": 0}
    doc = fav_store.load()
    have = {(f.get("name") or "").strip().lower(): f
            for f in (doc.get("folders") or [])}
    made = cards = 0
    for folder in folders:
        key = folder["name"].strip().lower()
        target = have.get(key)
        if target is None:
            # create_folder возвращает весь документ избранного -- папку из
            # него и берём, по имени: это единственное, что мы про неё знаем.
            doc = fav_store.create_folder(folder["name"])
            made += 1
            have = {(f.get("name") or "").strip().lower(): f
                    for f in (doc.get("folders") or [])}
            target = have.get(key)
        if not target:
            continue
        known = {(c.get("name") or "").strip().lower()
                 for c in (target.get("cards") or [])}
        for card in folder["cards"]:
            if mode != "replace" and card["name"].strip().lower() in known:
                continue
            fav_store.add_card(
                target["id"], card["name"], card["quantity"],
                set_code=card["set_code"] or None,
                collector_number=card["collector_number"] or None)
            cards += 1
    return {"folders": made, "cards": cards}


def import_all(data: dict[str, Any], store: DeckStore,
               mode: str = "merge") -> dict[str, Any]:
    """Положить принесённое. `mode`: "merge" или "replace"."""
    if mode not in ("merge", "replace"):
        raise TransferError("непонятный способ переноса: %s" % mode)
    return {
        "mode": mode,
        "collection": _import_collection(data.get("collection") or [], mode),
        "decks": _import_decks(data.get("decks") or [], store, mode),
        "favourites": _import_favourites(data.get("favourites") or [], mode),
    }


__all__ = ["FORMAT", "KIND", "TransferError", "export_all", "read_file",
           "import_all"]
