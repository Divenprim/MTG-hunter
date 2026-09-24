"""Browser check: первый экран, пустая выдача и узкий экран.

Три вещи, которые видит человек раньше всего и которые дольше всего были
никакими:

  * **первый экран**. Программа открывалась на поиске с пустой сеткой -- ни
    слова о том, что это и с чего начать. Теперь здороваемся и показываем
    примеры запросов, по которым можно нажать;
  * **пустая выдача**. «Ничего не найдено» мелкой строкой не отвечает на
    вопрос «я ошибся в имени или перемудрил с фильтрами». Теперь показан сам
    запрос, число условий и выход -- искать только по имени;
  * **узкий экран**. Таблицы группы, учёт коллекции и матрица исполнений не
    помещались в телефон и растягивали страницу вбок на три сотни пикселей.

Плюс постоянная проверка целей под палец: на сенсорном экране всё, во что надо
попадать, не мельче 32 px.

    .venv/Scripts/python.exe tests/ui_firstrun.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


WIDE = """() => {
  return Math.max(0, document.documentElement.scrollWidth - window.innerWidth);
}"""

SMALL = """() => {
  const out = [];
  document.querySelectorAll("button, .tab, select, a").forEach((el) => {
    if (el.classList.contains("linkish")) return;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    const side = Math.min(r.width, r.height);
    if (side < 32) {
      out.push((el.className || el.tagName) + " " + Math.round(side) + "px: " +
               (el.textContent || "").trim().slice(0, 16));
    }
  });
  return out;
}"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    print("=== первый экран ===")
    ctx = browser.new_context(viewport={"width": 1400, "height": 950})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    page.evaluate("() => localStorage.clear()")
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1500)

    check("на пустом поиске программа здоровается",
          page.locator(".welcome").count() == 1)
    check("и показывает примеры запросов",
          page.locator(".welcome [data-try]").count() >= 3,
          str(page.locator(".welcome [data-try]").count()))
    check("в приветствии сказано, что наружу ничего не уходит",
          "наружу" in (page.text_content(".welcome") or "").lower())

    query = page.locator(".welcome [data-try]").first.get_attribute("data-try")
    page.locator(".welcome [data-try]").first.click()
    page.wait_for_selector("#search-results .card", timeout=30000)
    check("нажатие на пример запускает поиск",
          page.input_value("#search-q") == query,
          page.input_value("#search-q"))

    print()
    print("=== пустая выдача объясняет себя ===")
    page.fill("#search-q", "t:creature c:g mv<=0 зззз")
    page.keyboard.press("Enter")
    page.wait_for_selector(".nothing", timeout=30000)
    said = page.text_content(".nothing") or ""
    check("показан сам запрос", "зззз" in said)
    check("сказано, сколько условий", "Условий в запросе" in said, said[:60])
    check("есть выход — искать только по имени",
          page.locator("[data-onlyname]").count() == 1)
    page.click("[data-onlyname]")
    page.wait_for_timeout(2000)
    check("и он оставляет только имя",
          page.input_value("#search-q") == "зззз",
          page.input_value("#search-q"))
    ctx.close()

    print()
    print("=== узкий экран не растягивает страницу ===")
    ctx = browser.new_context(viewport={"width": 420, "height": 900},
                              has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")

    for tab, label in (("collection", "коллекция"), ("hunt", "охота"),
                       ("builder", "билдер"), ("favourites", "избранное")):
        page.click('.tab[data-tab="%s"]' % tab)
        page.wait_for_timeout(1500)
        check("%s помещается в телефон" % label,
              page.evaluate(WIDE) <= 2, "лишних %d px" % page.evaluate(WIDE))

    page.click('.tab[data-tab="family"]')
    page.wait_for_timeout(1200)
    page.evaluate("() => famOpen('turbo fog')")
    page.wait_for_timeout(2500)
    check("матрица исполнений помещается",
          page.evaluate(WIDE) <= 2, "лишних %d px" % page.evaluate(WIDE))

    page.evaluate("() => fgShow('buy')")
    page.wait_for_selector("#fam-group .fgtable", timeout=60000)
    page.wait_for_timeout(1200)
    check("список покупок помещается",
          page.evaluate(WIDE) <= 2, "лишних %d px" % page.evaluate(WIDE))
    check("и читается карточками, а не таблицей",
          page.evaluate("""() => {
            const td = document.querySelector('#fam-group .fgtable td');
            return td ? getComputedStyle(td).display === 'flex' : false;
          }"""))

    print()
    print("=== пальцем попасть можно ===")
    small = page.evaluate(SMALL)
    check("все цели крупнее 32 px", not small, "; ".join(small[:4]))

    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    ctx.close()
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
