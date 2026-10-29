"""Что ещё есть у продавца, которому вы и так платите за посылку.

План охоты говорит, у кого что брать. Но посылка стоит денег и времени
независимо от того, одна в ней карта или двадцать: если продавец уже в плане,
добрать у него остальное — бесплатно по доставке. Вопрос «а что у него ещё
есть из моего списка» до сих пор решался руками: открыть его тему, искать
глазами среди восьми тысяч строк.

**Откуда берётся его список.** У частника на topdeck все объявления ведут на
одну ссылку — тему на форуме, где он держит весь свой склад: в образце из
1212 объявлений у 122 продавцов из 131 ссылка ровно одна (у одного 87
объявлений на одну тему). Тема открыта без всякого входа в аккаунт, и
программа читает её как обычную страницу. Склад магазина так не устроен —
там каждая ссылка ведёт на свой товар, и для магазинов этот ход не работает.

**Запросы.** Одна тема — один запрос, и только по явному нажатию. Тринадцать
продавцов плана — это тринадцать запросов с той же задержкой 1.5 с, то есть
полминуты; перебирать вместо этого 250 хотелок поиском было бы и дольше, и
наглее.

**Как узнаётся своя карта.** Не «разобрать весь склад» — это тысячи строк и
чужих карт, — а найти в нём **свои хотелки**. Имя ищется по границам слов:
«Island» не должен ловить «Tropical Island», и это единственная настоящая
ловушка здесь. Дальше строку проверяет `offermatch`, который уже умеет
отличать «Burgeoning» от «Urban Burgeoning».

**Цена.** В теме она стоит где попало и без пометки «руб»: «4 Misty
Rainforest 2800 zen rus». Обычный разбор строки, рассчитанный на выдачу
поиска, видит цену у 1050 строк из 8898; здешний — у 8803. Номера карт
(`#235`, `№275`, `0278`) из рассмотрения выброшены: принять номер за цену —
старая ошибка, про которую написано в `lineparse`.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from . import pricemoves
from .cards import CardDB, normalize_name
from .lineparse import (SetIndex, parse_line, price_in_line,
                        qty_in_line)
from .offermatch import MATCH, OfferMatcher, clean_line

# Базовые земли в списке хотелок ловят половину склада: «Forest» есть в
# «Misty Rainforest», «Island» -- в «Tropical Island». Их и не покупают
# поштучно у частников.
BASIC_LANDS = {
    "forest", "island", "mountain", "plains", "swamp", "wastes",
    "snow-covered forest", "snow-covered island", "snow-covered mountain",
    "snow-covered plains", "snow-covered swamp",
    "лес", "остров", "гора", "равнина", "болото",
}

# Слишком короткое имя внутри чужой строки -- это совпадение, а не карта.
MIN_NAME = 5

# Числа, которые ценой не бывают. Проверено на девяти настоящих складах:
#
#   «4 Negate 10 M20 RU NM»        -- M20 это набор, а не двадцать рублей;
#   «4 Fog 15 C21 EN»              -- то же с C21;
#   «2 Explore 25 PLST DDO-45»     -- DDO-45 это номер в сборнике;
#   «1 Plains (#194) [eng] 30.4 р» -- номер в решётке и дробная цена.
#
# Главная ловушка здесь -- буква, прилипшая к числу: код набора у MTG почти
# всегда такой (M20, C21, 2XM, MH2, DDO-45), и без этого отсева цена
# набиралась из названия набора.
NUMBERISH = re.compile(
    r"(?:[#№]\s*\d+)"              # номер карты: #194, № 275
    r"|(?<!\d)0\d+"                # с ведущим нулём: 0278
    r"|[A-Za-zА-Яа-я]+-?\d+"       # буквы впереди: M20, C21, DDO-45
    r"|\d+[A-Za-zА-Яа-я]+"         # буквы следом: 2XM, 40k
)

# Начало и конец полезной части темы.
POST_START = "ipsType_richText"
POST_END = "ipsItemControls"


def post_text(html: str) -> str:
    """Текст первого сообщения темы -- там продавец держит свой список."""
    start = html.find(POST_START)
    if start < 0:
        return ""
    # Начинаем ПОСЛЕ закрывающей скобки тега: иначе в первую строку попадает
    # хвост его атрибутов, и количество в ней уже не прочитать -- разбор ждёт
    # число в начале строки, а находит `richText" data-controller=...`.
    opened = html.find(">", start)
    start = opened + 1 if opened > start else start
    end = html.find(POST_END, start)
    chunk = html[start:end if end > start else len(html)]
    chunk = re.sub(r"<br\s*/?>", "\n", chunk, flags=re.I)
    chunk = re.sub(r"</(?:p|div|li|tr)\s*>", "\n", chunk, flags=re.I)
    chunk = re.sub(r"<[^>]+>", "", chunk)
    # Хвост начатого, но не закрытого тега. Кусок режется по признаку
    # начала панели под сообщением, и этот признак лежит ВНУТРИ тега: в
    # кусок попадает его начало, `<div class="`. На девяти настоящих темах
    # это давало ровно одну мусорную строку в каждой -- она шла в счётчик
    # «строк в складе» и в поиск совпадений наравне с объявлениями.
    chunk = re.sub(r"<[^>]*$", "", chunk)
    return (chunk.replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&quot;", '"').replace("&#39;", "'")
            .replace("&lt;", "<").replace("&gt;", ">"))


def stock_lines(html: str) -> list[str]:
    """Строки склада: по одной на объявление, пустые выброшены."""
    return [ln.strip() for ln in post_text(html).splitlines() if ln.strip()]


def price_of(line: str) -> int | None:
    """Цена в строке склада.

    Сперва честный разбор -- там, где цена подписана «руб» или стоит в
    конце, он точнее. Если он молчит, берём наибольшее число, выбросив
    номера карт и мелочь до десяти: количество всегда меньше цены, а номер
    мы уже убрали.
    """
    text = clean_line(line)
    if not text:
        return None
    known = price_in_line(line)
    if known:
        return known
    cleaned = NUMBERISH.sub(" ", text)
    # Дробные рубли -- «30.4 руб.» -- это тридцать рублей, а не триста
    # четыре: обычный разбор выбрасывал точку и умножал цену на десять.
    fractional = re.findall(r"(?<!\d)(\d{2,6})[.,](\d{1,2})(?!\d)", cleaned)
    if fractional:
        return max(int(whole) for whole, _cents in fractional)
    numbers = [int(n) for n in re.findall(r"(?<!\d)(\d{2,6})(?!\d)", cleaned)]
    numbers = [n for n in numbers if 10 <= n <= 999999]
    return max(numbers) if numbers else None


def _word_bounded(name_key: str, line_key: str) -> bool:
    """Имя встречается как целое, а не куском чужого имени."""
    at = line_key.find(name_key)
    while at >= 0:
        before_ok = at == 0 or not line_key[at - 1].isalnum()
        after = at + len(name_key)
        after_ok = after >= len(line_key) or not line_key[after].isalnum()
        if before_ok and after_ok:
            return True
        at = line_key.find(name_key, at + 1)
    return False


def wanted_index(names: Iterable[str]) -> dict[str, str]:
    """Что ищем: нормализованное имя -> как его показать.

    Базовые земли и совсем короткие имена выброшены: они ловят чужие строки
    и топят настоящие находки.
    """
    out: dict[str, str] = {}
    for name in names:
        clean = (name or "").strip()
        if not clean:
            continue
        key = normalize_name(clean)
        if len(key) < MIN_NAME or key in BASIC_LANDS:
            continue
        out.setdefault(key, clean)
    return out


def find_wanted(
    html: str,
    wants: Iterable[str],
    db: CardDB,
    matcher: OfferMatcher | None = None,
    set_index: SetIndex | None = None,
) -> list[dict[str, Any]]:
    """Какие из наших хотелок лежат в этом складе.

    Строка разбирается целиком, а не только на цену: из неё достаются
    фойл, печать, состояние и язык. Без этого цену фойловой «Чаши» не с
    чем сравнивать -- а сравнивали, и выходила «экономия 3990 ₽» на том,
    что это просто разные карты под одним именем.
    """
    index = wanted_index(wants)
    if not index:
        return []
    matcher = matcher or OfferMatcher(db)
    set_index = set_index or SetIndex.load()

    out: list[dict[str, Any]] = []
    for line in stock_lines(html):
        line_key = normalize_name(clean_line(line))
        if not line_key:
            continue
        for key, shown in index.items():
            if key not in line_key or not _word_bounded(key, line_key):
                continue
            verdict = matcher.classify(shown, line)
            # Ответ отбраковщика лежит в поле `verdict`, а не в `rejected`:
            # того в ответе нет вовсе, и проверка на него не отбрасывала
            # ничего. На настоящих складах это дало ровно ту беду, ради
            # которой отбраковщик и писан: «Burgeoning» находился в «March
            # of Burgeoning Life» за 22 ₽ и шёл первой находкой при рынке
            # от 2074 ₽, «Darkness» -- в «Grasp of Darkness» за 10 ₽. Из
            # девяти «находок» настоящей была одна.
            if verdict.get("verdict") != MATCH or verdict.get("rejected"):
                break
            parsed = parse_line(line, set_index, shown)
            out.append({
                "want": shown,
                "line": line.strip(),
                "price": price_of(line),
                "quantity": qty_in_line(line),
                "certainty": verdict.get("certainty") or "partial",
                # Чем эта версия отличается от обычной. `foil=None` значит
                # «в строке не сказано», и это не то же самое, что «нефойл».
                "foil": parsed.foil,
                "set_code": parsed.set_code,
                "condition": parsed.condition,
                "language": parsed.language,
                "treatments": list(parsed.treatments or []),
            })
            break
    return out


def cheapest_per_card(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """По одной строке на карту -- самой дешёвой из найденных у него."""
    best: dict[str, dict[str, Any]] = {}
    for row in found:
        key = normalize_name(row["want"])
        price = row.get("price")
        if price is None:
            best.setdefault(key, row)
            continue
        have = best.get(key)
        if have is None or have.get("price") is None or price < have["price"]:
            best[key] = row
    return sorted(best.values(), key=lambda r: r["want"].lower())


# Во сколько раз медиана должна превышать минимум, чтобы считать, что под
# одним именем лежат разные вещи. Проверено на настоящем кеше: у 139 карт из
# 435 медиана втрое и выше минимума -- это фойла, старые печати и обычные
# версии в одной куче. Сравнивать с такой медианой нельзя ни с какой стороны.
WIDE_SPREAD = 3.0

# Признаки, после которых сравнение с ценой «по имени» теряет смысл: такая
# версия стоит своих денег, а кеш знает среднюю температуру по палате.
SPECIAL_CONDITIONS = {"PL", "MP", "HP", "DMG"}


def _worn(condition: str | None) -> bool:
    return (condition or "").upper() in SPECIAL_CONDITIONS


def pick_variant(row: dict[str, Any],
                 variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Та же версия карты среди записанных цен -- или None.

    Это и есть ответ на «обычная за 10 против фойлы за 4000». Цены теперь
    пишутся по версиям (печать, фойл, состояние), и фойл сравнивается с
    фойлом, а убитая копия -- с убитой. Сравнение по имени остаётся
    запасным путём: у цен, узнанных до разбора по версиям, версий нет.

    Печать учитывается, только если она у нас записана: продавец мог
    указать набор, которого в наших ценах нет, -- тогда сравниваем с
    остальными объявлениями той же обычности, а не отказываемся вовсе.
    """
    if not variants:
        return None
    foil = bool(row.get("foil"))
    worn = _worn(row.get("condition"))
    same = [v for v in variants
            if bool(v.get("foil")) == foil and _worn(v.get("condition")) == worn]
    if not same:
        return None
    code = (row.get("set_code") or "").lower()
    if code:
        by_set = [v for v in same if (v.get("set_code") or "").lower() == code]
        if by_set:
            same = by_set
    priced = [v for v in same if v.get("rub_min")]
    if not priced:
        return None
    return min(priced, key=lambda v: v["rub_min"])


