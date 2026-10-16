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

from .cards import CardDB, normalize_name
from .lineparse import price_in_line, qty_in_line
from .offermatch import OfferMatcher, clean_line

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

# Число, помеченное как номер карты, а не цена.
NUMBERISH = re.compile(r"(?:[#№]\s*\d+)|(?<!\d)0\d+")

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
) -> list[dict[str, Any]]:
    """Какие из наших хотелок лежат в этом складе."""
    index = wanted_index(wants)
    if not index:
        return []
    matcher = matcher or OfferMatcher(db)

    out: list[dict[str, Any]] = []
    for line in stock_lines(html):
        line_key = normalize_name(clean_line(line))
        if not line_key:
            continue
        for key, shown in index.items():
            if key not in line_key or not _word_bounded(key, line_key):
                continue
            verdict = matcher.classify(shown, line)
            if verdict.get("rejected"):
                break
            out.append({
                "want": shown,
                "line": line.strip(),
                "price": price_of(line),
                "quantity": qty_in_line(line),
                "certainty": verdict.get("certainty") or "partial",
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


def against_market(
    rows: list[dict[str, Any]],
    prices: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Насколько это дёшево против рынка.

    Мерка -- медиана по карте из кеша цен: она собрана из всех объявлений,
    которые программа видела. Честная оговорка в том, что это цена одного
    дня, и так и написано в интерфейсе.
    """
    out = []
    for row in rows:
        known = prices.get(normalize_name(row["want"])) or {}
        median = known.get("rub_median")
        price = row.get("price")
        cut = None
        if median and price:
            cut = round((median - price) / median * 100)
        out.append(dict(row, median=median, cheaper_by=cut))
    out.sort(key=lambda r: (r["cheaper_by"] is None, -(r["cheaper_by"] or 0)))
    return out


__all__ = ["post_text", "stock_lines", "price_of", "find_wanted",
           "cheapest_per_card", "against_market", "wanted_index"]
