"""Пачка карт на одном снимке: прочитать имена и понять, какие это карты.

Так снимают коллекцию: карты лежат внахлёст, у каждой видно только верхнюю
полосу -- имя и мана-стоимость. Отпечаток арта (app/artscan.py) тут бесполезен,
арта не видно; имя надо прочитать, и это единственное место в программе, где
нужен OCR.

Первая попытка была честной и неправильной: искать края карт по резким
горизонтальным линиям, вырезать из каждой полосы место, где должно быть имя, и
читать вырезки по одной. У карты своих горизонтальных линий хватает -- рамка,
полоса имени, край арта, -- и восемь карт превращались в пятнадцать полос,
после чего распознаватель читал куски текста правил.

Оказалось, что вся эта геометрия не нужна. Распознаватель читает **весь снимок
сразу** и отдаёт строки вместе с их местом. Имена карт -- это и есть строки,
идущие ровным шагом сверху вниз; чтобы понять, какая карта, их надо просто
сличить с именами карт, которые у нас все есть -- английские, русские и имена
сторон. Восемь карт из восьми, десятая доля секунды, никаких порогов.

Что при этом попадает в улов лишнего: у нижней карты видно не только имя, но и
тип, и текст правил, и флейвор. Такие строки отсеиваются двумя признаками:
они плохо сходятся с именами карт, а те, что всё же сошлись (флейвор бывает
цитатой с названием), стоят вне того ровного шага, по которому идут имена.
"""

from __future__ import annotations

import io
import re
from difflib import SequenceMatcher
from typing import Any

from .cards import CardDB, normalize_name

try:
    import numpy as np
    from PIL import Image, ImageOps
    DEPS_OK = True
except ImportError:                                      # pragma: no cover
    np = None                                            # type: ignore[assignment]
    Image = None                                         # type: ignore[assignment]
    DEPS_OK = False

# К этой высоте приводится снимок: имя карты в пачке из двадцати штук на
# телефонном снимке -- буквы высотой в десяток пикселей, и распознавателю их
# мало. Больше 2600 смысла нет: точность не растёт, время растёт.
WORK_HEIGHT = 2200
MAX_WORK_WIDTH = 2600

# Насколько похоже прочитанное должно быть на имя карты. Ниже первого -- не
# показываем вовсе, ниже второго -- показываем как догадку, не отмеченную.
MIN_RATIO = 0.72
SURE_RATIO = 0.88
# Две строки считаются одной и той же, если они стоят в одном месте снимка:
# это два прочтения одной строки разными языками. Сравнивать только по высоте
# нельзя -- на снимке, где карты разложены рядами, в одной строке высоты стоят
# несколько разных имён, и они схлопывались в одно.
SAME_ROW = 0.012
SAME_COL = 0.06


def _prepare(data: bytes) -> "Image.Image":
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    scale = WORK_HEIGHT / max(1, img.height)
    width = int(img.width * scale)
    if width > MAX_WORK_WIDTH:
        scale = MAX_WORK_WIDTH / max(1, img.width)
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                     Image.LANCZOS)
    return img


def _png(img: "Image.Image") -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Поиск имени среди карт
# --------------------------------------------------------------------------- #

_JUNK = re.compile(r"[^\w\s'’-]+", re.UNICODE)


def clean_text(text: str) -> str:
    """Из прочитанного -- то, что можно искать: без мусорных знаков."""
    return " ".join(_JUNK.sub(" ", text or "").split()).strip()


def _trigrams(text: str) -> set[str]:
    text = " %s " % text
    return {text[i:i + 3] for i in range(max(0, len(text) - 2))}


