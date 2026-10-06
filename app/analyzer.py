"""Разбор колоды: из чего она состоит и что умеет.

Это нижний слой анализа. Он не выносит оценок и не ставит баллов -- он только
считает, и считает так, чтобы каждое число можно было развернуть в список
карт, которые его набрали. Балл без слагаемых не проверяется и не
оспаривается; «Salt 78» -- это мнение, а «mass-land-denial: Armageddon,
Ravages of War, Winter Orb» -- это факт, с которым можно спорить по существу.
Поэтому здесь у каждого признака есть `cards`, и верхние слои обязаны брать
объяснение отсюда, а не сочинять его заново.

Откуда берутся признаки. Больше всего -- из меток Scryfall Tagger, которые
лежат в локальной базе. Это чужая, живая таксономия, и главное правило работы
с ней такое: **метка, которой нет, не ошибается -- она просто не срабатывает
никогда**. В `family.py` по этой причине годами жили четырнадцать выдуманных
меток (stax, prison, land-destruction, wincon, infinite-combo и другие),
ничего не помечая и никак себя не выдавая. Поэтому каждый корень из
`TAG_FEATURES` проверяется тестом на существование и на непустую ветку, а
проверять его надо именно по дереву: `_expand_tag_slugs` разворачивает корень
вместе с потомками, и подстроками тут пользоваться нельзя -- «%ramp%» ловит
`gives-trample`, а «%counter%» приводит полторы тысячи карт с жетонами +1/+1
вместо контрмагии.

Чего в таксономии нет вовсе -- stax, prison, жёстких замков, бесплатного
взаимодействия, быстрой маны, -- то собирается здесь явными правилами по
тексту карты или поимённым списком. Это честнее, чем сослаться на метку,
которой не существует, и видно в коде: правило можно прочитать и оспорить.

Наружу отсюда не уходит ничего: всё считается по локальной базе.
"""

from __future__ import annotations

import re
from typing import Any

from .cards import CardDB, _expand_tag_slugs
from .holdings import _cheapest_usd

# --------------------------------------------------------------- словарь меток

# Корни веток Tagger. Рядом -- сколько карт в ветке на момент написания: не
# для проверки (база обновляется), а чтобы при чтении было видно, о каком
# порядке величин речь, и чтобы опустевшая ветка бросалась в глаза.
#
# Все корни ниже проверены по собранной базе: они существуют и непусты. То,
# чего в таксономии не нашлось (stax, prison, lock, denial, wincon, combo,
# free-spell, card-selection, fast-mana), сюда не попало и собирается ниже
# правилами по тексту.
TAG_FEATURES: dict[str, tuple[str, ...]] = {
    "ramp": ("ramp",),                       # ~2900 карт в ветке
    "ritual": ("ritual",),                   # ~70
    "tutor": ("tutor",),                     # ~2800
    "draw": ("draw",),                       # ~7200
    "recursion": ("recursion",),             # ~3200
    "protection": ("protection",),           # ~2300
    "removal": ("removal",),                 # ~19700
    "sweeper": ("sweeper",),                 # ~980
    "counterspell": ("counterspell",),       # ~870
    "discard": ("discard",),                 # ~600
    # Разведены нарочно. Beast Within умеет убить землю и поэтому помечен
    # `removal-land` -- но это гибкое точечное удаление, а не снос земель, и
    # считать его Армагеддоном нельзя: иначе казуальная колода с одной
    # универсальной картой получает командирский бракет B4 и «вы портите всем
    # игру». Massовый снос -- отдельная метка и отдельный вес.
    "mass_land_denial": ("mass-land-denial",),   # ~115 карт
    "land_removal": ("removal-land",),           # ~300
    "extra_turn": ("extra-turn",),           # ~64
    "alt_win": ("alternate-win-condition",),  # ~84
    "pillowfort": ("pillowfort",),           # ~20
}

# Метки, которые сами по себе ничего не говорят о карте: они про то, как карта
# относится к чужому эффекту, а не про то, что она делает. «hate-discard» --
# это защита от дискарда, а не дискард, и считать её дискардом значит записать
# противоядие в яд.
TAG_INVERTS = ("hate-", "prevent-", "removes-", "synergy-")


def _branch(root: str) -> set[str]:
    """Корень вместе с потомками, без «отношенческих» меток."""
    return {slug for slug in _expand_tag_slugs(root)
            if not slug.startswith(TAG_INVERTS)}


# ------------------------------------------------------- правила по тексту

# Ниже -- то, чего в таксономии Scryfall нет. Каждое правило написано так,
# чтобы его можно было прочитать и не согласиться: это суждения, а не данные.

# Налоги и замки. Общее у них одно: карта не отвечает на действие противника,
# а делает само действие дороже или невозможным -- постоянно и для всех.
#
# Налог и запрет разведены нарочно. «Существа не могут атаковать вас, если их
# хозяин не заплатит {2}» -- это цена, её платят и играют дальше; «существа не
# могут атаковать» -- это запрет. Оба мешают, но по-разному, и спека просит
# считать taxes и hard locks порознь. Поэтому у запрета стоит условие «без
# unless»: с ним же правило превратило бы Ghostly Prison в жёсткий замок.
TAX_RULES: tuple[tuple[str, str], ...] = (
    (r"spells? (you don't control )?cost \{\d+\}", "заклинания дороже"),
    (r"costs? \{\d+\} more to cast", "заклинания дороже"),
    (r"can't attack[^.]*unless[^.]*pays?", "атака платная"),
    (r"can't be cast unless[^.]*pays?", "розыгрыш платный"),
    (r"unless (that player|they|its controller) pays", "действие платное"),
)

