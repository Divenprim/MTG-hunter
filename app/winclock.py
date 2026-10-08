"""На каком ходу колода убивает, если ей не мешать.

Это голдфишинг доведённый до конца: не «хватает ли земель», а «когда наберётся
смертельное». Вопрос ставится ровно так, как его задают вслух: противники
бездействуют, блоков нет, удаления нет, лечения нет — на каком ходу теоретически.

Считается тактами. Каждый ход: добор, земля, розыгрыш того, на что хватает
маны (сначала дешёвое), затем атака теми, кто вышел раньше этого хода, и теми,
у кого есть Haste. Сила существ берётся из базы, прямой урон — из текста карты
по явным оборотам. Накопленное сравнивается с порогом: сорок жизней на
противника в командире, двадцать в остальных форматах, десять ядов — отдельно.

**Две оговорки, и обе обязаны стоять под цифрами.**

Первая: внутри голдфиша модель занижает скорость. Жетоны, лорды, экипировка,
счётчики, лишние бои, рампа и туторы не учитываются, а все они ускоряют. Значит
«убивает к ходу N» читается как «не позже N», и «быстро» отсюда следует, а
«медленно» — нет.

Вторая: против живых противников всё медленнее. Они блокируют, убирают существ
и лечатся. Голдфиш отвечает на «на каком ходу теоретически», а не «чем
кончится партия», и выдавать одно за другое нельзя.

И третье, без чего всё это было бы красивой выдумкой: **покрытие**. Сколько
неземельных карт колоды модель вообще сумела оценить. Колода, в которой она
поняла восемь карт из шестидесяти, не описана — и число рядом с ней должно об
этом говорить.

Наружу отсюда не уходит ничего.
"""

from __future__ import annotations

import random
import re
from typing import Any

from .cards import CardDB

# Сколько жизней у одного противника. Командирские сорок — не формальность:
# на них держится весь расчёт такта.
LIFE = {"commander": 40, "brawl": 25, "oathbreaker": 40}
LIFE_DEFAULT = 20
POISON = 10

HAND_SIZE = 7
CLOCK_GAMES = 2000
CLOCK_TURNS = 14

# Прямой урон. Обороты взяты буквально, с цифрой: «deals 3 damage to any
# target». Условный урон, X-заклинания и урон, зависящий от состояния стола,
# сюда не входят -- посчитать их можно только угадав, а угаданное число
# выглядит на экране точно так же, как посчитанное.
BURN_ANY = re.compile(r"deals (\d+) damage to any target", re.I)
BURN_PLAYER = re.compile(r"deals (\d+) damage to target (?:player|opponent)", re.I)
BURN_EACH = re.compile(r"deals (\d+) damage to each opponent", re.I)

# Числа в правилах карт пишутся словами: «create two 1/1 tokens», «mills four
# cards». Цифрами -- только урон. Из-за этого жетоны и милл раньше не
# считались вовсе: регулярка с \d+ не находила ровным счётом ничего.
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
         "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "twenty": 20}


def count_word(word: str) -> int | None:
    """Число словом. None -- если это «X» или что-то неизвестное.

    Неизвестное -- именно None, а не единица: «create X tokens» зависит от
    того, сколько маны влили, и подставлять туда любое число значит выдумывать.
    """
    return WORDS.get((word or "").strip().lower())


# Жетоны-существа с написанной силой. Жетоны без силы (Treasure, Food, Clue) и
# с нулевой (их сила набирается счётчиками, которых мы не моделируем) сюда не
# попадают: они честно считаются непонятыми.
#
# Количество разбирается не в число, а в **выражение**, которое прогон
# вычисляет в момент розыгрыша. Карта в отрыве непонятна -- «create X tokens»
# зависит от влитой маны, -- а в партии вполне: мана известна, земли известны,
# стол известен. Разбирать такое в константу значит или выбросить карту, или
# подставить выдуманное число.
TOKEN_RX = re.compile(
    r"creates? (a|an|one|two|three|four|five|six|seven|eight|nine|ten|x) "
    r"(\d+)/(\d+)[^.]{0,70}?creature tokens?", re.I)

