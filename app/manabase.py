"""Манабаза: сколько и каких земель нужно, и чем их закрыть подешевле.

Три вопроса, на которые обычно отвечают на глаз:

  1. сколько источников каждого цвета нужно именно этой колоде;
  2. хватает ли их сейчас;
  3. чем добить, не разорившись.

Первый решается арифметикой. Ориентир взят у Фрэнка Карстена: чтобы разыграть
карту вовремя с вероятностью около 90%, нужно столько-то источников цвета --
зависит от того, сколько в стоимости цветных значков и на каком ходу карта
играется. Числа ниже -- его таблица для колоды в шестьдесят карт; для
командирской сотни они пересчитываются пропорционально размеру библиотеки.

Второй решается не формулой, а прогоном: у программы уже есть голдфиш, и
честнее посчитать, в скольких партиях из тысячи нужные цвета оказались на
столе к нужному ходу, чем поверить таблице на слово.

Третий -- поиск по локальной базе: что земля производит, выходит ли она
развёрнутой и сколько стоит. Цена берётся долларовая: она есть почти у всех
земель локально, и отбор не требует ни одного запроса наружу.

Наружу отсюда не уходит ничего.
"""

from __future__ import annotations

import re
from typing import Any

from .cards import CardDB

COLORS = ("W", "U", "B", "R", "G")

# Сколько источников цвета нужно, чтобы разыграть карту вовремя примерно в 90%
# партий. Ключ -- (сколько цветных значков этого цвета, ход, когда карта
# играется). Таблица Карстена для шестидесяти карт; между ходами значения
# меняются медленно, поэтому хватает опорных точек.
KARSTEN_60: dict[tuple[int, int], int] = {
    (1, 1): 14, (1, 2): 13, (1, 3): 12, (1, 4): 11, (1, 5): 10, (1, 6): 9,
    (2, 2): 21, (2, 3): 20, (2, 4): 18, (2, 5): 17, (2, 6): 16,
    (3, 3): 23, (3, 4): 22, (3, 5): 21, (3, 6): 20,
    (4, 4): 25, (4, 5): 24, (4, 6): 23,
}
# Больше шести ходов -- уже не «вовремя»: дальше требование не растёт.
MAX_TURN = 6

# Что земля делает с маной. Разбирается из текста: колонки с производимой
# маной в базе нет, а текст есть у всех.
ADD_LINE = re.compile(r"add\b([^.;]*)", re.I)
PIP = re.compile(r"\{([wubrgc])(?:/([wubrgc]))?\}", re.I)
ANY_COLOR = re.compile(r"mana of any (?:one )?color", re.I)
# «Add one mana of any type that a Gate you control could produce» и
# «choose a basic land type. This land is the chosen type» -- земля, дающая
# любой цвет окольным путём. Считать её бесцветной было бы неправдой.
ANY_TYPE = re.compile(r"mana of any type|choose a basic land type", re.I)
# «Земля входит в игру повёрнутой» -- и то, что это условие, а не приговор.
TAPPED = re.compile(r"enters (?:the battlefield )?tapped", re.I)
MAYBE_UNTAPPED = re.compile(
    r"unless|you may pay|if you (?:control|have|don't)|as this land enters", re.I)
# Земля, которая маны не даёт, но приносит другую: фетчи и поиск.
FETCHES = re.compile(
    r"search your library for a[n]? [^.]*land|sacrifice (?:it|this land):", re.I)


# Способность, дающая ману, со своей стоимостью слева от двоеточия. Именно
# она отличает настоящий источник от того, что цветом только притворяется.
ABILITY = re.compile(r"(?:^|\n)([^\n:]{0,60}?):\s*add\b([^.\n]*)", re.I)
# Что остаётся от стоимости способности, если убрать поворот самой земли.
# Любой остаток -- доплата: мана, энергия, жизнь, жетон, поворот существа.
# Перечислять виды доплат бессмысленно, их выдумывают каждый сет; проще
# спросить, осталось ли хоть что-то.
TAP_SELF = re.compile(r"\{t\}|\{q\}", re.I)
# Цвет, который зависит не от вас: «...that a land an opponent controls could
# produce». Такой источник в расчёт брать нельзя.
THEIRS = re.compile(r"an opponent controls|opponents control", re.I)
# Мана с оговоркой, на что её можно потратить, -- не источник цвета вообще, а
# источник для одной колоды. «Spend this mana only to cast a creature spell of
# the chosen type» -- прекрасная земля для типовой колоды и пустая для любой
# другой.
LIMITED = re.compile(r"spend this mana only", re.I)
# Командирская зона: «any color in your commander's identity» вне командирских
# форматов не даёт ничего -- командира там попросту нет.
COMMANDER_ONLY = re.compile(r"commander'?s? (?:color )?identity", re.I)


