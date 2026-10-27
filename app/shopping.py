"""Что покупать первым, если колод несколько.

Вопрос, на который до сих пор никто не отвечал: деньги одни, а колод десять.
«Чего не хватает» умеет считать по одной колоде, и это правильный ответ на
другой вопрос -- «что нужно вот этой». Но карта, которая нужна трём колодам
сразу, и карта, которая нужна одной, стоят в том списке рядом, без всякого
различия. А различие и есть весь смысл: за одни и те же деньги первая
двигает втрое больше.

Поэтому здесь счёт идёт не по колоде, а по карте:

  * **в скольких колодах нужна** -- и в каких именно;
  * **сколько не хватает**, если собирать все эти колоды одновременно.
    Карты, занятые уже собранными колодами, в запас не идут: четыре Молнии,
    лежащие в собранном Бёрне, для остальных колод не существуют;
  * **во что обойдётся** -- по самой дешёвой известной цене на topdeck;
  * **кого это достроит** -- колоды, которым, кроме этой карты, не нужно
    больше ничего. Такая покупка не «приближает», а заканчивает, и это
    сильнее любого другого довода.

Цены берутся из кеша и никуда не ходят: страница с ответом не должна стоить
двухсот запросов к чужому сайту.
"""

from __future__ import annotations

from typing import Any

from .cards import CardDB, normalize_name
from .formats import BASIC_LANDS
from .holdings import gather


# Ключи базовых земель в том же виде, в каком считается всё остальное.
_BASIC_KEYS = {normalize_name(n) for n in BASIC_LANDS}


def _cached(prices: dict[str, Any], key: str, name: str) -> dict[str, Any]:
    return prices.get(key) or prices.get((name or "").lower()) or {}


def _price(prices: dict[str, Any], key: str, name: str) -> int:
    return int(_cached(prices, key, name).get("rub_min") or 0)


def _plain_price(prices: dict[str, Any], key: str, name: str) -> int:
    """Цена обычной копии: не фойла и не потрёпанной.

    Ноль значит «неизвестно»: цену узнавали до того, как программа стала
    раскладывать её по версиям. Это не то же самое, что «равна нижней».
    """
    return int(_cached(prices, key, name).get("rub_plain") or 0)