# «... for each land you control» -- приписка к тому же обороту. Прогон знает,
# сколько у него земель, поэтому и это считается, а не выбрасывается.
PER_LAND_RX = re.compile(
    r"creates? \w+ \d+/\d+[^.]{0,70}?creature tokens?[^.]{0,40}?"
    r"for each land you control", re.I)

# «where X is the number of Goblins you control» -- здесь X переопределён
# текстом и к влитой мане отношения не имеет. Считать его маной значит молча
# завысить: у Krenko это число гоблинов, а не заплаченное.
WHERE_X_RX = re.compile(r"where x is", re.I)

# Когда жетоны появляются. Разница существенная: «при выходе» срабатывает один
# раз, «при атаке» -- каждый бой, и считать второе за первое значит занизить
# колоду вчетверо и больше.
TRIGGER_BOTH = re.compile(
    r"when(?:ever)? (?:this creature|[\w,' ]{1,28}) enters or attacks", re.I)
TRIGGER_ETB = re.compile(
    r"when(?:ever)? (?:this creature|[\w,' ]{1,28}) enters\b", re.I)
TRIGGER_ATTACK = re.compile(
    r"when(?:ever)? (?:this creature|[\w,' ]{1,28}) attacks\b", re.I)

# «В начале вашего шага конца хода / поддержания / боя» -- срабатывает каждый
# ход, пока карта на столе. Таких карт полторы сотни, и считать их за одно
# срабатывание при розыгрыше значит занижать их в разы.
TRIGGER_TURN = re.compile(r"at the beginning of [^,]{1,40},", re.I)

# Счётчики при выходе. Сила такого существа написана не в поле «power», а в
# тексте: Hangarback Walker напечатан 0/0 и приходит с X счётчиками. Считать
# его нулём значит выбросить всю «вырастающую» механику.
COUNTERS_RX = re.compile(
    r"enters with (a|an|one|two|three|four|five|six|seven|eight|nine|ten|x) "
    r"\+1/\+1 counters?", re.I)

# Экипировка. Прибавка написана в одной строке, цена -- в другой.
EQUIP_GIVES = re.compile(r"equipped creature gets \+(\d+)/\+(\d+)", re.I)
EQUIP_COST = re.compile(r"^equip[^{]{0,24}\{(\d+)\}", re.I | re.M)

# Лишний бой: существа бьют этот ход дважды.
EXTRA_COMBAT = re.compile(r"additional combat phase", re.I)

# Сколько раз X входит в стоимость. У Hangarback Walker она {X}{X}, то есть
# на X уходит половина влитого, а не всё. Без этого счёта такая карта
# выглядела бы вдвое сильнее, чем есть.
X_IN_COST = re.compile(r"\{X\}", re.I)

# Способность с ценой: «{T}: создать...». Сколько раз её успеют включить --
# вопрос про развязывание, стол и помехи, а не про текст карты. Не считаем.
ACTIVATED_RX = re.compile(r"\{[^}]+\}[^:\n]{0,24}:", re.I)


def _clause(text: str, at: int) -> str:
    """Предложение, в котором стоит найденный оборот."""
    start = max(text.rfind(".", 0, at), text.rfind("\n", 0, at)) + 1
    end = text.find(".", at)
    return text[start:(end if end > 0 else len(text))]

# Анфем: статическая прибавка всем своим существам.
ANTHEM_RX = re.compile(r"creatures you control get \+(\d+)/\+(\d+)", re.I)

# Милл. Себе колоду сносят не для победы, поэтому берутся только обороты,
# направленные на противника.
MILL_ONE = re.compile(
    r"target (?:player|opponent) mills (\w+) cards?", re.I)
MILL_EACH = re.compile(
    r"each opponent mills (\w+) cards?", re.I)

# Сколько карт в библиотеке противника после стартовой руки.
LIBRARY = {"commander": 99 - 7, "brawl": 59 - 7, "oathbreaker": 99 - 7}
LIBRARY_DEFAULT = 60 - 7


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace("’", "'")


