"""Browser check: сканер карт камерой.

Проверяется весь путь, каким он будет у человека: камера включена, карта лежит
в рамке, кадр уходит на сервер, карта узнаётся и попадает в список, список
уходит в коллекцию.

Камера здесь поддельная: Chromium умеет играть видеофайл вместо камеры
(--use-file-for-fake-video-capture), и файл мы делаем сами -- кадр с картой,
положенной ровно в рамку сканера. Это и есть настоящая проверка: та же
обрезка, то же сжатие, тот же запрос.

Нужна собранная база отпечатков (build_art.py) -- без неё сценарий скажет об
этом и выйдет.

Коллекцию не трогает: добавление проверяется на карте, которая тут же
убирается обратно.

    .venv/Scripts/python.exe tests/ui_scan.py
"""

import io
import json
import os
import sqlite3
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests                                          # noqa: E402
from PIL import Image                                    # noqa: E402
from playwright.sync_api import sync_playwright          # noqa: E402

from app import artscan                                  # noqa: E402

# Куда стучаться. По умолчанию -- обычный запуск; MTGH_UI_BASE нужна,
# когда на этом порту уже работает другая копия программы (скажем,
# запущенная по https для планшета).
BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def some_cards(limit=5):
    """Несколько карт с картинками -- из тех, что уже отпечатаны."""
    art = sqlite3.connect("file:%s?mode=ro" % artscan.ART_DB_PATH.replace("\\", "/"),
                          uri=True)
    ids = [r[0] for r in art.execute("SELECT card_id FROM art LIMIT 600")]
    art.close()
    cards = sqlite3.connect(
        "file:%s?mode=ro" % os.path.join(ROOT, "data", "cards.sqlite").replace("\\", "/"),
        uri=True)
    cards.row_factory = sqlite3.Row
    out = []
    for card_id in ids:
        row = cards.execute(
            "SELECT name, ru_name, image_normal FROM cards WHERE id = ?",
            (card_id,)).fetchone()
        # Имена со скобками и косыми чертами читаются иначе, чем пишутся:
        # для проверки берём обычные.
        if row and row["image_normal"] and "//" not in row["name"]:
            out.append(dict(row))
        if len(out) >= limit:
            break
    cards.close()
    return out


def a_hashed_card():
    """Карта, которая уже есть в базе отпечатков, и ссылка на её картинку."""
    art = sqlite3.connect("file:%s?mode=ro" % artscan.ART_DB_PATH.replace("\\", "/"),
                          uri=True)
    ids = [r[0] for r in art.execute("SELECT card_id FROM art LIMIT 400")]
    art.close()
    cards = sqlite3.connect(
        "file:%s?mode=ro" % os.path.join(ROOT, "data", "cards.sqlite").replace("\\", "/"),
        uri=True)
    cards.row_factory = sqlite3.Row
    for card_id in ids:
        row = cards.execute(
            "SELECT id, name, ru_name, image_normal FROM cards WHERE id = ?",
            (card_id,)).fetchone()
        if row and row["image_normal"]:
            cards.close()
            return dict(row)
    cards.close()
    return None


def pile_photo(images: list[bytes], overlap=0.16) -> str:
    """Снимок пачки: карты внахлёст, у каждой видно имя.

    Ровно то, ради чего разбор пачки и написан: двести карт не наводят под
    камеру по одной, их снимают одним кадром.
    """
    cards = [Image.open(io.BytesIO(d)).convert("RGB") for d in images]
    w, h = cards[0].size
    step = int(h * overlap)
    canvas = Image.new("RGB", (w + 60, step * (len(cards) - 1) + h + 60), (38, 36, 33))
    for i, card in enumerate(cards):
        canvas.paste(card, (30, 30 + i * step))
    path = os.path.join(tempfile.gettempdir(), "mtgh_pile.jpg")
    canvas.save(path, "JPEG", quality=88)
    return path


