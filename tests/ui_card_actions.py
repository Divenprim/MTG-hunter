"""Browser check: с картой можно сделать всё, не уходя с экрана.

Обход по мерке «сколько действий до цели» нашёл четыре места, где программа
заставляет уйти и вернуться, хотя знает ответ:

* **У1** — «В избранное» молча кладёт в первую папку: выбрать её в окне было
  нельзя, и путь в нужную выходил в девять действий против четырёх;
* **У2** — «в коллекцию» в окне карты не было вовсе; единственным способом
  отметить пришедшую карту была правка списка из 87 строк и перезапись всей
  коллекции, хотя сервер умеет добавлять по одной;
* **У3** — ни в выдаче, ни в окне не сказано, что карта уже у тебя, хотя
  программа пишет «коллекция: 105 шт.» в шапке;
* **У6** — в «Нехватках» у предложения есть «+ в колоду», но нет «+ в охоту».

Сценарий заводит свою папку «ПРОБА …», свою карту в коллекции и убирает их
за собой.

    .venv/Scripts/python.exe tests/ui_card_actions.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
FOLDER = "ПРОБА папка окна карты"
CARD = "Lightning Bolt"


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


def here(page, selector):
    """Защита: на непочиненном коде сценарий должен отчитаться, а не упасть."""
    return page.evaluate("(s) => !!document.querySelector(s)", selector)


MAKE_FOLDER = """async (name) => {
  await fetch('/api/favourites/folders', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name})});
  const r = await fetch('/api/favourites').then((x) => x.json());
  return (r.favourites.folders || []).map((f) => [f.id, f.name]);
}"""

CLEAN_FOLDER = """async (name) => {
  const r = await fetch('/api/favourites').then((x) => x.json());
  for (const f of (r.favourites.folders || []).filter((x) => x.name === name)) {
    await fetch('/api/favourites/folders/' + f.id, {method: 'DELETE'});
  }
}"""

FOLDERS = """async () => {
  const r = await fetch('/api/favourites').then((x) => x.json());
  return (r.favourites.folders || []).map(
    (f) => [f.name, (f.cards || []).map((c) => c.name)]);
}"""

OWNED = """async (name) => {
  const r = await fetch('/api/collection').then((x) => x.json());
  return (r.collection || {})[name] || 0;
}"""

SET_OWNED = """async (args) => {
  const [name, n] = args;
  const r = await fetch('/api/collection').then((x) => x.json());
  const coll = r.collection || {};
  if (n > 0) coll[name] = n; else delete coll[name];
  const text = Object.keys(coll).map((k) => coll[k] + ' ' + k).join('\\n');
  await fetch('/api/collection', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: text})});
}"""

print("=== что можно сделать с картой, не уходя с экрана ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)

    page.evaluate(CLEAN_FOLDER, FOLDER)
    folders = page.evaluate(MAKE_FOLDER, FOLDER)
    was_owned = page.evaluate(OWNED, CARD)
    mine = [f for f in folders if f[1] == FOLDER]
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1800)

    # ------------------------------------------------------------ У3: метка
    page.fill("#search-q", CARD)
    page.keyboard.press("Enter")
    page.wait_for_timeout(3500)
    page.evaluate(SET_OWNED, [CARD, 3])
    page.evaluate("() => (typeof loadOwned === 'function') ? loadOwned() : null")
    page.wait_for_timeout(1200)

    tile = page.evaluate("""(nm) => {
      const c = [...document.querySelectorAll('#search-results .card')]
        .find((x) => x.dataset.name === nm);
      const h = c && c.querySelector('.have');
      return h ? h.textContent.trim() : null;
    }""", CARD)
    ok(tile is not None and "3" in tile,
       "в выдаче видно, что карта уже в коллекции", tile)

    page.evaluate("""(nm) => {
      const c = [...document.querySelectorAll('#search-results .card')]
        .find((x) => x.dataset.name === nm);
      if (c) c.click();
    }""", CARD)
    page.wait_for_timeout(2500)

    rows = page.evaluate("""() => [...document.querySelectorAll('#modal-body .qtyadd')]
        .map((r) => (r.querySelector('span') || {}).textContent.trim())""")
    ok(rows == ["В охоту:", "В избранное:", "В колоду:", "В коллекцию:"],
       "в окне карты четыре ряда: охота, избранное, колода, коллекция", rows)
    ok("3" in (page.evaluate(
        "() => (document.querySelector('#modal-have') || {}).textContent") or ""),
       "и сказано, сколько копий уже есть")

    # ------------------------------------------------------- У1: папка на выбор
    ok(here(page, "#modal-fav"), "папку избранного можно выбрать в окне")
    names = page.evaluate("""() => {
      const s = document.querySelector('#modal-fav');
      return s ? [...s.options].map((o) => o.textContent) : [];
    }""")
    ok(any(FOLDER in n for n in names), "в списке все папки", names[:4])

    if here(page, "#modal-fav") and mine:
        page.select_option("#modal-fav", mine[0][0])
        page.wait_for_timeout(400)
        page.evaluate("""() => {
          const b = document.querySelector('.add-fav[data-n="2"]');
          if (b) b.click();
        }""")
        page.wait_for_timeout(2000)
    got = page.evaluate(FOLDERS)
    picked = [f for f in got if f[0] == FOLDER]
    ok(bool(picked) and CARD in (picked[0][1] if picked else []),
       "карта легла в выбранную папку, а не в первую", got[:3])
    first_folder = got[0] if got else None
    ok(first_folder is None or first_folder[0] == FOLDER
       or CARD not in first_folder[1],
       "в первую папку при этом ничего не попало", first_folder)

    # ---------------------------------------------------- У2: в коллекцию
    before = page.evaluate(OWNED, CARD)
    ok(here(page, ".add-coll"), "в окне есть «В коллекцию»")
    if here(page, ".add-coll"):
        page.evaluate("""() => {
          const b = document.querySelector('.add-coll[data-n="1"]');
          if (b) b.click();
        }""")
        page.wait_for_timeout(2500)
    after = page.evaluate(OWNED, CARD)
    ok(after == before + 1, "одна копия добавилась к коллекции",
       "было %s, стало %s" % (before, after))
    ok("4" in (page.evaluate(
        "() => (document.querySelector('#modal-have') || {}).textContent") or ""),
       "строка в окне пересчиталась сразу")

    page.evaluate("() => closeModal()")
    page.wait_for_timeout(700)
    ok("4" in (page.evaluate("""(nm) => {
          const c = [...document.querySelectorAll('#search-results .card')]
            .find((x) => x.dataset.name === nm);
          const h = c && c.querySelector('.have');
          return h ? h.textContent : '';
        }""", CARD) or ""),
       "и метка в выдаче тоже — без нового поиска")

    # ------------------------------------------------- У6: в охоту из нехваток
    decks = page.evaluate(
        "async () => (await fetch('/api/decks').then(r => r.json())).decks")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(1200)
    if decks:
        page.evaluate("(id) => bdOpen(id)", decks[0]["id"])
        page.wait_for_timeout(2500)
        page.evaluate("""() => {
          const b = document.querySelector('[data-act=gaps]');
          if (b) b.click();
        }""")
        page.wait_for_timeout(2500)
    ok(here(page, "#bd-gaps .gaphunt"),
       "у предложения в «Нехватках» есть «+ в охоту»",
       page.evaluate("() => document.querySelectorAll('#bd-gaps .gapadd').length"))

    if here(page, "#bd-gaps .gaphunt"):
        wanted = page.evaluate(
            "() => document.querySelector('#bd-gaps .gaphunt').dataset.hunt")
        page.evaluate("() => document.querySelector('#bd-gaps .gaphunt').click()")
        page.wait_for_timeout(1500)
        inlist = page.evaluate(
            "(nm) => (document.querySelector('#hunt-wants').value || '').includes(nm)",
            wanted)
        ok(inlist, "нажатие кладёт карту в список охоты", wanted)

    # ------------------------------------------------- У5: про меню сказано
    ok(here(page, "#bd-menu-hint"), "над колодой сказано про меню карты")
    dots = page.evaluate("""() => {
      const b = document.querySelector('.cardmore');
      return b ? parseFloat(getComputedStyle(b).opacity) : null;
    }""")
    ok(dots is not None and dots > 0.2,
       "значок «…» виден без наведения мыши", dots)

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))

    page.evaluate(CLEAN_FOLDER, FOLDER)
    page.evaluate(SET_OWNED, [CARD, was_owned])
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
