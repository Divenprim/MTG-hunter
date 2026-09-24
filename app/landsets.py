"""Наборы земель: то, что покупают и играют вместе.

Манабаза собирается не по одной карте, а наборами. Десять шоковых земель --
это один набор, пять трайомов -- другой, шесть артефактных земель под аффинити
-- третий. Вопрос «что бы такого купить по четыре штуки, чтобы потом собирать
что угодно» -- это вопрос про наборы, а не про карты.

Каталог собирается из данных, а не из головы:

  * **циклы тегов Scryfall**. В таксономии циклы уже размечены:
    `cycle-rav-shockland`, `cycle-iko-triome`, `cycle-som-fastland`,
    `cycle-mrd-artifact-land`. Берутся те, где все карты набора -- земли;
  * **комбо из базы Commander Spellbook**, у которых все куски -- земли.
    Dark Depths с Thespian's Stage покупают именно вместе;
  * **короткий список руками** -- для того, чего в таксономии нет. Urza's
    Mine, Power-Plant и Tower тегом не связаны, а набором являются; таких
    случаев единицы, и врать про них нечего.

Цена считается двумя способами, потому что покупают по-разному: по одной карте
набора (посмотреть) и по четыре каждой (чтобы собрать что угодно). Для
командирских колод четыре штуки не нужны -- там и одной хватает, -- поэтому
показываются оба числа.
"""

from __future__ import annotations

from typing import Any

from .cards import CardDB
from . import manabase

# Наборы, которых нет в таксономии тегов. Каждый -- список точных имён.
HANDMADE: dict[str, dict[str, Any]] = {
    "urza-tron": {
        "label": "Трон Урзы",
        "why": "три земли, которые вместе дают семь маны",
        "cards": ["Urza's Mine", "Urza's Power Plant", "Urza's Tower"],
    },
    "dark-depths": {
        "label": "Dark Depths + копия",
        "why": "земля, делающая 20/20 за ноль маны, и то, чем её копируют",
        "cards": ["Dark Depths", "Thespian's Stage", "Vesuva"],
    },
}

# Циклы меньше трёх карт -- не набор, а пара случайных совпадений; больше
# пятнадцати -- уже не цикл, а вся категория.
MIN_SET = 3
MAX_SET = 15

