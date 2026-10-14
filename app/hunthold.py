"""Память об охоте: что найдено, и как это пережить перезапуск.

Жило в `main.py` среди трёх с лишним тысяч строк ручек. Это не ручка, а
состояние: словарь последних охот в памяти процесса и один файл рядом с
коллекцией, из которого охота собирается обратно, если в памяти её уже нет.

Почему это вообще нужно, написано ниже у каждой части. Коротко: охота стоит
полутора секунд запроса на пачку имён, и терять её от закрытия вкладки значит
снова дёргать чужой сайт ради того, что уже спрашивали.

Наружу отсюда не уходит ни одного запроса: здесь только память и свой файл.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import fields as dataclass_fields
from typing import Any

from . import storage
from .hunt import SELLER_FEE_DEFAULT, Candidate, Want
from .lineparse import ParsedLine
from .storage import load_json, save_json
from .topdeck import Offer, Seller

# A hunt costs a 1.5s request per batch, so the offers it fetched are kept in
# memory. Changing your mind about a card then rebuilds the plan instantly and
# without touching topdeck again. Only the few most recent hunts are held.
# Последняя охота на диске. Поиск ходит к чужому сайту по полторы секунды на
# запрос, и программа сама предупреждает, что это вежливость, а не медлительность.
# Терять такой результат от закрытия вкладки нельзя: повторить его -- значит
# снова дёргать магазин ради того, что уже спрашивали. Поэтому он кладётся
# рядом с остальными данными и возвращается при следующем открытии.
# Кладётся туда же, куда коллекция и колоды, а не в папку репозитория: это
# данные человека, и `MTGH_DATA_DIR` обязана их уводить -- иначе тесты пишут
# в настоящие.
def last_hunt_file() -> str:
    return os.path.join(storage.data_dir(), "last-hunt.json")

_HUNT_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_HUNT_CACHE_LOCK = threading.Lock()
HUNT_CACHE_KEEP = 4


def _rebuild_hunt(kept: dict[str, Any]) -> dict[str, Any] | None:
    """Собрать охоту обратно из сохранённого ответа.

    Без этого прошлый поиск открывался картинкой: план на экране есть, а любая
    кнопка решения отвечает «этот поиск больше не в памяти» -- и человека
    отправляет ровно туда, откуда его уводили, спрашивать магазин заново.

    Пересобирать есть из чего: в ответе лежит каждое объявление целиком, слово
    в слово, как его написал продавец. Ключ объявления считается из тех же
    полей, поэтому отказы и закрепления узнают свои предложения. Наружу при
    этом не ходим ни разу -- в том и смысл.
    """
    answer = (kept or {}).get("answer") or {}
    rows = answer.get("candidates")
    if not rows:
        return None

    wants = [
        Want(name=w.get("name") or "", quantity=int(w.get("quantity") or 0),
             set_code=w.get("set_code"), section=w.get("section") or "main")
        for w in answer.get("wants") or []
        if w.get("name")
    ]

    known = {f.name for f in dataclass_fields(ParsedLine)}
    candidates = []
    for d in rows:
        raw = d.get("seller") or {}
        seller = Seller(name=raw.get("name") or "", kind=raw.get("kind") or "user",
                        id=raw.get("id"), city=raw.get("city"), refs=raw.get("refs"))
        offer = Offer(
            name=d.get("name") or "", eng_name=d.get("eng_name") or "",
            rus_name=d.get("rus_name") or "", qty=int(d.get("qty") or 0),
            cost=int(d.get("cost") or 0), seller=seller,
            source=d.get("source") or "", url=d.get("url") or "",
            stamp=d.get("stamp") or "", line=d.get("line") or "",
            city=d.get("city"))
        parsed = ParsedLine(**{k: v for k, v in (d.get("parsed") or {}).items()
                               if k in known})
        cand = Candidate(offer=offer, parsed=parsed,
                         want=d.get("want") or offer.eng_name or offer.name)
        cand.printing = d.get("printing") or None
        cand.rejected = d.get("rejected")
        cand.certainty = d.get("certainty") or "partial"
        cand.gaps = list(d.get("gaps") or [])
        cand.unmatched = bool(d.get("unmatched"))
        cand.price_dispute = d.get("price_dispute")
        cand.qty_in_line = d.get("qty_in_line")
        cand.qty_dispute = d.get("qty_dispute")
        cand.price_in_line = d.get("price_in_line")
        cand.refused = d.get("refused")
        candidates.append(cand)

    if not wants:
        return None
    return {
        "wants": wants,
        "candidates": candidates,
        "strategy": kept.get("strategy") or "sellers",
        "seller_fee": _seller_fee(kept.get("seller_fee", SELLER_FEE_DEFAULT)),
    }


def _held_hunt(hunt_id: str) -> dict[str, Any] | None:
    """Охота по её номеру: из памяти, а если там нет -- с диска.

    Четыре охоты назад или вчера до перезапуска -- для человека это один и тот
    же случай: на экране его прошлый поиск, и он хочет им пользоваться. Пока
    сохранённый ответ тот самый, поднимаем его в память один раз и дальше
    работаем как обычно.
    """
    with _HUNT_CACHE_LOCK:
        held = _HUNT_CACHE.get(hunt_id)
    if held:
        return held

    kept = load_json(last_hunt_file(), None) or {}
    if ((kept.get("answer") or {}).get("hunt_id")) != hunt_id:
        return None
    built = _rebuild_hunt(kept)
    if not built:
        return None
    with _HUNT_CACHE_LOCK:
        _HUNT_CACHE[hunt_id] = built
        while len(_HUNT_CACHE) > HUNT_CACHE_KEEP:
            _HUNT_CACHE.popitem(last=False)
    return built


def _seller_fee(value: Any) -> int:
    """A fee out of range is a typo, not an instruction."""
    try:
        return max(0, min(int(value), 5000))
    except (TypeError, ValueError):
        return SELLER_FEE_DEFAULT


def _remember_hunt(wants: list[Want], candidates: list[Any], strategy: str,
                   seller_fee: int = SELLER_FEE_DEFAULT) -> str:
    hunt_id = uuid.uuid4().hex[:12]
    with _HUNT_CACHE_LOCK:
        _HUNT_CACHE[hunt_id] = {
            "wants": wants,
            "candidates": candidates,
            "strategy": strategy,
            "seller_fee": seller_fee,
        }
        while len(_HUNT_CACHE) > HUNT_CACHE_KEEP:
            _HUNT_CACHE.popitem(last=False)
    return hunt_id