LOCK_RULES: tuple[tuple[str, str], ...] = (
    (r"players? can't cast (spells|more than)(?![^.]*unless)", "нельзя разыгрывать"),
    (r"creatures? can't attack(?![^.]*unless)", "нельзя атаковать"),
    (r"players? can't (draw|search|untap)(?![^.]*unless)", "нельзя добирать или разворачивать"),
    (r"don't untap during (their|your) untap step", "не разворачивается"),
    (r"skip (their|your) (draw|untap|upkeep) step", "пропуск шага"),
    (r"each player can't(?![^.]*unless)", "запрет всем"),
    (r"if a player would draw a card.*instead", "подмена добора"),
    (r"lands? don't untap", "земли не разворачиваются"),
)

# Быстрая мана -- поимённо. Правило по тексту здесь не работает: «add {C}{C}»
# есть и у Sol Ring, и у земли за четыре маны, а смысл у них разный. Список
# короткий, общеизвестный и датируется вместе с правилами форматов.
FAST_MANA: frozenset[str] = frozenset({
    "sol ring", "mana crypt", "mana vault", "grim monolith", "chrome mox",
    "mox diamond", "mox opal", "mox amber", "mox jet", "mox pearl",
    "mox ruby", "mox sapphire", "mox emerald", "lotus petal", "black lotus",
    "jeweled lotus", "ancient tomb", "city of traitors", "gaea's cradle",
    "lion's eye diamond", "simian spirit guide", "elvish spirit guide",
    "dark ritual", "cabal ritual", "rite of flame", "culling the weak",
    "springleaf drum", "lotus vale", "carpet of flowers",
})

# Бесплатное взаимодействие: заклинание, которое можно разыграть, не платя
# стоимость. Это то, что позволяет держать защиту и развиваться одновременно,
# поэтому оно считается отдельно от контрмагии и защиты.
FREE_RULES: tuple[str, ...] = (
    r"without paying its mana cost",
    r"rather than pay this spell's mana cost",
    r"you may exile a[n]? \w+ card from your hand rather than pay",
    r"if you control .*, you may cast this spell without paying",
)

_word = re.compile(r"[^a-z0-9' ]+")


def norm(name: str) -> str:
    """Имя карты в том же виде, в каком его хранит коллекция."""
    return _word.sub(" ", (name or "").strip().lower()
                     .replace("’", "'")).strip()


def _text_of(card: dict[str, Any]) -> str:
    """Весь текст карты, включая обе стороны двусторонней."""
    parts = [card.get("oracle_text") or ""]
    for face in card.get("faces") or []:
        if isinstance(face, dict):
            parts.append(face.get("oracle_text") or "")
    return "\n".join(parts).lower()


def _matches(text: str, rules: tuple[str, ...]) -> bool:
    return any(re.search(rule, text) for rule in rules)


def _reason(text: str, rules: tuple[tuple[str, str], ...]) -> str | None:
    for rule, why in rules:
        if re.search(rule, text):
            return why
    return None


# ------------------------------------------------------------------ подсчёт

class Feature:
    """Один признак: сколько и за счёт чего.

    `copies` -- с учётом количества в колоде, `cards` -- поимённо, в порядке
    убывания вклада. Верхние слои показывают именно `cards`: балл, который
    нельзя развернуть в список карт, ничего не значит.
    """

    __slots__ = ("key", "copies", "cards")

    def __init__(self, key: str):
        self.key = key
        self.copies = 0
        self.cards: list[dict[str, Any]] = []

    def add(self, name: str, copies: int, why: str | None = None) -> None:
        self.copies += copies
        entry: dict[str, Any] = {"name": name, "copies": copies}
        if why:
            entry["why"] = why
        self.cards.append(entry)

    def as_dict(self) -> dict[str, Any]:
        cards = sorted(self.cards, key=lambda c: (-c["copies"], c["name"]))
        return {"copies": self.copies, "cards": cards}


def _empty() -> dict[str, Feature]:
    keys = list(TAG_FEATURES) + ["tax", "lock", "fast_mana", "free_spell"]
    return {key: Feature(key) for key in keys}


# Единственное место, где признаки не независимы. Cultivate помечена и как
# рампа, и как тутор -- она правда ищет в библиотеке, -- но колода с двумя
# туторами и десятью Cultivate-подобными картами не «колода с двенадцатью
# туторами». Рампа выигрывает: карта, которая разгоняет ману, -- это рампа.
# То же правило и по той же причине, что в deckshape.
BEATEN_BY: dict[str, set[str]] = {"tutor": {"ramp"}}