# Как называются виды земель по-русски. Слаг цикла устроен как
# «cycle-<сет>-<что это>», и вторая часть повторяется из сета в сет.
KIND_WORDS = {
    "shockland": "шоковые земли",
    "fetchland": "фетчи",
    "triome": "трайомы",
    "fastland": "быстрые земли",
    "checkland": "чек-земли",
    "slowland": "медленные земли",
    "painland": "болевые земли",
    "painlands": "болевые земли",
    "filterland": "фильтры",
    "pathway": "пути",
    "horizon-land": "горизонтные земли",
    "artifact-land": "артефактные земли",
    "storage-land": "земли-копилки",
    "tapland": "тапленды",
    "dual-land": "двойные земли",
    "dual-tapland": "двойные тапленды",
    "gainland": "земли с жизнями",
    "scry-land": "земли со скраем",
    "surveil-land": "земли с наблюдением",
    "surveil-dual": "двойные земли с наблюдением",
    "cycling-land": "земли с циклированием",
    "bounce-land": "земли-возвраты",
    "creature-land": "земли-существа",
    "utility-land": "утилитарные земли",
    "utilityland": "утилитарные земли",
    "guildgate": "гейты",
    "refugeland": "земли-убежища",
    "landscape": "ландшафты",
    "bridge": "мосты",
    "realm": "чертоги",
    "memorial": "мемориалы",
    "blighted-land": "заражённые земли",
    "snow-tapland": "снежные тапленды",
    "thirteenland": "тринадцать земель",
    "typal-land": "типовые земли",
    "typal-dual": "типовые двойные",
    "town": "города",
    "basic-land": "базовые земли",
    "basic-snow-land": "снежные базовые",
    "creatureland": "земли-существа",
    "bounceland": "земли-возвраты",
    "karoo-land": "земли-возвраты",
    "tangoland": "земли битв",
    "reveal-land": "земли с показом",
    "napland": "земли со сном",
    "pingland": "земли-пинги",
    "shardland": "трёхцветные тапленды",
    "wedgeland": "трёхцветные тапленды",
    "panorama": "панорамы",
    "vivid-land": "яркие земли",
    "campus": "кампусы",
    "castle": "замки",
    "village": "деревни",
    "guildhall": "гильдейские залы",
    "thriving-land": "цветущие земли",
    "thriving-gate": "цветущие гейты",
    "hidden-land": "скрытые земли",
    "hideaway-land": "земли-тайники",
    "namedland": "именные земли",
    "legendary-land": "легендарные земли",
    "restless-land": "беспокойные земли",
    "adamant-land": "земли стойкости",
    "adventure-land": "земли-приключения",
    "bond-land": "земли дружбы",
    "lair": "логова",
    "lair-dual": "двойные логова",
    "tainted-land": "порченые земли",
    "depletion-land": "истощаемые земли",
    "sacland": "земли с жертвой",
    "sacrifice-cost-land": "земли с жертвой",
    "sol-land": "земли двойной маны",
    "storage-land": "земли-копилки",
    "colored-sphere": "сферы",
    "roads": "дороги",
    "raceway": "трассы",
    "planet": "планеты",
    "octoland": "земли восьми",
    "banding-land": "земли строя",
    "manaless-land": "земли без маны",
    "conditional-tapland": "условные тапленды",
    "mono-land": "одноцветные земли",
    "rupture-spire": "земли всех цветов",
    "dual-land": "двойные земли",
    "urza-tron": "трон Урзы",
    "triland": "трёхцветные земли",
    "verge": "грани",
}


def _kind_word(tail: str) -> str:
    """Вид земель по хвосту слага, или пусто, если вид незнакомый."""
    if tail in KIND_WORDS:
        return KIND_WORDS[tail]
    # Хвост бывает составным: «dual-surveil-land», «c-tapland». Длинные ключи
    # проверяются первыми, иначе «snow-tapland» опознается как обычный тапленд
    # и снег из названия пропадёт.
    for key in sorted(KIND_WORDS, key=len, reverse=True):
        if tail.endswith(key):
            return KIND_WORDS[key]
    return ""


def _nice_label(db: CardDB, slug: str, size: int, fallback: str = "") -> str:
    """«cycle-rav-shockland» -> «шоковые земли · Ravnica: City of Guilds».

    Слаг -- имя для машины; человеку нужно название вида земель и сет, из
    которого они. И то и другое лежит в базе, выдумывать ничего не нужно.
    """
    parts = slug.split("-")
    if parts and parts[0] == "cycle":
        parts = parts[1:]
    # «cycle-block-bfz-creatureland» -- цикл не одного сета, а блока; сет
    # всё равно назван следом.
    if parts and parts[0] == "block":
        parts = parts[1:]
    set_name = ""
    if parts and len(parts[0]) in (3, 4):
        row = db.conn.execute(
            "SELECT set_name FROM cards WHERE set_code = ? LIMIT 1",
            (parts[0],)).fetchone()
        if row and row["set_name"]:
            set_name = row["set_name"]
            parts = parts[1:]
    tail = "-".join(parts)
    kind = _kind_word(tail) or fallback or tail.replace("-", " ")
    return "%s · %s" % (kind, set_name) if set_name else kind