def reliability(card: dict[str, Any], fmt: str = "") -> str:
    """Насколько надёжно земля даёт цвет: «direct», «costly» или «theirs».

    Различие не косметическое. «{T}: Add {U} or {R}» -- источник обоих цветов.
    «{1}, {T}: Add one mana of any color» -- это не источник пяти цветов, а
    земля, которая один раз за ход превращает одну ману в другую; считать её
    наравне с двойной значит собрать манабазу, которая не работает. Ровно на
    этом список кандидатов и возглавляли двадцатицентовые фильтры.
    """
    text = card.get("oracle_text") or ""
    if THEIRS.search(text):
        return "theirs"
    if LIMITED.search(text):
        return "limited"
    if COMMANDER_ONLY.search(text) and fmt not in ("commander", "brawl",
                                                   "oathbreaker", "duel"):
        return "limited"
    colored = False
    cheap = False
    for cost, produced in ABILITY.findall(text):
        letters = {left.upper() for left, _r in PIP.findall(produced)}
        letters |= {r.upper() for _l, r in PIP.findall(produced) if r}
        any_color = bool(ANY_COLOR.search(produced) or ANY_TYPE.search(produced))
        if not (any_color or (letters - {"C"})):
            continue                      # способность даёт только бесцветную
        colored = True
        rest = TAP_SELF.sub("", cost)
        # Скобки напоминающего текста -- «({T}: Add {U} or {R}.)» -- частью
        # стоимости не являются: без этого двойные земли выглядели платными.
        rest = re.sub(r"[\s,\.\(\)—–-]+", "", rest)
        if not rest:
            cheap = True
    if not colored:
        # Цвет может быть записан и без двоеточия -- в скобках у двойных
        # земель: «({T}: Add {U} or {R}.)». Такие тоже настоящие.
        return "direct" if produces(card) else "none"
    return "direct" if cheap else "costly"


def produces(card: dict[str, Any]) -> str:
    """Какие цвета земля добавляет. «WUB» -- три, «C» -- только бесцветную.

    Читается из текста способности: «Add {W}, {U}, or {B}» и «Add one mana of
    any color». Гибридные значки считаются за оба цвета: {W/U} -- это выбор,
    и как источник он годится обоим.
    """
    text = (card.get("oracle_text") or "")
    found: set[str] = set()
    for chunk in ADD_LINE.findall(text):
        for left, right in PIP.findall(chunk):
            found.add(left.upper())
            if right:
                found.add(right.upper())
    if ANY_COLOR.search(text) or ANY_TYPE.search(text):
        found.update(COLORS)
    return "".join(c for c in ("W", "U", "B", "R", "G", "C") if c in found)


def entry(card: dict[str, Any]) -> str:
    """Как земля входит: «open» -- развёрнутой, «maybe» -- по условию, «tapped».

    Различать важно: шоковая земля входит развёрнутой за две жизни, и считать
    её тапландом -- врать. Но и обещать, что она всегда развёрнута, нельзя.
    """
    text = (card.get("oracle_text") or "")
    if not TAPPED.search(text):
        return "open"
    return "maybe" if MAYBE_UNTAPPED.search(text) else "tapped"


def fetches(card: dict[str, Any]) -> bool:
    """Земля, которая сама маны не даёт, а достаёт другую землю."""
    return bool(FETCHES.search(card.get("oracle_text") or "")) and not produces(card)


def is_land(card: dict[str, Any] | None) -> bool:
    line = ((card or {}).get("type_line") or "").split("//")[0].lower()
    return "land" in line


def is_basic(card: dict[str, Any] | None) -> bool:
    line = ((card or {}).get("type_line") or "").split("//")[0].lower()
    return "basic" in line and "land" in line


