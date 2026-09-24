"""Browser check: манабаза колоды и наборы земель в поиске.

Два вопроса, которые раньше решались на глаз:

  * **сколько и каких земель нужно этой колоде**. Панель «Манабаза» в билдере
    считает источники по цветам, сравнивает с требованием самой требовательной
    карты цвета и предлагает, чем добить -- в пределах заданной суммы, с
    пометкой, входит земля развёрнутой или нет;
  * **не держится ли на землях победа**. Турбофог выигрывает десятью Вратами,
    и советовать ему удобные двойные значит предлагать разобрать колоду.
    Панель обязана сперва сказать про план, а предлагать -- то, что план не
    ломает;
  * **что купить наборами**. В поиске есть режим «наборы земель»: циклы,
    известные связки и комбо из земель, с ценой за комплект и за плейсет.
    Отсюда же весь набор уходит в охоту по четыре штуки.

Сценарий заводит свои колоды и удаляет их в конце; список охоты возвращает
как был.

    .venv/Scripts/python.exe tests/ui_manabase.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

# Куда стучаться. По умолчанию -- обычный запуск; MTGH_UI_BASE нужна,
# когда на этом порту уже работает другая копия программы (скажем,
# запущенная по https для планшета).
BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
DECK = "UI Манабаза"
GATES_DECK = "UI Врата"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


# Двухцветная колода с требовательной картой: Cryptic Command просит три синих
# значка к четвёртому ходу, и одними горами это не закрыть.
SETUP = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: [
      {name: 'Island', quantity: 8, section: 'main'},
      {name: 'Mountain', quantity: 8, section: 'main'},
      {name: 'Cryptic Command', quantity: 4, section: 'main'},
      {name: 'Lightning Bolt', quantity: 4, section: 'main'}]})});
  return made.deck.id;
}"""