def variant_label(variant: dict[str, Any]) -> str:
    """Как назвать версию человеку: «фойл · MH2 · NM»."""
    parts = []
    if variant.get("foil"):
        parts.append("фойл")
    parts.append((variant.get("set_code") or "").upper() or "печать не указана")
    if variant.get("condition"):
        parts.append(variant["condition"])
    return " · ".join(parts)


def comparable(row: dict[str, Any], known: dict[str, Any]) -> tuple[bool, str]:
    """Можно ли сравнивать эту строку с тем, что мы знаем о цене.

    Кеш цен хранит одну запись на ИМЯ карты: ключ таблицы -- name_norm, без
    печати, фойла и состояния. Поэтому сравнивать с ним можно только то,
    что само по себе обычное, и только когда разброс цен по имени узкий.
    Иначе выходит знаменитое «обычная за 10 против фойлы за 4000 -- экономия
    3990».
    """
    if row.get("foil"):
        return False, "фойл — в наших ценах он смешан с обычными"
    if row.get("treatments"):
        return False, "особая версия (%s)" % ", ".join(row["treatments"][:2])
    cond = (row.get("condition") or "").upper()
    if cond in SPECIAL_CONDITIONS:
        return False, "состояние %s — цена не рыночная" % cond
    low = known.get("rub_min")
    median = known.get("rub_median")
    if not low or not median:
        return False, "рыночной цены ещё не знаем"
    if median >= low * WIDE_SPREAD:
        return False, "цены по этому имени слишком разные"
    return True, ""