def pips(mana_cost: str) -> dict[str, int]:
    """Сколько цветных значков каждого цвета в стоимости.

    Гибрид считается за оба цвета: разыграть карту можно любым из них, и
    источником годится любой.
    """
    out: dict[str, int] = {}
    for left, right in PIP.findall(mana_cost or ""):
        for letter in (left, right):
            if letter and letter.upper() in COLORS:
                out[letter.upper()] = out.get(letter.upper(), 0) + 1
    return out


def needed_sources(count: int, turn: int, library: int = 60) -> int:
    """Сколько источников цвета нужно для такого числа значков к такому ходу.

    Для колоды не в шестьдесят карт требование пересчитывается по доле: в
    сотне командирской колоды тот же шанс требует пропорционально больше
    источников.
    """
    count = max(1, min(4, count))
    turn = max(count, min(MAX_TURN, turn or count))
    base = KARSTEN_60.get((count, turn))
    if base is None:
        base = KARSTEN_60.get((count, MAX_TURN), 14)
    return int(round(base * (library / 60.0)))


# --------------------------------------------------------------------------- #
# Что в колоде сейчас и чего ей не хватает
# --------------------------------------------------------------------------- #

def _rows(deck: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in deck.get("cards") or []
            if r.get("section") in ("main", "commander")]


def _card(db: CardDB, row: dict[str, Any]) -> dict[str, Any]:
    card = row.get("card") or {}
    if card.get("oracle_text") is None:
        full = db.by_name(card.get("name") or row.get("name") or "")
        if full:
            return full
    return card


def sources(db: CardDB, deck: dict[str, Any]) -> dict[str, Any]:
    """Сколько источников каждого цвета в колоде -- и что это за карты.

    Источник -- всё, что добавляет ману этого цвета: земля, камень, дорк.
    Земли и остальное считаются отдельно: земля приходит сама, а существо
    надо сперва разыграть и дожить с ним до следующего хода.
    """
    by_color: dict[str, int] = {c: 0 for c in COLORS}
    land_copies = 0
    open_copies = 0
    maybe_copies = 0
    tapped_copies = 0
    fetch_copies = 0
    basics: dict[str, int] = {}
    lands: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []

    for row in _rows(deck):
        card = _card(db, row)
        qty = int(row.get("quantity") or 0)
        makes = produces(card)
        land = is_land(card)
        if land:
            land_copies += qty
            how = entry(card)
            if fetches(card):
                fetch_copies += qty
            elif how == "open":
                open_copies += qty
            elif how == "maybe":
                maybe_copies += qty
            else:
                tapped_copies += qty
            if is_basic(card):
                for letter in makes:
                    if letter in COLORS:
                        basics[letter] = basics.get(letter, 0) + qty
        if not makes:
            continue
        for letter in makes:
            if letter in COLORS:
                by_color[letter] = by_color.get(letter, 0) + qty
        item = {"name": card.get("name") or row.get("name"),
                "quantity": qty, "produces": makes,
                "entry": entry(card) if land else "spell"}
        (lands if land else others).append(item)

    return {
        "by_color": by_color,
        "lands": land_copies,
        "open": open_copies,
        "maybe": maybe_copies,
        "tapped": tapped_copies,
        "fetch": fetch_copies,
        "basics": basics,
        "land_rows": sorted(lands, key=lambda x: (-x["quantity"], x["name"] or "")),
        "other_rows": sorted(others, key=lambda x: (-x["quantity"], x["name"] or "")),
    }