class NameFinder:
    """Нестрогий поиск имени карты по тому, что удалось прочитать.

    Строгий тут не годится: распознаватель путает «l» и «I», теряет апострофы
    и запятые, склеивает буквы. Зато имён у нас все -- английские, русские и
    имена сторон, 59 914 записей, -- и среди них похожее находится уверенно.

    Сначала грубо, по общим трёхбуквенным кускам (это дешёвый способ выкинуть
    99.9% имён), потом точно -- сходством целых строк.
    """

    def __init__(self, db: CardDB) -> None:
        self.db = db
        self.names: list[tuple[str, str]] = []           # norm, display
        self.by_trigram: dict[str, list[int]] = {}
        self._loaded = False

    def load(self) -> int:
        if self._loaded:
            return len(self.names)
        rows = self.db.conn.execute(
            "SELECT name_norm, name_display FROM card_names").fetchall()
        seen: set[str] = set()
        for r in rows:
            norm = r["name_norm"] or ""
            if len(norm) < 3 or norm in seen:
                continue
            seen.add(norm)
            idx = len(self.names)
            self.names.append((norm, r["name_display"] or norm))
            for tri in _trigrams(norm):
                self.by_trigram.setdefault(tri, []).append(idx)
        self._loaded = True
        return len(self.names)

    def find(self, text: str, limit: int = 1) -> list[dict[str, Any]]:
        text = clean_text(text)
        if len(text) < 3:
            return []
        self.load()
        norm = normalize_name(text)

        counts: dict[int, int] = {}
        for tri in _trigrams(norm):
            for idx in self.by_trigram.get(tri, ()):
                counts[idx] = counts.get(idx, 0) + 1
        if not counts:
            return []

        rough = sorted(counts.items(), key=lambda p: -p[1])[:120]
        scored = []
        for idx, _hits in rough:
            candidate = self.names[idx]
            scored.append((SequenceMatcher(None, norm, candidate[0]).ratio(), candidate))
        scored.sort(key=lambda p: (-p[0], len(p[1][0])))
        return [{"name": disp, "score": round(ratio, 3)}
                for ratio, (_norm, disp) in scored[:limit]]


# --------------------------------------------------------------------------- #
# Ровный шаг
# --------------------------------------------------------------------------- #

def lattice(rows: list[int], tolerance: float = 0.22) -> list[bool]:
    """Какие из строк стоят ровным шагом, как имена карт в пачке.

    У нижней карты видно не только имя, но и тип, и текст правил, и флейвор.
    Строка «Artifact» сходится с картой «Artifacts» на 0.94, а имя художника --
    с какой-нибудь картой на 0.9: по похожести их не отличить.

    Отличает их шаг. Имена в пачке идут одно под другим через равные
    промежутки, и поэтому ищется не «похожий на соседа промежуток», а самая
    длинная цепочка строк с одним шагом. Всё, что вне неё, -- не имена, а
    текст с карты, попавшей в кадр целиком.
    """
    if len(rows) < 3:
        return [True] * len(rows)
    gaps = [rows[i + 1] - rows[i] for i in range(len(rows) - 1)]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return [True] * len(rows)

    # Шаг -- не медиана промежутков. Если одну карту не прочитали, между
    # соседями получается двойной промежуток, и медиана при чётном их числе
    # спокойно берёт именно его: настоящий шаг тогда «не подходит» ни к чему, а
    # подходит случайная строка внизу снимка. Поэтому шагом считается тот
    # промежуток, кратными которому оказывается больше всего остальных, а при
    # равенстве -- меньший из них.
    def explains(candidate: int) -> int:
        return sum(1 for g in gaps
                   if any(abs(g - candidate * k) <= candidate * tolerance * k
                          for k in (1, 2)))

    step = min(sorted(set(gaps)), key=lambda g: (-explains(g), g))

    def fits(gap: int) -> bool:
        # Пропущенная карта -- это двойной шаг, и это всё ещё та же пачка.
        # Тройной уже нет: с ним в ряд начинают попадать строки правил нижней
        # карты, а это ровно то, ради чего ряд и считается.
        return any(abs(gap - step * k) <= step * tolerance * k for k in (1, 2))

    best: list[int] = []
    start = 0
    while start < len(rows):
        run = [start]
        i = start
        while i + 1 < len(rows) and fits(rows[i + 1] - rows[i]):
            i += 1
            run.append(i)
        if len(run) > len(best):
            best = run
        start = max(start + 1, i)

    if len(best) < 3:
        return [True] * len(rows)
    keep = set(best)
    return [i in keep for i in range(len(rows))]


# --------------------------------------------------------------------------- #
# Разбор снимка
# --------------------------------------------------------------------------- #