def against_market(
    rows: list[dict[str, Any]],
    prices: dict[str, dict[str, Any]],
    variants: dict[str, list[dict[str, Any]]] | None = None,
    bands: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Что известно про рыночную цену каждой находки.

    Раньше тут считался один процент -- «дешевле медианы на столько». Это
    была негодная мерка: кеш цен сведён по имени карты, и у трети карт под
    одним именем лежат вещи, отличающиеся в десятки раз. Процент выходил
    громкий и бессмысленный.

    Поэтому теперь: цифры рынка отдаются как есть (от скольких, медиана,
    по скольким объявлениям), а вывод делается только там, где его можно
    сделать честно -- и называется он прямо.

    Второй вопрос -- «дёшево ли это по меркам самой карты». Рыночная цена
    отвечает только про сегодня: 180 ₽ за карту, которая весь сентябрь
    стоила 170, -- не находка, а обычный вторник. Если замеров хватает
    (три и больше), к строке добавляется коридор, в котором цена ходила,
    и вывод из него. Замеров мало -- поле пустое, и никто ничего не
    обещает.
    """
    out = []
    for row in rows:
        key = normalize_name(row["want"])
        known = prices.get(key) or {}
        band = pricemoves.unusual(row.get("price"), (bands or {}).get(key))
        low = known.get("rub_min")
        median = known.get("rub_median")
        price = row.get("price")

        # Сперва -- та же версия: фойл с фойлом, убитая с убитой. Это
        # прямой ответ на «обычная за 10 против фойлы за 4000»: сравнение
        # по имени складывало их в одну цифру, и отказ сравнивать был
        # меньшим злом, а не ответом.
        same = pick_variant(row, (variants or {}).get(key) or [])
        if same and price:
            seen = same["rub_min"]
            top = same.get("rub_max") or seen
            if price < seen:
                verdict = "below-floor"
                cut = round((seen - price) / seen * 100)
            elif price <= top:
                verdict = "in-range"
                cut = None
            else:
                verdict = "above"
                cut = -round((price - top) / top * 100)
            out.append(dict(
                row, median=median, market_min=seen, market_max=top,
                market_offers=same.get("offers"),
                verdict=verdict, why="", cheaper_by=cut,
                basis="version", version=variant_label(same), band=band,
            ))
            continue

        fit, why = comparable(row, known)
        verdict, cut = "unknown", None
        if price and low:
            if not fit:
                verdict = "incomparable"
            elif price < low:
                verdict = "below-floor"
                cut = round((low - price) / low * 100)
            elif median and price <= median:
                verdict = "in-range"
            else:
                verdict = "above"
                cut = -round((price - (median or low)) / (median or low) * 100)
        elif not price:
            verdict = "no-price"

        out.append(dict(
            row,
            median=median,
            market_min=low,
            market_offers=known.get("offers"),
            verdict=verdict,
            why=why,
            cheaper_by=cut,
            basis="name",
            version="",
            band=band,
        ))

    # Вперёд -- то, что дешевле всего виденного, потом «в рынке», потом
    # несравнимое, и в самом конце то, что дороже рынка.
    order = {"below-floor": 0, "in-range": 1, "incomparable": 2,
             "unknown": 3, "no-price": 4, "above": 5}
    # Внутри каждой кучки вперёд идёт то, что дёшево не только сегодня:
    # для несравнимых строк -- фойлов, особых версий -- это единственное,
    # что о цене вообще можно сказать.
    out.sort(key=lambda r: (order.get(r["verdict"], 9),
                            0 if (r.get("band") or {}).get("verdict") == "cheap" else 1,
                            -(r["cheaper_by"] or 0), r["want"].lower()))
    return out


def version_coverage(
    wants: Iterable[str],
    prices: dict[str, dict[str, Any]],
    split: set[str] | None = None,
) -> dict[str, int]:
    """На скольких ценах сравнение честное, а на скольких грубое.

    Цена, записанная одним числом на имя, смешивает фойл, убитую копию и
    обычную карту -- разница между ними бывает в десятки раз. Сравнение с
    таким числом на экране выглядит точно так же, как сравнение версии с
    версией, и это единственное место, где разницу можно назвать вслух.

    Считаются только те имена, у которых цена вообще есть: «не спрашивали»
    -- это не грубое сравнение, а его отсутствие.
    """
    known = set(split or ())
    priced = [normalize_name(w) for w in wants
              if (prices.get(normalize_name(w)) or {}).get("rub_min") is not None]
    return {"priced": len(priced),
            "split": sum(1 for key in priced if key in known)}


__all__ = ["post_text", "stock_lines", "price_of", "find_wanted",
           "cheapest_per_card", "against_market", "comparable", "pick_variant",
           "variant_label", "wanted_index", "version_coverage",
           "WIDE_SPREAD"]