# Колода, в которой земли -- не обслуга, а замысел: Maze's End выигрывает
# десятью Вратами с разными именами. Врат здесь три, то есть план ещё не
# собран, и панель обязана это сказать, а не советовать удобные двойные.
GATES = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: [
      {name: "Maze's End", quantity: 4, section: 'main'},
      {name: 'Azorius Guildgate', quantity: 4, section: 'main'},
      {name: 'Boros Guildgate', quantity: 4, section: 'main'},
      {name: 'Dimir Guildgate', quantity: 4, section: 'main'},
      {name: 'Forest', quantity: 6, section: 'main'},
      {name: 'Fog', quantity: 4, section: 'main'}]})});
  return made.deck.id;
}"""

CLEAN = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1100}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    hunt_before = page.evaluate("() => $('#hunt-wants').value")
    deck_id = page.evaluate(SETUP, DECK)

    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(700)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(1500)

    print("=== разбор манабазы ===")
    page.evaluate("""() => {
      document.querySelector('#bd-actions [data-act="manabase"]').click();
    }""")
    page.wait_for_selector("#bd-manabase .mbcolor", timeout=60000)
    rep = page.evaluate("() => mbData.report")
    check("панель посчитала цвета",
          len(rep["colors"]) >= 2, str(len(rep["colors"])))

    blue = [c for c in rep["colors"] if c["color"] == "U"][0]
    check("синих источников посчитано верно", blue["have"] == 8, str(blue["have"]))
    check("требование берётся по самой требовательной карте",
          (blue.get("worst") or {}).get("name") == "Cryptic Command",
          str((blue.get("worst") or {}).get("name")))
    check("и его не хватает", blue["short"] > 0, "не хватает %d" % blue["short"])
    check("видно, как входят земли",
          rep["entry"]["open"] == 16, str(rep["entry"]))

    print()
    print("=== чем добить ===")
    check("двойные и тройные предложены",
          page.locator("#bd-manabase .mblands .mbland").count() > 0)
    first = page.evaluate("() => mbData.duals[0]")
    check("у предложенной земли видно цвета, вход и цену",
          bool(first["covers"]) and bool(first["entry"]),
          "%s · %s · $%s" % (first["covers"], first["entry"], first["usd"]))
    check("земли за доплату вынесены отдельно",
          all(d.get("reliable") == "direct" for d in page.evaluate("() => mbData.duals")))
    check("фетчи считаются отдельно",
          all(f["produces"] == "" for f in page.evaluate("() => mbData.fetch")))

    cheap = page.evaluate("() => mbData.duals.filter(d => d.usd !== null).length")
    page.evaluate("""() => {
      const box = document.getElementById('mb-budget');
      box.value = '0.3';
      box.dispatchEvent(new Event('change', {bubbles: true}));
    }""")
    page.wait_for_function("() => mbData && mbData.budget === 0.3", timeout=30000)
    over = [d for d in page.evaluate("() => mbData.duals")
            if d["usd"] is not None and d["usd"] > 0.3]
    check("порог цены соблюдается", not over,
          "; ".join(d["name"] for d in over[:3]))

    print()
    print("=== земля добавляется в колоду ===")
    name = page.evaluate("() => (mbData.duals[0] || {}).name")
    if name:
        page.evaluate("""() => {
          document.querySelector('#bd-manabase [data-mbadd]').click();
        }""")
        page.wait_for_function("""(n) => (bdDeck.cards || []).some(
          (c) => c.name === n || ((c.card || {}).name === n))""",
          arg=name, timeout=30000)
        check("«+ в колоду» кладёт землю", True, name)
        # Разбор пересчитывается сам, но не мгновенно: правки колоды копятся
        # 150 мс, потом уходит запрос.
        try:
            page.wait_for_function("() => mbData && mbData.report.lands >= 17",
                                   timeout=30000)
            lands = page.evaluate("() => mbData.report.lands")
        except Exception:
            lands = page.evaluate("() => mbData && mbData.report.lands")
        check("и разбор пересчитался сам", lands >= 17, str(lands))

    print()
    print("=== колода, где земли и есть победа ===")
    gates_id = page.evaluate(GATES, GATES_DECK)
    page.evaluate("(id) => bdOpen(id)", gates_id)
    page.wait_for_function("(id) => bdDeck && bdDeck.id === id", arg=gates_id,
                           timeout=20000)
    page.wait_for_selector("#bd-manabase .mbplan", timeout=60000)
    plan = page.evaluate("() => mbData.report.plan[0]")
    check("план на землях распознан", plan["card"] == "Maze's End", str(plan["card"]))
    check("названо, чего и сколько нужно",
          plan["what"] == "Gate" and plan["need"] == 10 and plan["distinct"],
          "%s x%d" % (plan["what"], plan["need"]))
    check("и что план ещё не собран", not plan["ok"],
          "сейчас %d" % plan["have"])
    check("сказано, что это победа", plan["wins"])

    said = " ".join((page.locator(".mbplan").first.text_content() or "").split())
    check("подтип написан по-русски", "Врат" in said, said[:70])
    check("видно, сколько слотов занято планом",
          "занято" in said and "остаётся" in said, said[-90:])

    check("предложены только настоящие Врата",
          all("Gate" in (l["type_line"] or "").split("—")[-1]
              for l in page.evaluate("() => mbData.plan")),
          "; ".join(l["name"] for l in page.evaluate("() => mbData.plan")[:3]))
    check("Врата, которые уже в колоде, второй раз не предлагаются",
          "Azorius Guildgate" not in
          {l["name"] for l in page.evaluate("() => mbData.plan")})
    check("обычные двойные отмечены как не двигающие план",
          "плана эти земли не двигают" in
          page.evaluate("() => document.querySelector('#bd-manabase').textContent"))

    print()
    print("=== наборы земель в поиске ===")
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(500)
    page.select_option("#search-mode", "landsets")
    page.wait_for_selector(".lsset", timeout=90000)
    sets = page.evaluate("() => lsData.sets")
    check("наборы собрались", len(sets) > 5, str(len(sets)))
    check("у набора есть цена за комплект и за плейсет",
          sets[0]["usd_playset"] > 0 and sets[0]["usd_one"] > 0,
          "$%s / $%s" % (sets[0]["usd_one"], sets[0]["usd_playset"]))
    check("названия человеческие, а не слаги",
          not any(s["label"].startswith("cycle-") for s in sets),
          "; ".join(s["label"] for s in sets[:2]))

    page.evaluate("""() => document.querySelector('[data-lsshow]').click()""")
    page.wait_for_selector(".lsset.open .lscard", timeout=20000)
    check("набор раскрывается картами",
          page.locator(".lsset.open .lscard").count() == sets[0]["size"],
          str(page.locator(".lsset.open .lscard").count()))

    print()
    print("=== набор уходит в охоту по четыре ===")
    page.evaluate("""() => document.querySelector('[data-lshunt="4"]').click()""")
    page.wait_for_timeout(900)
    lines = [l.strip() for l in
             page.evaluate("() => $('#hunt-wants').value").splitlines() if l.strip()]
    wanted = {c["name"] for c in sets[0]["cards"]}
    got = {l.split(" ", 1)[1] for l in lines if " " in l}
    check("все карты набора в списке охоты", wanted <= got,
          "; ".join(sorted(wanted - got))[:60])
    check("и каждой по четыре",
          all(l.startswith("4 ") for l in lines if l.split(" ", 1)[-1] in wanted),
          "; ".join(lines[:3]))
    check("открылась сама охота",
          page.evaluate("() => document.querySelector('.tab.active').dataset.tab")
          == "hunt")

    print()
    print("=== уборка ===")
    page.evaluate("""(text) => {
      $('#hunt-wants').value = text;
      store.set('hunt', text);
    }""", hunt_before)
    page.evaluate("() => { store.set('searchMode', 'cards'); }")
    page.evaluate(CLEAN, DECK)
    page.evaluate(CLEAN, GATES_DECK)
    left = [d for d in get("/api/decks")["decks"]
            if d["name"] in (DECK, GATES_DECK)]
    check("свои колоды удалены", not left,
          "; ".join(d["name"] for d in left))
    check("список охоты возвращён",
          page.evaluate("() => $('#hunt-wants').value") == hunt_before)
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
