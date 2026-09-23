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
from .formats import BASIC_LANDS

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


# --------------------------------------------------------------------------- #
# Группа целиком: спеки рядом и общий список покупок
# --------------------------------------------------------------------------- #

# Что нужно, чтобы колода лежала в коробке: основная, командир и сайдборд.
# «Возможно» -- это черновик мыслей, за него не платят.
BUY_SECTIONS = ("main", "commander", "side")


def specs(decks: list[dict[str, Any]]) -> dict[str, Any]:
    """Спеки исполнений рядом -- чем они отличаются как колоды, а не как списки.

    Матрица отвечает на вопрос «какие карты общие». Этот -- на другой: одна и
    та же идея в пионере и в модерне обычно расходится не списком, а формой.
    Двадцать четыре земли против двадцати шести, средняя мана 2.1 против 2.6,
    половина кривой на двойке против ровной -- вот это и решает, какая из них
    как играет.

    Считается по уже собранной статистике колоды (deckbuild.stats), поэтому
    цифры здесь те же самые, что в билдере, а не отдельная их версия.
    """
    rows: list[dict[str, Any]] = []
    for deck in decks:
        st = deck.get("stats") or {}
        curve = {int(k): int(v) for k, v in (st.get("curve") or {}).items()}
        copies = int(st.get("copies") or 0)
        lands = int(st.get("lands") or 0)
        side = sum(int(c.get("quantity") or 0) for c in deck.get("cards") or []
                   if c.get("section") == "side")
        rows.append({
            "id": deck.get("id"),
            "name": deck.get("name"),
            "format": deck.get("format"),
            "assembled": bool(deck.get("assembled")),
            "copies": copies,
            "side": side,
            "names": len({(c.get("name") or "").lower()
                          for c in deck.get("cards") or []
                          if c.get("section") in BUY_SECTIONS}),
            "lands": lands,
            "land_share": round(lands / copies, 3) if copies else 0.0,
            "avg_mv": st.get("avg_mv"),
            "median_mv": st.get("median_mv"),
            "curve": curve,
            "colors": st.get("colors") or {},
            "types": st.get("types") or {},
            "total_rub": int(deck.get("total_rub") or 0),
            "missing_copies": int(deck.get("missing_copies") or 0),
            "missing_rub": int(deck.get("missing_rub") or 0),
            "problems": len(deck.get("problems") or []),
        })

    # Пределы по каждому столбцу -- чтобы в таблице было видно, кто крайний, и
    # не приходилось сравнивать числа глазами.
    def span(field: str) -> dict[str, Any]:
        values = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
        return {"min": min(values), "max": max(values)} if values else {}

    return {
        "decks": rows,
        "span": {f: span(f) for f in
                 ("copies", "lands", "land_share", "avg_mv", "total_rub",
                  "missing_copies", "missing_rub")},
        "buckets": sorted({b for r in rows for b in r["curve"]}),
    }


def _is_basic(name: str, card: dict[str, Any] | None) -> bool:
    if (name or "").strip().lower() in BASIC_LANDS:
        return True
    line = ((card or {}).get("type_line") or "").lower()
    return "basic" in line and "land" in line


def shopping(decks: list[dict[str, Any]], collection: dict[str, int] | None = None,
             prices: dict[str, Any] | None = None,
             mode: str = "together", basics: bool = False) -> dict[str, Any]:
    """Что докупить, чтобы эти колоды существовали.

    Тут два разных вопроса, и ответ на них разный настолько, что выбирать
    приходится вам:

      together -- «хочу, чтобы все они лежали собранными одновременно».
        Тогда четыре «Тумана» в пионерской и четыре в модерновой -- это восемь
        «Туманов», и купить надо недостающие до восьми.

      byturn -- «играю ими по очереди, пересобираю между играми».
        Тогда тех же «Туманов» нужно четыре, а не восемь: карты кочуют из
        колоды в колоду. Это и дешевле, и честнее для большинства.

    Своё уже посчитано: из коллекции вычитается то, что есть. Цена -- рублёвая
    из кеша topdeck, и она умножается на недостающее, а не на всё подряд.

    Базовые земли по умолчанию не считаются: «20 Forest» в списке покупок -- это
    не покупка, а шум, лес есть у всех. Но сказать о них надо: сколько их и
    сколько бы стоили, если начинать с нуля.
    """
    prices = prices or {}
    owned = {normalize_name(str(k)): int(v or 0)
             for k, v in (collection or {}).items() if str(k).strip()}

    display: dict[str, str] = {}
    want: dict[str, dict[str, int]] = {}      # карта -> колода -> сколько
    basic_keys: set[str] = set()
    for deck in decks:
        deck_id = deck.get("id") or ""
        for card in deck.get("cards") or []:
            if card.get("section") not in BUY_SECTIONS:
                continue
            name = card.get("name") or ""
            key = normalize_name(name)
            if not key:
                continue
            display.setdefault(key, name or key)
            if _is_basic(name, card.get("card")):
                basic_keys.add(key)
            per = want.setdefault(key, {})
            per[deck_id] = per.get(deck_id, 0) + int(card.get("quantity") or 0)

    rows: list[dict[str, Any]] = []
    for key, per in want.items():
        needed = sum(per.values()) if mode == "together" else max(per.values())
        have = owned.get(key, 0)
        missing = max(0, needed - have)
        price = int((prices.get(key) or {}).get("rub_min") or 0)
        rows.append({
            "key": key,
            "name": display.get(key, key),
            "needed": needed,
            "owned": have,
            "missing": missing,
            "price": price,
            "cost": price * missing,
            "basic": key in basic_keys,
            "per_deck": per,
            # Карта, которую хотят сразу несколько исполнений: из-за них и
            # расходятся два ответа.
            "shared": len([d for d, n in per.items() if n > 0]) > 1,
        })

    rows.sort(key=lambda r: (-r["cost"], -r["missing"], r["name"]))
    counted = [r for r in rows if basics or not r["basic"]]
    buy = [r for r in counted if r["missing"] > 0]
    skipped = [r for r in rows if r["basic"] and not basics and r["missing"] > 0]
    shared = [r for r in counted if r["shared"]]
    unpriced = [r["name"] for r in buy if not r["price"]]

    # Насколько дешевле обойдётся «по очереди»: та же группа, другой ответ.
    other = "byturn" if mode == "together" else "together"
    other_cost = 0
    for row in counted:
        per = row["per_deck"]
        needed = sum(per.values()) if other == "together" else max(per.values())
        other_cost += max(0, needed - row["owned"]) * row["price"]

    return {
        "mode": mode,
        "basics": basics,
        "decks": [{"id": d.get("id"), "name": d.get("name"),
                   "format": d.get("format")} for d in decks],
        "rows": rows,
        "buy": buy,
        "totals": {
            "names": len(counted),
            "copies": sum(r["needed"] for r in counted),
            "owned": sum(min(r["owned"], r["needed"]) for r in counted),
            # Базовые земли, которые не вошли в счёт: сказать о них надо.
            "basic_names": len(skipped),
            "basic_copies": sum(r["missing"] for r in skipped),
            "basic_cost": sum(r["cost"] for r in skipped),
            "missing_names": len(buy),
            "missing_copies": sum(r["missing"] for r in buy),
            "cost": sum(r["cost"] for r in buy),
            "unpriced": len(unpriced),
            "shared_names": len(shared),
            "other_mode": other,
            "other_cost": other_cost,
        },
        "unpriced": unpriced,
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
