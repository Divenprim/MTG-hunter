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

    is_creature = "creature" in front
    return {
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
        # урона. Она честно считается непонятой, а не нулём.
        "blank": not (
            (is_creature and power is not None) or burn or burn_each),
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
        damage = 0
        poison = 0
        got_damage = None
        got_poison = None

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
            for card in sorted([c for c in hand if not c["is_land"]],
                               key=lambda c: c["cmc"]):
                if card["cmc"] > mana:
                    continue
                mana -= card["cmc"]
                hand.remove(card)
                if card["is_creature"] and card["power"] is not None:
                    board.append({"power": card["power"], "infect": card["infect"],
                                  "since": turn, "haste": card["haste"]})
                damage += card["burn"] + card["burn_each"] * opponents

            # Атака: вышедшие раньше этого хода и спешащие.
            for creature in board:
                if creature["since"] < turn or creature["haste"]:
                    if creature["infect"]:
                        poison += creature["power"]
                    else:
                        damage += creature["power"]

            if got_damage is None and damage >= need_damage:
                got_damage = turn
            if got_poison is None and poison >= need_poison:
                got_poison = turn
            if got_damage is not None and got_poison is not None:
                break

        if got_damage is not None:
            hit_damage.append(got_damage)
        if got_poison is not None:
            hit_poison.append(got_poison)
        # Партия записывается целиком. Складывать «самый быстрый путь» из двух
        # отдельных списков нельзя: в них разные партии, и минимум получился бы
        # между уроном одной игры и ядом другой.
        soonest = [t for t in (got_damage, got_poison) if t is not None]
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
            "жетоны, лорды, экипировка, счётчики и лишние бои НЕ учитываются",
            "сила берётся из базы; существа с нечисловой силой не считаются",
            "прямой урон — только по явным оборотам с цифрой",
            "милл и альтернативные победы пока не считаются вовсе",
            "командирский налог не моделируется",
            "счёт односторонний: настоящая колода убивает не позже — "
            "значит «быстро» отсюда следует, а «медленно» нет",
            "против живых противников всё медленнее: это «на каком ходу "
            "теоретически», а не «чем кончится партия»",
        ],
    }
