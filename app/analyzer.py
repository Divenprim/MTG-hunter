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
    "land_denial": ("mass-land-denial", "removal-land"),   # ~115 и ~300
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
        "of": {"land_denial": 2.0, "discard": 1.0, "tax": 1.4},
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
SALT_WEIGHTS: dict[str, float] = {
    "denial": 0.34,
    "lock": 0.34,
    "extra_turn": 0.16,
    "land_denial": 0.16,
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
