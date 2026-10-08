"""Чего колоде не хватает — и чем это добрать.

Два вопроса, которые обычно задают друг другу вслух: «мало ли у меня добора»
и «а что вообще поставить». Первый решается счётом, второй — поиском по
назначению; и то и другое у программы уже есть, не хватало только связать.

Счёт идёт от ожиданий формата: восемь карт взаимодействия в шестидесяти
картах модерна и в командирской сотне — разная доля колоды. Ожидания те же,
по которым считаются метрики разбора, и это не случайность: показывать в двух
местах два разных «нормально» значит получить два разных ответа на один
вопрос.

Предложения отбираются **в цвета колоды**. Это главное, что отличает полезный
список от списка вообще: синий «Rhystic Study» в бесцветном Троне — не совет,
а шум. Цветовая идентичность кандидата должна укладываться в идентичность
колоды, формат — совпадать, а карта — не лежать в колоде уже.

Порядок — по цене, сверху дорогие. Это **заменитель** популярности, а не она:
данных о том, как часто карту играют, у программы нет и взяться им неоткуда.
В конструктивных форматах дорого стоит то, что играют, и для подсказки этого
довольно — но называть это популярностью было бы враньём.

Наружу отсюда не уходит ни одного запроса.
"""

from __future__ import annotations

from typing import Any

from . import analyzer, manabase
from .cards import CardDB

# Что ищем, под какой меткой и как это назвать человеку. Метки — корни веток
# Tagger, те же, по которым считается разбор; каждая проверена тестом на
# существование и непустую ветку.
WANTED: tuple[dict[str, Any], ...] = (
    {"key": "draw", "title": "Добор", "tag": "draw", "against": "draw",
     "why": "без добора колода кончается раньше партии"},
    {"key": "removal", "title": "Удаление", "tag": "removal",
     "against": "interaction",
     "why": "нечем ответить на то, что уже вышло на стол"},
    {"key": "ramp", "title": "Разгон маны", "tag": "ramp", "against": "ramp",
     "why": "дорогие карты приходят позже, чем нужны"},
    {"key": "tutor", "title": "Туторы", "tag": "tutor", "against": "tutor",
     "why": "нечем найти нужную карту, когда она нужна"},
    {"key": "protection", "title": "Защита", "tag": "protection",
     "against": "interaction",
     "why": "ключевую карту снимут, и плана не останется"},
)

# Ниже этой доли от ожидания считается, что не хватает. Порог — суждение, а
# не измерение, и назван суждением в ответе: колода нарочно без туторов не
# «сломана», она такая задумана.
SHORT_AT = 0.7

# Сколько кандидатов показывать на каждую нехватку.
PICK = 8

# Сколько источников цвета нужно, чтобы вообще предлагать карту с его значком.
# Цветовая идентичность -- это не «можно сыграть»: колода с четырьмя Bomat
# Courier формально красная, но Worldfire за {6}{R}{R}{R} в ней не
# разыгрывается никогда. Число наше и названо суждением; за ориентир взята
# нижняя граница таблицы Карстена -- меньше шести источников не держит даже
# один значок к позднему ходу.
CASTABLE_AT = 6


# Сколько карт должно нести цвет, чтобы считать его цветом колоды. Одна
# забытая гора в бесцветном Троне не делает его красным, а предложения в её
# цвет -- это уже не совет, а шум.
COLOUR_AT = 2