def _entry(card: dict[str, Any], name: str) -> dict[str, Any]:
    """Что модель знает про карту: сила, спешка, яд, прямой урон."""
    type_line = (card.get("type_line") or "").lower()
    front = type_line.split("//")[0]
    keywords = (card.get("keywords") or "")
    if isinstance(keywords, (list, tuple)):
        keywords = ",".join(keywords)
    keywords = keywords.lower()

    power: int | None = None
    raw = card.get("power")
    if raw is not None and str(raw).strip().isdigit():
        power = int(str(raw).strip())

    text = card.get("oracle_text") or ""
    burn = 0
    burn_each = 0
    for rx, where in ((BURN_ANY, "one"), (BURN_PLAYER, "one"), (BURN_EACH, "each")):
        found = rx.search(text)
        if not found:
            continue
        if where == "each":
            burn_each = max(burn_each, int(found.group(1)))
        else:
            burn = max(burn, int(found.group(1)))

    # Жетоны: сколько, с какой силой и по какому правилу считать количество.
    # Нулевая сила по-прежнему не считается: она набирается счётчиками.
    tokens = 0
    tokens_kind = ""
    token_power = 0
    tokens_when = "cast"
    found = TOKEN_RX.search(text)
    if found:
        word = (found.group(1) or "").lower()
        power_of = int(found.group(2))
        clause = _clause(text, found.start())
        if power_of > 0 and not ACTIVATED_RX.search(clause):
            if TRIGGER_BOTH.search(clause):
                tokens_when = "enters_attacks"
            elif TRIGGER_TURN.search(clause):
                tokens_when = "each_turn"
            elif TRIGGER_ETB.search(clause):
                tokens_when = "enters"
            elif TRIGGER_ATTACK.search(clause):
                tokens_when = "attacks"
            if PER_LAND_RX.search(text):
                tokens_kind = "per_land"
                token_power = power_of
            elif word == "x":
                # X от маны -- только если текст его не переопределил.
                if not WHERE_X_RX.search(clause):
                    tokens_kind = "x"
                    token_power = power_of
            else:
                many = count_word(word)
                if many:
                    tokens = many
                    tokens_kind = "fixed"
                    token_power = power_of

    anthem = 0
    found = ANTHEM_RX.search(text)
    if found:
        anthem = int(found.group(1))

    mill = 0
    mill_each = 0
    found = MILL_ONE.search(text)
    if found:
        mill = count_word(found.group(1)) or 0
    found = MILL_EACH.search(text)
    if found:
        mill_each = count_word(found.group(1)) or 0

    # Счётчики при выходе прибавляются к напечатанной силе.
    counters = 0
    counters_kind = ""
    found = COUNTERS_RX.search(text)
    if found:
        word = (found.group(1) or "").lower()
        if word == "x":
            if not WHERE_X_RX.search(_clause(text, found.start())):
                counters_kind = "x"
        else:
            many = count_word(word)
            if many:
                counters = many
                counters_kind = "fixed"

    equips = 0
    equip_cost = 0
    found = EQUIP_GIVES.search(text)
    if found:
        equips = int(found.group(1))
        cost = EQUIP_COST.search(text)
        equip_cost = int(cost.group(1)) if cost else 2

    extra_combat = 1 if EXTRA_COMBAT.search(text) else 0

    is_creature = "creature" in front
    return {
        "counters": counters,
        "counters_kind": counters_kind,
        "equips": equips,
        "equip_cost": equip_cost,
        "extra_combat": extra_combat,
        "x_in_cost": max(1, len(X_IN_COST.findall(card.get("mana_cost") or ""))),
        "tokens": tokens,
        "tokens_kind": tokens_kind,
        "tokens_when": tokens_when,
        "token_power": token_power,
        "anthem": anthem,
        "mill": mill,
        "mill_each": mill_each,
        "plain": _norm(card.get("name") or name),
        "name": card.get("name") or name,
        "cmc": float(card.get("cmc") or 0),
        "is_land": "land" in front,
        "is_creature": is_creature,
        "power": power if is_creature else None,
        "haste": "haste" in keywords,
        "infect": "infect" in keywords,
        "burn": burn,
        "burn_each": burn_each,
        # Карта, про которую модель не знает ничего полезного: ни силы, ни
        # урона, ни жетонов, ни милла. Она честно считается непонятой, а не
        # нулём.
        "blank": not (
            (is_creature and power is not None) or burn or burn_each
            or tokens_kind or anthem or mill or mill_each
            or counters_kind or equips or extra_combat),
    }


