"""Browser check: перенос коллекции и колод на другое устройство.

С его слов: «сделай экспортёр коллекции и колод, чтобы можно было с 1
устройства переносить коллекции на другие».

Проверяется путь целиком: кнопка отдаёт файл, файл принимается обратно, и
принесённое оказывается на месте. Отдельно — что испорченный файл не
применяется и говорит об этом словами.

Сценарий заводит свою колоду «ПРОБА перенос» и убирает её за собой;
коллекцию он только читает.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_transfer.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
DECK = "ПРОБА перенос"


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


MAKE = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, format: 'pioneer'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: [
      {name: 'Fog', quantity: 4, section: 'main'},
      {name: 'Root Snare', quantity: 2, section: 'side'}]})});
  return made.deck.id;
}"""

CLEAN = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

print("=== перенос на другое устройство ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(
        viewport={"width": 1500, "height": 1000},
        accept_downloads=True).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)

    page.evaluate(CLEAN, DECK)
    page.evaluate(MAKE, DECK)
    page.wait_for_timeout(800)

    # ------------------------------------------------------- кнопка на месте
    page.click('.tab[data-tab="collection"]')
    page.wait_for_timeout(2500)
    ok(page.evaluate("() => !!document.querySelector('#transfer-save')"),
       "в коллекции есть «Выгрузить для переноса»")
    ok(page.evaluate("() => !!document.querySelector('#transfer-load')"),
       "и «Принять перенос»")

    # ------------------------------------------------------- файл отдаётся
    with page.expect_download(timeout=60000) as got:
        page.click("#transfer-save")
    download = got.value
    path = download.path()
    ok(download.suggested_filename.endswith(".json"),
       "файл скачивается с понятным именем", download.suggested_filename)

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    ok(data.get("kind") == "mtg-hunter-transfer",
       "внутри — файл переноса, а не что попало", data.get("kind"))
    ok(data["summary"]["decks"] >= 1 and data["summary"]["collection_rows"] >= 1,
       "в нём есть и колоды, и коллекция", data.get("summary"))
    mine = [d for d in data["decks"] if d["name"] == DECK]
    ok(bool(mine), "своя колода попала в файл")
    if mine:
        sections = sorted({c["section"] for c in mine[0]["cards"]})
        ok(sections == ["main", "side"],
           "вместе с разделами — сайдборд не потерялся", sections)

    # ------------------------------- принять обратно: ничего не ломается
    page.evaluate(CLEAN, DECK)
    page.wait_for_timeout(600)
    gone = page.evaluate("""async (name) => {
      const list = await fetch('/api/decks').then(r => r.json());
      return list.decks.some((d) => d.name === name);
    }""", DECK)
    ok(not gone, "колода убрана — проверяем, вернётся ли она переносом")

    page.set_input_files("#transfer-load", path)
    page.wait_for_timeout(1200)
    # confirm() в сценарии подтверждать некому: вешаем ответ заранее.
    page.evaluate("() => { window.confirm = () => false; }")
    page.set_input_files("#transfer-load", path)
    page.wait_for_timeout(2500)
    # Уведомление живёт три секунды и после скрытия очищается -- спрашиваем
    # сразу, а не после всех остальных проверок.
    said = page.evaluate(
        "() => (document.querySelector('.toast') || {}).textContent || ''")
    page.wait_for_timeout(2500)

    back = page.evaluate("""async (name) => {
      const list = await fetch('/api/decks').then(r => r.json());
      const d = list.decks.find((x) => x.name === name);
      if (!d) return null;
      const full = await fetch('/api/decks/' + d.id).then(r => r.json());
      const cards = full.deck.entries || full.deck.cards || [];
      return cards.map((c) => c.name + '/' + c.section).sort();
    }""", DECK)
    ok(back is not None, "колода вернулась из файла", back)
    if back:
        ok("Fog/main" in back and "Root Snare/side" in back,
           "и вернулась целиком, с разделами", back)

    ok("еренес" in said or "ерено" in said,
       "сказано, что именно перенеслось", repr(said[:90]))

    # ------------------------------------------------- чужой файл не берём
    bad = os.path.join(os.path.dirname(path), "не-наш.json")
    with open(bad, "w", encoding="utf-8") as fh:
        json.dump({"hello": "world"}, fh)
    page.set_input_files("#transfer-load", bad)
    page.wait_for_timeout(3000)
    toast = page.evaluate(
        "() => (document.querySelector('.toast') || {}).textContent || ''")
    ok("не вышел" in toast or "не файл переноса" in toast,
       "чужой файл отвергнут со словами, а не молча", repr(toast[:90]))

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    page.evaluate(CLEAN, DECK)
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