def _identity(deck: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
    """Цвета колоды и карты, выпадающие из них.

    Считается не «какие цвета встречаются», а «какие цвета у колоды есть».
    Разница в одной забытой карте: она не меняет колоду, но меняет весь
    список предложений, если её посчитать.
    """
    seen: dict[str, int] = {}
    cards: list[dict[str, Any]] = []
    for row in deck.get("cards") or []:
        if row.get("section") not in ("main", "commander"):
            continue
        card = row.get("card") or {}
        identity = set(card.get("color_identity") or "")
        copies = int(row.get("quantity") or 0)
        for colour in identity:
            seen[colour] = seen.get(colour, 0) + copies
        if identity:
            cards.append({"name": card.get("name") or row.get("name"),
                          "copies": copies, "identity": "".join(sorted(identity))})
    palette = {c for c, n in seen.items() if n >= COLOUR_AT}
    stray = [c for c in cards if not set(c["identity"]) <= palette]
    return palette, sorted(stray, key=lambda c: c["copies"])


def _already(deck: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for row in deck.get("cards") or []:
        names.add((row.get("name") or "").strip().lower())
        card = row.get("card") or {}
        if card.get("name"):
            names.add(card["name"].strip().lower())
    return names


def _fits(card: dict[str, Any], palette: set[str]) -> bool:
    """Карта играется в этой колоде по цветам."""
    return set(card.get("color_identity") or "") <= palette


def _price(card: dict[str, Any]) -> float:
    prices = card.get("prices") or {}
    try:
        return float(prices.get("usd") or 0)
    except (TypeError, ValueError):
        return 0.0


def _brief(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "oracle_id": card.get("oracle_id"),
        "name": card.get("name"),
        "ru_name": card.get("ru_name"),
        "type_line": card.get("type_line"),
        "mana_cost": card.get("mana_cost"),
        "cmc": card.get("cmc"),
        "rarity": card.get("rarity"),
        "image_small": card.get("image_small"),
        "image_normal": card.get("image_normal"),
        "prices": card.get("prices"),
    }


def _sources(deck: dict[str, Any]) -> dict[str, int]:
    """Сколько карт колоды дают каждый цвет."""
    out: dict[str, int] = {}
    for row in deck.get("cards") or []:
        if row.get("section") not in ("main", "commander"):
            continue
        card = row.get("card") or {}
        copies = int(row.get("quantity") or 0)
        for colour in manabase.produces(card):
            out[colour] = out.get(colour, 0) + copies
    return out


def _castable(card: dict[str, Any], sources: dict[str, int]) -> bool:
    """Хватит ли колоде источников на цветные значки этой карты."""
    for colour, pips in manabase.pips(card.get("mana_cost") or "").items():
        if colour not in manabase.COLORS:
            continue
        # Два значка одного цвета требуют вдвое более плотной базы: это не
        # точная таблица Карстена, а грубая отсечка для подсказки.
        need = CASTABLE_AT if pips < 2 else CASTABLE_AT * 2
        if sources.get(colour, 0) < need:
            return False
    return True


def _candidates(db: CardDB, tag: str, fmt: str, palette: set[str],
                already: set[str], limit: int,
                sources: dict[str, int]) -> list[dict[str, Any]]:
    """Карты нужного назначения, которые эта колода может сыграть."""
    query = "otag:%s f:%s" % (tag, fmt)
    if not palette:
        # Бесцветная колода: берём только бесцветные, иначе предложим то,
        # что в ней физически не разыграть.
        query += " c:c"
    found = db.search(query, limit=max(limit * 12, 120), sort="price")
    out: list[dict[str, Any]] = []
    for card in found:
        name = (card.get("name") or "").strip().lower()
        if name in already:
            continue
        if not _fits(card, palette):
            continue
        if not _castable(card, sources):
            continue
        # Двусторонние с цветной лицевой стороной сюда попадать не должны:
        # «бесцветная» у них записана от оборота, а играют лицевую.
        if "//" in (card.get("name") or "") and not palette:
            continue
        out.append(_brief(card))
        if len(out) >= limit:
            break
    return out


def hidden_pips(deck: dict[str, Any], db: CardDB) -> list[dict[str, Any]]:
    """Карты, которым цветная мана нужна не для розыгрыша, а для способности.

    Манабаза считает цветные значки в стоимости -- и это правильно для неё.
    Но Bomat Courier разыгрывается за {1}, а сбрасывается в руку за {R}, и по
    стоимости выходит, что красная мана колоде не нужна совсем. Четыре таких
    карты при одном источнике -- это не «мало добора», это добор, который
    нечем включить, и разница между этими диагнозами огромная.

    Признак простой и надёжный: цветовая идентичность карты шире, чем цвета
    её стоимости. Разницу и требует способность.
    """
    produced: dict[str, int] = {}
    from_whom: dict[str, list[dict[str, Any]]] = {}
    found: dict[str, dict[str, Any]] = {}
    for row in deck.get("cards") or []:
        if row.get("section") not in ("main", "commander"):
            continue
        card = row.get("card") or {}
        copies = int(row.get("quantity") or 0)
        name = card.get("name") or row.get("name") or ""
        for colour in manabase.produces(card):
            produced[colour] = produced.get(colour, 0) + copies
            from_whom.setdefault(colour, []).append(
                {"name": name, "copies": copies,
                 "land": manabase.is_land(card)})

        # У земли нет стоимости розыгрыша, поэтому её идентичность всегда
        # «шире» -- и базовая гора попадала бы в список как карта со скрытым
        # требованием. Земля цвет даёт, а не просит.
        if manabase.is_land(card):
            continue
        identity = set(card.get("color_identity") or "")
        in_cost = set(manabase.pips(card.get("mana_cost") or ""))
        hidden = identity - in_cost
        if not hidden:
            continue
        key = card.get("name") or row.get("name") or ""
        entry = found.setdefault(key, {
            "name": key, "copies": 0, "needs": "".join(sorted(hidden)),
            "mana_cost": card.get("mana_cost"),
        })
        entry["copies"] += copies

    out = []
    for entry in found.values():
        entry["sources"] = min(produced.get(c, 0) for c in entry["needs"])
        # Чем именно даётся цвет -- половина ответа. Две мана-банки за пять
        # маны и одна базовая земля это «четыре источника» только на бумаге,
        # и человек должен видеть, из чего сложено число.
        givers: list[dict[str, Any]] = []
        for colour in entry["needs"]:
            for giver in from_whom.get(colour, []):
                if giver["name"] not in [g["name"] for g in givers]:
                    givers.append(giver)
        entry["from"] = sorted(givers, key=lambda g: (not g["land"], g["name"]))[:8]
        entry["lands"] = sum(g["copies"] for g in entry["from"] if g["land"])
        out.append(entry)
    return sorted(out, key=lambda e: (e["sources"], -e["copies"]))


def report(deck: dict[str, Any], db: CardDB, fmt: str | None = None,
           picks: int = PICK) -> dict[str, Any]:
    """Чего не хватает этой колоде и чем добрать.

    Нехватка считается от ожиданий формата -- тех же, по которым считается
    разбор. «Хватает» тоже сообщается: список, в котором видно только
    недостачу, не даёт понять, всё ли остальное в порядке.
    """
    fmt = (fmt or deck.get("format") or "modern").lower()
    rows = [(row.get("name") or "", int(row.get("quantity") or 0))
            for row in deck.get("cards") or []
            if row.get("section") in ("main", "commander")]
    vector = analyzer.features(rows, db)
    profile = analyzer.profile_for(fmt)
    palette, stray = _identity(deck)
    already = _already(deck)
    sources = _sources(deck)

    # Ожидание пересчитывается на фактический размер колоды: недособранная
    # колода не «бедна на добор», она просто ещё не собрана.
    size = float(profile.get("size") or 60)
    scale = max(0.5, min(1.5, (vector["cards"] or size) / size))

    short: list[dict[str, Any]] = []
    enough: list[dict[str, Any]] = []
    for want in WANTED:
        have = (vector["features"].get(want["key"]) or {"copies": 0})["copies"]
        expect = round(float(profile.get(want["against"], 8)) * scale)
        block = {
            "key": want["key"],
            "title": want["title"],
            "have": have,
            "expect": expect,
            "why": want["why"],
            # Какие карты сосчитаны. Без этого списка с числом не поспоришь:
            # «у тебя пять карт добора» звучит одинаково и когда это правда,
            # и когда программа посчитала добором что-то своё.
            "counted": (vector["features"].get(want["key"])
                        or {"cards": []})["cards"][:10],
        }
        if expect and have < expect * SHORT_AT:
            block["candidates"] = _candidates(
                db, want["tag"], fmt, palette, already, picks, sources)
            short.append(block)
        else:
            enough.append(block)

    return {
        "format": fmt,
        "cards": vector["cards"],
        "colors": "".join(sorted(palette)) or "бесцветная",
        # Карты вне цветов колоды: обычно это забытый остаток, и сказать про
        # него полезнее, чем молча подстроить под него все предложения.
        "stray": stray,
        "hidden_pips": hidden_pips(deck, db),
        "short": sorted(short, key=lambda b: b["have"] - b["expect"]),
        "enough": enough,
        "basis": [
            "ожидания взяты от формата — те же, что в разборе колоды",
            "«не хватает» — это меньше %d%% от ожидаемого; порог наш, "
            "а не из правил" % round(SHORT_AT * 100),
            "предложения отобраны в цвета колоды и по её формату",
            "карта со значком цвета предлагается, только если в колоде хотя "
            "бы %d источников этого цвета: идентичность -- это не «можно "
            "сыграть»" % CASTABLE_AT,
            "цветом колоды считается тот, что несут хотя бы %d карты: одна "
            "забытая карта не должна менять весь список" % COLOUR_AT,
            "отдельно показаны карты, которым цветная мана нужна для "
            "способности, а не для розыгрыша: манабаза их не видит",
            "порядок — по цене: это заменитель популярности, а не она; "
            "данных о том, как часто карту играют, у программы нет",
        ],
    }
