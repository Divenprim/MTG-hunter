"""Прочитать текст с картинки -- тем, что уже есть в системе.

Нужно это ровно для одного: узнать карты в пачке, снятой одним кадром. Там у
каждой карты видно только верхушку -- имя и мана-стоимость, -- а арта нет,
поэтому отпечаток арта (app/artscan.py) бесполезен. Имя надо прочитать.

Чем читаем. В Windows с десятой версии есть свой распознаватель текста
(Windows.Media.Ocr), и языковые модели к нему ставятся вместе с системой: на
русской Windows уже есть русский и английский. Это лучший вариант из
возможных -- ничего не скачивается, ничего не весит, работает без интернета и
читает оба языка. Доступ к нему даёт пакет winsdk, тонкая обвязка над
системным API.

Если его нет -- пробуем Tesseract, если он установлен и лежит в PATH. Нет и
его -- честно говорим, чего не хватает.

Читаем **строками, а не сплошным текстом**: у каждой строки известно, где она
на снимке, и по этому видно, что имена карт идут ровным шагом, а поясняющий
текст нижней карты -- нет.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from typing import Any

try:                                                     # pragma: no cover
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    WINDOWS_OCR = True
except Exception:                                        # noqa: BLE001
    WINDOWS_OCR = False

# Оба языка: русское имя читается русским распознавателем, английское --
# английским, и наоборот они путаются. Две попытки дешевле одной ошибки, тем
# более что снимок распознаётся за доли секунды.
LANGS = ("ru", "en-US")


def _engines() -> list[tuple[str, Any]]:
    if not WINDOWS_OCR:
        return []
    out: list[tuple[str, Any]] = []
    for tag in LANGS:
        try:
            engine = OcrEngine.try_create_from_language(Language(tag))
        except Exception:                                # noqa: BLE001
            engine = None
        if engine is not None:
            out.append((tag, engine))
    return out


async def _lines_windows(png: bytes, engine: Any) -> list[dict[str, Any]]:
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)

    lines: list[dict[str, Any]] = []
    for line in result.lines:
        text = (line.text or "").strip()
        if not text:
            continue
        boxes = [w.bounding_rect for w in line.words]
        if not boxes:
            continue
        top = min(b.y for b in boxes)
        left = min(b.x for b in boxes)
        right = max(b.x + b.width for b in boxes)
        bottom = max(b.y + b.height for b in boxes)
        lines.append({
            "text": text,
            "x": int(left), "y": int(top),
            "width": int(right - left), "height": int(bottom - top),
        })
    return lines


def _lines_tesseract(png: bytes) -> list[dict[str, Any]]:
    exe = shutil.which("tesseract")
    if not exe:
        return []
    path = os.path.join(tempfile.gettempdir(), "mtgh_ocr.png")
    with open(path, "wb") as fh:
        fh.write(png)
    out: list[dict[str, Any]] = []
    for langs in ("rus+eng", "eng"):
        try:
            proc = subprocess.run([exe, path, "stdout", "-l", langs],
                                  capture_output=True, timeout=60)
        except Exception:                                # noqa: BLE001
            continue
        for i, text in enumerate(proc.stdout.decode("utf-8", "replace").splitlines()):
            text = text.strip()
            if text:
                # Tesseract без tsv не даёт рамок: порядок строк -- всё, что
                # у нас есть, и он всё-таки сверху вниз.
                out.append({"text": text, "x": 0, "y": i * 10,
                            "width": 0, "height": 0})
        if out:
            break
    return out


def available() -> dict[str, Any]:
    """Чем именно мы умеем читать -- и что сказать, если ничем."""
    engines = _engines()
    if engines:
        return {"ok": True, "engine": "windows", "languages": [t for t, _e in engines]}
    if shutil.which("tesseract"):
        return {"ok": True, "engine": "tesseract", "languages": ["rus", "eng"]}
    return {
        "ok": False,
        "engine": None,
        "languages": [],
        "detail": (
            "Нечем прочитать имена с фотографии. В Windows распознаватель уже "
            "есть, нужен только доступ к нему: "
            ".venv/Scripts/python.exe -m pip install winsdk — "
            "и проверьте, что в языках системы стоят русский и английский."
        ),
    }


def read_lines(png: bytes) -> list[dict[str, Any]]:
    """Все строки со снимка -- по разу на каждый язык, с их местом на снимке.

    Возвращаются оба прочтения одной и той же строки: какое из них настоящее,
    решает поиск по именам карт, а не распознаватель.
    """
    found: list[dict[str, Any]] = []
    for tag, engine in _engines():
        try:
            lines = asyncio.run(_lines_windows(png, engine))
        except Exception:                                # noqa: BLE001
            continue
        for line in lines:
            line["lang"] = tag
            found.append(line)
    if found:
        return found
    return _lines_tesseract(png)


__all__ = ["available", "read_lines"]