def read_pile(data: bytes, db: CardDB, ocr: Any,
              finder: NameFinder | None = None) -> dict[str, Any]:
    """Разобрать снимок пачки: какие карты на нём видно."""
    if not DEPS_OK:
        return {"ok": False, "cards": [],
                "detail": "нужны Pillow и numpy: pip install -r requirements.txt"}
    engine = ocr.available()
    if not engine.get("ok"):
        return {"ok": False, "cards": [], "detail": engine.get("detail")}

    img = _prepare(data)
    lines = ocr.read_lines(_png(img))
    if not lines:
        return {"ok": True, "cards": [], "lines": 0, "engine": engine.get("engine"),
                "detail": "на снимке не нашлось текста"}

    finder = finder or NameFinder(db)
    tolerance = max(4, int(img.height * SAME_ROW))

    # Одна строка снимка, прочитанная двумя языками, -- это одна строка.
    # Одно место, а не одна высота: в ряду разложенных карт имена стоят на
    # одной высоте, но это разные карты.
    side = max(20, int(img.width * SAME_COL))
    rows: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda l: (l["y"], l["x"])):
        hit = (finder.find(line["text"], limit=1) or [None])[0]
        if hit is None or hit["score"] < MIN_RATIO:
            continue
        slot = None
        for row in rows:
            if (abs(row["y"] - line["y"]) <= tolerance
                    and abs(row["x"] - line.get("x", 0)) <= side):
                slot = row
                break
        if slot is None:
            rows.append({"y": line["y"], "x": line.get("x", 0),
                         "text": clean_text(line["text"]),
                         "name": hit["name"], "score": hit["score"],
                         "lang": line.get("lang")})
        elif hit["score"] > slot["score"]:
            slot.update({"text": clean_text(line["text"]), "name": hit["name"],
                         "score": hit["score"], "lang": line.get("lang")})

    rows.sort(key=lambda r: (r["y"], r["x"]))
    # Ровный шаг ищется по столбцу: карты в пачке идут одна под другой. Если
    # карты разложены рядами, столбцов несколько, и каждый проверяется сам.
    on_step = [False] * len(rows)
    # Столбцы -- это скопления близких x, а не клетки сетки: делением на
    # ширину клетки два соседних имени, стоящих в одном столбце, попадали
    # по разные стороны границы, и столбец разваливался на два по одной
    # строке, где никакого шага уже не видно.
    columns: list[list[int]] = []
    for i in sorted(range(len(rows)), key=lambda k: rows[k]["x"]):
        if columns and rows[i]["x"] - rows[columns[-1][-1]]["x"] <= side:
            columns[-1].append(i)
        else:
            columns.append([i])
    for indexes in columns:
        indexes.sort(key=lambda k: rows[k]["y"])
        for i, steady in zip(indexes, lattice([rows[i]["y"] for i in indexes])):
            on_step[i] = steady

    cards: list[dict[str, Any]] = []
    for row, steady in zip(rows, on_step):
        card = db.by_name(row["name"]) or {}
        cards.append({
            "text": row["text"],
            # id печати и карты: по ним открывается окно карты и список печатей.
            "card_id": card.get("id"),
            "oracle_id": card.get("oracle_id"),
            "name": card.get("name") or row["name"],
            "ru_name": card.get("ru_name"),
            "image_small": card.get("image_small"),
            "set_code": card.get("set_code"),
            "collector_number": card.get("collector_number"),
            "score": row["score"],
            "y": int(row["y"]),
            # Уверенно -- это и похоже на имя, и стоит в общем ряду с другими.
            # Одной похожести мало: «Artifact» сходится с картой «Artifacts» на
            # 0.94, а строки флейвора -- с чем угодно на 0.9. Послабление «если
            # совсем точно, то и без ряда» пробовалось и добавляло ложных
            # больше, чем верных.
            "sure": bool(row["score"] >= SURE_RATIO and steady),
            "in_step": bool(steady),
        })

    return {
        "ok": True,
        "engine": engine.get("engine"),
        "lines": len(lines),
        "cards": cards,
    }


__all__ = ["NameFinder", "clean_text", "lattice", "read_pile"]
