"""Узнать карту по картинке: отпечатки артов и поиск по ним.

Задача -- та же, что у ManaBox: навёл камеру, и программа сказала, что это за
карта. Решается это не распознаванием текста, а перцептивным хешем арта.

Почему не OCR. Имя на карте написано шрифтом, который камера видит под углом,
в бликах и мелко; языков два (русский и английский), и у половины русских карт
имя вообще не совпадает с английским. Арт же у одной печати один и тот же на
любом языке -- русская «Спираль Роста» и английская Growth Spiral одной печати
это одна картинка. Хеш арта не знает про языки, и это ровно то, что нужно
рынку, где половина карт русская.

Как это работает:

  * у каждой печати берётся картинка со Scryfall (small, 146 px -- этого с
    запасом хватает: хеш считается по 32x32);
  * из неё вырезается арт -- всегда одна и та же доля от карты, потому что
    сравнивать надо одинаковые области, а не «настоящий арт»: рамка у старых
    карт другая, но доля остаётся долей;
  * из вырезки считается pHash (DCT 32x32, младшие 8x8 без постоянной
    составляющей) и dHash (яркость соседних пикселей). Два хеша ошибаются
    по-разному: pHash плывёт на бликах, dHash -- на размытии;
  * при поиске берётся расстояние Хэмминга до всех отпечатков сразу (numpy,
    сотня тысяч чисел -- это доли миллисекунды).

Отпечатки лежат отдельным файлом (data/art_hashes.sqlite), а не в базе карт:
собираются они часами, а базу карт пересобирают.
"""

from __future__ import annotations

import io
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable

import requests

from .cards import DATA_DIR, DB_PATH, connect as cards_connect

# Pillow и numpy нужны только сканеру, а программа должна запускаться и без
# него: у того, кто обновился распаковкой архива поверх старой папки, их ещё
# нет, и падать из-за этого всем остальным нельзя.
try:
    import numpy as np
    from PIL import Image
    DEPS_OK = True
    DEPS_NOTE = ""
except ImportError as exc:                               # pragma: no cover
    np = None                                            # type: ignore[assignment]
    Image = None                                         # type: ignore[assignment]
    DEPS_OK = False
    DEPS_NOTE = ("сканеру нужны Pillow и numpy: "
                 ".venv/Scripts/python.exe -m pip install -r requirements.txt "
                 "(%s)" % exc)

ART_DB_PATH = os.path.join(DATA_DIR, "art_hashes.sqlite")
USER_AGENT = "mtg-hunter/1.9.6 (local personal tool)"

# Доля карты, занятая артом. Одинаковая для всех: важно не попасть ровно в
# рамку арта, а вырезать у эталона и у снимка одно и то же место.
ART_BOX = (0.08, 0.10, 0.92, 0.47)
HASH_SIDE = 32          # сторона картинки, по которой считается DCT
HASH_BITS = 8           # сторона квадрата младших частот

Progress = Callable[[str], None]