def within_budget(rows: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    """Что взять, если денег столько.

    Список покупок целиком не покупают: на живых колодах это шестьсот копий
    и сорок пять тысяч рублей. Вопрос, который человек задаёт себе у кассы,
    другой: «есть пять тысяч -- что брать».

    Порядок тот же, что и в списке, только теперь он тратит деньги:

      * **сперва то, что достраивает колоду целиком** -- дешёвое вперёд. Это
        единственная покупка, которая не приближает, а заканчивает: колода
        после неё встаёт на стол;
      * **потом -- колод на рубль.** Карта, нужная трём колодам за триста
        рублей, идёт впереди карты, нужной одной за сто;
      * **сайдборды -- в хвост своей группы.** Без них колода играет.

    Карта берётся целиком или никак: две Молнии из четырёх не достраивают
    ничего. Дорогая строка не обрывает подбор -- деньги тратятся дальше на
    то, что влезает; так за те же средства уезжает больше карт.

    Карты без известной цены не планируются вовсе -- их число названо
    отдельно, чтобы набор не выглядел полным ответом, когда он неполный.
    """
    budget = max(0, int(budget or 0))
    if not budget:
        return {}
    priced = [r for r in rows if r.get("price") and r.get("cost")]
    finishing = sorted(
        [r for r in priced if r.get("finishes")],
        key=lambda r: (1 if r.get("side_only") else 0, r["cost"],
                       r["name"].lower()))
    rest = sorted(
        [r for r in priced if not r.get("finishes")],
        key=lambda r: (1 if r.get("side_only") else 0,
                       -(r["decks"] / max(1, r["cost"])), r["cost"],
                       r["name"].lower()))

    take: list[dict[str, Any]] = []
    spent = 0
    for row in finishing + rest:
        if spent + row["cost"] <= budget:
            take.append(row)
            spent += row["cost"]
    taken = {r["key"] for r in take}
    left = [r for r in priced if r["key"] not in taken]
    done: list[str] = []
    for row in take:
        done.extend(row.get("finishes") or [])
    return {
        "rub": budget,
        "spent": spent,
        "cards": len(take),
        "copies": sum(r["lack"] for r in take),
        "keys": [r["key"] for r in take],
        # Какие колоды этот набор заканчивает -- ради этого всё и считается.
        "finishes": sorted(set(done)),
        "left": len(left),
        # Сколько стоит ближайшее, на что не хватило: «добавьте триста рублей»
        # -- ответ полезнее, чем «на остальное не хватает».
        "next_rub": min((r["cost"] for r in left), default=0),
        "no_price": len([r for r in rows if not r.get("price")]),
    }


def plan(
    deck_store: Any,
    collection: dict[str, int],
    db: CardDB | None = None,
    prices: dict[str, Any] | None = None,
    limit: int = 200,
    include_assembled: bool = False,
    skip_basics: bool = True,
    skip_side: bool = False,
    splits: set[str] | None = None,
    budget: int = 0,
) -> dict[str, Any]:
    """Список покупок по всем колодам сразу, самое полезное сверху.

    `include_assembled` -- считать ли собранные колоды. По умолчанию нет:
    собранная колода уже стоит на столе, и докупать в неё нечего. Но если
    в ней чего-то недостаёт (так бывает после правки списка), счёт по ней
    включается этим флагом.

    `splits` -- ключи карт, у которых цена записана с разбором по версиям.
    Остальные цены -- одно число на имя, и к чему оно относится, неизвестно:
    такую цену видно в итогах отдельным счётом, а не молча.

    `budget` -- сколько денег есть на самом деле. Список из шестисот копий
    целиком не покупают; с бюджетом из него выбирается набор, который за эти
    деньги двигает больше всего (см. `within_budget`).

    `skip_side` -- не считать сайдборды. Сайд участвует в счёте с самого
    начала (карты он занимает так же, как мейн), но покупка в сайд -- это
    решение другой срочности: колода, которой не хватает двух карт мейна,
    на стол не встанет вовсе, а без сайда в неё можно играть сегодня же.
    Поэтому сайд виден отдельной пометкой, и его можно убрать из счёта.
    """
    prices = prices or {}
    data = gather(deck_store, collection, db)
    owned, committed = data["owned"], data["committed"]
    where, display = data["where"], data["display"]

    # Свободно на руках: всё, что не занято собранными колодами.
    free = {key: owned.get(key, 0) - committed.get(key, 0)
            for key in set(owned) | set(committed)}

    # Чего каждой колоде не хватает -- по тем же правилам, что в учёте.
    short_by_deck: dict[str, dict[str, int]] = {}
    side_by_deck: dict[str, dict[str, int]] = {}
    deck_name: dict[str, str] = {}
    deck_format: dict[str, str] = {}
    side_lack = 0
    for deck in data["decks"]:
        if deck["assembled"] and not include_assembled:
            continue
        deck_name[deck["id"]] = deck["name"]
        deck_format[deck["id"]] = deck.get("format") or ""
        wants = dict(deck["wants"])
        side = dict(deck.get("wants_side") or {})
        if skip_side:
            # Вычитаем сайд из потребности, а не выбрасываем карту целиком:
            # четыре Молнии в мейне и две в сайде -- это шесть, из которых
            # покупать сейчас надо четыре.
            for key, qty in side.items():
                left = wants.get(key, 0) - qty
                if left > 0:
                    wants[key] = left
                else:
                    wants.pop(key, None)
            side = {}
        lacks: dict[str, int] = {}
        for key, need in wants.items():
            have = owned.get(key, 0) if deck["assembled"] else max(
                0, free.get(key, 0))
            lack = max(0, need - have)
            if lack:
                lacks[key] = lack
        short_by_deck[deck["id"]] = lacks
        # Сколько из недостающего уходит в сайд. Недостача закрывается
        # сперва мейном: если карты не хватает на обе секции, первым без
        # неё остаётся сайд, а не основная колода.
        in_side = {}
        for key, lack in lacks.items():
            share = min(lack, side.get(key, 0))
            if share:
                in_side[key] = share
                side_lack += share
        side_by_deck[deck["id"]] = in_side

    # Колоды, которым не хватает ровно одного названия: купив его, человек
    # не «приближается», а заканчивает колоду.
    finishes: dict[str, list[str]] = {}
    for deck_id, lacks in short_by_deck.items():
        if len(lacks) == 1:
            finishes.setdefault(next(iter(lacks)), []).append(deck_id)

    rows: list[dict[str, Any]] = []
    basics_lack = 0
    for key in {k for lacks in short_by_deck.values() for k in lacks}:
        name = display.get(key, key)
        # Базовые земли -- не покупка. Их берут горстью из коробки, они стоят
        # пять рублей и лежат у всех; на живых колодах они занимали первые
        # три строки списка («Forest, не хватает 33») и отодвигали то, ради
        # чего список и открывают. Считаем их отдельным числом.
        if skip_basics and normalize_name(name) in _BASIC_KEYS:
            basics_lack += sum(lacks.get(key, 0)
                               for lacks in short_by_deck.values())
            continue
        price = _price(prices, key, name)
        needs = []
        total = 0
        for deck_id, lacks in short_by_deck.items():
            if key not in lacks:
                continue
            total += lacks[key]
            needs.append({
                "deck_id": deck_id,
                "deck": deck_name.get(deck_id, ""),
                "format": deck_format.get(deck_id, ""),
                "lack": lacks[key],
                # Сколько из них -- в сайдборд этой колоды.
                "side": side_by_deck.get(deck_id, {}).get(key, 0),
                # Сколько эта колода просит всего -- чтобы было видно «4 из 4»
                # против «1 из 4».
                "need": next((w["quantity"] for w in where.get(key, [])
                              if w["deck_id"] == deck_id), lacks[key]),
            })
        needs.sort(key=lambda n: (-n["lack"], n["deck"].lower()))
        done = [deck_name.get(d, "") for d in finishes.get(key, [])]
        rows.append({
            "key": key,
            "name": name,
            "decks": len(needs),
            "lack": total,
            "price": price,
            # Спрашивали ли уже. «Цену не спрашивали» и «спрашивали -- не
            # нашлось» это разные вещи: первое чинится кнопкой, второе
            # значит, что у продавцов этой карты сейчас нет.
            "asked": bool(_cached(prices, key, name).get("checked_at")),
            # Цена обычной копии, если она известна и отличается: нижняя
            # цена могла прийти от убитой карты или от фойла, и тогда это
            # цена другой вещи. Сумма считается по нижней -- человек может
            # и купить потрёпанную, -- но знать об этом он должен.
            "price_plain": _plain_price(prices, key, name),
            # Разложена ли цена по версиям вообще. Пустая «обычная цена» при
            # разборе значит «обычных копий в продаже нет, только фойл и
            # потрёпанные»; без разбора -- «неизвестно». Разные вещи.
            "split": (key in splits) if splits is not None
                     else bool(_plain_price(prices, key, name)),
            "cost": price * total if price else 0,
            "owned": owned.get(key, 0),
            "free": max(0, free.get(key, 0)),
            "needs": needs,
            "finishes": done,
            "side": sum(n["side"] for n in needs),
            # Карта нужна ТОЛЬКО сайдбордам: это покупка, без которой
            # колода всё равно встанет на стол.
            "side_only": bool(needs) and all(n["side"] >= n["lack"]
                                             for n in needs),
        })

    # Порядок: сперва то, что достраивает колоду целиком; потом по числу
    # колод; потом дешёвое -- за те же деньги оно двигает больше.
    #
    # Цена без рубля -- в конец своей группы, а не вперёд: «цену не знаем»
    # это не «бесплатно». Неизвестную цену ставим выше дорогой только в том
    # смысле, что о ней стоит узнать.
    rows.sort(key=lambda r: (
        0 if r["finishes"] else 1,
        # Карта, нужная только сайдборду, -- ниже: без сайда колода на стол
        # встанет, без карты мейна не встанет.
        1 if r["side_only"] else 0,
        -r["decks"],
        1 if not r["price"] else 0,
        r["cost"] or r["price"] or 10 ** 9,
        r["name"].lower(),
    ))

    # Бюджет считается по всему списку, а не по показанной сотне: набор на
    # пять тысяч не должен зависеть от того, сколько строк влезло на экран.
    pick = within_budget(rows, budget)
    chosen = set(pick.get("keys") or ())
    for row in rows:
        row["in_budget"] = row["key"] in chosen

    shown = rows[: max(1, int(limit or 200))]
    multi = [r for r in rows if r["decks"] > 1]
    return {
        "cards": shown,
        "budget": pick,
        "totals": {
            "cards": len(rows),
            "copies": sum(r["lack"] for r in rows),
            "rub": sum(r["cost"] for r in rows),
            # Сколько из них с неизвестной ценой -- чтобы сумма не выглядела
            # полной, когда она неполная.
            "no_price": len([r for r in rows if not r["price"]]),
            # Из них ещё не спрашивали вовсе -- это и есть работа для
            # кнопки «узнать цены»; остальные спрашивали, и не нашлось.
            "never_asked": len([r for r in rows
                                if not r["price"] and not r.get("asked")]),
            # Цена есть, а разбора по версиям нет: неизвестно, фойл это,
            # убитая копия или обычная карта. Дополнение цен спрашивает
            # такие заново, второй очередью.
            "no_split": len([r for r in rows
                             if r["price"] and not r.get("split")]),
            "multi_deck": len(multi),
            "finishing": len([r for r in rows if r["finishes"]]),
            "decks": len(short_by_deck),
            "decks_short": len([d for d, l in short_by_deck.items() if l]),
            "basics": basics_lack,
            # Сколько копий из списка уходит в сайдборды и сколько названий
            # нужны только им: без этих покупок колоды всё равно играют.
            "side_copies": side_lack,
            "side_only": len([r for r in rows if r["side_only"]]),
        },
    }


def spare(
    deck_store: Any,
    collection: dict[str, int],
    db: CardDB | None = None,
    prices: dict[str, Any] | None = None,
    limit: int = 200,
    keep: int = 0,
) -> dict[str, Any]:
    """Что лежит сверх всех нужд -- и сколько за это дадут.

    Обратная сторона списка покупок, и пара к нему: деньги на нужное чаще
    всего лежат тут же, в коробке. Карта считается лишней, если её больше,
    чем просят ВСЕ колоды вместе взятые, -- собранные и на бумаге. Запас
    (`keep`) оставляется сверху: человек, который играет, не хочет остаться
    без единственной копии стейпла ради двухсот рублей.

    Базовые земли сюда не попадают по той же причине, по которой не попадают
    в покупки: их не продают поштучно.
    """
    prices = prices or {}
    data = gather(deck_store, collection, db)
    owned, listed, display = data["owned"], data["listed"], data["display"]

    keep = max(0, int(keep or 0))
    rows: list[dict[str, Any]] = []
    for key, have in owned.items():
        if have <= 0:
            continue
        name = display.get(key, key)
        if normalize_name(name) in _BASIC_KEYS:
            continue
        needed = listed.get(key, 0)
        extra = have - needed - keep
        if extra <= 0:
            continue
        price = _price(prices, key, name)
        rows.append({
            "key": key,
            "name": name,
            "owned": have,
            "needed": needed,
            "spare": extra,
            "price": price,
            "worth": price * extra if price else 0,
            # Нужна ли она хоть одной колоде: «лишние три из четырёх» и
            # «лишние четыре, не нужна никому» -- разные решения.
            "in_decks": bool(needed),
        })

    # Вперёд -- то, за что дадут больше: ради этого список и читают.
    rows.sort(key=lambda r: (-(r["worth"]), -(r["spare"]), r["name"].lower()))
    shown = rows[: max(1, int(limit or 200))]
    return {
        "cards": shown,
        "totals": {
            "cards": len(rows),
            "copies": sum(r["spare"] for r in rows),
            "rub": sum(r["worth"] for r in rows),
            "no_price": len([r for r in rows if not r["price"]]),
            "unused": len([r for r in rows if not r["in_decks"]]),
        },
    }


__all__ = ["plan", "spare"]
