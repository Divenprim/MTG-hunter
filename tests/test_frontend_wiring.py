"""Static checks on the frontend wiring.

We have no JS runtime here, and the realistic failure is not exotic: app.js
looks up an element by id, gets null, and calling addEventListener on it throws
during initial evaluation -- which kills the whole script and leaves a blank UI.
So: every id/class app.js reaches for must exist in index.html, and every API
path it calls must be a route the backend actually serves.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
CSS = open(os.path.join(ROOT, "web", "style.css"), encoding="utf-8").read()
JS_BUILDER = open(os.path.join(ROOT, "web", "builder.js"), encoding="utf-8").read()
JS_REC = open(os.path.join(ROOT, "web", "recommend.js"), encoding="utf-8").read()
JS_COMBO = open(os.path.join(ROOT, "web", "combos.js"), encoding="utf-8").read()
JS_UX = open(os.path.join(ROOT, "web", "ux.js"), encoding="utf-8").read()
JS_FAV = open(os.path.join(ROOT, "web", "favourites.js"), encoding="utf-8").read()
JS_DRAG = open(os.path.join(ROOT, "web", "dragdrop.js"), encoding="utf-8").read()
with open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8") as _fh:
    JS_MAIN = _fh.read()   # the server side these checks reach into

def _ids(text):
    return set(re.findall(r'id="([^"{}]+)"', text))


def _classes(text):
    out = set()
    for group in re.findall(r'class="([^"{}]+)"', text):
        out.update(group.split())
    return out


# app.js builds part of the DOM itself (the card modal, offer rows, deck rows),
# so an element it later queries may be declared in a JS template string rather
# than in index.html. Both count as "exists".
HTML_IDS = _ids(HTML) | _ids(JS)
HTML_CLASSES = _classes(HTML) | _classes(JS)


class TestSelectors(unittest.TestCase):
    def test_every_id_selector_exists_in_html(self):
        """$("#foo") must find something, or the script dies on load."""
        used = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', JS))
        self.assertTrue(used, "no id selectors found -- did the regex break?")
        missing = sorted(used - HTML_IDS)
        self.assertEqual(missing, [], "app.js references ids absent from index.html: %s" % missing)

    def test_every_class_selector_exists(self):
        """$$(".foo") over a class that never appears is dead code at best."""
        used = set(re.findall(r'\$\$\("\.([A-Za-z0-9_-]+)(?::[a-z]+)?"\)', JS))
        missing = sorted(used - HTML_CLASSES)
        self.assertEqual(missing, [], "app.js queries classes absent from index.html: %s" % missing)

    def test_panels_exist_for_every_tab(self):
        """Tabs switch panels by id convention panel-<tab>."""
        tabs = set(re.findall(r'data-tab="([^"]+)"', HTML))
        self.assertTrue(tabs)
        for tab in tabs:
            self.assertIn("panel-" + tab, HTML_IDS, "tab %r has no matching panel" % tab)


class TestApiContract(unittest.TestCase):
    def test_js_only_calls_routes_that_exist(self):
        from app.main import app

        static_routes = set()
        prefix_routes = set()
        for r in app.routes:
            path = getattr(r, "path", None)
            if not path:
                continue
            if "{" in path:
                # "/api/printings/{oracle_id}" -- JS builds it as a prefix plus
                # an encoded value, so compare against the part before the param.
                prefix_routes.add(path[: path.index("{")])
            else:
                static_routes.add(path)

        called = set(re.findall(r'["\'](/api/[A-Za-z0-9/_-]+)', JS))
        self.assertTrue(called, "no API calls found in app.js")
        missing = sorted(
            p for p in called
            if p not in static_routes and p not in prefix_routes
        )
        self.assertEqual(missing, [], "app.js calls routes the server does not define: %s" % missing)


class TestAssets(unittest.TestCase):
    def test_html_references_the_files_we_ship(self):
        self.assertIn("/static/style.css", HTML)
        self.assertIn("/static/app.js", HTML)

    def test_css_defines_the_classes_js_generates(self):
        """Classes created only in JS templates still need styling."""
        for cls in ("rawline", "chip", "lot", "offer", "msgbox", "unfilled", "card"):
            self.assertIn("." + cls, CSS, "style.css has no rule for .%s" % cls)


class TestHiddenActuallyHides(unittest.TestCase):
    """The `hidden` attribute is only as strong as the CSS lets it be.

    The browser rule is just `[hidden] { display: none }`, so ANY author rule
    setting `display` on the same element overrides it. That shipped once:
    `.overlay { display: flex }` kept the modal permanently over the page and
    ate every click, and `.filters-panel` / `.row` did the same for the filter
    panel and the action rows.
    """

    @staticmethod
    def _classes_with_display_rules():
        """Classes for which style.css sets `display`."""
        out = set()
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS):
            if not re.search(r"(^|[;\s])display\s*:", body):
                continue
            out.update(re.findall(r"\.([A-Za-z0-9_-]+)", selector))
        return out

    @staticmethod
    def _has_override():
        return bool(
            re.search(r"\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important", CSS, re.I)
        )

    def test_hidden_override_exists(self):
        self.assertTrue(
            self._has_override(),
            "style.css needs `[hidden] { display: none !important; }` so the "
            "hidden attribute wins over class display rules",
        )

    def test_every_hidden_element_is_really_hidable(self):
        risky = self._classes_with_display_rules()
        has_override = self._has_override()

        offenders = []
        for attrs in re.findall(r"<[^>]*hidden[^>]*>", HTML):
            classes = set()
            m = re.search(r'class="([^"]+)"', attrs)
            if m:
                classes.update(m.group(1).split())
            clash = sorted(classes & risky)
            if clash and not has_override:
                offenders.append((attrs[:70], clash))

        self.assertEqual(
            offenders, [],
            "these hidden elements carry classes whose CSS sets `display`, "
            "so they would stay visible: %s" % offenders,
        )


class TestReadingAndScanningResults(unittest.TestCase):
    """Hover preview and grid density.

    Both existed because the grid was unusable for scanning: 180px tiles meant
    six cards visible out of six hundred, and reading a card required opening a
    modal.
    """

    def test_the_preview_container_exists(self):
        self.assertIn("hoverpreview", _ids(HTML))

    def test_the_preview_never_swallows_the_pointer(self):
        """It floats over tiles, so it must not eat their clicks."""
        block = CSS[CSS.index("#hoverpreview"):]
        self.assertIn("pointer-events: none", block[:600])

    def test_the_preview_reuses_the_images_already_marked_for_clicking(self):
        # data-full/data-img are already on the plan thumbnails, favourites and
        # the printings rows; the preview picks them up instead of each
        # renderer repeating itself.
        self.assertIn("data-preview", JS)
        self.assertIn("data-full", JS)
        self.assertIn("tr[data-img]", JS)

    def test_tiles_carry_the_big_image_for_the_preview(self):
        self.assertIn("image_normal", JS)

    def test_the_density_switch_is_wired_to_the_grid(self):
        self.assertIn("search-density", _ids(HTML))
        for mode in ("tight", "snug", "roomy"):
            self.assertIn('data-density="%s"' % mode, HTML,
                          "нет кнопки плотности %s" % mode)
            self.assertIn('body[data-density="%s"]' % mode, CSS,
                          "плотность %s ничего не меняет в сетке" % mode)

    def test_the_grid_width_comes_from_the_density_variable(self):
        grid = CSS[CSS.index(".grid {"):]
        self.assertIn("var(--tile", grid[:200],
                      "сетка не читает размер плитки из переменной")

    def test_the_density_choice_is_remembered(self):
        self.assertIn('store.set("density"', JS)

    def test_quick_actions_do_not_also_open_the_card(self):
        """The tile click opens the card, so the buttons must return early."""
        self.assertIn("q-hunt", JS)
        self.assertIn("q-fav", JS)
        handler = JS[JS.index('$("#search-results").addEventListener("click"'):]
        head = handler[:1200]
        self.assertIn('closest(".q-hunt")', head)
        self.assertIn("return", head)

    def test_the_search_row_stays_reachable(self):
        toolbar = CSS[CSS.index(".toolbar {"):]
        self.assertIn("position: sticky", toolbar[:400],
                      "строка поиска уезжает при прокрутке")


class TestAddingOneMoreCard(unittest.TestCase):
    """Look first, add second -- and look at your own sellers first of all."""

    def test_the_row_and_its_parts_exist(self):
        for hook in ("hunt-addbox", "hunt-add", "hunt-add-qty",
                     "hunt-suggest", "hunt-lookup"):
            self.assertIn(hook, _ids(HTML), "нет элемента #%s" % hook)
            self.assertIn(hook, JS, "#%s не используется" % hook)

    def test_looking_and_adding_are_separate_calls(self):
        """The plan must not move until a listing is chosen."""
        self.assertIn("/api/hunt/lookup", JS)
        self.assertIn("/api/hunt/add", JS)
        self.assertIn("PRICE_NAMES_LIMIT", JS_MAIN)      # unrelated guard, kept
        self.assertIn("hunt_lookup", JS_MAIN)
        self.assertIn("hunt_add", JS_MAIN)

    def test_the_lookup_changes_nothing_on_the_server(self):
        """It holds the candidates aside instead of merging them."""
        block = JS_MAIN[JS_MAIN.index("def hunt_lookup("):JS_MAIN.index("def hunt_add(")]
        self.assertIn('setdefault("pending"', block)
        self.assertNotIn('held["wants"] =', block,
                         "просмотр не должен менять список карт")

    def test_the_sellers_already_in_the_order_come_first(self):
        self.assertIn("with_sellers_in_plan", JS_MAIN)
        self.assertIn("with_sellers_in_plan", JS)
        here = JS.index("with_sellers_in_plan")
        there = JS.index("elsewhere")
        self.assertLess(here, there, "свои продавцы должны идти первыми")

    def test_the_reason_is_spelled_out(self):
        self.assertIn("без второй пересылки", JS)
        self.assertIn("ещё одна посылка", JS)

    def test_the_choice_is_pinned_so_a_replan_keeps_it(self):
        self.assertIn("pinnedOffers.set(name, offerKey)", JS)

    def test_confirming_keeps_the_wants_box_in_step(self):
        block = JS[JS.index("async function huntAddConfirmed"):]
        self.assertIn("addToHunt(name, qty)", block[:1200])

    def test_the_lookup_rows_are_styled(self):
        for cls in (".lookbox", ".lookgroup", ".lookrow"):
            self.assertIn(cls, CSS, "нет оформления для %s" % cls)


class TestBuilderColumns(unittest.TestCase):
    """The Archidekt-shaped view: columns of stacked cards, drag to file."""

    def test_the_view_is_offered(self):
        self.assertIn('<option value="columns"', HTML)

    def test_columns_and_stacks_are_drawn(self):
        for fn in ("bdStackCard", "bdColumn"):
            self.assertIn(fn, JS_BUILDER, "нет функции %s" % fn)
        self.assertIn("bdcolumns", JS_BUILDER)

    def test_dragging_is_wired_end_to_end(self):
        """Перетаскивание на pointer events, а не на HTML5 drag-and-drop.

        HTML5-перетаскивания на iOS Safari нет вовсе, так что с планшета
        колоду нельзя было ни разложить, ни перекинуть карту из сайдборда.
        Один механизм на мышь, перо и палец -- в web/dragdrop.js.
        """
        for ev in ("pointerdown", "pointermove", "pointerup", "pointercancel"):
            self.assertIn(ev, JS_DRAG, "нет обработчика %s" % ev)
        self.assertNotIn('draggable="true"', JS_BUILDER,
                         "остался HTML5-атрибут draggable")
        self.assertIn("makeDraggable({", JS_BUILDER)
        # Бросок правит карту на сервере: категорию, секцию или и то и другое.
        drop = JS_BUILDER[JS_BUILDER.index("async function bdDropCard"):]
        for word in ("category", "section", "PATCH"):
            self.assertIn(word, drop[:1600], "бросок не меняет %s" % word)

    def test_a_card_can_be_dropped_into_another_section(self):
        """Карта из сайдборда в основную колоду -- то же движение.

        Секция-приёмник есть у каждой группы, а на время перетаскивания внизу
        появляется полоса: иначе в пустой сайдборд бросить было некуда.
        """
        self.assertIn('data-section="', JS_BUILDER)
        self.assertIn('id="bd-dock"', HTML)
        for sec in ("commander", "main", "side", "maybe"):
            self.assertIn('data-section="%s"' % sec, HTML)
        self.assertIn("#bd-dock", CSS)
        self.assertIn("dragging-now", CSS)

    def test_dragging_is_only_offered_where_it_means_something(self):
        """Columns derived from the cards cannot be rearranged by hand.

        Grouped by mana value or colour, a column is computed from the cards
        themselves -- dropping a card into it could not mean anything, so the
        cards are not draggable and the header says why.
        """
        self.assertIn('$("#bd-group").value === "category"', JS_BUILDER)
        self.assertIn("колонки здесь считаются из самих", JS_BUILDER)
        # ...но перенести карту в другую секцию можно при любой группировке.
        self.assertIn("bdSectionOf", JS_BUILDER)

    def test_a_new_category_can_be_made_by_dropping(self):
        self.assertIn("newgroup", JS_BUILDER)
        self.assertIn("newcol", CSS)

    def test_the_stack_shows_the_title_strip_and_nothing_more(self):
        """A stack shows the title bar, not half the card.

        The first version left 47% of every card visible, so a column of 24
        creatures was 2328 px tall -- a cascade, not a pile. The card element is
        now exactly the strip, its picture overflows upward, and the stack
        carries the bottom padding the last picture needs.

        Всё в процентах от ширины колонки: колонка тянется по ширине окна, и
        полоска в фиксированных пикселях превратилась бы из шапки в ниточку.
        """
        block = CSS[CSS.index(".stackcard {"):]
        self.assertIn("aspect-ratio: 6.45", block[:700],
                      "полоса должна задаваться долей ширины, а не пикселями")
        self.assertNotIn("height: var(--strip,", block[:700],
                         "пиксельная высота полосы не тянется с колонкой")
        self.assertNotIn("margin-bottom: -", block[:600],
                         "отрицательные поля схлопывали контейнер")
        stack = CSS[CSS.index(".bdstack {"):]
        self.assertIn("padding-bottom: calc(139.4%", stack[:600],
                      "нет запаса под картинку последней карты")
        self.assertIn("var(--striph", stack[:600],
                      "запас под картинку считается от той же доли")

    def test_every_density_sets_the_strip_share(self):
        for mode in ("tight", "snug", "roomy"):
            block = CSS[CSS.index('body[data-bddensity="%s"] .bdcolumn' % mode):]
            self.assertIn("--striph:", block[:120], mode)
            self.assertIn("%", block[:120], "доля, а не пиксели: %s" % mode)

    def test_columns_fill_the_width_without_squashing_the_cards(self):
        """Колонки тянутся по ширине, но не уже читаемого и не шире экрана.

        Горизонтальная прокрутка колоды -- ровно то, из-за чего билдер
        назывался неудобным, поэтому не влезшие колонки переносятся на
        следующий ряд.
        """
        # Именно правило .bdcolumn, а не «.bdcolumn.multi > .bdcolumn».
        block = CSS[CSS.index(chr(10) + ".bdcolumn {"):]
        self.assertIn("flex: 1 1 var(--colw", block[:800])
        self.assertIn("min-width: var(--colw", block[:800])
        self.assertIn("max-width: calc(var(--colw", block[:800])

        columns = CSS[CSS.index(".bdcolumns {"):]
        self.assertIn("flex-wrap: wrap", columns[:400])
        self.assertNotIn("overflow-x: auto", columns[:400])

    def test_the_builder_asks_for_the_sharp_image(self):
        """small -- это 146 px, а колонка бывает 280: карта мылила."""
        for fn in ("function bdStackCard(", "function bdGridCard("):
            block = JS_BUILDER.split(fn)[1].split(chr(10) + "}")[0]
            self.assertIn("image_normal", block, fn)

    def test_a_commander_can_be_set_from_a_card_already_in_the_deck(self):
        """Раньше для этого надо было удалить карту и добавить заново."""
        self.assertIn("function bdCommanderButton(", JS_BUILDER)
        self.assertIn("async function bdSetCommander(", JS_BUILDER)
        self.assertIn("data-commander", JS_BUILDER)
        self.assertIn(".crown", CSS)
        # Прежний командир возвращается в колоду, а не пропадает.
        body = JS_BUILDER.split("async function bdSetCommander(")[1].split(chr(10) + "}")[0]
        self.assertIn('"main"', body)
        self.assertIn("previous", body)

    def test_the_column_width_follows_the_density_switch(self):
        self.assertIn("--colw", CSS)


class TestShopOrders(unittest.TestCase):
    """A shop lot is an order; a person stays a conversation."""

    def test_the_order_box_is_drawn_for_shops_only(self):
        self.assertIn("shopOrderBox", JS)
        self.assertIn("isShop ? shopOrderBox(lot.order, lot, index)", JS)

    def test_the_message_draft_is_hidden_for_a_shop(self):
        self.assertIn('(isShop ? " hidden" : "")', JS)

    def test_both_copy_buttons_are_handled(self):
        for cls in ("copy-order", "copy-links"):
            self.assertIn(cls, JS, "нет кнопки %s" % cls)
            self.assertIn('classList.contains("%s")' % cls, JS,
                          "кнопка %s ничего не делает" % cls)

    def test_it_says_who_fills_the_cart(self):
        """The program prepares the order and stops -- and says so."""
        self.assertIn("Корзину собираете вы", JS)

    def test_orders_come_with_the_drafts(self):
        self.assertIn('"orders"', JS_MAIN)
        self.assertIn("orders_for_plan", JS_MAIN)

    def test_the_order_box_is_styled(self):
        for cls in (".orderbox", ".orderlinks", ".olink"):
            self.assertIn(cls, CSS, "нет оформления для %s" % cls)

    def test_a_lot_repeats_its_total_beside_the_copy_controls(self):
        self.assertIn("Сумма заказа:", JS)
        self.assertIn("orderControls(lot, index)", JS)

    def test_pending_orders_have_persistent_controls(self):
        self.assertIn("hunt-orders", _ids(HTML))
        for marker in ("data-mark-order", "data-remove-order", "data-receive-order"):
            self.assertIn(marker, JS)

    def test_marking_an_order_keeps_your_place_in_the_plan(self):
        """Re-rendering the plan must restore the view, as a re-plan does."""
        body = JS.split("function refreshOrderViews(")[1].split("\n}")[0]
        self.assertIn("huntViewState()", body)
        self.assertIn("restoreHuntView(view)", body)

    def test_a_drifted_lot_is_not_offered_a_second_mark(self):
        """The badge follows the seller, not the exact composition.

        Otherwise refusing one card after marking the order makes the lot look
        unordered, and the "mark it" button files a near-duplicate order with
        the same seller.
        """
        self.assertIn("function orderForLot(", JS)
        self.assertIn("orderForLot(lot)", JS)
        body = JS.split("function orderControls(")[1].split("\n}\n")[0]
        # Not exact -> update the existing mark; there is no second "mark it".
        self.assertIn("data-update-order", body)
        self.assertIn("data-update-lot", body)
        self.assertIn("состав в плане изменился", body)
        marked = body.split("if (!match)")[1].split("\n  }")[1]
        self.assertNotIn("data-mark-order", marked)


class TestPriceSurvivesTheCopy(unittest.TestCase):
    """Цена видна в плане и не должна теряться при копировании.

    Список для магазина -- формат массового ввода «количество имя», в него
    цену класть нельзя. Значит цена должна быть где-то ещё: в строках со
    ссылками и во втором, человеческом списке.
    """

    def test_the_paste_list_stays_a_paste_list(self):
        from app.shops import order_for_lot

        order = order_for_lot({
            "seller_name": "mtgsale.ru", "seller_kind": "shop", "total": 145,
            "items": [{"want": "Lightning Bolt", "quantity": 1, "unit_price": 145,
                       "subtotal": 145, "offer": {"line": "Bolt - 145 руб", "qty": 1}}],
        })
        self.assertEqual(order["list_text"], "1 Lightning Bolt")
        self.assertIn("145", order["priced_text"])

    def test_the_interface_offers_both_lists(self):
        self.assertIn("copy-order", JS)
        self.assertIn("copy-priced", JS)
        self.assertIn("priced_text", JS)

    def test_the_card_rows_show_the_price(self):
        block = JS.split("function shopOrderBox(")[1].split(chr(10) + "}")[0]
        self.assertIn("c.unit_price", block)
        self.assertIn("цена не известна", block)

    def test_a_draft_never_loses_the_price_the_plan_showed(self):
        from app.messages import draft_for_lot

        lot = {
            "seller_name": "seller-a", "seller_kind": "user", "total": 800,
            "items": [{"want": "Dark Ritual", "quantity": 2, "unit_price": 400,
                       "subtotal": 800,
                       "offer": {"line": "2 Dark Ritual (NM, рус)", "qty": 2}}],
        }
        msg = draft_for_lot(lot)
        self.assertIn("400 ₽ за шт.", msg)
        # И по-прежнему без чека.
        for banned in ("Итого", " × ", " = ", "800"):
            self.assertNotIn(banned, msg, banned)


class TestDisputedPriceIsNotShownAsTheTruth(unittest.TestCase):
    """topdeck иногда принимает за цену число, которое ценой не является.

    «13 Болото (#241) [11 рус, 2 eng] - 30 руб.» приезжает как 11 ₽: «11 рус»
    -- это количество. В план такое объявление не берётся (price_check), но
    показывалось всё равно числом topdeck, и в окне карты значилось «от 11 ₽»
    там, где карта стоит 30. Правило то же, что и везде: строка продавца важнее.
    """

    def test_there_is_one_place_that_decides_which_number_to_trust(self):
        self.assertIn("function trustedPrice(", JS)
        block = JS.split("function trustedPrice(")[1].split(chr(10) + "}")[0]
        self.assertIn("price_disputed", block)
        self.assertIn("price_in_line", block)

    def test_the_row_shows_the_trusted_number_and_says_it_is_in_doubt(self):
        block = JS.split("function offerLine(")[1].split(chr(10) + "}")[0]
        self.assertIn("trustedPrice(o)", block)
        self.assertIn("цена под вопросом", block)
        self.assertNotIn("rub(o.cost)", block)

    def test_the_heading_and_the_sorting_use_it_too(self):
        block = JS.split("async function loadCardOffers(")[1].split(chr(10) + "}")[0]
        self.assertIn("trustedPrice(a)", block)
        self.assertNotIn("a.cost - b.cost", block)
        self.assertNotIn("rub(mine[0].cost)", block)

    def test_the_server_sends_what_that_decision_needs(self):
        for field in ("price_disputed", "price_in_line", "price_reason"):
            self.assertIn(field, JS_MAIN, "сервер не отдаёт %s" % field)


class TestUnknownPriceIsNotZero(unittest.TestCase):
    """Ноль -- это «числа не дали», и в плане так и должно быть написано."""

    def test_the_row_says_so_instead_of_showing_zero(self):
        block = JS.split("function offerRow(")[1].split(chr(10) + "}")[0]
        self.assertIn("цена не указана", block)
        self.assertIn("item.unit_price" + chr(10), block + chr(10))

    def test_the_picker_falls_back_to_the_lot_instead_of_a_dash(self):
        """Предложение, которого нет среди альтернатив, всё равно чьё-то."""
        block = JS.split("function supplierPicker(")[1].split(chr(10) + "}")[0]
        self.assertIn("currentLabel", block)
        self.assertIn("продавец не назван", block)
        self.assertNotIn('esc(current ? supplierLabel(current) : "—")', block)


class TestComfort(unittest.TestCase):
    """Тема, отмена, клавиши, недавние запросы, профили, что нового."""

    def test_ux_is_loaded_after_everything_it_uses(self):
        """ux.js опирается на помощники из app.js и на bdDeck из билдера."""
        self.assertIn("/static/ux.js", HTML)
        self.assertGreater(HTML.index("/static/ux.js"), HTML.index("/static/app.js"))
        self.assertGreater(HTML.index("/static/ux.js"), HTML.index("/static/builder.js"))

    def test_the_theme_is_set_before_the_page_is_painted(self):
        """Скриптом в конце страницы светлая тема мигнула бы тёмной."""
        head = HTML[: HTML.index("</head>")]
        self.assertIn("mtgh.theme", head)
        self.assertIn("data-theme", head.replace("dataset.theme", "data-theme"))

    def test_the_default_theme_is_the_one_the_program_always_had(self):
        head = HTML[: HTML.index("</head>")]
        self.assertIn('JSON.parse(raw) : "dark"', head)
        self.assertIn('store.get(THEME_KEY, "dark")', JS_UX)

    def test_light_theme_only_redefines_tokens(self):
        block = CSS.split('[data-theme="light"]')[1].split("}")[0]
        for token in ("--bg:", "--text:", "--line:", "--accent:", "--on-accent:"):
            self.assertIn(token, block, "светлая тема не задаёт %s" % token)

    def test_undo_is_offered_where_loss_is_visible(self):
        from app.main import app

        paths = {getattr(r, "path", "") for r in app.routes}
        self.assertIn("/api/undo", paths)
        self.assertIn("/api/undo/status", paths)
        self.assertIn("/api/undo", JS_UX)
        # Удаление папки, удаление карты, замена коллекции, заказы.
        self.assertIn('"favourites")', JS_FAV)
        self.assertIn('toastUndo("Коллекция сохранена", "collection"', JS)
        self.assertIn('undoable("Отметка заказа снята", "orders")', JS)
        self.assertIn('undoable("Карты добавлены в коллекцию", "receive")', JS)

    def test_the_hotkey_window_is_built_from_the_same_list(self):
        self.assertIn("HOTKEYS", JS_UX)
        self.assertIn("keys-body", _ids(HTML))
        self.assertIn("keys-overlay", _ids(HTML))
        # В списке есть все четыре раздела, включая билдер.
        block = JS_UX.split("const HOTKEYS")[1].split("];")[0]
        for group in ("Везде", "Поиск", "Билдер"):
            self.assertIn(group, block)

    def test_builder_keys_exist_and_are_panel_aware(self):
        """Клавиши билдера не должны срабатывать на других вкладках."""
        self.assertIn("function bdKeys(", JS_BUILDER)
        block = JS_BUILDER.split("document.addEventListener(\"keydown\"")[-1]
        self.assertIn("panel-builder", block)
        self.assertIn("bd-filter", block)

    def test_recent_and_saved_queries_are_wired(self):
        self.assertIn("recentQueries", JS_UX)
        self.assertIn("savedQueries", JS_UX)
        self.assertIn("rememberQuery", JS)          # поиск их запоминает
        for cls in ("qrow", "qhead"):
            self.assertIn("." + cls, CSS)

    def test_filter_profiles_cover_the_real_fields(self):
        self.assertIn("hunt-profiles", _ids(HTML))
        block = JS_UX.split("const FILTER_FIELDS")[1].split("];")[0]
        for field in ("f-condition", "f-maxprice", "f-strategy", "f-skip-ordered"):
            self.assertIn(field, block, "профиль не сохраняет %s" % field)
            self.assertIn(field, _ids(HTML), "нет поля %s" % field)
        # Языки без id, поэтому собираются по классу, а не через этот список.
        self.assertIn('$$(".lang:checked")', JS_UX)
        self.assertIn("langs", JS_UX)

    def test_the_hunt_can_skip_what_is_already_coming(self):
        self.assertIn("skip_ordered", JS)
        self.assertIn("f-skip-ordered", _ids(HTML))

    def test_the_previous_price_is_shown_where_prices_are(self):
        self.assertIn("function wasPrice(", JS)
        self.assertIn("wasPrice(rub)", JS_BUILDER)
        self.assertIn("wasPrice(x.rub)", JS_REC)
        self.assertIn(".wasprice", CSS)

    def test_whats_new_is_dismissed_for_good(self):
        from app.main import app

        self.assertIn("/api/whatsnew", {getattr(r, "path", "") for r in app.routes})
        self.assertIn("/api/whatsnew", JS_UX)
        self.assertIn("seenVersion", JS_UX)
        self.assertIn("whatsnew", _ids(HTML))


class TestOrderHistory(unittest.TestCase):
    """Received orders: the part that was stored and never shown."""

    def test_the_history_is_rendered_in_the_hunt_panel(self):
        self.assertIn("order-history", JS)
        self.assertIn("got-order", JS)
        for cls in ("order-history", "got-order", "bought"):
            self.assertIn("." + cls, CSS, "нет оформления для .%s" % cls)

    def test_it_arrives_with_the_pending_list(self):
        """One request keeps the panel right the moment an order is received."""
        body = JS.split("function applyOrderState(")[1].split(chr(10) + "}")[0]
        self.assertIn("state.history", body)
        self.assertIn("state.spent", body)

    def test_the_history_shows_even_with_nothing_on_the_way(self):
        body = JS.split("function renderOrdersPanel(")[1].split(chr(10) + "}")[0]
        empty = body.split("if (!savedOrders.length)")[1].split("}")[0]
        self.assertIn("orderHistoryHtml()", empty)

    def test_a_card_window_can_say_what_was_paid_for_it(self):
        from app.main import app

        paths = {getattr(r, "path", "") for r in app.routes}
        self.assertIn("/api/orders/purchases", paths)
        self.assertIn("/api/orders/purchases", JS)
        self.assertIn("modal-bought", _ids(HTML) | _ids(JS))

    def test_a_missing_date_is_not_invented(self):
        self.assertIn("дата не записана", JS)


class TestDeckShape(unittest.TestCase):
    """The shape tab and the suggestion strip in the builder."""

    def test_the_panel_has_the_three_panes(self):
        ids = _ids(HTML)
        for pane in ("rec-tabs", "rec-pane-cards", "rec-pane-shape", "rec-pane-themes"):
            self.assertIn(pane, ids, "нет %s" % pane)

    def test_the_panels_tabs_are_not_the_pages_tabs(self):
        """app.js wires every .tab to the main router: a .tab here would blank
        the page behind the modal."""
        block = HTML.split('id="rec-tabs"')[1].split("</div>")[0]
        self.assertIn('class="subtab', block)
        self.assertNotIn('class="tab', block)
        self.assertIn("#rec-tabs .subtab", JS_REC)
        self.assertIn(".subtab {", CSS)

    def test_the_shape_tab_asks_the_right_endpoint(self):
        self.assertIn("/api/deckshape?", JS_REC)

    def test_the_suggestion_strip_is_its_own_element(self):
        """#bd-suggest is the card autocomplete; the strip must not share it."""
        self.assertIn("bd-advice", _ids(HTML))
        self.assertIn('$("#bd-advice")', JS_REC)
        self.assertNotIn('$("#bd-suggest")', JS_REC)

    def test_the_builder_offers_suggestions_when_a_deck_opens(self):
        self.assertIn("recSuggestHint", JS_BUILDER)

    def test_the_answer_is_remembered_per_deck(self):
        self.assertIn('"bdAdvice." + bdDeck.id', JS_REC)
        for act in ("on", "off", "open"):
            self.assertIn('data-advice="%s"' % act, JS_REC)

    def test_nothing_is_fetched_before_the_mode_is_on(self):
        """The offer state must not call the endpoint -- only the enabled one."""
        offer = JS_REC.split("if (pref !== true) {")[1].split("return;")[0]
        self.assertNotIn("api(", offer)
        self.assertNotIn("bdAdviceLine", offer)

    def test_the_strip_has_styling(self):
        for cls in ("suggestbar", "sbar", "shape-advice", "themechips"):
            self.assertIn(cls, CSS, "нет оформления для %s" % cls)


class TestSampleOfRealDecks(unittest.TestCase):
    """The tab that answers from a sample of Archidekt decks."""

    def test_the_pane_and_its_controls_exist(self):
        ids = _ids(HTML)
        for el in ("rec-pane-cooccur", "rec-sample", "rec-cooccur-body"):
            self.assertIn(el, ids, "нет %s" % el)
        self.assertIn('data-rectab="cooccur"', HTML)

    def test_it_calls_the_endpoints_the_server_defines(self):
        from app.main import app

        paths = {getattr(r, "path", "") for r in app.routes}
        for path in ("/api/cooccur", "/api/cooccur/status",
                     "/api/cooccur/collect", "/api/cooccur/pairs"):
            self.assertIn(path, paths, "сервер не отдаёт %s" % path)
            self.assertIn(path, JS_REC, "интерфейс не зовёт %s" % path)

    def test_nothing_is_fetched_until_the_button_is_pressed(self):
        """Opening the tab reads the cache; only the button collects."""
        opening = JS_REC.split('if (name === "cooccur")')[1].split("return;")[0]
        self.assertIn("coStatus()", opening)
        self.assertNotIn("/api/cooccur/collect", opening)
        self.assertIn("rec-sample-go", JS_REC)
        self.assertIn("rec-sample-stop", JS_REC)

    def test_collecting_is_a_loop_that_can_be_stopped(self):
        body = JS_REC.split("async function coCollect(")[1].split(chr(10) + "}")[0]
        self.assertIn("while (!coStop)", body)
        self.assertIn("/api/cooccur/collect", body)

    def test_the_rows_are_the_same_rows(self):
        """One renderer for both tabs, and one click handler for both panes."""
        body = JS_REC.split("function coRender(")[1].split(chr(10) + "}")[0]
        self.assertIn("recRow", body)
        self.assertIn("recSort(recVisible(", body)
        self.assertIn('$("#rec-cooccur-body").addEventListener("click", recRowClick)',
                      JS_REC)
        self.assertIn('data-rec="pairs"', JS_REC)

    def test_the_sample_is_described_not_dressed_up(self):
        self.assertIn("Archidekt", JS_REC)
        self.assertIn("не вся правда", JS_REC)

    def test_the_new_blocks_have_styling(self):
        for cls in ("copairs", "pairlist"):
            self.assertIn(cls, CSS, "нет оформления для %s" % cls)


class TestCombos(unittest.TestCase):
    """The combo panel and the card window's combo section."""

    def test_the_panel_exists_and_is_shipped(self):
        self.assertIn("cb-overlay", _ids(HTML))
        self.assertIn("/static/combos.js", HTML)

    def test_both_entry_points_are_wired(self):
        self.assertIn('data-act="combos"', HTML)
        self.assertIn("cbOpen", JS_BUILDER)
        self.assertIn("modal-combos-btn", JS)
        self.assertIn("loadCardCombos", JS_COMBO)

    def test_every_control_it_draws_is_declared(self):
        for hook in ("cb-missing", "cb-commander", "cb-hunt-missing", "cb-rebuild",
                     "cb-meta", "cb-body", "cb-title", "cb-close"):
            self.assertIn(hook, _ids(HTML), "нет элемента #%s" % hook)
            self.assertIn(hook, JS_COMBO, "#%s не используется" % hook)

    def test_nothing_downloads_on_its_own(self):
        """27 MB has to be asked for, and the status is checked first."""
        self.assertIn("/api/combos/status", JS_COMBO)
        self.assertIn("cb-download", JS_COMBO)

    def test_a_missing_card_can_go_straight_to_the_hunt(self):
        self.assertIn('data-cb="hunt"', JS_COMBO)
        self.assertIn("addToHunt", JS_COMBO)

    def test_completeness_is_only_claimed_when_a_deck_says_so(self):
        # In the card window there is no deck, so `missing` is absent and the
        # block must not label itself "собрано".
        self.assertIn("Array.isArray(combo.missing)", JS_COMBO)

    def test_combo_rows_take_part_in_the_hover_preview(self):
        self.assertIn("data-preview", JS_COMBO)

    def test_the_combo_blocks_are_styled(self):
        for cls in (".cbcombo", ".cbcard", ".cbcard.miss", ".cbresults"):
            self.assertIn(cls, CSS, "нет оформления для %s" % cls)


class TestCommanderSuggestions(unittest.TestCase):
    """The suggestions panel, and the promise that it stays off topdeck."""

    def test_the_panel_exists_and_is_shipped(self):
        self.assertIn("rec-overlay", _ids(HTML))
        self.assertIn("/static/recommend.js", HTML)

    def test_the_builder_can_open_it(self):
        self.assertIn('data-act="recommend"', HTML)
        self.assertIn("recOpen", JS_BUILDER)

    def test_every_control_it_draws_is_declared(self):
        for hook in ("rec-commander", "rec-run", "rec-refresh", "rec-hide-deck",
                     "rec-only-missing", "rec-min-share", "rec-sort", "rec-body",
                     "rec-meta", "rec-add-picked", "rec-hunt-picked",
                     "rec-prices-picked"):
            self.assertIn(hook, _ids(HTML), "нет элемента #%s" % hook)
            self.assertIn(hook, JS_REC, "#%s не используется" % hook)

    def test_it_never_asks_topdeck_by_itself(self):
        """Prices are a deliberate act: 250 cards at 1.5s would be minutes."""
        self.assertNotIn("/api/offers", JS_REC)
        # The only topdeck path here is the explicit button.
        self.assertEqual(JS_REC.count("/api/prices"), 1)
        idx = JS_REC.index("/api/prices")
        self.assertIn("recPrices", JS_REC[:idx],
                      "цены запрашиваются вне явного действия")

    def test_the_price_request_has_a_ceiling_on_the_server(self):
        with open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8") as fh:
            main = fh.read()
        self.assertIn("PRICE_NAMES_LIMIT", main)

    def test_rows_take_part_in_the_hover_preview(self):
        self.assertIn("data-preview", JS_REC)

    def test_the_suggestion_rows_are_styled(self):
        for cls in (".recrow", ".recgroup", ".modal.wide"):
            self.assertIn(cls, CSS, "нет оформления для %s" % cls)


class TestKeyboardAndBuilderDensity(unittest.TestCase):
    """Arrow navigation over the grid, and the builder's own density."""

    def test_arrow_keys_are_handled(self):
        for key in ("ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"):
            self.assertIn(key, JS, "стрелка %s не обрабатывается" % key)
        self.assertIn("gridKeys", JS)

    def test_the_cursor_has_a_look_of_its_own(self):
        """:hover and the keyboard cursor can both be on screen at once."""
        self.assertIn(".card.cursor", CSS)

    def test_the_keyboard_preview_is_not_cancelled_by_its_own_scrolling(self):
        # scrollIntoView fires a scroll event, and the scroll handler used to
        # hide the preview -- so arrows showed nothing at all.
        self.assertIn('previewSource', JS)
        self.assertIn('"keys"', JS)

    def test_the_preview_starts_from_the_thumbnail_already_on_screen(self):
        self.assertIn("previewThumb", JS)

    def test_the_builder_density_is_wired(self):
        self.assertIn("bd-density", _ids(HTML))
        for mode in ("tight", "snug", "roomy"):
            self.assertIn('data-bddensity="%s"' % mode, HTML,
                          "нет кнопки плотности билдера %s" % mode)
            self.assertIn('body[data-bddensity="%s"]' % mode, CSS,
                          "плотность билдера %s ничего не меняет" % mode)
        self.assertIn('store.set("bdDensity"', JS_BUILDER)

    def test_the_builder_grid_reads_its_tile_size_from_the_variable(self):
        grid = CSS[CSS.index(".bdgrid {"):]
        self.assertIn("var(--bdtile", grid[:220])

    def test_the_stats_block_can_be_folded(self):
        """It is 250px tall and sits above the card list."""
        self.assertIn("bd-stats-toggle", _ids(HTML))
        self.assertIn('store.set("bdStats"', JS_BUILDER)


class TestChangingYourMindIsWired(unittest.TestCase):
    """The plan must be undoable, and that lives in these exact hooks.

    Static checks, because the failure they guard is silent: a renamed data
    attribute leaves a button that looks clickable and does nothing.
    """

    def test_the_choices_strip_exists(self):
        self.assertIn("hunt-choices", _ids(HTML),
                      "нет контейнера для решений по картам")

    def test_replan_endpoint_is_called(self):
        self.assertIn("/api/hunt/replan", JS)

    def test_every_refusal_control_has_a_handler(self):
        # button attribute -> the property app.js reads it back through
        pairs = [
            ("data-skip-offer", "skipOffer"),
            ("data-skip-want", "skipWant"),
            ("data-undrop", "undrop"),
            ("data-unskip", "unskip"),
            ("data-qty", "qty"),
        ]
        for attr, prop in pairs:
            self.assertIn(attr, JS, "кнопка %s не рисуется" % attr)
            self.assertIn("dataset." + prop, JS,
                          "%s рисуется, но не обрабатывается" % attr)

    def test_the_sellers_line_is_shown_without_topdecks_markup(self):
        """topdeck wraps the searched name in <b>; escaping it shows the tags.

        The plan read "1 -<b>Lightning Bolt</b> (SP, Magic 2011)". The markup is
        topdeck's highlighting, not the seller's writing, so it is stripped
        before display -- everywhere the raw line is shown.
        """
        self.assertIn("function plainLine", JS)
        shown = re.findall(r'class="rawline">' + "'" + r' \+ ([^+]+)', JS)
        self.assertTrue(shown, "не нашлось ни одной отрисовки строки продавца")
        for expr in shown:
            self.assertIn("plainLine", expr,
                          "строка продавца показывается без plainLine: %s" % expr.strip())

    def test_the_draft_is_editable(self):
        """It is the user's message; a readonly box cannot be corrected."""
        self.assertNotIn("<textarea readonly>", JS)

    def test_a_way_back_is_offered(self):
        for hook in ("hunt-reset-choices", "reset-msg"):
            self.assertIn(hook, JS, "нет способа вернуть: %s" % hook)

    def test_the_new_chips_are_styled(self):
        for cls in ("wantchip", "rowacts", "tiny"):
            self.assertIn("." + cls, CSS, "класс .%s без оформления" % cls)


class TestNoStaleFrontend(unittest.TestCase):
    """The browser must revalidate our HTML/JS/CSS on every load.

    Heuristic caching served an old app.js for a while, which made already-fixed
    bugs look like they had come back.
    """

    def test_static_and_index_are_marked_no_cache(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            for path in ("/", "/static/app.js", "/static/style.css"):
                resp = client.get(path)
                self.assertEqual(resp.status_code, 200, path)
                self.assertIn("no-cache", resp.headers.get("cache-control", ""), path)

    def test_api_responses_are_not_forced_no_cache(self):
        """Only the frontend assets: API responses have their own semantics."""
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/api/status")
            self.assertNotIn("no-cache", resp.headers.get("cache-control", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