def _library(rows: list[tuple[str, int]], db: CardDB,
             zone: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Библиотека, командная зона и счёт понятого."""
    library: list[dict[str, Any]] = []
    command: list[dict[str, Any]] = []
    tally = {"nonland": 0, "modelled": 0, "unknown_power": 0, "unknown_card": 0}
    for name, quantity in rows:
        copies = int(quantity or 0)
        if copies <= 0:
            continue
        card = db.by_name(name)
        if not card:
            tally["unknown_card"] += copies
            tally["nonland"] += copies
            continue
        entry = _entry(card, name)
        if not entry["is_land"]:
            tally["nonland"] += copies
            if entry["blank"]:
                if entry["is_creature"]:
                    tally["unknown_power"] += copies
            else:
                tally["modelled"] += copies
        if entry["plain"] in zone:
            command.append(entry)
            continue
        library.extend([dict(entry) for _ in range(copies)])
    return library, command, tally


def clock(rows: list[tuple[str, int]], db: CardDB, fmt: str | None = None,
          commanders: tuple[str, ...] = (), opponents: int = 1,
          games: int = CLOCK_GAMES, turns: int = CLOCK_TURNS,
          seed: int | None = None) -> dict[str, Any]:
    """Ход, на котором колода добивает противников, если они бездействуют."""
    opponents = max(1, min(3, int(opponents or 1)))
    life = LIFE.get((fmt or "").lower(), LIFE_DEFAULT)
    zone = {_norm(n) for n in commanders}
    library, command, tally = _library(rows, db, zone)
    if len(library) < HAND_SIZE:
        return {"known": False, "why": "в колоде слишком мало карт"}

    rng = random.Random(seed)
    games = max(1, min(int(games), 20000))
    need_damage = life * opponents
    need_poison = POISON * opponents

    # Милл направленный бьёт одного противника, «каждому» -- всех. Поэтому
    # против стола в счёт идёт только второе: заслать всю библиотеку одному и
    # объявить, что побеждены трое, нельзя.
    library_size = LIBRARY.get((fmt or "").lower(), LIBRARY_DEFAULT)
    hit_mill: list[int] = []
    hit_damage: list[int] = []
    hit_poison: list[int] = []
    per_game: list[int | None] = []    # когда победа пришла в этой партии
    best_damage: list[int] = []        # сколько урона набралось к концу

    for _ in range(games):
        shuffled = library[:]
        rng.shuffle(shuffled)
        hand = shuffled[:HAND_SIZE] + [dict(c) for c in command]
        rest = shuffled[HAND_SIZE:]
        lands = 0
        board: list[dict[str, Any]] = []
        gear: list[dict[str, Any]] = []     # экипировка, ждущая существа
        anthem = 0
        left = library_size
        damage = 0
        poison = 0
        got_damage = None
        got_poison = None
        got_mill = None

        for turn in range(1, turns + 1):
            if turn > 1 and rest:
                hand.append(rest.pop(0))
            land = next((c for c in hand if c["is_land"]), None)
            if land is not None:
                hand.remove(land)
                lands += 1

            # Розыгрыш: мана за ход -- это земли, тратится один раз, сначала
            # дешёвое. Командирский налог не моделируется.
            mana = lands
            combats = 0
            for card in sorted([c for c in hand if not c["is_land"]],
                               key=lambda c: c["cmc"]):
                if card["cmc"] > mana:
                    continue
                hand.remove(card)
                # Сколько жетонов выйдет -- решается здесь, когда известны и
                # мана, и стол. В X-заклинание вливают всё, что осталось:
                # играть «Create X tokens» за X=0 никто не станет.
                # При розыгрыше выходят жетоны «сразу» и «при выходе».
                # «Только при атаке» -- не сейчас, они пойдут в бою.
                # Счётчики при выходе. Hangarback Walker напечатан 0/0, и
                # вся его сила -- в них; считать такое существо нулём значит
                # выбросить всю «вырастающую» механику.
                extra_power = card["counters"]
                if card["counters_kind"] == "x":
                    # {X}{X} -- на X уходит половина влитого, а не всё.
                    extra_power = int((mana - card["cmc"]) // card["x_in_cost"])
                    mana = 0
                extra_power = max(0, extra_power)

                many = (0 if card["tokens_when"] in ("attacks", "each_turn")
                        else card["tokens"])
                if card["tokens_kind"] == "x":
                    many = int(mana - card["cmc"])
                    mana = 0
                elif card["tokens_kind"] == "per_land":
                    many = lands
                    mana -= card["cmc"]
                else:
                    mana -= card["cmc"]
                many = max(0, many)
                every_turn = (card["tokens"]
                              if card["tokens_when"] == "each_turn"
                              and card["tokens_kind"] == "fixed" else 0)
                if (card["is_creature"] and card["power"] is not None) \
                        or every_turn:
                    # На столе оказывается не только существо. Bitterblossom --
                    # чары, и делает жетон каждый ход; пока источники клались
                    # только существами, она не делала ничего и колода из
                    # восьми Bitterblossom не убивала ни разу.
                    board.append({
                        "creature": bool(card["is_creature"]
                                         and card["power"] is not None),
                        "power": (card["power"] or 0) + extra_power,
                        "infect": card["infect"],
                        "since": turn, "haste": card["haste"],
                        "makes": (card["tokens"]
                                  if card["tokens_when"] in ("attacks",
                                                             "enters_attacks")
                                  and card["tokens_kind"] == "fixed" else 0),
                        "makes_power": card["token_power"],
                        "every_turn": every_turn})
                # Жетоны выходят вызванными этим ходом, как и всё остальное.
                for _ in range(many):
                    board.append({"creature": True,
                                  "power": card["token_power"], "infect": False,
                                  "since": turn, "haste": False,
                                  "makes": 0, "makes_power": 0,
                                  "every_turn": 0})
                anthem += card["anthem"]
                if card["equips"]:
                    gear.append({"gives": card["equips"],
                                 "cost": card["equip_cost"], "on": False})
                combats += card["extra_combat"]
                damage += card["burn"] + card["burn_each"] * opponents
                left -= (card["mill"] + card["mill_each"]) if opponents == 1 \
                    else card["mill_each"]

            # Экипировка надевается, когда есть на кого и чем заплатить.
            # Кому именно -- неважно: существа в этой модели равнозначны, и
            # разница была бы выдумкой.
            for item in gear:
                if item["on"] or item["cost"] > mana:
                    continue
                wearer = next((c for c in board
                               if c["creature"] and not c.get("geared")), None)
                if wearer is None:
                    continue
                mana -= item["cost"]
                wearer["power"] += item["gives"]
                wearer["geared"] = True
                item["on"] = True

            # Атака: вышедшие раньше этого хода и спешащие. Анфемы
            # прибавляются каждому -- в этом и смысл слова. Лишний бой
            # повторяет её целиком.
            born: list[dict[str, Any]] = []
            for _ in range(1 + combats):
              for creature in board:
                if not creature["creature"]:
                    continue          # чары и артефакты не бьют
                if creature["since"] < turn or creature["haste"]:
                    hits = creature["power"] + anthem
                    if creature["infect"]:
                        poison += hits
                    else:
                        damage += hits
                    # Жетоны «при атаке» выходят вызванными: в этом бою они
                    # уже не бьют, а в следующем -- да.
                    for _ in range(creature.get("makes", 0)):
                        born.append({"creature": True,
                                     "power": creature["makes_power"],
                                     "infect": False, "since": turn,
                                     "haste": False, "makes": 0,
                                     "makes_power": 0, "every_turn": 0})

            # Ежеходные жетоны считаются после боя -- как у «шага конца хода».
            # Это заведомо осторожно: «в начале поддержания» успело бы и
            # ударить. Занижать здесь можно, завышать нельзя.
            for source in board:
                if source["since"] >= turn:
                    continue
                for _ in range(source.get("every_turn", 0)):
                    born.append({"creature": True,
                                 "power": source["makes_power"],
                                 "infect": False, "since": turn,
                                 "haste": False, "makes": 0,
                                 "makes_power": 0, "every_turn": 0})
            board.extend(born)

            # Противник тоже тянет карту каждый ход -- он бездействует, а не
            # перестаёт играть.
            left -= 1

            if got_damage is None and damage >= need_damage:
                got_damage = turn
            if got_poison is None and poison >= need_poison:
                got_poison = turn
            if got_mill is None and left <= 0:
                got_mill = turn
            if None not in (got_damage, got_poison, got_mill):
                break

        if got_damage is not None:
            hit_damage.append(got_damage)
        if got_poison is not None:
            hit_poison.append(got_poison)
        if got_mill is not None:
            hit_mill.append(got_mill)
        # Партия записывается целиком. Складывать «самый быстрый путь» из двух
        # отдельных списков нельзя: в них разные партии, и минимум получился бы
        # между уроном одной игры и ядом другой.
        soonest = [t for t in (got_damage, got_poison, got_mill)
                   if t is not None]
        per_game.append(min(soonest) if soonest else None)
        best_damage.append(damage)

    def route(hits: list[int], title: str, need: int) -> dict[str, Any]:
        return {
            "title": title,
            "need": need,
            "pct": round(100.0 * len(hits) / games, 1),
            "avg_turn": round(sum(hits) / len(hits), 2) if hits else None,
            "soonest": min(hits) if hits else None,
        }

    fastest = [t for t in per_game if t is not None]

    modelled = tally["modelled"]
    nonland = tally["nonland"] or 1
    return {
        "known": True,
        "games": games,
        "turns": turns,
        "opponents": opponents,
        "life": life,
        "routes": {
            "damage": route(hit_damage, "Урон", need_damage),
            "poison": route(hit_poison, "Отравление", need_poison),
            "mill": route(hit_mill, "Снос библиотеки", library_size),
        },
        "fastest": {
            "pct": round(100.0 * len(fastest) / games, 1),
            "avg_turn": round(sum(fastest) / len(fastest), 2) if fastest else None,
            "soonest": min(fastest) if fastest else None,
        },
        "avg_damage": round(sum(best_damage) / games, 1),
        "coverage": {
            "nonland": tally["nonland"],
            "modelled": modelled,
            "pct": round(100.0 * modelled / nonland, 1),
            "unknown_power": tally["unknown_power"],
            "unknown_card": tally["unknown_card"],
        },
        "assumptions": [
            "противники бездействуют: не блокируют, не убирают, не лечатся",
            "одна земля за ход; рампа и быстрая мана НЕ учитываются",
            "счётчики при выходе, экипировка и лишние бои учитываются; "
            "лорды по типу («Goblins you control get +1/+1») — пока нет",
            "сила берётся из базы; существа с нечисловой силой не считаются",
            "прямой урон — только по явным оборотам с цифрой",
            "жетоны считаются с написанной силой; количество через X "
            "считается по влитой мане, «за каждую землю» — по землям на столе",
            "жетоны «при выходе» выходят раз, «при атаке» — каждый бой, "
            "«в начале шага» — каждый ход; способности с ценой ({T}: ...) "
            "не считаются вовсе",
            "жетоны с нулевой силой не считаются: она набирается счётчиками",
            "милл считается по явным оборотам; «половину библиотеки» и "
            "подобное не считается",
            "направленный милл бьёт одного противника, против стола в счёт "
            "идёт только «каждому противнику»",
            "альтернативные победы не считаются вовсе",
            "командирский налог не моделируется",
            "счёт односторонний: настоящая колода убивает не позже — "
            "значит «быстро» отсюда следует, а «медленно» нет",
            "против живых противников всё медленнее: это «на каком ходу "
            "теоретически», а не «чем кончится партия»",
        ],
    }
