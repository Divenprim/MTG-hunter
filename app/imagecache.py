"""Local card-image proxy with persistent disk cache.

The browser never talks to an external image host directly.  A successful image
is cached under data/image-cache and is then available offline forever.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
import sqlite3

import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "image-cache"
USER_AGENT = "mtg-hunter/1.19.4"
TIMEOUT = (5, 20)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "image/*"})


def _safe_size(size: str) -> str:
    return size if size in {"small", "normal"} else "small"


def _cache_path(card_id: str, size: str, face: int | None) -> Path:
    key = "%s|%s|%s" % (card_id, size, "" if face is None else face)
    name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".img"
    return CACHE_DIR / name


def _row(database: Any, card_id: str, size: str, face: int | None) -> tuple[str | None, str]:
    column = "image_normal" if size == "normal" else "image_small"
    if face is not None:
        row = database.conn.execute(
            "SELECT %s AS image_url, name FROM card_faces "
            "WHERE card_id = ? AND face_index = ? LIMIT 1" % column,
            (card_id, face),
        ).fetchone()
        if row:
            return row["image_url"], row["name"] or "Magic card"
    row = database.conn.execute(
        "SELECT %s AS image_url, name FROM cards WHERE id = ? LIMIT 1" % column,
        (card_id,),
    ).fetchone()
    if row:
        return row["image_url"], row["name"] or "Magic card"
    return None, "Magic card"


def _gatherer_url(database: Any, card_id: str) -> str | None:
    try:
        row = database.conn.execute(
            "SELECT multiverse_id FROM card_external_ids "
            "WHERE card_id = ? AND multiverse_id IS NOT NULL LIMIT 1",
            (card_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row["multiverse_id"]:
        return None
    return (
        "https://gatherer.wizards.com/Handlers/Image.ashx"
        "?type=card&multiverseid=%s" % row["multiverse_id"]
    )


def _candidates(database: Any, card_id: str, upstream: str | None, size: str) -> list[str]:
    out: list[str] = []
    if upstream:
        out.append(upstream)

    # Independent provider/domain. Gatherer does not have every printing, so
    # it is a fallback rather than the primary source.
    gatherer = _gatherer_url(database, card_id)
    if gatherer:
        out.append(gatherer)

    # Different Scryfall host/path: useful if only cards.scryfall.io is blocked.
    out.append(
        "https://api.scryfall.com/cards/%s?format=image&version=%s" % (card_id, size)
    )
    return list(dict.fromkeys(out))


def _download(url: str) -> tuple[bytes, str] | None:
    try:
        resp = _SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        content_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            return None
        data = resp.content
        if len(data) < 512:
            return None
        return data, content_type
    except requests.RequestException:
        return None


def get_image(database: Any, card_id: str, size: str = "small",
              face: int | None = None) -> tuple[bytes, str, str]:
    """Return (bytes, media_type, source).

    source is cache/network/placeholder and is exposed as a response header for
    diagnostics.
    """
    size = _safe_size(size)
    path = _cache_path(card_id, size, face)
    if path.exists():
        try:
            data = path.read_bytes()
            if data:
                return data, "image/jpeg", "cache"
        except OSError:
            pass

    upstream, name = _row(database, card_id, size, face)
    for url in _candidates(database, card_id, upstream, size):
        got = _download(url)
        if not got:
            continue
        data, media_type = got
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError:
            pass
        return data, media_type, "network"

    # A valid image response means broken networks never leave an ugly browser
    # icon or break layout.  SVG contains no external resources.
    safe_name = (
        name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;")
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="488" height="680" viewBox="0 0 488 680">
<rect width="488" height="680" rx="28" fill="#20242b"/>
<rect x="22" y="22" width="444" height="636" rx="20" fill="#303640" stroke="#6b7280" stroke-width="3"/>
<text x="244" y="302" text-anchor="middle" fill="#e5e7eb" font-family="Arial,sans-serif" font-size="22">{safe_name}</text>
<text x="244" y="350" text-anchor="middle" fill="#9ca3af" font-family="Arial,sans-serif" font-size="18">изображение недоступно</text>
<text x="244" y="384" text-anchor="middle" fill="#9ca3af" font-family="Arial,sans-serif" font-size="16">данные карты доступны офлайн</text>
</svg>""".encode("utf-8")
    return svg, "image/svg+xml", "placeholder"


def cache_stats() -> dict[str, int]:
    try:
        files = [p for p in CACHE_DIR.iterdir() if p.is_file()]
    except OSError:
        files = []
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files if p.exists()),
    }