def features(rows: list[tuple[str, int]], db: CardDB) -> dict[str, Any]:
    """Разобрать список карт на признаки.

    `rows` -- пары (имя, количество), как их отдаёт хранилище колод. Карты,
    которых нет в локальной базе, попадают в `unknown` поимённо, а не молча
    исчезают: анализ, построенный на наполовину понятом списке, обязан об
    этом сказать -- на это опирается confidence.
    """
    conn = db.conn                      # ветки тегов грузятся на это соединение
    branches = {key: set().union(*(_branch(root) for root in roots))
                for key, roots in TAG_FEATURES.items()}

    found = _empty()
    curve: dict[int, int] = {}
    types: dict[str, int] = {}
    cards = 0
    lands = 0
    unknown: list[dict[str, Any]] = []

    for name, quantity in rows:
        copies = int(quantity or 0)
        if copies <= 0:
            continue
        cards += copies
        card = db.by_name(name)
        if not card:
            unknown.append({"name": name, "copies": copies})
            continue

        type_line = (card.get("type_line") or "").lower()
        kind = type_line.split("—")[0].strip()
        for word in ("land", "creature", "artifact", "enchantment",
                     "instant", "sorcery", "planeswalker", "battle"):
            if word in kind:
                types[word] = types.get(word, 0) + copies
        if "land" in kind:
            lands += copies
        else:
            curve[min(7, int(card.get("cmc") or 0))] = (
                curve.get(min(7, int(card.get("cmc") or 0)), 0) + copies)

        text = _text_of(card)
        plain = norm(card.get("name") or name)

        if plain in FAST_MANA:
            found["fast_mana"].add(card.get("name") or name, copies)
        if _matches(text, FREE_RULES):
            found["free_spell"].add(card.get("name") or name, copies)
        why = _reason(text, TAX_RULES)
        if why:
            found["tax"].add(card.get("name") or name, copies, why)
        why = _reason(text, LOCK_RULES)
        if why:
            found["lock"].add(card.get("name") or name, copies, why)

        oracle_id = card.get("oracle_id")
        if not oracle_id:
            continue
        tags = {row["slug"] for row in conn.execute(
            "SELECT slug FROM card_tags WHERE oracle_id = ?", (oracle_id,))}
        if not tags:
            continue
        # Земля -- это земля, а не функция: девять фетчей не «девять туторов».
        # То же правило, по которому считает deckshape.
        if "land" in kind:
            continue
        serves = {key: sorted(tags & slugs)[0]
                  for key, slugs in branches.items() if tags & slugs}
        for key, winners in BEATEN_BY.items():
            if key in serves and serves.keys() & winners:
                serves.pop(key)
        for key, slug in serves.items():
            found[key].add(card.get("name") or name, copies, slug)

    return {
        "cards": cards,
        "lands": lands,
        "types": types,
        "curve": curve,
        "unknown": unknown,
        "features": {key: f.as_dict() for key, f in found.items()},
    }


# =========================================================== метрики и баллы

"""Дальше -- слой оценок. Всё, что здесь считается, обязано складываться из
названных слагаемых: у каждой метрики есть `parts`, у каждой части -- имя,
вклад и карты, которые его дали. Это не украшение вывода, а условие честности.
«Power 78» проверить нельзя и спорить с ним не о чем; «туторы +12 (Demonic
Tutor, Vampiric Tutor)» -- можно.

Веса ниже -- суждение, а не измерение. Их не подбирали по данным (данных о
том, какая колода «сильнее», у программы нет и взяться им неоткуда), их
написали руками. Поэтому они лежат в коде отдельным словарём, уходят в ответ
вместе с оценкой и называются в объяснении. Человек, который с ними не
согласен, должен видеть, с чем именно он не согласен.
"""

# Ожидания по форматам. Числа -- ориентиры, от которых считается плотность:
# «восемь карт взаимодействия» в шестидесятикарточном модерне и в сотне
# командира -- это разная доля колоды, а значит и разный вес. Спека требует
# ровно этого: одна и та же карта весит по-разному в разных форматах.
#
# Шкала от этих ориентиров такая: попасть в ожидание формата -- это 50, вдвое
# перекрыть -- 100. Не «процентиль» и не «место среди колод»: таких данных у
# программы нет и взяться им неоткуда, а выдавать за них свою шкалу нельзя.
# Поэтому 50 читается как «как у обычной колоды этого формата», и так и должно
# быть написано в интерфейсе.
FORMAT_PROFILE: dict[str, dict[str, float]] = {
    #              размер  земель  взаимод.  рампа  добор  туторы
    "commander": {"size": 100, "lands": 37, "interaction": 10,
                  "ramp": 10, "draw": 10, "tutor": 3, "cmc": 3.2},
    "legacy":    {"size": 60, "lands": 20, "interaction": 12,
                  "ramp": 4, "draw": 6, "tutor": 4, "cmc": 2.0},
    "vintage":   {"size": 60, "lands": 18, "interaction": 12,
                  "ramp": 6, "draw": 8, "tutor": 6, "cmc": 1.8},
    "modern":    {"size": 60, "lands": 22, "interaction": 10,
                  "ramp": 3, "draw": 5, "tutor": 2, "cmc": 2.4},
    "pioneer":   {"size": 60, "lands": 23, "interaction": 9,
                  "ramp": 3, "draw": 4, "tutor": 1, "cmc": 2.6},
    "standard":  {"size": 60, "lands": 24, "interaction": 8,
                  "ramp": 3, "draw": 4, "tutor": 1, "cmc": 2.8},
    "pauper":    {"size": 60, "lands": 22, "interaction": 9,
                  "ramp": 3, "draw": 5, "tutor": 1, "cmc": 2.3},
}
DEFAULT_PROFILE = FORMAT_PROFILE["modern"]