SCHEMA = """
CREATE TABLE IF NOT EXISTS art (
    card_id           TEXT PRIMARY KEY,
    oracle_id         TEXT,
    name              TEXT,
    set_code          TEXT,
    collector_number  TEXT,
    phash             INTEGER,
    dhash             INTEGER
);
CREATE INDEX IF NOT EXISTS idx_art_oracle ON art(oracle_id);

-- Печати, по которым картинка не пришла. Нужны, чтобы повторный запуск не
-- ломился в те же битые ссылки.
CREATE TABLE IF NOT EXISTS failed (
    card_id  TEXT PRIMARY KEY,
    reason   TEXT,
    at       TEXT
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: str = ART_DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------------------- #
# Хеши
# --------------------------------------------------------------------------- #

def _dct_matrix(n: int) -> "np.ndarray":
    """Матрица DCT-II. Своя, чтобы не тащить scipy ради одной формулы."""
    k = np.arange(n).reshape((n, 1))
    i = np.arange(n).reshape((1, n))
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n))
    m[0] *= np.sqrt(0.5)
    return m * np.sqrt(2.0 / n)


_DCT_CACHE: dict[int, Any] = {}


def _dct(n: int = HASH_SIDE) -> "np.ndarray":
    """Считается один раз и живёт до конца: матрица 32x32 одна на всех."""
    if n not in _DCT_CACHE:
        _DCT_CACHE[n] = _dct_matrix(n)
    return _DCT_CACHE[n]


def _bits_to_int(bits: np.ndarray) -> int:
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def crop_art(img: "Image.Image") -> "Image.Image":
    w, h = img.size
    left, top, right, bottom = ART_BOX
    return img.crop((int(w * left), int(h * top), int(w * right), int(h * bottom)))


def phash(img: "Image.Image") -> int:
    """Перцептивный хеш: какие низкие частоты картинки выше среднего.

    Устойчив к яркости, размеру и слабому размытию -- то есть ровно к тому,
    чем снимок с камеры отличается от эталона.
    """
    small = img.convert("L").resize((HASH_SIDE, HASH_SIDE), Image.BILINEAR)
    pixels = np.asarray(small, dtype=np.float64)
    dct = _dct()
    freq = dct @ pixels @ dct.T
    block = freq[:HASH_BITS, :HASH_BITS].copy()
    block[0, 0] = 0.0          # постоянная составляющая -- это просто яркость
    return _bits_to_int(block > np.median(block))


def dhash(img: "Image.Image") -> int:
    """Хеш разностей: где соседний пиксель светлее предыдущего.

    Ошибается в других местах, чем pHash: тот плывёт на бликах фойла, этот --
    на размытии. Два хеша вместе спасают больше снимков, чем любой поодиночке.
    """
    small = img.convert("L").resize((HASH_BITS + 1, HASH_BITS), Image.BILINEAR)
    pixels = np.asarray(small, dtype=np.int16)
    return _bits_to_int(pixels[:, 1:] > pixels[:, :-1])


def signed64(value: int) -> int:
    """64 бита так, как их принимает SQLite: со знаком.

    Хеш -- это просто 64 бита, но в столбце INTEGER они лежат знаковым числом,
    и без этого каждый второй отпечаток не записывался бы вовсе. Обратно
    читается маской, которая в Python возвращает то же число без знака.
    """
    value &= 0xFFFFFFFFFFFFFFFF
    return value - (1 << 64) if value >= (1 << 63) else value


def hashes_for(data: bytes, already_cropped: bool = False) -> tuple[int, int]:
    """Пара отпечатков картинки карты (или уже вырезанного арта)."""
    if not DEPS_OK:
        raise RuntimeError(DEPS_NOTE)
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        art = img if already_cropped else crop_art(img)
        return phash(art), dhash(art)


# --------------------------------------------------------------------------- #
# Сборка базы отпечатков
# --------------------------------------------------------------------------- #

def printings_to_hash(scope: str = "representative",
                      cards_db: str = DB_PATH) -> list[dict[str, Any]]:
    """Какие печати надо отпечатать.

    representative -- по одной на карту (~36 тысяч, около часа): узнаёт карту,
    но не обязательно её печать. all -- все 108 тысяч: тогда узнаётся и
    печать, а значит и цена на topdeck будет от той же версии.
    """
    conn = cards_connect(cards_db)
    where = "image_small IS NOT NULL AND image_small <> ''"
    if scope != "all":
        where += " AND representative = 1"
    rows = conn.execute(
        "SELECT id, oracle_id, name, set_code, collector_number, image_small "
        "FROM cards WHERE %s ORDER BY released_at DESC" % where
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


class _Pace:
    """Не больше N запросов в секунду на всех рабочих сразу."""

    def __init__(self, per_second: float) -> None:
        self._gap = 1.0 / max(0.1, per_second)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        """Занять себе место в очереди и спать уже без замка.

        Со сном внутри замка рабочие выстраивались в затылок друг другу:
        шесть потоков работали как один, и вместо десяти картинок в секунду
        выходило две с небольшим -- пять часов вместо часа.
        """
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self._gap
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


def build(scope: str = "representative", workers: int = 6,
          per_second: float = 10.0, progress: Progress = print,
          stop: Callable[[], bool] | None = None,
          cards_db: str = DB_PATH, art_db: str = ART_DB_PATH) -> dict[str, Any]:
    """Скачать картинки и посчитать отпечатки. Прерывать можно: продолжит.

    Картинки не хранятся -- только два числа на печать. Скачанные 13 КБ живут
    ровно до конца функции, которая их посчитала.
    """
    conn = connect(art_db)
    done = {r["card_id"] for r in conn.execute("SELECT card_id FROM art")}
    bad = {r["card_id"] for r in conn.execute("SELECT card_id FROM failed")}
    todo = [p for p in printings_to_hash(scope, cards_db)
            if p["id"] not in done and p["id"] not in bad]
    progress("отпечатков уже есть: %d, осталось: %d" % (len(done), len(todo)))

    pace = _Pace(per_second)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    lock = threading.Lock()
    counts = {"ok": 0, "fail": 0}
    started = time.time()

    def one(row: dict[str, Any]) -> tuple[str, Any]:
        pace.wait()
        try:
            r = session.get(row["image_small"], timeout=30)
            r.raise_for_status()
            ph, dh = hashes_for(r.content)
            return "ok", (row["id"], row["oracle_id"], row["name"],
                          row["set_code"], row["collector_number"],
                          signed64(ph), signed64(dh))
        except Exception as exc:                       # noqa: BLE001
            return "fail", (row["id"], str(exc)[:200])

    batch_ok: list[tuple] = []
    batch_bad: list[tuple] = []

    def flush() -> None:
        if batch_ok:
            conn.executemany(
                "INSERT OR REPLACE INTO art (card_id, oracle_id, name, set_code,"
                " collector_number, phash, dhash) VALUES (?,?,?,?,?,?,?)", batch_ok)
        if batch_bad:
            conn.executemany(
                "INSERT OR REPLACE INTO failed (card_id, reason, at) "
                "VALUES (?,?,datetime('now'))", batch_bad)
        conn.commit()
        batch_ok.clear()
        batch_bad.clear()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for kind, payload in pool.map(one, todo):
            if kind == "ok":
                batch_ok.append(payload)
                counts["ok"] += 1
            else:
                batch_bad.append(payload)
                counts["fail"] += 1
            total = counts["ok"] + counts["fail"]
            if total % 200 == 0:
                with lock:
                    flush()
                speed = total / max(1e-6, time.time() - started)
                left = (len(todo) - total) / max(0.1, speed)
                progress("%d из %d, %.1f/с, осталось ~%d мин"
                         % (total, len(todo), speed, left / 60))
            if stop and stop():
                progress("остановлено")
                break
    flush()

    have = conn.execute("SELECT COUNT(*) AS n FROM art").fetchone()["n"]
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('scope', ?)",
                 (scope,))
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('built_at', datetime('now'))")
    conn.commit()
    conn.close()
    progress("готово: %d отпечатков, не вышло %d" % (have, counts["fail"]))
    return {"hashed": counts["ok"], "failed": counts["fail"], "total": have}


# --------------------------------------------------------------------------- #
# Поиск
# --------------------------------------------------------------------------- #

def _popcount(x: np.ndarray) -> np.ndarray:
    """Сколько единичных битов в каждом числе (numpy своего не даёт)."""
    x = x.astype(np.uint64)
    m1 = np.uint64(0x5555555555555555)
    m2 = np.uint64(0x3333333333333333)
    m4 = np.uint64(0x0F0F0F0F0F0F0F0F)
    h01 = np.uint64(0x0101010101010101)
    x = x - ((x >> np.uint64(1)) & m1)
    x = (x & m2) + ((x >> np.uint64(2)) & m2)
    x = (x + (x >> np.uint64(4))) & m4
    return ((x * h01) >> np.uint64(56)).astype(np.int16)


class ArtIndex:
    """Все отпечатки в памяти: 36 тысяч чисел -- это 300 КБ и доли миллисекунды."""

    def __init__(self, path: str = ART_DB_PATH) -> None:
        self.path = path
        self.ids: list[str] = []
        self.rows: list[dict[str, Any]] = []
        self.phash = None
        self.dhash = None
        self.loaded_at = 0.0
        self.load()

    @property
    def ready(self) -> bool:
        return len(self.ids) > 0

    def load(self) -> int:
        if not DEPS_OK or not os.path.exists(self.path):
            return 0
        conn = connect(self.path)
        rows = conn.execute(
            "SELECT card_id, oracle_id, name, set_code, collector_number, "
            "phash, dhash FROM art").fetchall()
        conn.close()
        self.rows = [dict(r) for r in rows]
        self.ids = [r["card_id"] for r in self.rows]
        self.phash = np.array([r["phash"] & 0xFFFFFFFFFFFFFFFF for r in self.rows],
                              dtype=np.uint64)
        self.dhash = np.array([r["dhash"] & 0xFFFFFFFFFFFFFFFF for r in self.rows],
                              dtype=np.uint64)
        self.loaded_at = time.time()
        return len(self.ids)

    def match(self, ph: int, dh: int, limit: int = 5) -> list[dict[str, Any]]:
        """Ближайшие печати. Расстояние -- сумма двух хеммингов из 128 возможных."""
        if not self.ready:
            return []
        dp = _popcount(self.phash ^ np.uint64(ph & 0xFFFFFFFFFFFFFFFF))
        dd = _popcount(self.dhash ^ np.uint64(dh & 0xFFFFFFFFFFFFFFFF))
        total = dp.astype(np.int32) + dd.astype(np.int32)
        take = min(limit, len(total))
        best = np.argpartition(total, take - 1)[:take]
        best = best[np.argsort(total[best])]
        out = []
        for i in best:
            row = dict(self.rows[int(i)])
            row["distance"] = int(total[int(i)])
            row["phash_distance"] = int(dp[int(i)])
            row["dhash_distance"] = int(dd[int(i)])
            out.append(row)
        return out


_INDEX: ArtIndex | None = None
_INDEX_LOCK = threading.Lock()


def index(reload: bool = False) -> ArtIndex:
    global _INDEX
    with _INDEX_LOCK:
        if _INDEX is None:
            _INDEX = ArtIndex()
        elif reload:
            _INDEX.load()
        return _INDEX


def status(art_db: str = ART_DB_PATH) -> dict[str, Any]:
    if not DEPS_OK:
        return {"built": False, "hashed": 0, "failed": 0, "scope": None,
                "deps": False, "detail": DEPS_NOTE}
    if not os.path.exists(art_db):
        return {"built": False, "hashed": 0, "failed": 0, "scope": None, "deps": True}
    conn = connect(art_db)
    hashed = conn.execute("SELECT COUNT(*) AS n FROM art").fetchone()["n"]
    failed = conn.execute("SELECT COUNT(*) AS n FROM failed").fetchone()["n"]
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    conn.close()
    return {
        "built": hashed > 0,
        "deps": True,
        "hashed": hashed,
        "failed": failed,
        "scope": meta.get("scope"),
        "built_at": meta.get("built_at"),
    }


def identify(data: bytes, limit: int = 5, already_cropped: bool = False,
             both_ways: bool = False) -> list[dict[str, Any]]:
    """Что это за карта. `data` -- снимок карты целиком, вырезанный по рамке.

    `both_ways` пробует ещё и перевёрнутую на 180 градусов: выпрямленная
    камерой карта может оказаться вверх ногами, и по картинке этого не понять,
    а по отпечатку -- мгновенно. Берётся тот разворот, который ближе.
    """
    ph, dh = hashes_for(data, already_cropped=already_cropped)
    best = index().match(ph, dh, limit=limit)
    if not both_ways:
        return best

    with Image.open(io.BytesIO(data)) as img:
        img.load()
        flipped = img.rotate(180, expand=True)
        art = flipped if already_cropped else crop_art(flipped)
        other = index().match(phash(art), dhash(art), limit=limit)
    if other and (not best or other[0]["distance"] < best[0]["distance"]):
        for row in other:
            row["upside_down"] = True
        return other
    return best


__all__ = [
    "ART_DB_PATH", "ArtIndex", "build", "crop_art", "dhash", "hashes_for",
    "identify", "index", "phash", "printings_to_hash", "signed64",
    "status",
]
