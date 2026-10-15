"""Browser check: снятие отметки о заказе — видно, что оно опасное, и обратимо.

Обход записал это как «стирает заказ молча и навсегда». Замер подтвердил
только половину: отмена есть и работает — тост держится девять секунд и
возвращает заказ из снимка. Неверным было слово «навсегда».

Осталось то, что подтвердилось: кнопка выглядела ровно как две соседние,
которые ничего не теряют («получено → в коллекцию», «обновить отметку»).

Проверяется: кнопка отличается от соседок, говорит, что сделает, и её
действие откатывается.

Сценарий заводит свой заказ «ПРОВЕРКА-…» и убирает его за собой.

    .venv/Scripts/python.exe tests/ui_order_undo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
SELLER = "ПРОВЕРКА-снятие отметки"


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


PENDING = """async (seller) => {
  const r = await fetch('/api/orders').then((x) => x.json());
  return (r.orders || []).filter((o) => o.status === 'pending' &&
    (!seller || o.seller_name === seller)).map((o) => o.id);
}"""

MAKE = """async (seller) => {
  const r = await fetch('/api/orders', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({seller_name: seller, seller_kind: 'user',
      items: [{name: 'Lightning Bolt', quantity: 2, unit_price: 120}]})
  }).then((x) => x.json());
  return (r.orders || []).filter((o) => o.seller_name === seller).length;
}"""

CLEAN = """async (seller) => {
  const r = await fetch('/api/orders').then((x) => x.json());
  for (const o of (r.orders || []).filter((x) => x.seller_name === seller)) {
    await fetch('/api/orders/' + o.id + '/remove',
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
  }
}"""

print("=== снятие отметки о заказе ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)

    page.evaluate(CLEAN, SELLER)
    page.evaluate(MAKE, SELLER)
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(2500)

    btn = page.evaluate("""(seller) => {
      const box = [...document.querySelectorAll('.pending-order')]
        .find((d) => d.textContent.includes(seller));
      if (!box) return null;
      const kill = box.querySelector('[data-remove-order]');
      const safe = box.querySelector('[data-receive-order]');
      if (!kill || !safe) return null;
      return {
        опасная: {класс: kill.className, цвет: getComputedStyle(kill).color,
                  подсказка: kill.title},
        безобидная: {класс: safe.className, цвет: getComputedStyle(safe).color},
      };
    }""", SELLER)
    ok(btn is not None, "заказ виден в «Заказано, ожидает получения»")

    if btn:
        ok("danger" in btn["опасная"]["класс"],
           "у кнопки «Снять отметку» своё оформление", btn["опасная"]["класс"])
        ok(btn["опасная"]["цвет"] != btn["безобидная"]["цвет"],
           "она отличается цветом от соседней безобидной",
           "%s против %s" % (btn["опасная"]["цвет"], btn["безобидная"]["цвет"]))
        ok(len(btn["опасная"]["подсказка"] or "") > 20,
           "подсказка объясняет, что будет", repr(btn["опасная"]["подсказка"]))

    page.evaluate("""(seller) => {
      const box = [...document.querySelectorAll('.pending-order')]
        .find((d) => d.textContent.includes(seller));
      const kill = box && box.querySelector('[data-remove-order]');
      if (kill) kill.click();
    }""", SELLER)
    page.wait_for_timeout(2000)

    gone = page.evaluate(PENDING, SELLER)
    ok(not gone, "заказ снят", gone)

    toast = page.evaluate("""() => {
      const t = document.querySelector('.toast');
      if (!t || !t.classList.contains('show')) return null;
      return {текст: t.textContent.trim(),
              отмена: [...t.querySelectorAll('button')]
                .some((b) => /отмен/i.test(b.textContent))};
    }""")
    ok(toast is not None and toast["отмена"],
       "сказано, что произошло, и предложена отмена", toast)

    if toast and toast["отмена"]:
        page.evaluate("""() => {
          const b = [...document.querySelectorAll('.toast button')]
            .find((x) => /отмен/i.test(x.textContent));
          if (b) b.click();
        }""")
        page.wait_for_timeout(2500)
    back = page.evaluate(PENDING, SELLER)
    ok(bool(back), "«Отменить» возвращает заказ", back)

    shown = page.evaluate("""(seller) => [...document.querySelectorAll('.pending-order')]
        .some((d) => d.textContent.includes(seller))""", SELLER)
    ok(shown, "и он снова на экране, без перезагрузки страницы")

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    page.evaluate(CLEAN, SELLER)
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
