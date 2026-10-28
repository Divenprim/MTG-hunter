"""Что цены сделали с прошлого раза и дождались ли вы своей.

Цену карты программа узнаёт по частям: что-то спросили в колоде, что-то в
окне карты, остальное понемногу дополняет фоновая очередь. Каждый такой
ответ записывается замером, и рядом с нынешней ценой остаётся прошлая. До
сих пор из этого было видно только одно число в одном окне -- «70 ₽ (было
90)», -- и, чтобы заметить, что карта подешевела, надо было угадать, в
какое окно заглянуть.

Здесь из тех же замеров собираются две вещи, ради которых их и копили:

  * **что изменилось** -- одним списком, по всем ценам сразу, вперёд то,
    что сильнее подешевело;
  * **дождались ли** -- у карты в избранном может стоять цена, по которой
    человек готов её купить, и дальше ответ даёт программа, а не память.

Про «обычный уровень» цены здесь считается ровно то, что можно: по трём
замерам видно, что карта ходила от 170 до 220, и 180 сегодня -- не
находка. По двум замерам не видно ничего, и тогда здесь молчат, а не
выдают разницу двух дней за размах рынка.
"""

from __future__ import annotations

from typing import Any, Iterable

from .cards import normalize_name

# Насколько близко к цели, чтобы сказать «почти»: цель 500, цена 540 --
# стоит знать, цена 900 -- нет.
NEAR_GOAL = 0.15

# Ниже скольких процентов от обычного низа цена называется необычно
# дешёвой. Пять процентов -- это разница округления у продавца, а не
# повод бежать покупать.
UNUSUAL = 0.05


def goals(folders: Iterable[dict[str, Any]],
          prices: dict[str, dict[str, Any]],
          bands: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Карты с назначенной ценой и то, что с ними сейчас.

    Папки берутся как есть из избранного: цель живёт у карточки, а не
    отдельным списком, потому что избранное и есть «хочу купить». Одна и
    та же карта может лежать в двух папках с разными целями -- это два
    разных желания (фойл в одной, игровая копия в другой), и складывать
    их в одно нельзя.
    """
    bands = bands or {}
    hit, near, waiting, unknown = [], [], [], []
    for folder in folders or ():
        for card in folder.get("cards") or ():
            target = int(card.get("target") or 0)
            if target <= 0:
                continue
            key = normalize_name(card.get("name") or "")
            price = (prices.get(key) or {}).get("rub_min")
            row = {
                "name": card.get("name"),
                "folder": folder.get("name"),
                "folder_id": folder.get("id"),
                "card_id": card.get("id"),
                "quantity": int(card.get("quantity") or 1),
                "target": target,
                "rub": price,
                "checked_at": (prices.get(key) or {}).get("checked_at"),
                "band": bands.get(key) or {},
            }
            if price is None:
                unknown.append(row)
            elif price <= target:
                row["under"] = target - price
                hit.append(row)
            elif price <= target * (1 + NEAR_GOAL):
                row["over"] = price - target
                near.append(row)
            else:
                row["over"] = price - target
                waiting.append(row)
    hit.sort(key=lambda r: -r["under"])
    near.sort(key=lambda r: r["over"])
    waiting.sort(key=lambda r: r["over"])
    unknown.sort(key=lambda r: (r["name"] or "").lower())
    return {"hit": hit, "near": near, "waiting": waiting, "unknown": unknown,
            "goals": len(hit) + len(near) + len(waiting) + len(unknown)}


def unusual(price: int | None, band: dict[str, Any] | None) -> dict[str, Any]:
    """Дёшево ли это по меркам самой карты, а не сегодняшнего дня.

    Ответ нужен там, где уже сказано «на рынке от 180 ₽»: человек видит
    сегодняшний низ и не знает, низко это или так всегда. Если замеров
    хватает, добавляется второе число -- за сколько эту карту видели
    дешевле всего и как давно, -- и вывод делается только когда разница
    больше округления.
    """
    if not price or not band or not band.get("points"):
        return {}
    low, high = band.get("low"), band.get("high")
    if not low:
        return {}
    out = {"points": band["points"], "low": low, "high": high,
           "since": band.get("since"), "until": band.get("until")}
    if price < low * (1 - UNUSUAL):
        out["verdict"] = "cheap"
    elif high and price > high * (1 + UNUSUAL):
        out["verdict"] = "dear"
    elif low and high and high > low:
        # Цена внутри знакомого коридора. Сказать «обычно» можно, а
        # «выгодно» -- нет.
        out["verdict"] = "usual"
    else:
        out["verdict"] = "flat"
    return out


def digest(moves: list[dict[str, Any]],
           goal_state: dict[str, Any] | None = None,
           show: int = 6) -> dict[str, Any]:
    """Сводка для экрана: сколько подешевело, сколько подорожало, что из этого.

    Списки режутся: на экране нужны те несколько строк, ради которых
    смотрят, а не все четыреста. Числа при этом считаются по всему, что
    есть, -- иначе «подешевело 5» значило бы «показано 5».
    """
    cheaper = [m for m in moves if m["move"] < 0]
    dearer = [m for m in moves if m["move"] > 0]
    state = goal_state or {}
    return {
        "cheaper": len(cheaper),
        "dearer": len(dearer),
        "down": cheaper[:show],
        "up": sorted(dearer, key=lambda m: -m["move"])[:show],
        "hit": (state.get("hit") or [])[:show],
        "goals": state.get("goals") or 0,
        "hits": len(state.get("hit") or []),
        "near": len(state.get("near") or []),
    }


__all__ = ["goals", "unusual", "digest", "NEAR_GOAL", "UNUSUAL"]