# Из чего складывается каждая метрика: признак -> сколько он весит. Вес --
# это «сколько баллов даёт одна карта относительно ожидания формата», а не
# доля: складывать доли пришлось бы с пояснением, почему именно так.
METRICS: dict[str, dict[str, Any]] = {
    "acceleration": {
        "title": "Разгон маны",
        "of": {"ramp": 1.0, "fast_mana": 2.0, "ritual": 1.2},
        "against": "ramp",
    },
    "selection": {
        "title": "Туторы и отбор",
        "of": {"tutor": 1.6, "draw": 0.4},
        "against": "tutor",
    },
    "card_advantage": {
        "title": "Преимущество в картах",
        "of": {"draw": 1.0, "recursion": 0.7},
        "against": "draw",
    },
    "interaction": {
        "title": "Взаимодействие",
        "of": {"removal": 1.0, "counterspell": 1.1, "sweeper": 1.2,
               "free_spell": 1.5},
        "against": "interaction",
    },
    "resilience": {
        "title": "Живучесть",
        "of": {"protection": 1.2, "recursion": 1.0, "free_spell": 0.8},
        "against": "interaction",
    },
    "denial": {
        "title": "Отказ в ресурсах",
        "of": {"mass_land_denial": 2.5, "discard": 1.0, "tax": 1.4,
               "land_removal": 0.3},
        "against": "interaction",
    },
    "lock": {
        "title": "Замки",
        "of": {"lock": 2.5, "pillowfort": 1.2, "extra_turn": 1.5},
        "against": "interaction",
    },
}

# Power: из каких метрик складывается и с каким весом. Сумма весов -- 1.0,
# поэтому балл читается как «сколько процентов от предела эта колода набрала»,
# а не как безразмерное число.
POWER_WEIGHTS: dict[str, float] = {
    "speed": 0.18,
    "consistency": 0.20,
    "interaction": 0.16,
    "acceleration": 0.12,
    "selection": 0.12,
    "card_advantage": 0.12,
    "resilience": 0.10,
}

# Salt: из чего складывается «насколько колода портит игру другим». Это
# суждение о вкусе, а не измерение силы, и называться в интерфейсе оно должно
# именно так. Сильное удаление и хорошая контрмагия сюда не входят нарочно:
# спека прямо просит их не считать солью, и это правильно -- иначе солёной
# окажется любая играющая колода.
#
# Считается по метрикам, а не по метрикам и признакам разом. Массовое
# уничтожение земель и лишние ходы -- самое ненавидимое, что бывает, -- уже
# весят больше прочего внутри «отказа в ресурсах» и «замков»; добавить их
# сверху отдельной строкой значит сосчитать дважды и получить балл, который
# не сходится со своими же слагаемыми.
SALT_WEIGHTS: dict[str, float] = {
    "denial": 0.5,
    "lock": 0.5,
}

# Нелинейные сочетания: спека права, что простая сумма их не ловит. Каждое --
# это «одно усиливает другое», и каждое названо, чтобы его было видно в
# объяснении отдельной строкой, а не растворённым в общем балле.
SYNERGIES: tuple[tuple[str, tuple[str, str], str, int], ...] = (
    ("power", ("selection", "combo"), "туторы к собранному комбо", 8),
    ("power", ("acceleration", "speed"), "быстрая мана к быстрому плану", 6),
    ("power", ("card_advantage", "resilience"), "добор поверх живучести", 4),
    ("salt", ("lock", "denial"), "замок поверх отказа в ресурсах", 10),
    ("salt", ("denial", "acceleration"), "отказ с опережением по мане", 6),
)
SYNERGY_AT = 55        # с какого уровня обе стороны считаются «в наличии»


def _score(title: str, weights: dict[str, float], kind: str,
           measured: dict[str, Any], basis: str) -> dict[str, Any]:
    """Балл как сумма названных слагаемых.

    Ни одно слагаемое не безымянно: каждое -- это метрика со своим весом либо
    сочетание, у которого есть имя. Веса уходят в ответ вместе с баллом:
    человек, который с ними не согласен, должен видеть, с чем именно он не
    согласен, а не спорить с числом 78.
    """
    parts: list[dict[str, Any]] = []
    for key, weight in weights.items():
        got = measured.get(key)
        if not got or not got["value"]:
            continue
        parts.append({
            "what": got["title"],
            "adds": int(round(weight * got["value"])),
            "weight": weight,
            "cards": [c for p in got["parts"] for c in p.get("cards", [])][:6],
        })

    # Нелинейные сочетания. Простая сумма их не ловит: туторы сами по себе --
    # это стабильность, но туторы к собранному комбо -- это совсем другая
    # колода. Каждое сочетание -- отдельная строка, а не растворённая добавка.
    for where, (left, right), what, bonus in SYNERGIES:
        if where != kind:
            continue
        a, b = measured.get(left), measured.get(right)
        if not a or not b:
            continue            # метрики ещё нет -- сочетание не срабатывает
        if a["value"] >= SYNERGY_AT and b["value"] >= SYNERGY_AT:
            parts.append({"what": what, "adds": bonus, "cards": []})

    return _capped(title, parts, basis)


