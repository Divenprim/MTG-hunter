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

Отбор идёт по цене, сверху дорогие. Это **заменитель** популярности, а не
она: данных о том, как часто карту играют, у программы нет и взяться им
неоткуда. В конструктивных форматах дорого стоит то, что играют, и для отбора
этого довольно — но называть это популярностью было бы враньём.

А **показ** — наоборот, снизу. Отбор и порядок показа отвечают на разные
вопросы: «что вообще играют» и «с чего начать мне». Человек приходит сюда
чинить колоду, и первым он видел артефакт за $51 — совет, который нельзя
выполнить, читается как «ну и ладно». Карты без цены идут в конец: у них не
«ноль», у них «неизвестно».

Наружу отсюда не уходит ни одного запроса.
"""

from __future__ import annotations

from typing import Any

from . import analyzer, manabase
from .cards import CardDB, normalize_name

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

# Сайдборд -- отдельный вопрос, и мерка у него другая.
#
# В мейне спрашивают «сколько»: восемь карт добора, двенадцать удаления. В
# сайде спрашивают «есть ли вообще»: одна карта против кладбища -- это мало,
# но это не ноль, а ноль означает, что против колоды с кладбищем вы во
# второй и третьей партии играете тем же, чем в первой, то есть проигрываете
# их заранее. Поэтому здесь считается покрытие, а не доля.
#
# Метки -- корни веток Tagger, как и в мейне. Шесть вопросов, которые задаёт
# сайдборд любого конструктивного формата; это не список «правильного
# сайдборда», это список того, на что в нём обычно есть ответ.
SIDE_SIZE = 15

# Дороже этого в сайде не держат. Карту из сайда меняют на карту из мейна,
# и меняют её на дешёвый ответ, который успеет сработать: десятимановый
# Козилек формально контрспелл, но в сайдборде его нет ни у кого. Число --
# суждение, и в ответе оно названо суждением.
SIDE_MAX_MV = 4

# Сколько карт просматривать, прежде чем отбирать по цветам. В мейне ветка
# метки -- это тысячи карт, и верхушки по цене хватает. В сайде ветки узкие
# («снести артефакт» дешевле четырёх маны -- полторы сотни карт на все
# цвета), а фильтр по цветам у одноцветной колоды режет девять десятых:
# окно в сотню оставляло мононую колоду вовсе без предложений.
SIDE_POOL = 400

SIDE_WANTED: tuple[dict[str, Any], ...] = (
    {"key": "artifact", "title": "Против артефактов", "tag": "removal-artifact",
     "why": "без этого артефактная колода просто выставляет свою железку"},
    {"key": "enchantment", "title": "Против чар",
     "tag": "removal-enchantment",
     "why": "чары не убираются тем, чем убирают существ"},
    {"key": "graveyard", "title": "Кладбище", "tag": "hate-graveyard",
     "why": "против колоды, которая живёт из кладбища, первая партия "
            "показывает проблему, а вторую выигрывает ответ на неё"},
    {"key": "counter", "title": "Контрмагия", "tag": "counterspell",
     "why": "единственный ответ на то, что нельзя убрать со стола"},
    {"key": "sweeper", "title": "Массовое удаление", "tag": "sweeper",
     "why": "точечное удаление не успевает против колоды, которая ставит "
            "по две-три твари за ход"},
    {"key": "discard", "title": "Дискард", "tag": "discard",
     "why": "против комбо дешевле вынуть ключевую карту из руки, чем "
            "отвечать на неё на столе"},
    {"key": "lifegain", "title": "Лайфгейн", "tag": "lifegain",
     "why": "против бёрна жизни и есть ресурс, за который идёт игра"},
)

# Форматы, где сайдборда нет вовсе: спрашивать «чего в нём не хватает»
# бессмысленно, и честнее сказать это словами.
NO_SIDEBOARD = ("commander", "brawl", "oathbreaker")

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


def _usd(card: dict[str, Any]) -> float:
    """Цена в долларах. Без цены -- в конец списка, а не в начало как ноль."""
    try:
        return float((card.get("prices") or {}).get("usd") or 0) or 1e9
    except (TypeError, ValueError):
        return 1e9


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
                sources: dict[str, int], extra: str = "",
                pool: int = 0) -> list[dict[str, Any]]:
    """Карты нужного назначения, которые эта колода может сыграть.

    `extra` дописывается в запрос: сайдборду нужно то же самое, но дешёвое
    по мане -- десятимановый Козилек формально контрспелл, а в сайде его не
    держит никто.
    """
    query = "otag:%s f:%s" % (tag, fmt)
    if extra:
        query += " " + extra
    if not palette:
        # Бесцветная колода: берём только бесцветные, иначе предложим то,
        # что в ней физически не разыграть.
        query += " c:c"
    found = db.search(query, limit=pool or max(limit * 12, 120), sort="price")
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
    # Отбор идёт сверху по цене, а показ -- снизу. Это разные вопросы.
    # Отбирать по цене нужно: дорого в конструктивном формате стоит то, что
    # играют, и дешёвый конец ветки -- это сотни карт, которых не играет
    # никто. А показывать сверху дорогое -- значит встречать человека,
    # пришедшего чинить колоду, артефактом за $51: совет, который нельзя
    # выполнить, читается как «ну и ладно».
    return sorted(out, key=_usd)


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


def _tagged(db: CardDB, tag: str,
            rows: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    """Карты из этих строк, попадающие под метку: сколько копий и какие.

    Спрашивается тем же языком, что и поиск кандидатов (`otag:`), и это не
    лень: две разные мерки -- «что считать ответом на кладбище» для вашей
    колоды и для предложения -- разошлись бы в первый же день.
    """
    names = [row.get("name") or "" for row in rows if row.get("name")]
    if not names:
        return 0, []
    hit = db.matching_names("otag:%s" % tag, names)
    copies = 0
    found: list[dict[str, Any]] = []
    for row in rows:
        if normalize_name(row.get("name") or "") not in hit:
            continue
        qty = int(row.get("quantity") or 0)
        copies += qty
        found.append({"name": row.get("name"), "copies": qty})
    return copies, found


def sideboard(deck: dict[str, Any], db: CardDB, fmt: str,
              palette: set[str], already: set[str],
              sources: dict[str, int], picks: int = PICK) -> dict[str, Any]:
    """Чего нет в сайдборде -- и чем это закрыть.

    До сих пор сайдборда не видел никто: «нехватки», покупки и охота
    считали мейн. А это пятнадцать карт из семидесяти пяти, и во второй и
    третьей партии матча играют именно они.

    Мерка здесь другая, чем в мейне: не «сколько карт добора», а «есть ли
    хоть один ответ». Одна карта против кладбища -- мало, но это не ноль;
    ноль значит, что вторую партию против такой колоды вы играете тем же,
    чем первую.
    """
    if fmt in NO_SIDEBOARD:
        return {"applies": False,
                "why_not": "в «%s» сайдборда нет" % fmt}

    rows = [r for r in (deck.get("cards") or [])
            if r.get("section") == "side"]
    main_rows = [r for r in (deck.get("cards") or [])
                 if r.get("section") in ("main", "commander")]
    used = sum(int(r.get("quantity") or 0) for r in rows)

    blocks = []
    for want in SIDE_WANTED:
        in_side, counted = _tagged(db, want["tag"], rows)
        in_main, _main_counted = _tagged(db, want["tag"], main_rows)
        block = {
            "key": want["key"],
            "title": want["title"],
            "why": want["why"],
            "in_side": in_side,
            # То же самое в мейне -- это не ответ на вопрос, но меняет
            # его срочность: колода с четырьмя контрспеллами в мейне не
            # беззащитна перед тем, на что отвечают контрспеллом.
            "in_main": in_main,
            "counted": counted[:10],
        }
        if not in_side:
            block["candidates"] = _candidates(
                db, want["tag"], fmt, palette, already, picks, sources,
                extra="mv<=%d" % SIDE_MAX_MV, pool=SIDE_POOL)
        blocks.append(block)

    blocks.sort(key=lambda b: (b["in_side"], b["in_main"]))
    return {
        "applies": True,
        "size": used,
        "max": SIDE_SIZE,
        "free": max(0, SIDE_SIZE - used),
        "over": max(0, used - SIDE_SIZE),
        "missing": len([b for b in blocks if not b["in_side"]]),
        "blocks": blocks,
    }


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
        "sideboard": sideboard(deck, db, fmt, palette, already, sources, picks),
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
            "отобрано по цене сверху: это заменитель популярности, а не она; "
            "данных о том, как часто карту играют, у программы нет",
            "показано от дешёвого к дорогому: начать проще с того, что "
            "можно купить; карты без известной цены — в конце",
            "сайдборд считается по покрытию, а не по доле: вопрос к нему не "
            "«сколько», а «есть ли вообще ответ»",
        ],
    }