def _cycle_sets(db: CardDB) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT t.slug AS slug, COUNT(*) AS n, "
        "  SUM(CASE WHEN LOWER(c.type_line) LIKE '%land%' THEN 1 ELSE 0 END) AS lands "
        "FROM card_tags t JOIN cards c ON c.oracle_id = t.oracle_id "
        "WHERE c.representative = 1 "
        "GROUP BY t.slug HAVING n BETWEEN ? AND ? AND lands = n",
        (MIN_SET, MAX_SET)).fetchall()
    labels = {r["slug"]: (r["label"] or r["slug"])
              for r in db.conn.execute("SELECT slug, label FROM tags")}
    out = []
    for r in rows:
        # Собственная подпись тега -- запасной вариант, а не первый: она
        # английская («storage land»), и русское название вида, если оно у нас
        # есть, читается лучше.
        own = labels.get(r["slug"]) or ""
        label = _nice_label(db, r["slug"], r["n"],
                            fallback="" if own == r["slug"] else own)
        out.append({"key": r["slug"], "label": label, "kind": "cycle",
                    "slug": r["slug"], "size": r["n"]})
    return out


def _cards_of_tag(db: CardDB, slug: str) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT c.* FROM card_tags t JOIN cards c ON c.oracle_id = t.oracle_id "
        "WHERE t.slug = ? AND c.representative = 1 ORDER BY c.name", (slug,))
    return [db.card_dict(r) for r in rows]


def _all_lands(cards: list[dict[str, Any]]) -> bool:
    """Все ли карты набора -- земли по передней стороне.

    Запрос к базе спрашивает про строку типа целиком, а «Creature // Land» --
    это существо: землёй оно станет, если доживёт и перевернётся. Такие наборы
    манабазой не считаются.
    """
    return bool(cards) and all(manabase.is_land(c) for c in cards)


def _cheapest(db: CardDB, oracle_id: str) -> float | None:
    row = db.conn.execute(
        "SELECT MIN(CAST(json_extract(prices, '$.usd') AS REAL)) AS usd "
        "FROM cards WHERE oracle_id = ? "
        "AND json_extract(prices, '$.usd') IS NOT NULL", (oracle_id,)).fetchone()
    return None if row is None or row["usd"] is None else float(row["usd"])


def _describe(db: CardDB, cards: list[dict[str, Any]],
              fmt: str = "") -> dict[str, Any]:
    """Во что обходится набор и что он умеет."""
    colors: set[str] = set()
    entries = {"open": 0, "maybe": 0, "tapped": 0}
    fetch = 0
    rows: list[dict[str, Any]] = []
    one = 0.0
    four = 0.0
    unpriced = 0
    for card in cards:
        price = _cheapest(db, card.get("oracle_id") or "")
        makes = manabase.produces(card)
        how = manabase.entry(card)
        if manabase.fetches(card):
            fetch += 1
        else:
            entries[how] = entries.get(how, 0) + 1
        colors.update(c for c in makes if c in manabase.COLORS)
        if price is None:
            unpriced += 1
        else:
            one += price
            four += price * 4
        rows.append({
            "name": card.get("name"),
            "ru_name": card.get("ru_name"),
            "image_small": card.get("image_small"),
            "image_normal": card.get("image_normal"),
            "produces": makes,
            "entry": how,
            "reliable": manabase.reliability(card, fmt),
            "usd": price,
            "legal": (card.get("legalities") or {}).get(fmt) if fmt else None,
        })
    # Насколько набор хорош сам по себе: сколько цветов он закрывает, какая
    # доля карт -- настоящие источники, и как они входят. Тапнутая земля не
    # запрещена, но набор из одних таплендов стоит ниже набора, который
    # выходит развёрнутым.
    total = max(1, len(rows))
    direct = sum(1 for r in rows if r["reliable"] == "direct") / total
    openness = (entries["open"] * 1.0 + entries["maybe"] * 0.7
                + entries["tapped"] * 0.15) / total
    dual = sum(1 for r in rows
               if len([c for c in r["produces"] if c in manabase.COLORS]) >= 2)
    quality = round(len(colors) * 0.6 + direct * 3.0 + openness * 3.0
                    + (dual / total) * 3.0, 2)
    return {
        "cards": rows,
        "colors": "".join(c for c in ("W", "U", "B", "R", "G") if c in colors),
        "entry": entries,
        "fetch": fetch,
        "duals": dual,
        "quality": quality,
        "usd_one": round(one, 2),
        "usd_playset": round(four, 2),
        "unpriced": unpriced,
    }


