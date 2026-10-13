"""Русская фраза → запрос на языке программы.

Нужно ровно для одного места: пустой выдачи поиска.

Замер показал, что «поиск по-русски ничего не находит» — неточность. По
русским **именам** он ищет и находит: «Лес» даёт 60 карт, «Погребальный» —
три. Пусто выходит на другом: «зелёная рампа» — это не имя карты, а описание
того, что человек хочет, и ни одна карта так не называется. Нужное находится
запросом `otag:ramp c:g`, но чтобы его набрать, надо уже знать язык.

Поэтому: когда не нашлось ничего, а в запросе русские слова — попробовать
собрать из них запрос. Словарь не выдумывается здесь, он передаётся снаружи:
это те же списки, по которым нарисована панель фильтров, и расходиться им
нечему.

Что не перевелось — названо вслух. Молча выкинуть слово значит показать
человеку выдачу не по тому, что он просил, и не сказать об этом.

Наружу отсюда не уходит ни одного запроса.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Цвет -- это не назначение карты, поэтому отдельным списком. Основы, а не
# слова целиком: «зелёная», «зелёные», «зелёный» -- одно и то же.
COLOURS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("бел",), "W"),
    (("син", "голуб"), "U"),
    (("черн", "чёрн"), "B"),
    (("красн",), "R"),
    (("зелен", "зелён"), "G"),
    (("бесцвет",), "C"),
)

# Слова, которые ничего не значат сами по себе и не должны попадать в
# «не понял»: их говорят между делом. Из разбора их не выбрасываем -- «карт»
# стоит внутри подписи «добор карт», и выкинув его заранее, мы бы перестали
# понимать саму подпись.
NOISE = frozenset((
    "карты", "карта", "карт", "карточки", "мне", "нужно", "нужна", "нужны",
    "хочу", "найди", "ищу", "поиск", "что", "чтобы", "для", "или", "под",
    "это", "как", "все", "всё", "самые", "самый", "дешевые", "дешёвые",
))

WORD = re.compile(r"[0-9a-zA-Zа-яёА-ЯЁ]+", re.UNICODE)


def _norm(word: str) -> str:
    return word.lower().replace("ё", "е")


def _stem(word: str) -> str:
    """Грубая основа: русский склоняется, а запрос печатают как придётся.

    «рампа», «рампу», «рампой» -- одно слово. Отрезаем два знака, но не
    короче четырёх: на трёх «мел» поймало бы «мельницу» и «мелочь».
    """
    word = _norm(word)
    return word[:max(4, len(word) - 2)]


def _same(a: str, b: str) -> bool:
    """Два слова об одном, если основа одного начинает другое."""
    sa, sb = _stem(a), _stem(b)
    return sa.startswith(sb) or sb.startswith(sa)


def _label_hit(label: str, words: list[str]) -> list[str]:
    """Какие слова запроса покрыли эту подпись.

    Подпись бывает из нескольких слов («кража существ», «масс-удаление»), и
    засчитывается она только целиком: «кража» одна -- это ещё не «кража
    существ», в словаре есть и «смена контроля».
    """
    need = [w for w in WORD.findall(label) if len(w) > 2]
    if not need:
        return []
    used: list[str] = []
    for part in need:
        hit = next((w for w in words if _same(w, part)), None)
        if hit is None:
            return []
        used.append(hit)
    return used


def translate(q: str,
              themes: Iterable[tuple[str, str]],
              keywords: Iterable[tuple[str, str]]) -> dict[str, Any] | None:
    """Собрать запрос из русских слов. None -- если собирать не из чего.

    `themes` и `keywords` -- пары (подпись по-русски, значение), те же, что
    отданы панели фильтров.
    """
    if not q or not re.search(r"[а-яёА-ЯЁ]", q):
        return None
    words = WORD.findall(q)
    if not words:
        return None

    taken: set[str] = set()
    parts: list[dict[str, str]] = []

    # Цвет -- первым: он однословный, и «зелёная» не должна достаться метке.
    colours: list[str] = []
    for stems, letter in COLOURS:
        hit = next((w for w in words
                    if _norm(w) not in taken
                    and any(_norm(w).startswith(_norm(s)) for s in stems)), None)
        if hit is None:
            continue
        taken.add(_norm(hit))
        colours.append(letter)
        parts.append({"term": "c:" + letter.lower(), "what": hit.lower()})

    # Длинные подписи -- раньше коротких: «масс-удаление» должно выиграть у
    # «удаления», иначе второе слово осядет в «не понял».
    slugs: list[str] = []
    for label, slug in sorted(themes, key=lambda p: -len(p[0])):
        used = _label_hit(label, words)
        if not used or any(_norm(w) in taken for w in used):
            continue
        taken.update(_norm(w) for w in used)
        slugs.append(slug)
        parts.append({"term": "otag:" + slug, "what": label})

    kws: list[str] = []
    for label, keyword in sorted(keywords, key=lambda p: -len(p[0])):
        used = _label_hit(label, words)
        if not used or any(_norm(w) in taken for w in used):
            continue
        taken.update(_norm(w) for w in used)
        kws.append(keyword)
        parts.append({"term": "kw:" + keyword, "what": label})

    if not parts:
        return None

    # Собираем в том порядке, в каком это читается: цвет, назначение, слова.
    terms = (["c:" + "".join(colours).lower()] if colours else [])
    terms += ["otag:" + s for s in slugs]
    if kws:
        terms.append("kw:" + ",".join(kws))

    rest = [w for w in words
            if _norm(w) not in taken and _norm(w) not in NOISE]
    return {
        "query": " ".join(terms),
        "parts": parts,
        # Слова, для которых в словаре ничего нет. Их не выкидываем молча:
        # запрос без них отвечает не на тот вопрос, и сказать об этом честнее,
        # чем показать выдачу и промолчать.
        "unknown": rest,
    }