def demands(db: CardDB, deck: dict[str, Any],
            library: int | None = None) -> dict[str, Any]:
    """Чего колода требует от манабазы -- по самой требовательной карте цвета.

    Требование колоды -- это не среднее, а максимум: если в колоде есть одна
    карта с тремя синими значками на третьем ходу, манабаза обязана её
    обслуживать, иначе карта мёртвая.
    """
    rows = _rows(deck)
    # Считаем по тому размеру, которым колода будет играть, а не по тому,
    # сколько карт в неё уже положили: у недособранной колоды требования иначе
    # выходят заниженными -- «двенадцать источников хватит», а в готовой
    # шестидесятке та же карта требует двадцати двух.
    total = sum(int(r.get("quantity") or 0) for r in rows)
    singleton = (deck.get("format") or "").lower() in (
        "commander", "brawl", "oathbreaker", "duel", "historicbrawl")
    library = library or max(99 if singleton else 60, total)
    need: dict[str, int] = {}
    worst: dict[str, dict[str, Any]] = {}

    for row in rows:
        card = _card(db, row)
        if is_land(card):
            continue
        # У разделённых и двусторонних карт в стоимости стоят обе половины
        # («{2}{W}{W} // {3}{W}{W}»), а разыгрывают их по одной. Считаем по
        # передней: иначе карта требует вдвое больше значков, чем есть, и
        # манабаза оказывается «недостаточной» на ровном месте.
        whole = card.get("mana_cost") or ""
        cost = whole.split("//")[0].strip()
        turn = int(float(card.get("cmc") or 0)) or 1
        if "//" in whole:
            # Стоимость по значкам передней половины: cmc в базе -- сумма обеих.
            turn = sum(1 for _ in PIP.findall(cost)) + sum(
                int(n) for n in re.findall(r"\{(\d+)\}", cost)) or 1
        for letter, count in pips(cost).items():
            want = needed_sources(count, turn, library)
            if want > need.get(letter, 0):
                need[letter] = want
                worst[letter] = {
                    "name": card.get("name") or row.get("name"),
                    "pips": count, "turn": turn, "cost": cost,
                }
    return {"need": need, "worst": worst, "library": library}


# --------------------------------------------------------------------------- #
# Когда земли -- это не обслуга, а сам план
# --------------------------------------------------------------------------- #

# Бывают колоды, где манабаза и есть замысел: турбофог с Maze's End выигрывает
# десятью Вратами, трон Урзы -- тремя землями, Valakut -- горами. Советовать
# такой колоде «поменяйте тапленды на развёрнутые двойные» значит предлагать
# разобрать то, ради чего она собрана. Поэтому сперва отдельный вопрос: не
# держится ли на землях победа -- и если держится, на каких именно.

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "twenty": 20,
}
# «control ten or more Gates with different names», «control at least five
# other Mountains» -- счётчик земель, а не просто упоминание.
COUNT_MORE = re.compile(
    r"control\s+(?:at least\s+)?([a-z]+|\d+)\s+or\s+more\s+(?:other\s+)?"
    r"([A-Za-z][A-Za-z'\-]*?)s\b", re.I)
COUNT_LEAST = re.compile(
    r"control\s+at least\s+([a-z]+|\d+)\s+(?:other\s+)?"
    r"([A-Za-z][A-Za-z'\-]*?)s\b", re.I)
# «If you control an Urza's Power-Plant and an Urza's Tower» -- набор земель,
# который работает только целиком.
PAIR = re.compile(
    r"if you control an?\s+([A-Za-z'\- ]{3,30}?)\s+and an?\s+([A-Za-z'\- ]{3,30}?)[,.]",
    re.I)
WINS = ("you win the game", "loses the game")


def _plain(text: str) -> str:
    """Имя без дефисов и регистра: в тексте «Urza's Power-Plant», на карте --
    «Urza's Power Plant»."""
    return re.sub(r"[^a-z ]", "", (text or "").lower().replace("-", " ")).strip()


def _count_word(word: str) -> int:
    word = (word or "").lower()
    if word.isdigit():
        return int(word)
    return NUMBER_WORDS.get(word, 0)


def _text_of(card: dict[str, Any]) -> str:
    text = card.get("oracle_text") or ""
    for face in card.get("card_faces") or []:
        if isinstance(face, dict) and face.get("oracle_text"):
            text += "\n" + face["oracle_text"]
    return text


def _subtypes(card: dict[str, Any]) -> list[str]:
    line = card.get("type_line") or ""
    tail = line.split("—")[-1] if "—" in line else ""
    return [w for w in tail.replace("//", " ").split() if w]


def _matches_what(card: dict[str, Any], what: str) -> bool:
    """Годится ли земля под требование «десять Врат» или «пять Гор».

    Только по подтипу и точному имени. Слово в имени не годится: «Mystic Gate»
    и «Sea Gate Wreckage» -- не Врата, Maze's End их не считает, и предлагать
    их колоде на Вратах значит советовать карту, которая план не двигает.
    """
    if what == "land":
        return True
    low = what.lower()
    if any(s.lower() == low for s in _subtypes(card)):
        return True
    return _plain(card.get("name") or "") == _plain(what)


