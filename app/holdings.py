"""Что у меня есть и где оно лежит.

Коллекция сама по себе -- просто список «сколько каких карт есть». Вопрос, на
который она не отвечает, звучит так: **можно ли собрать вот эту колоду прямо
сейчас** -- и ответ зависит не только от коллекции, но и от того, что уже
разобрано по другим колодам.

Поэтому у колоды есть признак: собрана она физически или существует на бумаге.

* **Собрана** -- её карты лежат в ней. Они заняты: их нельзя одновременно
  положить в другую колоду. Четыре Молнии, занятые собранной колодой, для всех
  остальных колод не существуют.
* **На бумаге** -- это замысел. Её карты ничем не заняты; вопрос к ней другой:
  хватит ли свободных карт, чтобы её собрать, и сколько стоит недостающее.

Отсюда три числа на каждую карту: сколько есть, сколько занято собранными
колодами и сколько свободно. И два рода несоответствий, которые стоит видеть:
карта, которой в собранных колодах больше, чем есть в коллекции (две колоды
делят одни и те же карты -- значит, одна из них собрана только на словах), и
карта из собранной колоды, которой в коллекции нет вовсе.

Ничего из этого не хранится: всё считается из коллекции и колод на лету, а
единственное новое, что появляется в базе, -- признак «собрана» у колоды.
"""

from __future__ import annotations

from typing import Any

from .cards import CardDB, normalize_name

# Секции, которые физически лежат в колоде. «Возможно» -- это список пожеланий,
# картами он не распоряжается.
REAL_SECTIONS = ("main", "commander", "side")


def _add(store: dict[str, int], key: str, count: int) -> None:
    store[key] = store.get(key, 0) + count


def gather(deck_store: Any, collection: dict[str, int],
           db: CardDB | None = None) -> dict[str, Any]:
    """Свести коллекцию и колоды в одну картину.

    Ключ -- нормализованное имя: «Tiamat's» и «Tiamat’s» это одна карта, и
    складывать их в разные строки значило бы врать в обе стороны.
    """
    owned: dict[str, int] = {}
    display: dict[str, str] = {}
    for name, count in (collection or {}).items():
        key = normalize_name(name)
        if not key:
            continue
        _add(owned, key, int(count or 0))
        display.setdefault(key, name)

    decks = deck_store.list_decks()
    committed: dict[str, int] = {}
    listed: dict[str, int] = {}
    where: dict[str, list[dict[str, Any]]] = {}
    deck_rows: list[dict[str, Any]] = []

    for deck in decks:
        full = deck_store.get_deck(deck["id"])
        assembled = bool(deck.get("assembled"))
        wants: dict[str, int] = {}
        for card in full.get("cards", []):
            if card.get("section") not in REAL_SECTIONS:
                continue
            key = normalize_name(card.get("name") or "")
            if not key:
                continue
            _add(wants, key, int(card.get("quantity") or 0))
            display.setdefault(key, card.get("name") or key)

        for key, count in wants.items():
            _add(listed, key, count)
            if assembled:
                _add(committed, key, count)
            where.setdefault(key, []).append({
                "deck_id": deck["id"],
                "deck": deck["name"],
                "quantity": count,
                "assembled": assembled,
            })

        deck_rows.append({
            "id": deck["id"],
            "name": deck["name"],
            "format": deck.get("format"),
            "assembled": assembled,
            "copies": sum(wants.values()),
            "distinct": len(wants),
            "wants": wants,
        })

    return {"owned": owned, "committed": committed, "listed": listed,
            "where": where, "display": display, "decks": deck_rows}


def report(deck_store: Any, collection: dict[str, int],
           db: CardDB | None = None,
           prices: dict[str, Any] | None = None) -> dict[str, Any]:
    """Полная картина: карты, колоды, несоответствия.

    `prices` -- кеш рублёвых цен по имени (тот же, что у билдера): по нему
    считается, во сколько обойдётся недостающее.
    """
    data = gather(deck_store, collection, db)
    owned, committed = data["owned"], data["committed"]
    listed, where, display = data["listed"], data["where"], data["display"]
    prices = prices or {}

    def price_of(key: str) -> int:
        row = prices.get(key) or prices.get(display.get(key, "").lower())
        return int((row or {}).get("rub_min") or 0)

    cards: list[dict[str, Any]] = []
    for key in sorted(set(owned) | set(listed)):
        have = owned.get(key, 0)
        held = committed.get(key, 0)
        cards.append({
            "key": key,
            "name": display.get(key, key),
            "owned": have,
            "committed": held,
            "free": have - held,
            "listed": listed.get(key, 0),
            "price": price_of(key),
            "decks": where.get(key, []),
        })

    # Что может пойти не так, и это стоит видеть отдельно.
    conflicts: list[dict[str, Any]] = []
    for card in cards:
        if card["committed"] > card["owned"]:
            conflicts.append({
                "kind": "shared" if card["owned"] else "missing",
                "name": card["name"],
                "owned": card["owned"],
                "committed": card["committed"],
                "decks": [d for d in card["decks"] if d["assembled"]],
            })

    # Свободно на руках -- то, из чего можно собрать следующую колоду.
    free = {c["key"]: c["free"] for c in cards}

    for deck in data["decks"]:
        missing = 0
        missing_rub = 0
        short: list[dict[str, Any]] = []
        for key, need in deck["wants"].items():
            available = owned.get(key, 0) if deck["assembled"] else free.get(key, 0)
            lack = max(0, need - max(0, available))
            if lack:
                missing += lack
                missing_rub += lack * price_of(key)
                short.append({"name": display.get(key, key), "need": need,
                              "have": max(0, available), "lack": lack,
                              "price": price_of(key)})
        short.sort(key=lambda s: (-s["lack"] * max(1, s["price"]), s["name"]))
        deck["missing"] = missing
        deck["missing_rub"] = missing_rub
        deck["short"] = short[:60]
        deck["ready"] = missing == 0
        del deck["wants"]

    totals = {
        # Строк в таблице больше, чем карт в коллекции: в неё попадает и то,
        # что числится в колодах, но чего на руках нет. Это не одно и то же
        # число, и в сводке они названы по-разному.
        "rows": len(cards),
        "cards": sum(1 for c in cards if c["owned"] > 0),
        "copies": sum(c["owned"] for c in cards),
        "committed": sum(c["committed"] for c in cards),
        "free": sum(max(0, c["free"]) for c in cards),
        "decks": len(data["decks"]),
        "assembled": sum(1 for d in data["decks"] if d["assembled"]),
    }
    return {"cards": cards, "decks": data["decks"], "conflicts": conflicts,
            "totals": totals}


__all__ = ["REAL_SECTIONS", "gather", "report"]
