"""Browser check: числа в шапке результата охоты не спорят друг с другом.

Проход пользователя нашёл пять расхождений подряд, и все — про смысл чисел:

* **П2** — «Lightning Bolt [4] из 4» сверху и «не хватает 2 шт.» красным
  внизу. Поле — это «сколько хочу», но читается как «столько нашлось»;
* **П3** — «итог: 750 ₽» без единого слова о пересылке;
* **П4** — отказ от предложения перетасовывает план целиком: сумма меньше,
  карт тоже меньше, и ничто на это не указывает;
* **П5** — «вы отказались: 4» после отказа от одной карты (считались её
  объявления, а единица не называлась);
* **П6** — «✓ заказ оформлен» на продавце, у которого в плане теперь другое.

Сценарий запускает охоту в песочнице с подменённым клиентом topdeck. На
настоящем сервере он тоже проходит, но тогда это настоящие запросы — его
место в наборе рядом с остальными `ui_*`, которые гоняются по песочнице.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_hunt_head.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
WANTS = "4 Lightning Bolt\n2 Sol Ring\n3 Counterspell\n1 Brainstorm"


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


def head(page):
    return page.evaluate(
        "() => document.querySelector('#hunt-meta').textContent.replace(/\\s+/g, ' ').trim()")


print("=== шапка результата охоты ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)

    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(1200)
    page.evaluate("""(text) => {
      const t = document.querySelector('#hunt-wants');
      t.value = text;
      t.dispatchEvent(new Event('input', {bubbles: true}));
    }""", WANTS)
    page.evaluate("() => document.querySelector('#hunt-btn').click()")
    page.wait_for_timeout(9000)

    got = head(page)
    ok("берём" in got and re.search(r"берём \d+ из \d+ шт", got) is not None,
       "сказано, сколько копий привезут из скольких нужных", got[:90])

    plan = page.evaluate("""() => {
      if (!lastPlan) return null;
      let taken = 0;
      for (const lot of lastPlan.lots || []) {
        for (const it of lot.items || []) taken += it.quantity || 0;
      }
      return {взято: taken, итог: lastPlan.total, продавцов: lastPlan.sellers};
    }""")
    m = re.search(r"берём (\d+) из (\d+) шт", got)
    ok(plan is not None and m is not None and int(m.group(1)) == plan["взято"],
       "и это число сходится с самим планом",
       "в шапке %s, в плане %s" % (m.group(1) if m else "?",
                                   plan["взято"] if plan else "?"))

    ok("без пересылки" in got,
       "про пересылку сказано прямо у суммы", got[:120])
    ok("итог за карты" in got, "и сумма названа тем, что она есть")

    chips = page.evaluate("""() => [...document.querySelectorAll('.wantchip')]
        .filter((c) => !c.classList.contains('off'))
        .map((c) => c.textContent.replace(/\\s+/g, ' ').trim())""")
    ok(all("брать" in c for c in chips) if chips else False,
       "у поля в чипе написано, что оно значит", chips[:2])
    ok(all("нужных" in c for c in chips) if chips else False,
       "и что второе число — это сколько нужно")

    short = page.evaluate("""() => {
      const c = [...document.querySelectorAll('.wantchip')]
        .find((x) => /нашлось/.test(x.textContent));
      return c ? c.textContent.replace(/\\s+/g, ' ').trim() : null;
    }""")
    if short is not None:
        ok("нашлось" in short,
           "а если план закрыл не всё — сказано, сколько нашлось", short)

    # --------------------------------------------------- отказ меняет картину
    before = page.evaluate("""() => {
      let taken = 0;
      for (const lot of lastPlan.lots || []) {
        for (const it of lot.items || []) taken += it.quantity || 0;
      }
      return {взято: taken, итог: lastPlan.total};
    }""")
    pressed = page.evaluate("""() => {
      const b = document.querySelector('#hunt-plan [data-skip-offer]');
      if (!b) return false;
      b.click();
      return true;
    }""")
    ok(pressed, "в плане есть отказ от предложения")
    if pressed:
        page.wait_for_timeout(5000)
        after_head = head(page)
        after = page.evaluate("""() => {
          let taken = 0;
          for (const lot of lastPlan.lots || []) {
            for (const it of lot.items || []) taken += it.quantity || 0;
          }
          return {взято: taken, итог: lastPlan.total};
        }""")
        changed = (after["взято"] != before["взято"]
                   or after["итог"] != before["итог"])
        ok(not changed or "после отказа" in after_head,
           "перестроенный план объясняет, что изменилось",
           "было %s, стало %s; шапка: %s" % (before, after, after_head[:80]))

        refused = page.evaluate("""() => {
          const t = document.querySelector('#hunt-meta').textContent;
          const m = t.match(/вы отказались от (\\d+) ([^ ·]+)/);
          return m ? [m[1], m[2]] : null;
        }""")
        ok(refused is not None and refused[1].startswith("предложени"),
           "у счётчика отказов названа единица — предложения, а не карты",
           refused)
        ok(refused is None or refused[1] != "предложение",
           "и в правильном падеже: «от 1 предложения»", refused)

    # ------------------------------------ П6: заказ разошёлся с планом
    # Расклад, в котором продавец остаётся в плане, но с другим составом,
    # в песочнице не подогнать: выдуманные предложения перетасовывают план
    # целиком. Поэтому спрашиваем саму функцию -- она и решает, что показать.
    note = page.evaluate("""() => {
      if (typeof orderDiffNote !== 'function') return null;
      const order = {total: 215, items: [
        {name: 'Lightning Bolt', quantity: 1},
        {name: 'Sol Ring', quantity: 1}]};
      const lot = {total: 375, items: [
        {want: 'Lightning Bolt', quantity: 2},
        {want: 'Counterspell', quantity: 1}]};
      const div = document.createElement('div');
      div.innerHTML = orderDiffNote(order, lot);
      return div.textContent.replace(/\\s+/g, ' ').trim();
    }""")
    ok(note is not None, "разницу заказа и плана есть кому посчитать")
    if note:
        ok("заказано" in note and "215" in note,
           "сказано, на какую сумму заказ вправду оформлен", note)
        ok("в плане сейчас" in note and "375" in note,
           "и что в плане стоит теперь", note)
        ok("добавилось" in note or "ушло" in note or "количество" in note,
           "и чем состав отличается", note)

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