def land_plan(db: CardDB, deck: dict[str, Any]) -> list[dict[str, Any]]:
    """Планы победы, которые держатся на землях.

    Считается по тексту карт самой колоды: карта, которая пересчитывает ваши
    земли (или земли одного вида) и что-то за это даёт, делает эти земли
    занятыми -- их нельзя менять на «более удобные».
    """
    rows = _rows(deck)
    lands = [(r, _card(db, r)) for r in rows]
    lands = [(r, c) for r, c in lands if is_land(c)]
    if not lands:
        return []

    found: dict[str, dict[str, Any]] = {}

    def remember(card: dict[str, Any], need: int, what: str, distinct: bool,
                 kind: str) -> None:
        if need < 2:
            return
        matched = [(r, c) for r, c in lands if _matches_what(c, what)]
        if not matched:
            return
        names = sorted({(c.get("name") or r.get("name") or "")
                        for r, c in matched})
        copies = sum(int(r.get("quantity") or 0) for r, _ in matched)
        have = len(names) if distinct else copies
        # Один вид земель -- один план. «Десять Врат с разными именами» и «два
        # Врат для трёх жизней» -- одно требование, и главным берётся то, что
        # выигрывает игру, а среди равных -- строгое; иначе панель повторяет
        # себя двумя строками.
        key = what.lower()
        wins = any(w in (_text_of(card) or "").lower() for w in WINS)
        weight = (wins, need)
        old = found.get(key)
        if old and (old["wins"], old["need"]) >= weight:
            return
        found[key] = {
            "card": card.get("name") or "",
            "kind": kind,
            "what": what,
            "distinct": distinct,
            "need": need,
            "have": have,
            "copies": copies,
            "names": names,
            "wins": wins,
            "ok": have >= need,
        }

    for row in rows:
        card = _card(db, row)
        text = _text_of(card)
        if not text:
            continue
        low = text.lower()
        for rx in (COUNT_MORE, COUNT_LEAST):
            for word, thing in rx.findall(text):
                need = _count_word(word)
                if not need:
                    continue
                thing = thing.strip()
                if thing.lower() in ("card", "permanent", "creature", "token",
                                     "spell", "player", "opponent", "turn"):
                    continue
                what = "land" if thing.lower() == "land" else thing
                distinct = "different names" in low
                remember(card, need, what, distinct, "count")
        for first, second in PAIR.findall(text):
            pair = [_plain(first), _plain(second)]
            own = {_plain(c.get("name") or r.get("name") or "")
                   for r, c in lands}
            if all(p in own for p in pair):
                names = sorted(set(pair) | {_plain(card.get("name") or "")})
                key = "+".join(names)
                found.setdefault(key, {
                    "card": card.get("name") or "",
                    "kind": "pair",
                    "what": "",
                    "distinct": True,
                    "need": len(names),
                    "have": len(names),
                    "copies": 0,
                    "names": [n.title() for n in names],
                    "wins": False,
                    "ok": True,
                })

    plans = list(found.values())
    plans.sort(key=lambda p: (not p["wins"], -p["need"]))
    return plans


def plan_lands(plans: list[dict[str, Any]], db: CardDB,
               deck: dict[str, Any]) -> int:
    """Сколько земель в колоде занято планом -- в штуках, без двойного счёта."""
    if not plans:
        return 0
    taken: dict[str, int] = {}
    for row, card in ((r, _card(db, r)) for r in _rows(deck)):
        if not is_land(card):
            continue
        name = card.get("name") or row.get("name") or ""
        for plan in plans:
            # Сама карта-выплата тоже занимает слот: Maze's End -- земля, и
            # четыре её копии играются ради плана, а не ради маны.
            if (plan["what"] and _matches_what(card, plan["what"])
                    or name in plan["names"] or name == plan["card"]):
                taken[name] = int(row.get("quantity") or 0)
                break
    return sum(taken.values())