def confidence(vector: dict[str, Any]) -> dict[str, Any]:
    """Насколько можно верить ответу -- и почему именно настолько.

    Уверенность не украшение. Анализ, построенный на списке, который понят
    наполовину, обязан об этом сказать: иначе человек принимает за оценку
    колоды оценку той её части, которую программа узнала.
    """
    parts: list[dict[str, Any]] = [
        {"what": "список разобран", "adds": 100, "cards": []}]
    cards = vector["cards"] or 1
    unknown = sum(u["copies"] for u in vector["unknown"])
    if unknown:
        share = unknown / float(cards)
        parts.append({
            "what": "карт не знаем: %d из %d" % (unknown, cards),
            "adds": -int(round(min(60.0, share * 150))),
            "cards": vector["unknown"][:6],
        })
    return _capped("Уверенность", parts,
                   "100 — весь список знаком; незнакомые карты снижают")


def price(rows: list[tuple[str, int]], db: CardDB) -> dict[str, Any]:
    """Сколько стоит этот список -- и какой доли цены мы не знаем.

    Методика одна и названа в ответе: **самая дешёвая печать каждой карты, в
    долларах, без фойла**. Это нижняя граница, а не оценка сверху, и сравнивать
    две колоды по ней честно -- обе меряны одинаково.

    Отдельно считается покрытие: доля карт, у которых цена вообще нашлась. Без
    него «колода за $90» означает и дешёвую колоду, и дорогую, у которой
    известна цена трёх карт. Поэтому Salt/$ без покрытия не показывается.

    Цена коллекции сюда не примешивается. Salt/$ -- свойство списка карт, а не
    того, сколько вы за него доплатили: иначе одна и та же колода у двух людей
    получит разную «мерзость на доллар», что бессмысленно.
    """
    ids: dict[str, int] = {}
    unpriced: list[dict[str, Any]] = []
    known_names: dict[str, str] = {}
    cards = 0
    for name, quantity in rows:
        copies = int(quantity or 0)
        if copies <= 0:
            continue
        cards += copies
        card = db.by_name(name)
        oracle_id = (card or {}).get("oracle_id")
        if not oracle_id:
            unpriced.append({"name": name, "copies": copies})
            continue
        ids[oracle_id] = ids.get(oracle_id, 0) + copies
        known_names[oracle_id] = card.get("name") or name

    cheapest = _cheapest_usd(db, list(ids))
    total = 0.0
    priced = 0
    for oracle_id, copies in ids.items():
        got = cheapest.get(oracle_id)
        if got is None:
            unpriced.append({"name": known_names[oracle_id], "copies": copies})
            continue
        total += got * copies
        priced += copies

    coverage = (priced / float(cards)) if cards else 0.0
    return {
        "usd": round(total, 2),
        "cards": cards,
        "priced": priced,
        "coverage": round(coverage, 3),
        "unpriced": sorted(unpriced, key=lambda u: -u["copies"])[:12],
        "basis": "самая дешёвая печать каждой карты, доллары, без фойла",
    }


# Ниже какого покрытия цены считать нечего. Сорок процентов известной цены --
# это не «колода за столько-то», это гадание с видом точности.
PRICE_ENOUGH = 0.8


def salt_per_dollar(salt: dict[str, Any], priced: dict[str, Any]) -> dict[str, Any]:
    """Сколько раздражающей игры покупается на доллар.

    Две колоды с одинаковой солью -- одна за $1200, другая за $90 -- это очень
    разные вещи, и спека права, что это стоит показывать. Но делить на цену,
    известную наполовину, нельзя: ответ будет выглядеть точным и не будет им.
    Поэтому при низком покрытии метрика не показывается вовсе, и сказано,
    почему.
    """
    usd = priced["usd"]
    if priced["coverage"] < PRICE_ENOUGH:
        return {
            "known": False,
            "why": "цена известна у %d%% карт — слишком мало, чтобы делить"
                   % round(priced["coverage"] * 100),
            "coverage": priced["coverage"],
        }
    if usd <= 0:
        return {"known": False, "why": "колода ничего не стоит — делить не на что",
                "coverage": priced["coverage"]}
    return {
        "known": True,
        "per_dollar": round(salt["value"] / usd, 3),
        "per_100": round(salt["value"] * 100.0 / usd, 1),
        "usd": usd,
        "coverage": priced["coverage"],
        "basis": priced["basis"],
    }


# ===================================== комбо и командирский бракет

"""Здесь кончаются наши суждения и начинаются чужие правила.

Бракеты Commander и список Game Changers придумали не мы, они меняются, и
выдавать их за своё знание нельзя. Поэтому всё внешнее лежит ниже с датой и
источником, а ответ эту дату называет: устаревший список -- это нормально,
молчащий устаревший список -- нет.
"""

