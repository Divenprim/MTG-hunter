"""Семейство колод: разные исполнения одного замысла.

История колоды идёт вдоль: версия за версией, «было -- стало», и вернуться
можно только назад. Но развитие колоды так не выглядит. Два turbofog -- это не
две версии одной колоды и не две разные колоды: это один замысел в двух
исполнениях, и главный вопрос к ним не «что поменялось», а **что у них общего**.

Общее и есть колода. Остальное -- сменные части.

Поэтому здесь считается:

* **ядро** -- карты, которые есть во всех исполнениях. Это и есть тот самый
  замысел, выраженный картами: если карта пережила все переделки, она нужна;
* **почти ядро** -- карты больше чем в половине исполнений: их выкидывали, но
  возвращали;
* **сменные** -- карты одного-двух исполнений. Это место, где колода ещё не
  решена, и именно отсюда берётся сайдборд;
* **кандидаты в сайдборд** -- сменные карты, которые по назначению ответные:
  удаление, контрмагия, защита, кладбищенская ненависть. Такую карту держат
  против чего-то, а не всегда, и место ей за пределами основной колоды;
* **условие победы** -- карты, которыми колода выигрывает, и есть ли они у всех
  исполнений. Ищется по функциональным тегам Scryfall Tagger.

Матрица «карта x исполнение» -- это всё сразу и без чтения: строка, закрашенная
целиком, и есть ядро.
"""

from __future__ import annotations

from typing import Any

from .cards import CardDB, normalize_name

# Секции, которые считаются самой колодой. Сайдборд разбирается отдельно --
# он и есть предмет разговора.
MAIN_SECTIONS = ("main", "commander")

# По этим тегам карта считается ответной: её держат против чего-то конкретного,
# а не играют каждую партию. Такие карты и есть кандидаты в сайдборд.
REACTIVE_TAGS = (
    "counterspell", "spot-removal", "removal", "sweeper", "graveyard-hate",
    "artifact-removal", "enchantment-removal", "land-destruction", "protection",
    "hexproof-granting", "fog", "lifegain", "discard", "stax", "tax",
    "anti-aggro", "prison",
)

# А по этим -- карта выигрывает игру сама: альтернативная победа, комбо-финиш,
# «вы выигрываете партию» прямым текстом.
WINCON_TAGS = (
    "alternate-win-condition", "wincon", "infinite-combo", "win-the-game",
    "mill-wincon", "combo-finisher", "damage-wincon",
)


def _key(name: str) -> str:
    return normalize_name(name or "")


def _tags_of(conn: Any, oracle_id: str) -> set[str]:
    if not oracle_id:
        return set()
    return {r["slug"] for r in conn.execute(
        "SELECT slug FROM card_tags WHERE oracle_id = ?", (oracle_id,))}