def catalogue(db: CardDB, fmt: str = "", combo_db: Any = None,
              budget: float | None = None, colors: str = "",
              order: str = "value", only_open: bool = False,
              limit: int = 60) -> dict[str, Any]:
    """Все наборы земель -- с ценой за комплект и за плейсет.

    Отбор по формату честный: набор попадает в выдачу, только если в этом
    формате легальны все его карты. Половина шоковых земель в стандарте --
    это не набор, а недоразумение.
    """
    want = set(colors) & set(manabase.COLORS)
    out: list[dict[str, Any]] = []

    for meta in _cycle_sets(db):
        cards = _cards_of_tag(db, meta["slug"])
        if not _all_lands(cards):
            continue
        if fmt and any((c.get("legalities") or {}).get(fmt) != "legal"
                       for c in cards):
            continue
        body = _describe(db, cards, fmt)
        if want and not (set(body["colors"]) & want):
            continue
        if budget is not None and body["usd_playset"] > budget:
            continue
        if only_open and body["entry"]["tapped"]:
            continue
        out.append(dict(meta, **body))

    for key, meta in HANDMADE.items():
        cards = [c for c in (db.by_name(n) for n in meta["cards"]) if c]
        if len(cards) < len(meta["cards"]):
            continue
        if fmt and any((c.get("legalities") or {}).get(fmt) != "legal"
                       for c in cards):
            continue
        body = _describe(db, cards, fmt)
        if want and not (set(body["colors"]) & want):
            continue
        if budget is not None and body["usd_playset"] > budget:
            continue
        out.append({"key": key, "label": meta["label"], "kind": "known",
                    "why": meta["why"], "size": len(cards), **body})

    if combo_db is not None:
        out.extend(_combo_sets(db, combo_db, fmt, want, budget))

    # По умолчанию -- польза за деньги: набор, который закрывает цвета и
    # выходит развёрнутым, стоит выше пяти таплендов за доллар. Сортировку
    # можно сменить снаружи.
    if order == "price":
        out.sort(key=lambda s: (s["usd_playset"], -s["quality"]))
    elif order == "quality":
        out.sort(key=lambda s: (-s["quality"], s["usd_playset"]))
    else:
        out.sort(key=lambda s: (-(s["quality"] / max(1.0, s["usd_playset"] ** 0.4)),
                                s["usd_playset"]))
    return {"format": fmt, "sets": out[:limit], "total": len(out),
            "order": order}


def _combo_sets(db: CardDB, combo_db: Any, fmt: str, want: set[str],
                budget: float | None) -> list[dict[str, Any]]:
    """Комбо, у которых все куски -- земли: их и покупают вместе."""
    try:
        if not combo_db.ready:
            return []
    except Exception:  # noqa: BLE001
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in ("Dark Depths", "Thespian's Stage", "Lotus Field",
                 "Urza's Saga", "Cabal Coffers", "Field of the Dead"):
        try:
            found = combo_db.for_card(name, limit=12, commander_only=False,
                                      min_popularity=0)
        except Exception:  # noqa: BLE001
            continue
        for combo in found:
            names = list(combo.get("cards") or [])
            if len(names) < 2 or len(names) > 4:
                continue
            key = "|".join(sorted(names))
            if key in seen:
                continue
            cards = [c for c in (db.by_name(n) for n in names) if c]
            if len(cards) != len(names):
                continue
            if not all(manabase.is_land(c) for c in cards):
                continue
            if fmt and any((c.get("legalities") or {}).get(fmt) != "legal"
                           for c in cards):
                continue
            body = _describe(db, cards, fmt)
            if want and not (set(body["colors"]) & want):
                continue
            if budget is not None and body["usd_playset"] > budget:
                continue
            seen.add(key)
            out.append({"key": "combo:" + key, "kind": "combo",
                        "label": " + ".join(names),
                        "why": combo.get("results") or "",
                        "size": len(cards), **body})
    return out