def report(db: CardDB, deck: dict[str, Any]) -> dict[str, Any]:
    """Полная картина: что есть, что нужно, чего не хватает."""
    have = sources(db, deck)
    want = demands(db, deck)
    colors: list[dict[str, Any]] = []
    for letter in COLORS:
        need = want["need"].get(letter, 0)
        got = have["by_color"].get(letter, 0)
        if not need and not got:
            continue
        colors.append({
            "color": letter,
            "have": got,
            "need": need,
            "short": max(0, need - got),
            "worst": want["worst"].get(letter),
        })
    colors.sort(key=lambda c: (-c["short"], c["color"]))
    short = [c for c in colors if c["short"] > 0]
    plans = land_plan(db, deck)
    taken = plan_lands(plans, db, deck)
    return {
        "colors": colors,
        "short": short,
        "plan": plans,
        "plan_lands": taken,
        "free_lands": max(0, have["lands"] - taken),
        "lands": have["lands"],
        "entry": {"open": have["open"], "maybe": have["maybe"],
                  "tapped": have["tapped"], "fetch": have["fetch"]},
        "basics": have["basics"],
        "land_rows": have["land_rows"],
        "other_rows": have["other_rows"],
        "library": want["library"],
        "ok": not short,
    }


# --------------------------------------------------------------------------- #
# Чем добить -- и не разориться
# --------------------------------------------------------------------------- #

# Во что обходится способ входа. Тапнутая земля не запрещена -- одними
# развёрнутыми манабазу не собрать, -- но каждый ход, проведённый в развороте,
# стоит темпа, и в списке она должна стоять ниже равной ей развёрнутой.
ENTRY_SCORE = {"open": 3.0, "maybe": 2.0, "tapped": 0.5}
# Дороже этого «дешёвой землёй» уже никто не назовёт: по умолчанию отсекаем,
# но порог задаётся снаружи.
DEFAULT_BUDGET = 5.0


def _usd(row: Any) -> float | None:
    value = row["usd"] if "usd" in row.keys() else None
    return float(value) if value is not None else None


def land_pool(db: CardDB, fmt: str) -> list[dict[str, Any]]:
    """Все земли формата -- с ценой самой дешёвой печати.

    Цена берётся минимальная по всем печатям: карта, которая в одном сете
    стоит три доллара, а в другом двадцать центов, -- дешёвая карта.
    """
    rows = db.conn.execute(
        "SELECT c.oracle_id AS oracle_id, "
        "       MIN(CAST(json_extract(c.prices, '$.usd') AS REAL)) AS usd "
        "FROM cards c "
        "WHERE LOWER(c.type_line) LIKE '%land%' "
        "  AND json_extract(c.legalities, '$.' || ?) = 'legal' "
        "GROUP BY c.oracle_id", (fmt,)).fetchall()
    prices = {r["oracle_id"]: _usd(r) for r in rows}
    if not prices:
        return []

    marks = ",".join("?" * min(len(prices), 900))
    out: list[dict[str, Any]] = []
    ids = list(prices)
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        marks = ",".join("?" * len(chunk))
        for row in db.conn.execute(
                "SELECT * FROM cards WHERE representative = 1 "
                "AND oracle_id IN (%s)" % marks, chunk):
            card = db.card_dict(row)
            # «Artifact // Land» -- это артефакт: землёй он станет, если
            # доживёт и перевернётся. В манабазу такие не считаются.
            if not is_land(card):
                continue
            out.append({
                "name": card.get("name"),
                "ru_name": card.get("ru_name"),
                "oracle_id": card.get("oracle_id"),
                "type_line": card.get("type_line"),
                "image_small": card.get("image_small"),
                "image_normal": card.get("image_normal"),
                "produces": produces(card),
                "reliable": reliability(card, fmt),
                "entry": entry(card),
                "fetch": fetches(card),
                "basic": is_basic(card),
                "usd": prices.get(card.get("oracle_id")),
            })
    return out