# Официальный список Game Changers. Взят у Scryfall по запросу `is:gamechanger`
# -- он ведёт его по решениям Wizards и обновляет вместе с ними.
GAME_CHANGERS_SOURCE = "Scryfall is:gamechanger"
GAME_CHANGERS_DATE = "2026-10-06"
GAME_CHANGERS: frozenset[str] = frozenset({
    'ad nauseam', 'ancient tomb', 'aura shards', 'biorhythm',
    "bolas's citadel", 'braids, cabal minion', 'chrome mox',
    'coalition victory', 'consecrated sphinx', 'crop rotation',
    'cyclonic rift', 'demonic tutor', 'drannith magistrate',
    'enlightened tutor', 'farewell', 'field of the dead',
    'fierce guardianship', 'force of will', "gaea's cradle", 'gamble',
    'gifts ungiven', 'glacial chasm', 'grand arbiter augustin iv',
    'grim monolith', 'humility', 'imperial seal', 'intuition',
    "jeska's will", "lion's eye diamond", 'mana vault', "mishra's workshop",
    'mox diamond', 'mystical tutor', 'narset, parter of veils',
    'natural order', 'necropotence', 'notion thief', 'opposition agent',
    'orcish bowmasters', 'panoptic mirror', 'rhystic study',
    'seedborn muse', "serra's sanctum", 'smothering tithe',
    'survival of the fittest', "teferi's protection",
    "tergrid, god of fright // tergrid's lantern", "thassa's oracle",
    'the one ring', 'the tabernacle at pendrell vale', 'underworld breach',
    'vampiric tutor', 'worldly tutor',
})

# Как Commander Spellbook помечает комбо и что эта пометка значит для бракета.
# Расшифровка букв -- из схемы их API, толкование -- из их же руководства по
# поиску; догадываться тут нельзя: «C» -- это Core, а вовсе не Casual, как
# напрашивается, а самый большой мешок «E» -- Exhibition.
SPELLBOOK_BRACKETS = "Commander Spellbook, схема API и руководство по поиску"
SPELLBOOK_BRACKET: dict[str, tuple[int, str]] = {
    "B": (0, "запрещено в Commander"),
    "E": (1, "Exhibition — казуальное и чудаковатое"),
    "O": (2, "Oddball — требует третьей карты или даёт неясный итог"),
    "C": (2, "Core — чуть быстрее казуального"),
    "S": (3, "Spicy — могло бы быть беспощадным, но нужно больше"),
    "P": (3, "Powerful — game changers или быстрая двойка"),
    "R": (4, "Ruthless — быстрая двойка, лишние ходы или снос земель"),
}

# Что бракеты запрещают. Своими словами, но по официальной системе: чем ниже
# бракет, тем короче список разрешённого.
BRACKET_TITLES = {
    1: "B1 — Exhibition",
    2: "B2 — Core",
    3: "B3 — Upgraded",
    4: "B4 — Optimized",
    5: "B5 — cEDH",
}
GC_ALLOWED = {1: 0, 2: 0, 3: 3, 4: None, 5: None}


def combos_in(rows: list[tuple[str, int]], db: CardDB, combo_db: Any,
              fmt: str | None = None) -> dict[str, Any]:
    """Какие комбо в колоде уже собраны и насколько они компактны.

    Без базы комбо отвечает честно: `known: False`. Анализ при этом не
    разваливается -- он просто не знает про комбо, и так и говорит, а не
    делает вид, что их нет.
    """
    names = [name for name, quantity in rows if int(quantity or 0) > 0]
    if combo_db is None or not getattr(combo_db, "ready", False) or not names:
        return {"known": False, "complete": [], "compact": 0, "best": None,
                "why": "база комбо не собрана"}
    found = combo_db.for_deck(
        names, commander_only=(fmt or "").lower() == "commander")
    complete = found.get("complete") or []
    best = None
    for combo in complete:
        tier = SPELLBOOK_BRACKET.get(combo.get("bracket") or "", (0, ""))[0]
        if best is None or tier > best[0]:
            best = (tier, combo)
    return {
        "known": True,
        "complete": [{"cards": c.get("cards") or [],
                      "card_count": c.get("card_count"),
                      "bracket": c.get("bracket") or "",
                      "means": SPELLBOOK_BRACKET.get(
                          c.get("bracket") or "", (0, "неизвестная пометка"))[1]}
                     for c in complete[:12]],
        "count": len(complete),
        "compact": sum(1 for c in complete if (c.get("card_count") or 9) <= 2),
        "best": {"tier": best[0], "means": SPELLBOOK_BRACKET.get(
            best[1].get("bracket") or "", (0, ""))[1],
            "cards": best[1].get("cards") or []} if best else None,
        "near": len(found.get("near") or []),
        "source": SPELLBOOK_BRACKETS,
    }