def y4m_from(card_png: bytes, width=1280, height=720, frames=40,
             angle=17, shift=(0.12, -0.06)) -> str:
    """Кадр «карта на столе» в формате, который Chromium играет вместо камеры.

    Карта лежит криво и не по центру -- именно так, как её кладут на стол. Это
    и есть проверка: программа должна найти её в кадре сама, а не требовать
    положить в нарисованную рамку.
    """
    card = Image.open(io.BytesIO(card_png)).convert("RGBA")
    target_h = int(height * 0.66)
    target_w = int(target_h * card.width / card.height)
    card = card.resize((target_w, target_h), Image.LANCZOS)
    card = card.rotate(angle, resample=Image.BICUBIC, expand=True,
                       fillcolor=(0, 0, 0, 0))

    frame = Image.new("RGB", (width, height), (78, 72, 64))
    frame.paste(card,
                (int((width - card.width) / 2 + shift[0] * width),
                 int((height - card.height) / 2 + shift[1] * height)),
                card.split()[3])

    ycbcr = frame.convert("YCbCr")
    y, cb, cr = ycbcr.split()
    # 4:2:0 -- цветность вдвое реже по обеим осям.
    cb = cb.resize((width // 2, height // 2), Image.BILINEAR)
    cr = cr.resize((width // 2, height // 2), Image.BILINEAR)
    plane = y.tobytes() + cb.tobytes() + cr.tobytes()

    path = os.path.join(tempfile.gettempdir(), "mtgh_scan_fake.y4m")
    with open(path, "wb") as fh:
        fh.write(("YUV4MPEG2 W%d H%d F15:1 Ip A1:1 C420\n" % (width, height)).encode())
        for _ in range(frames):
            fh.write(b"FRAME\n")
            fh.write(plane)
    return path


state = json.load(urllib.request.urlopen(BASE + "/api/scan/status"))
if not state.get("ready"):
    print("База отпечатков не собрана — запустите build_art.py. Сценарий пропущен.")
    raise SystemExit(0)
print("в базе отпечатков: %d" % state["hashed"])

card = a_hashed_card()
if not card:
    print("Нечего проверять: в базе отпечатков нет карт с картинкой.")
    raise SystemExit(0)

session = requests.Session()
session.headers["User-Agent"] = artscan.USER_AGENT
video = y4m_from(session.get(card["image_normal"], timeout=60).content)
print("карта для проверки: %s" % card["name"])

with sync_playwright() as pw:
    browser = pw.chromium.launch(args=[
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--use-file-for-fake-video-capture=" + video,
        "--autoplay-policy=no-user-gesture-required",
    ])
    page = browser.new_context(
        viewport={"width": 1280, "height": 1000},
        permissions=["camera"]).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    page.click('.tab[data-tab="scan"]')
    page.wait_for_timeout(700)
    check("вкладка сканера открылась",
          page.locator("#panel-scan.active").count() == 1)
    check("состояние базы отпечатков показано",
          "база отпечатков" in (page.text_content("#scan-dbstate") or "").lower(),
          (page.text_content("#scan-dbstate") or "")[:60])

    page.click("#scan-start")
    page.wait_for_selector("#scan-stage:not([hidden])", timeout=20000)
    check("камера включилась и кадр виден",
          page.evaluate("() => { const v = document.querySelector('#scan-video');"
                        " return v.videoWidth > 0 && v.videoHeight > 0; }"))
    check("рамка нарисована", page.locator(".scanframe").count() == 1)

    # Карта лежит криво и не по центру: программа обязана найти её сама.
    page.wait_for_function(
        "() => document.querySelector('#scan-outline polygon') !== null",
        timeout=30000)
    check("карта найдена в кадре и обведена", True)
    check("рамка при этом спрятана",
          page.evaluate("""() => {
            const f = document.querySelector('.scanframe');
            return getComputedStyle(f).display === 'none';
          }"""))

    # Карта должна опознаться сама: кадры уходят каждые 400 мс, зачёт -- со
    # второго одинакового ответа.
    page.wait_for_function(
        "(name) => [...document.querySelectorAll('#scan-found .nm b')]"
        ".some(e => e.textContent.trim() === name)",
        arg=(card["ru_name"] or card["name"]), timeout=40000)
    check("карта узналась и попала в список", True, card["name"])

    live = page.text_content("#scan-live") or ""
    check("под кадром видно, что узнано", card["name"][:12].lower() in live.lower()
          or (card["ru_name"] or "")[:8].lower() in live.lower(), live[:60])

    # Счётчик и кнопки появляются только когда есть что отправлять.
    check("счётчик показывает найденное",
          "шт." in (page.text_content("#scan-count") or ""),
          page.text_content("#scan-count") or "")
    check("кнопки отправки появились",
          page.locator("#scan-actions:not([hidden])").count() == 1)

    # Плюс и минус меняют количество, «убрать» убирает.
    page.locator("#scan-found [data-more]").first.click()
    page.wait_for_timeout(200)
    qty = page.locator("#scan-found .qty b").first.text_content()
    check("количество прибавляется", qty.strip() == "2", qty)

    print()
    print("=== со списком можно работать: увеличить и поправить ===")
    page.locator("#scan-found img.zoom").first.click()
    page.wait_for_selector("#overlay:not([hidden])", timeout=20000)
    check("картинка открывает окно карты",
          (page.text_content("#modal-body") or "").strip() != "")
    page.click("#modal-close")
    page.wait_for_timeout(300)

    page.locator("#scan-found [data-fix]").first.click()
    page.wait_for_timeout(300)
    check("разбор строки открылся",
          page.locator("#scan-found .scanfix:not([hidden])").count() == 1)

    was = page.locator("#scan-found .nm b").first.text_content()
    page.fill("#scan-found .fixsearch", "Sol Ring")
    page.wait_for_selector("#scan-found .fixresults .altpick", timeout=20000)
    check("поиск по имени что-то нашёл",
          page.locator("#scan-found .fixresults .altpick").count() > 0)
    page.locator("#scan-found .fixresults .altpick").first.click()
    page.wait_for_timeout(500)
    now = page.locator("#scan-found .nm b").first.text_content()
    check("карту можно заменить вручную", now != was, "%s -> %s" % (was, now))
    check("количество при замене сохранилось",
          (page.locator("#scan-found .qty b").first.text_content() or "").strip() == "2")

    # Возвращаем как было: дальше проверяется отправка в коллекцию.
    page.locator("#scan-found [data-drop]").first.click()
    page.wait_for_timeout(300)
    check("строку можно убрать",
          page.locator("#scan-found .scanrow").count() == 0)
    # Карта всё ещё лежит под камерой, а зачтённую программа нарочно не
    # считает второй раз, пока её не уберут. Для сценария снимаем эту память.
    page.evaluate("() => { scanCommitted = null; scanLast = null; }")
    page.wait_for_function(
        "(name) => [...document.querySelectorAll('#scan-found .nm b')]"
        ".some(e => e.textContent.trim() === name)",
        arg=(card["ru_name"] or card["name"]), timeout=40000)

    before = json.load(urllib.request.urlopen(BASE + "/api/status"))["collection_cards"]
    page.click("#scan-tocollection")
    page.wait_for_timeout(1200)
    after = json.load(urllib.request.urlopen(BASE + "/api/status"))["collection_cards"]
    check("список ушёл в коллекцию", after > before, "%d -> %d" % (before, after))
    check("и список очистился", page.locator("#scan-found .scanrow").count() == 0)

    # Возвращаем коллекцию как было: сценарий не должен ничего оставлять.
    restored = page.evaluate("""async (args) => {
      const r = await fetch('/api/collection').then(x => x.json());
      const coll = r.collection || {};
      const key = Object.keys(coll).find(k => k.toLowerCase() === args.name.toLowerCase());
      if (!key) return 'не нашлось';
      const left = coll[key] - args.count;
      const text = Object.entries(coll)
        .map(([n, c]) => (n.toLowerCase() === key.toLowerCase() ? left : c) + ' ' + n)
        .filter(line => !line.startsWith('0 '))
        .join('\\n');
      await fetch('/api/collection', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text})});
      return 'ок';
    }""", {"name": card["name"], "count": after - before})
    now = json.load(urllib.request.urlopen(BASE + "/api/status"))["collection_cards"]
    check("коллекция возвращена как была", now == before,
          "%s, стало %d при исходных %d" % (restored, now, before))

    # Выход с вкладки гасит камеру: индикатор рядом с объективом не должен
    # гореть на закрытой странице.
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(600)
    check("камера выключается при уходе с вкладки",
          page.evaluate("() => !scanReady()"))

    print()
    print("=== снимок пачки: имена читаются с одного кадра ===")
    page.click('.tab[data-tab="scan"]')
    page.wait_for_timeout(500)
    pack = some_cards(5)
    photo = pile_photo([session.get(c["image_normal"], timeout=60).content
                        for c in pack])
    page.set_input_files("#scan-pilefile", photo)
    page.wait_for_selector("#scan-pile .pilerow", timeout=60000)
    read = page.eval_on_selector_all(
        "#scan-pile .pilerow .nm b", "els => els.map(e => e.textContent.trim())")
    want = [c["ru_name"] or c["name"] for c in pack]
    missed = [n for n in want if n not in read]
    check("все карты пачки прочитаны", not missed,
          "не нашлись: %s" % ", ".join(missed) if missed else "%d из %d"
          % (len(read), len(want)))
    checked = page.eval_on_selector_all(
        "#scan-pile input[data-pile]", "els => els.filter(e => e.checked).length")
    check("уверенные отмечены заранее", checked >= len(want),
          "%d отмечено" % checked)

    page.click("#pile-take")
    page.wait_for_timeout(800)
    listed = page.eval_on_selector_all(
        "#scan-found .nm b", "els => els.map(e => e.textContent.trim())")
    check("отмеченные ушли в общий список",
          all(n in listed for n in want), "; ".join(listed[:4]))
    check("панель разбора закрылась",
          page.locator("#scan-pile[hidden]").count() == 1)
    os.remove(photo)

    print()
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

os.remove(video)
print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