def candidates(db: CardDB, deck: dict[str, Any], fmt: str,
               colors: str = "", budget: float | None = None,
               only_open: bool = False, include_fetch: bool = True,
               limit: int = 24) -> dict[str, Any]:
    """Земли, которыми закрывают нехватку цветов -- по возрастанию цены.

    Порядок такой: сперва сколько нужных цветов земля закрывает (двойная в
    нужной паре лучше одноцветной), потом как она входит, и только потом
    цена. Иначе список возглавляют двадцатицентовые тапленды, которые и так
    все знают.
    """
    report_now = report(db, deck)
    short = colors or "".join(c["color"] for c in report_now["short"])
    if not short:
        short = "".join(c["color"] for c in report_now["colors"])
    wanted = set(short) & set(COLORS)
    budget = DEFAULT_BUDGET if budget is None else budget

    in_deck = {(r.get("name") or "").lower() for r in deck.get("cards") or []}
    for row in deck.get("cards") or []:
        real = ((row.get("card") or {}).get("name") or "").lower()
        if real:
            in_deck.add(real)

    # Если на землях держится победа, добирать цвет надо теми землями, которые
    # план не ломают: колоде с Maze's End нужны не «удобные двойные», а ещё
    # одни Врата -- они и цвет дают, и приближают выигрыш.
    plans = report_now.get("plan") or []
    main = plans[0] if plans else None
    plan_group: list[dict[str, Any]] = []

    duals: list[dict[str, Any]] = []
    anycolor: list[dict[str, Any]] = []
    fetchers: list[dict[str, Any]] = []
    costly: list[dict[str, Any]] = []
    for land in land_pool(db, fmt):
        if land["basic"]:
            continue
        price = land["usd"]
        if price is not None and budget and price > budget:
            continue
        here = (land["name"] or "").lower() in in_deck
        if main and main["what"] and _matches_what(land, main["what"]):
            # План на разные имена повторной копией не двигается: такие земли
            # предлагать незачем.
            if not (main["distinct"] and here):
                covers_plan = set(land["produces"]) & wanted
                plan_group.append(dict(
                    land, covers="".join(sorted(covers_plan)), have=here,
                    score=round(len(covers_plan) * 4.0
                                + ENTRY_SCORE.get(land["entry"], 1.0)
                                - min(3.0, (price or 0) ** 0.5), 2)))
        if land["fetch"]:
            if include_fetch:
                land = dict(land, score=round(2.0 - (price or 0) / 10.0, 2),
                            covers="", have=(land["name"] or "").lower() in in_deck)
                fetchers.append(land)
            continue
        covers = set(land["produces"]) & wanted
        if not covers:
            continue
        if only_open and land["entry"] != "open":
            continue
        if land.get("reliable") != "direct":
            # Земля, дающая цвет за доплату или с оглядкой на чужие земли, --
            # не источник, а размен. Показываем отдельно и не считаем.
            costly.append(dict(land, covers="".join(sorted(covers)),
                               have=(land["name"] or "").lower() in in_deck))
            continue
        # Цена в счёте участвует мягко: разница между двадцатью центами и
        # двумя долларами важна, между двумя и тремя -- почти нет.
        score = (len(covers) * 4.0
                 + ENTRY_SCORE.get(land["entry"], 1.0)
                 - min(3.0, (price or 0) ** 0.5))
        item = dict(land, covers="".join(sorted(covers)), score=round(score, 2),
                    have=(land["name"] or "").lower() in in_deck)
        # Двойные и тройные -- отдельно от «любого цвета». Земля на все пять
        # цветов по числу источников выглядит лучше любой двойной, но играют
        # их по-разному: двойная выходит в нужный ход, а пятицветная почти
        # всегда с оговоркой. Сравнивать их одним списком -- обманывать себя.
        colored = len([c for c in land["produces"] if c in COLORS])
        (duals if colored <= 3 else anycolor).append(item)

    order = lambda x: (-x["score"], x["usd"] if x["usd"] is not None else 99)
    duals.sort(key=order)
    anycolor.sort(key=order)
    plan_group.sort(key=order)
    fetchers.sort(key=lambda x: (x["usd"] if x["usd"] is not None else 99))
    costly.sort(key=lambda x: (-len(x["covers"]),
                               x["usd"] if x["usd"] is not None else 99))
    return {
        "format": fmt,
        "colors": "".join(sorted(wanted)),
        "budget": budget,
        "only_open": only_open,
        "plan": plan_group[:limit],
        "plan_what": (main or {}).get("what", ""),
        "duals": duals[:limit],
        "anycolor": anycolor[:max(6, limit // 3)],
        "fetch": fetchers[:limit] if include_fetch else [],
        "costly": costly[:limit],
        "report": report_now,
    }