def game_changers_in(rows: list[tuple[str, int]],
                     db: CardDB) -> list[dict[str, Any]]:
    """Какие Game Changers лежат в колоде -- поимённо."""
    out: list[dict[str, Any]] = []
    for name, quantity in rows:
        copies = int(quantity or 0)
        if copies <= 0:
            continue
        card = db.by_name(name)
        plain = norm((card or {}).get("name") or name)
        if plain in GAME_CHANGERS:
            out.append({"name": (card or {}).get("name") or name,
                        "copies": copies})
    return sorted(out, key=lambda c: c["name"])


def commander_bracket(vector: dict[str, Any], rows: list[tuple[str, int]],
                      db: CardDB, combos: dict[str, Any],
                      fmt: str | None) -> dict[str, Any] | None:
    """Какому бракету соответствует колода и почему.

    Отвечает только для Commander: в модерне или легаси бракетов нет, и
    выдавать их туда -- это выдумка, а не анализ.

    Пятый бракет сознательно не назначается. cEDH -- это не «сильнее
    четвёртого», это намерение и знание метагейма; по списку карт его не
    видно, и честнее сказать об этом, чем угадать.
    """
    if (fmt or "").lower() != "commander":
        return None

    feats = vector["features"]
    changers = game_changers_in(rows, db)
    changer_copies = sum(c["copies"] for c in changers)
    mld = feats.get("mass_land_denial") or {"copies": 0, "cards": []}
    turns = feats.get("extra_turn") or {"copies": 0, "cards": []}
    compact = combos.get("compact", 0) if combos.get("known") else 0

    levels: dict[int, dict[str, Any]] = {}
    for level in (1, 2, 3, 4):
        broken: list[dict[str, Any]] = []
        allowed = GC_ALLOWED[level]
        if allowed is not None and changer_copies > allowed:
            broken.append({
                "what": "Game Changers: %d, можно %d" % (changer_copies, allowed),
                "cards": changers[:6]})
        if level <= 3 and mld["copies"]:
            broken.append({"what": "массовое уничтожение земель",
                           "cards": mld["cards"][:6]})
        if level <= 3 and turns["copies"] > 1:
            broken.append({"what": "лишние ходы цепочкой: %d карт"
                                   % turns["copies"], "cards": turns["cards"][:6]})
        if level <= 2 and compact:
            broken.append({"what": "комбо из двух карт: %d" % compact,
                           "cards": []})
        levels[level] = {"title": BRACKET_TITLES[level], "fits": not broken,
                         "violations": broken}

    fits = next((lv for lv in (1, 2, 3, 4) if levels[lv]["fits"]), 4)
    warnings: list[str] = []
    if combos.get("known") and combos.get("best") and combos["best"]["tier"] >= 4:
        warnings.append("собранное комбо помечено как Ruthless — это уровень B4+")
    if not combos.get("known"):
        warnings.append("база комбо не собрана: двойки могли не найтись")
    if fits == 4:
        warnings.append("B5 (cEDH) по списку карт не определяется: это "
                        "намерение и метагейм, а не состав колоды")

    return {
        "bracket": fits,
        "title": BRACKET_TITLES[fits],
        "levels": levels,
        "game_changers": changers,
        "warnings": warnings,
        "rules": {
            "game_changers": "%s, снято %s" % (GAME_CHANGERS_SOURCE,
                                               GAME_CHANGERS_DATE),
            "combo_brackets": SPELLBOOK_BRACKETS,
        },
    }


def scores(measured: dict[str, Any], vector: dict[str, Any]) -> dict[str, Any]:
    """Power, Salt и уверенность -- каждый со своими слагаемыми."""
    return {
        "power": _score(
            "Сила", POWER_WEIGHTS, "power", measured,
            "сумма метрик с весами; 50 — как у обычной колоды формата"),
        "salt": _score(
            "Соль", SALT_WEIGHTS, "salt", measured,
            "насколько колода портит игру другим — по нашим меркам, "
            "а не измерение силы"),
        "confidence": confidence(vector),
        "weights": {"power": POWER_WEIGHTS, "salt": SALT_WEIGHTS},
    }


def profile_for(fmt: str | None) -> dict[str, float]:
    return FORMAT_PROFILE.get((fmt or "").lower(), DEFAULT_PROFILE)


def _scaled(raw: float, expected: float) -> int:
    """Плотность в баллах: попасть в ожидание формата -- 50, вдвое -- 100."""
    if expected <= 0:
        return 0
    return max(0, min(100, int(round(100.0 * raw / (2.0 * expected)))))


def _part(what: str, adds: int, cards: list[dict[str, Any]]) -> dict[str, Any]:
    return {"what": what, "adds": adds, "cards": cards[:6]}


def _capped(title: str, parts: list[dict[str, Any]], basis: str) -> dict[str, Any]:
    """Собрать метрику так, чтобы слагаемые сходились с итогом.

    Шкала упирается в 100, и если просто обрезать итог, слагаемые перестанут
    сходиться: «разгон 100» при слагаемых на 210. Объяснение, которое не
    сходится, -- декорация. Поэтому упор в предел -- это отдельная строка со
    своим (отрицательным) вкладом, и сумма слагаемых равна итогу всегда.
    """
    total = sum(p["adds"] for p in parts)
    value = max(0, min(100, total))
    shown = sorted(parts, key=lambda p: -p["adds"])
    if total > 100:
        shown.append({"what": "выше предела шкалы", "adds": value - total,
                      "cards": []})
    elif total < 0:
        shown.append({"what": "ниже нуля шкалы", "adds": value - total,
                      "cards": []})
    return {"title": title, "value": value, "parts": shown, "basis": basis}


