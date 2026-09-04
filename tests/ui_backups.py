"""Browser check: favourites survive, and a deletion can be undone from the UI.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_backups.py

Works on the live store on purpose -- that is what it is verifying -- but only
ever adds and then removes its own folder, and every step is snapshotted.
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_context(viewport={"width": 1500, "height": 950}).new_page()
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    p.on("dialog", lambda d: d.accept())
    p.goto(BASE, wait_until="networkidle")

    p.click('.tab[data-tab="favourites"]')
    p.wait_for_timeout(1000)
    folders_before = p.locator("#fav-folders .favfolder").count()
    check("favourites load", folders_before >= 1, "%d folders" % folders_before)

    print()
    print("=== the backup panel exists and is populated ===")
    p.click("#fav-backups-box summary")
    p.wait_for_timeout(600)
    snaps = p.locator("#fav-backups .backup").count()
    check("snapshots are listed", snaps >= 1, "%d snapshots" % snaps)

    print()
    print("=== create a folder with a card, then delete it ===")
    p.fill("#fav-newfolder", "Откат UI")
    p.press("#fav-newfolder", "Enter")
    p.wait_for_function(
        "() => Array.from(document.querySelectorAll('#fav-folders .favfolder'))"
        ".some(e => e.textContent.includes('Откат UI'))", timeout=20000)

    p.click('.tab[data-tab="search"]')
    p.fill("#search-q", "Sol Ring")
    p.wait_for_function(
        "() => { const m=document.querySelector('#search-meta');"
        " return m && (m.textContent||'').indexOf('показано') >= 0; }", timeout=30000)
    p.locator("#search-results .card").first.click()
    p.wait_for_timeout(900)
    p.locator(".add-fav").first.click()
    p.wait_for_timeout(1200)
    p.keyboard.press("Escape")

    p.click('.tab[data-tab="favourites"]')
    p.wait_for_timeout(800)
    cards = p.locator("#fav-cards .favrow").count()
    check("card saved into the new folder", cards == 1, "%d rows" % cards)

    p.click("#fav-delete")
    p.wait_for_function(
        "(n) => document.querySelectorAll('#fav-folders .favfolder').length === n",
        arg=folders_before, timeout=20000)
    gone = not any("Откат UI" in t for t in
                   p.locator("#fav-folders .favfolder").all_text_contents())
    check("folder is gone", gone)

    print()
    print("=== undo it from the UI ===")
    p.click("#fav-backups-box summary") if p.locator("#fav-backups .backup").count() == 0 else None
    p.wait_for_timeout(500)
    p.locator("#fav-backups [data-restore]").first.click()
    p.wait_for_function(
        "() => Array.from(document.querySelectorAll('#fav-folders .favfolder'))"
        ".some(e => e.textContent.includes('Откат UI'))", timeout=25000)
    check("folder came back", True)

    names = p.locator("#fav-folders .favfolder").all_text_contents()
    check("the restored folder still has its card",
          any("Откат UI" in t and "1" in t for t in names), str(names))

    print()
    print("=== cleanup ===")
    for _ in range(3):
        titles = p.locator("#fav-folders .favfolder").all_text_contents()
        target = next((i for i, t in enumerate(titles) if "Откат UI" in t), None)
        if target is None:
            break
        p.locator("#fav-folders .favfolder").nth(target).click()
        p.wait_for_timeout(400)
        p.click("#fav-delete")
        p.wait_for_timeout(1200)
    left = [t for t in p.locator("#fav-folders .favfolder").all_text_contents()
            if "Откат UI" in t]
    check("test folder removed", not left, str(left))

    print()
    check("no console errors", not errors, "; ".join(errors[:3]))
    p.screenshot(path="tests/ui_backups.png")
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL BACKUP CHECKS PASSED")
