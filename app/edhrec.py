"""What people actually put in decks with a given commander.

EDHREC publishes its commander pages as plain JSON -- json.edhrec.com/pages/
commanders/<slug>.json -- so there is nothing to crawl and nothing to scrape.
One request per commander gives every list the site shows: high synergy cards,
top cards, and then a list per card type.

Per card it reports:

    num_decks        decks of THIS commander that run the card
    potential_decks  decks of this commander in total
    synergy          how much more often it appears here than in decks generally

`num_decks / potential_decks` is the number a deckbuilder actually wants ("83%
of Ur-Dragon decks run this"), and `synergy` separates cards that are here
because of the commander from cards that are simply good everywhere -- Sol Ring
is in everything, Dragon Tempest is not.

Politeness and caching: this is someone else's free service, so a fetched page
is written to disk and reused. A commander's statistics move by fractions of a
percent per week, so the cache lives for two weeks and can be refreshed on
demand from the interface.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any

from .storage import data_dir

BASE = "https://json.edhrec.com/pages/commanders/%s.json"
USER_AGENT = "mtg-hunter/1.0 (local deckbuilding tool)"
TIMEOUT = 45
CACHE_TTL = 14 * 24 * 3600  # two weeks
MIN_INTERVAL = 1.0  # seconds between requests to edhrec

# Order the site itself uses, and the names we show. Anything we do not know
# about still comes through -- with its own header -- rather than disappearing.
SECTION_TITLES = {
    "highsynergycards": "Высокая синергия с командиром",
    "topcards": "Чаще всего берут",
    "gamechangers": "Game changers",
    "newcards": "Новинки",
    "creatures": "Существа",
    "instants": "Мгновенные заклинания",
    "sorceries": "Волшебства",
    "utilityartifacts": "Артефакты",
    "enchantments": "Чары",
    "planeswalkers": "Планисвокеры",
    "battles": "Битвы",
    "utilitylands": "Земли",
    "lands": "Земли",
    "manaartifacts": "Мана-артефакты",
    "battlelands": "Земли",
}

# Lists that are about the commander's own printing rather than cards to add.
SKIP_TAGS = {"commanders", "similar"}


class EdhrecError(RuntimeError):
    """Something went wrong talking to edhrec, said in Russian for the UI."""


def slug(name: str) -> str:
    """EDHREC's page slug for a card name.

    "Miirym, Sentinel Wyrm" -> miirym-sentinel-wyrm
    "Atraxa, Praetors' Voice" -> atraxa-praetors-voice
    A two-faced commander is filed under its front face.
    """
    text = (name or "").split("//")[0].strip().lower()
    # Accented letters (Márton, Sásaya) are filed without the accents.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("&", " and ")
    text = re.sub(r"[’']", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _cache_path(name: str) -> str:
    folder = os.path.join(data_dir(), "edhrec")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, slug(name) + ".json")


def _read_cache(path: str, ttl: int) -> dict[str, Any] | None:
    try:
        age = time.time() - os.path.getmtime(path)
        if ttl >= 0 and age > ttl:
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class RecClient:
    """One request per commander, cached on disk."""

    def __init__(self, ttl: int = CACHE_TTL) -> None:
        self.ttl = ttl
        self._last = 0.0

    def _throttle(self) -> None:
        wait = MIN_INTERVAL - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def fetch(self, name: str, refresh: bool = False) -> dict[str, Any]:
        path = _cache_path(name)
        if not refresh:
            cached = _read_cache(path, self.ttl)
            if cached is not None:
                cached["_cached"] = True
                cached["_fetched"] = os.path.getmtime(path)
                return cached

        url = BASE % slug(name)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        self._throttle()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = json.load(resp)
        except urllib.error.HTTPError as exc:
            # An unknown commander comes back as 403, not 404 -- but so would a
            # block, so the message says both rather than guessing.
            if exc.code in (403, 404):
                # Stale data beats no data when the page simply moved.
                stale = _read_cache(path, -1)
                if stale is not None:
                    stale["_cached"] = True
                    stale["_stale"] = True
                    stale["_fetched"] = os.path.getmtime(path)
                    return stale
                raise EdhrecError(
                    "EDHREC не отдал страницу для «%s» (%d). Либо такого "
                    "командира у него нет — проверьте имя, — либо он "
                    "ограничил доступ." % (name, exc.code)
                ) from exc
            raise EdhrecError("EDHREC ответил ошибкой %s" % exc.code) from exc
        except Exception as exc:  # noqa: BLE001
            stale = _read_cache(path, -1)
            if stale is not None:
                stale["_cached"] = True
                stale["_stale"] = True
                stale["_fetched"] = os.path.getmtime(path)
                return stale
            raise EdhrecError("не удалось получить данные EDHREC: %s" % exc) from exc

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(raw, fh, ensure_ascii=False)
        except OSError:
            pass  # a cache we cannot write is not a reason to fail
        raw["_cached"] = False
        raw["_fetched"] = time.time()
        return raw


def _section_title(tag: str, header: str) -> str:
    if tag in SECTION_TITLES:
        return SECTION_TITLES[tag]
    return header or tag or "Прочее"


def parse(raw: dict[str, Any]) -> dict[str, Any]:
    """Turn the site's payload into what we actually use."""
    container = raw.get("container") or {}
    payload = container.get("json_dict") or {}
    card = payload.get("card") or {}
    total = int(card.get("num_decks") or 0)

    sections = []
    for lst in payload.get("cardlists") or []:
        tag = (lst.get("tag") or "").strip()
        if tag in SKIP_TAGS:
            continue
        cards = []
        for view in lst.get("cardviews") or []:
            name = (view.get("name") or "").strip()
            if not name:
                continue
            decks = int(view.get("num_decks") or 0)
            pool = int(view.get("potential_decks") or 0) or total
            cards.append({
                "name": name,
                "decks": decks,
                "pool": pool,
                # The number a builder reads first: how usual this card is here.
                "share": round(decks / pool, 4) if pool else None,
                "synergy": view.get("synergy"),
            })
        if cards:
            sections.append({
                "tag": tag,
                "title": _section_title(tag, lst.get("header") or ""),
                "cards": cards,
            })

    return {
        "commander": {
            "name": card.get("name") or "",
            "decks": total,
            "type_line": card.get("type_line") or "",
            "color_identity": card.get("color_identity") or [],
            "salt": card.get("salt"),
        },
        "sections": sections,
        "cached": bool(raw.get("_cached")),
        "stale": bool(raw.get("_stale")),
        "fetched": raw.get("_fetched"),
    }


def recommendations(name: str, refresh: bool = False,
                    client: RecClient | None = None) -> dict[str, Any]:
    return parse((client or RecClient()).fetch(name, refresh=refresh))