def _avg_cmc(db: CardDB, rows: list[tuple[str, int]]) -> float | None:
    """Средняя стоимость неземельной карты. None, если считать не по чему."""
    total = 0.0
    seen = 0
    for name, quantity in rows:
        copies = int(quantity or 0)
        if copies <= 0:
            continue
        card = db.by_name(name)
        if not card:
            continue
        if "land" in (card.get("type_line") or "").lower().split("—")[0]:
            continue
        total += float(card.get("cmc") or 0) * copies
        seen += copies
    return (total / seen) if seen else None


def metrics(vector: dict[str, Any], fmt: str | None,
            db: CardDB | None = None,
            rows: list[tuple[str, int]] | None = None) -> dict[str, Any]:
    """Метрики из признаков. У каждой -- слагаемые с картами.

    Шкала одна на все метрики: 50 -- как у обычной колоды этого формата, 100 --
    вдвое перекрыто. Это не процентиль и не место среди колод: таких данных у
    программы нет, и выдавать за них свою шкалу нельзя.
    """
    prof = profile_for(fmt)
    feats = vector["features"]
    out: dict[str, Any] = {}

    for key, spec in METRICS.items():
        expected = float(prof.get(spec["against"], 8))
        parts: list[dict[str, Any]] = []
        # Одна карта -- одно слагаемое. Dark Ritual помечен и как быстрая
        # мана, и как ритуал; сложить оба веса значит сосчитать её дважды и
        # получить разгон на ровном месте. Берётся тот признак, который весит
        # больше: он и описывает карту точнее.
        taken: dict[str, tuple[str, float]] = {}
        for feature, weight in sorted(spec["of"].items(), key=lambda kv: -kv[1]):
            got = feats.get(feature) or {"copies": 0, "cards": []}
            for card in got["cards"]:
                if card["name"] not in taken:
                    taken[card["name"]] = (feature, weight)
        for feature, weight in spec["of"].items():
            got = feats.get(feature) or {"copies": 0, "cards": []}
            mine = [c for c in got["cards"] if taken.get(c["name"], ("",))[0] == feature]
            copies = sum(c["copies"] for c in mine)
            if not copies:
                continue
            parts.append(_part(feature, _scaled(weight * copies, expected), mine))
        out[key] = _capped(spec["title"], parts,
                           "50 — как у обычной колоды формата, 100 — вдвое больше")

    # Скорость: насколько колода дешевле обычной для формата. Средняя
    # стоимость -- не весь ответ, но она единственная здесь измеряется, а не
    # назначается, поэтому с неё и считается, а разгон идёт отдельной строкой.
    speed_parts: list[dict[str, Any]] = []
    value = 50
    avg = _avg_cmc(db, rows) if (db and rows) else None
    if avg is not None:
        want = float(prof.get("cmc", 2.4))
        # Вдвое дешевле ожидания -- 100, вдвое дороже -- 0.
        value = max(0, min(100, int(round(50.0 * (2.0 - avg / want)))))
        speed_parts.append({"what": "средняя стоимость %.2f при ожидании %.2f"
                                    % (avg, want), "adds": value, "cards": []})
    fast = feats.get("fast_mana") or {"copies": 0, "cards": []}
    ritual = feats.get("ritual") or {"copies": 0, "cards": []}
    counted: set[str] = set()
    for got, label in ((fast, "fast_mana"), (ritual, "ritual")):
        mine = [c for c in got["cards"] if c["name"] not in counted]
        counted.update(c["name"] for c in mine)
        copies = sum(c["copies"] for c in mine)
        if copies:
            speed_parts.append(_part(label, min(20, 5 * copies), mine))
    out["speed"] = _capped(
        "Скорость", speed_parts,
        "средняя стоимость карты против ожидания формата плюс разгон")

    # Стабильность: чем чаще колода делает то, что задумано. Считается по
    # тому, что видно: туторы, добор и попадание в норму земель.
    cons_parts: list[dict[str, Any]] = []
    raw = 0.0
    for feature, weight in (("tutor", 2.0), ("draw", 0.8), ("recursion", 0.3)):
        got = feats.get(feature) or {"copies": 0, "cards": []}
        if got["copies"]:
            add = weight * got["copies"]
            raw += add
            cons_parts.append(_part(feature, _scaled(add, float(prof["draw"])),
                                    got["cards"]))
    want_lands = float(prof["lands"]) * (vector["cards"] / float(prof["size"])
                                         if prof["size"] else 1.0)
    if want_lands > 0 and vector["cards"]:
        off = abs(vector["lands"] - want_lands) / want_lands
        hit = max(-20, int(round(10 - off * 40)))
        cons_parts.append({
            "what": "земель %d при ожидании %d" % (vector["lands"],
                                                   round(want_lands)),
            "adds": hit, "cards": []})
    out["consistency"] = _capped(
        "Стабильность", cons_parts,
        "туторы и добор плюс попадание манабазы в норму формата")
    return out