def families(deck_store: Any) -> list[dict[str, Any]]:
    """Какие семейства есть и кто в них входит.

    Колода без семейства -- сама себе семейство: она просто ещё не сравнивается
    ни с чем, и заводить для этого отдельное состояние незачем.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for deck in deck_store.list_decks():
        name = (deck.get("family") or "").strip()
        groups.setdefault(name or deck["name"], []).append({
            "id": deck["id"],
            "name": deck["name"],
            "format": deck.get("format"),
            "cards": deck.get("cards"),
            "assembled": bool(deck.get("assembled")),
            "own": bool(name),
        })
    out = [{"name": name, "decks": decks, "variants": len(decks),
            "explicit": any(d["own"] for d in decks)}
           for name, decks in groups.items()]
    out.sort(key=lambda f: (-f["variants"], f["name"].lower()))
    return out


def compare(deck_store: Any, deck_ids: list[str], db: CardDB | None = None,
            prices: dict[str, Any] | None = None) -> dict[str, Any]:
    """Сравнить исполнения между собой: матрица, ядро, сменные части."""
    prices = prices or {}
    variants: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    display: dict[str, str] = {}
    sideboards: dict[str, dict[str, int]] = {}

    for deck_id in deck_ids:
        deck = deck_store.get_deck(deck_id)
        wants: dict[str, int] = {}
        side: dict[str, int] = {}
        for card in deck.get("cards", []):
            key = _key(card.get("name"))
            if not key:
                continue
            display.setdefault(key, card.get("name"))
            qty = int(card.get("quantity") or 0)
            if card.get("section") in MAIN_SECTIONS:
                wants[key] = wants.get(key, 0) + qty
            elif card.get("section") == "side":
                side[key] = side.get(key, 0) + qty
        variants.append({
            "id": deck_id,
            "name": deck["name"],
            "format": deck.get("format"),
            "assembled": bool(deck.get("assembled")),
            "copies": sum(wants.values()),
            "names": len(wants),
        })
        counts[deck_id] = wants
        sideboards[deck_id] = side

    total = len(variants)
    rows: list[dict[str, Any]] = []
    # Карта, которая у кого-то уже в сайдборде, тоже попадает в матрицу: вопрос
    # «что можно вынести» без неё неполон -- не видно, что кто-то уже вынес.
    keys: set[str] = set()
    for store in list(counts.values()) + list(sideboards.values()):
        keys |= set(store)
    for key in keys:
        per = {deck_id: counts[deck_id].get(key, 0) for deck_id in deck_ids}
        present = sum(1 for v in per.values() if v > 0)
        price = int((prices.get(key) or {}).get("rub_min") or 0)
        rows.append({
            "key": key,
            "name": display.get(key, key),
            "counts": per,
            "present": present,
            "share": round(present / total, 3) if total else 0,
            "min": min(per.values()) if per else 0,
            "max": max(per.values()) if per else 0,
            "price": price,
            "in_side": {deck_id: sideboards[deck_id].get(key, 0) for deck_id in deck_ids},
        })

    # Назначение карты: по нему видно, что это -- ответ на чужой ход или то,
    # чем колода выигрывает.
    if db is not None:
        conn = db.conn
        for row in rows:
            card = db.by_name(row["name"])
            tags = _tags_of(conn, (card or {}).get("oracle_id") or "")
            row["reactive"] = any(any(t in tag for t in REACTIVE_TAGS) for tag in tags)
            row["wincon"] = any(any(t in tag for t in WINCON_TAGS) for tag in tags)
            row["tags"] = sorted(tags)[:6]
    else:
        for row in rows:
            row["reactive"] = False
            row["wincon"] = False
            row["tags"] = []

    rows.sort(key=lambda r: (-r["present"], -r["min"], -r["price"], r["name"]))

    core = [r for r in rows if total and r["present"] == total]
    often = [r for r in rows if total and total > 2 and 1 < r["present"] < total]
    # У единственного исполнения сменных частей нет: сравнивать не с чем, и
    # называть всю колоду «сменной» было бы неправдой.
    flex = [r for r in rows if total > 1 and r["present"] == 1]
    # Уже вынесенное: в основной колоде её нет ни у кого, а в сайдборде есть.
    side_only = [r for r in rows
                 if r["present"] == 0 and any(r["in_side"].values())]
    # Ядро в штуках: сколько карт совпадает у всех, если брать минимум копий.
    core_copies = sum(r["min"] for r in core)

    return {
        "variants": variants,
        "rows": rows,
        "core": [r["key"] for r in core],
        "often": [r["key"] for r in often],
        "flex": [r["key"] for r in flex],
        "side_only": [r["key"] for r in side_only],
        "sideboard_candidates": [r["key"] for r in flex if r.get("reactive")],
        "wincons": [r["key"] for r in rows if r.get("wincon")],
        "totals": {
            "variants": total,
            "names": len(rows),
            "core_names": len(core),
            "core_copies": core_copies,
            "often_names": len(often),
            "flex_names": len(flex),
            "side_names": len(side_only),
        },
    }


def report(deck_store: Any, name: str, db: CardDB | None = None,
           prices: dict[str, Any] | None = None) -> dict[str, Any]:
    """Всё об одном семействе."""
    found = next((f for f in families(deck_store) if f["name"] == name), None)
    if found is None:
        return {"name": name, "variants": [], "rows": [], "totals": {"variants": 0}}
    out = compare(deck_store, [d["id"] for d in found["decks"]], db, prices)
    out["name"] = name
    out["explicit"] = found["explicit"]
    return out


__all__ = ["MAIN_SECTIONS", "REACTIVE_TAGS", "WINCON_TAGS", "compare",
           "families", "report"]
