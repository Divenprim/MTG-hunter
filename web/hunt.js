"use strict";

/* Охота: список желаемого, выдача предложений, решения по ним и заказы.

   Жило в app.js и занимало там 1338 строк из 3414 -- больше трети файла, в
   котором кроме охоты есть поиск, окно карты, панель фильтров, колода и
   коллекция. Переехало целиком, без правок по сути: те же функции, те же
   имена, тот же порядок.

   Загружается после app.js и пользуется его помощниками ($, api, esc, toast,
   store, showTab). Обратно app.js зовёт отсюда одно -- loadOrders() при
   запуске, -- и зовёт через проверку на существование, как и всё остальное
   между файлами: иначе порядок загрузки превращается в скрытое требование.
*/

/* ============================================================ hunt helpers */

/* Сколько карт нужно -- это не то же самое, что «добавь ещё».

   addToHunt прибавляет: «в охоту» у одной карты означает «хочу ещё одну», и
   нажатие дважды честно даёт две. А список на группу колод -- это требование:
   «для этих колод нужно четыре Maze's End». Прибавлять его нельзя: нажали
   кнопку дважды -- и в охоте восемь, которых никто не просил. Поэтому
   групповой список именно ставит количество, а не прибавляет. */
function setInHunt(name, qty) {
  const box = $("#hunt-wants");
  const lines = box.value.split("\n").filter((l) => l.trim());
  const norm = (s) => s.trim().toLowerCase();
  let found = false;
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^\s*(\d{1,3})\s*[xX]?\s+(.+)$/);
    if (m && norm(m[2]) === norm(name)) {
      lines[i] = qty + " " + m[2].trim();
      found = true;
      break;
    }
  }
  if (!found) lines.push(qty + " " + name);
  box.value = lines.join("\n") + "\n";
  store.set("hunt", box.value);
}

/* Положить список в охоту, не стирая набранное руками.

   Шесть мест программы перезаписывали поле целиком: нажал «Недостающее в
   охоту» -- и список, который человек печатал сам, исчезал без предупреждения
   и без возможности вернуть. При этом набранное хранится в localStorage, то
   есть считается достаточно ценным, чтобы пережить перезагрузку страницы, --
   и недостаточно, чтобы пережить нажатие соседней кнопки.

   Два места делали правильно и объясняли почему; теперь так делают все. */
function huntTake(rows, source) {
  (rows || []).forEach((r) => {
    const name = r.name || r;
    const qty = Math.max(1, parseInt(r.quantity || r.lack || 1, 10) || 1);
    if (name) setInHunt(name, qty);
  });
  if (source) $("#hunt-source").textContent = source;
  return (rows || []).length;
}

function addToHunt(name, qty) {
  const box = $("#hunt-wants");
  const lines = box.value.split("\n").filter((l) => l.trim());
  const norm = (s) => s.trim().toLowerCase();
  let found = false;
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^\s*(\d{1,3})\s*[xX]?\s+(.+)$/);
    if (m && norm(m[2]) === norm(name)) {
      lines[i] = (parseInt(m[1], 10) + qty) + " " + m[2].trim();
      found = true;
      break;
    }
  }
  if (!found) lines.push(qty + " " + name);
  box.value = lines.join("\n") + "\n";
  store.set("hunt", box.value);
  toast('"' + name + '" ×' + qty + " — в списке охоты");
}

/* ==================================================================== hunt */

function parseWants(text) {
  const wants = [];
  (text || "").split("\n").forEach((raw) => {
    const line = raw.trim();
    if (!line) return;
    const m = line.match(/^(\d{1,3})\s*[xX]?\s+(.+)$/);
    if (m) wants.push({ name: m[2].trim(), quantity: parseInt(m[1], 10) });
    else wants.push({ name: line, quantity: 1 });
  });
  return wants;
}

function readHuntFilters() {
  const cities = $("#f-cities").value.split(",").map((s) => s.trim()).filter(Boolean);
  const maxPrice = parseInt($("#f-maxprice").value, 10);
  const refs = parseInt($("#f-refs").value, 10);
  return {
    languages: $$(".lang:checked").map((c) => c.value),
    min_condition: $("#f-condition").value || null,
    max_price: Number.isFinite(maxPrice) ? maxPrice : null,
    min_seller_refs: Number.isFinite(refs) ? refs : null,
    include_shops: $("#f-shops").checked,
    include_users: $("#f-users").checked,
    require_stated_language: $("#f-needlang").checked,
    require_stated_condition: $("#f-needcond").checked,
    exclude_proxy: true,
    cities,
  };
}

/* Заказанное и ещё не полученное вычитается из списка только по просьбе. */
function huntSkipOrdered() {
  const el = $("#f-skip-ordered");
  return !!(el && el.checked);
}

const CERTAINTY_LABEL = {
  exact: "",
  partial: '<span class="chip warn">описано неполно</span>',
  ambiguous: '<span class="chip mixed">неоднозначно — проверьте у продавца</span>',
};

function chipsFor(parsed, certaintyChip) {
  const chips = [];
  if (certaintyChip) chips.push(certaintyChip);
  if (parsed.set_code) {
    chips.push('<span class="chip set">' + esc(parsed.set_code.toUpperCase()) +
      (parsed.collector_number ? " #" + esc(parsed.collector_number) : "") + "</span>");
  } else if (parsed.collector_number) {
    chips.push('<span class="chip warn">#' + esc(parsed.collector_number) + ", сет не указан</span>");
  } else {
    chips.push('<span class="chip warn">сет не указан</span>');
  }
  if (parsed.language) chips.push('<span class="chip">' + esc(parsed.language) + "</span>");
  if (parsed.condition) chips.push('<span class="chip">' + esc(parsed.condition) + "</span>");
  if (parsed.foil === true) chips.push('<span class="chip">foil</span>');
  (parsed.treatments || []).forEach((t) => chips.push('<span class="chip">' + esc(t) + "</span>"));
  if (parsed.promo_family) chips.push('<span class="chip warn">' + esc(parsed.promo_family) + "</span>");
  if (parsed.mixed) chips.push('<span class="chip mixed">смешанный лот</span>');
  // topdeck hosts no images of its own, so a photo only exists when the seller
  // pasted a link into the listing text.
  (parsed.links || []).forEach((link) => {
    chips.push('<span class="chip photo"><a href="' + esc(link) +
      '" target="_blank" rel="noopener">фото продавца</a></span>');
  });
  return '<div class="chips">' + chips.join("") + "</div>";
}

/* Who else sells this card, and a way to pick one.

   The plan used to present one supplier as if it were the only one -- and got
   it wrong: it bought a card from a shop at 500 while a seller already in the
   plan had it at 400. The algorithm no longer does that, but the choice still
   belongs to the person paying: maybe you want the shop anyway, or a seller in
   your city, or the printing whose line you like better.

   A dropdown of everything was the first attempt and it was worse than nothing:
   Sol Ring had 185 offers. So the row shows only what matters -- what is chosen
   now, and the one or two listings that beat it -- and the full list opens on
   request. */

function alternativesFor(want) {
  return (lastPlan && lastPlan.alternatives && lastPlan.alternatives[want]) || [];
}

function supplierLabel(r) {
  const bits = [r.seller_name];
  if (r.seller_kind === "shop") bits.push("магазин");
  if (r.in_plan) bits.push("уже в плане");
  const marks = [r.set_code, r.language, r.condition].filter(Boolean).join(" ");
  if (marks) bits.push(marks);
  // Количество из строки продавца, когда число topdeck с ней разошлось:
  // «4 × Спираль Роста» topdeck считает за одну штуку.
  if (r.qty > 1) bits.push(r.qty + " шт." + (r.qty_dispute ? " (по строке)" : ""));
  return bits.join(" · ");
}

function supplierChip(want, r, kind, note) {
  return (
    '<button class="altchip ' + kind + '" data-pick="' + esc(want) +
      '" data-key="' + esc(r.key) + '">' +
      "<b>" + rub(r.price) + "</b> " + esc(supplierLabel(r)) +
      (note ? ' <i>' + esc(note) + "</i>" : "") +
    "</button>"
  );
}

function supplierPicker(item) {
  const want = item.want;
  const rows = alternativesFor(want);
  if (rows.length < 2) return "";

  const currentKey = (item.offer && item.offer.key) || "";
  const current = rows.find((r) => r.key === currentKey);
  const pinned = pinnedOffers.has(want);
  const price = current ? current.price : item.unit_price;
  // Предложение, которого нет в списке альтернатив, всё равно чьё-то: имя
  // продавца и цена известны из самого лота, и «берём у: —» вместо них — это
  // потеря сведений, а не их отсутствие.
  const seller = (item.offer && item.offer.seller) || {};
  const currentLabel = current
    ? supplierLabel(current)
    : (seller.name || "продавец не назван") +
      (item.unit_price ? " · " + rub(item.unit_price) : "");

  /* Предлагать имеет смысл только то, что ещё можно взять. Нужно четыре
     копии, одна уже взята дешевле у другого продавца -- и строка дорогого
     всё равно показывала зелёную кнопку на того же дешёвого, у которого
     копия была единственной и уже лежала в этом же плане. Нажатие не меняло
     ничего: брать нечего. `free` считает сервер -- запас минус то, что план
     у этого объявления уже забрал. */
  const canTake = (r) => r.key !== currentKey && r.price < price
    && (r.free === undefined || r.free > 0);
  const cheapest = rows.find(canTake);
  const cheapestHere = rows.find((r) => canTake(r) && r.in_plan);

  const chips = [];
  if (cheapestHere && (!cheapest || cheapestHere.key !== cheapest.key)) {
    chips.push(supplierChip(want, cheapestHere, "here", "без второй пересылки"));
  }
  if (cheapest) {
    chips.push(supplierChip(want, cheapest, "cheap",
      cheapest.in_plan ? "без второй пересылки" : "отдельная пересылка"));
  }

  return (
    '<div class="picker">' +
      '<span class="altnow' + (pinned ? " pinned" : "") + '">' +
        // Строка читалась как набор обрывков через точки: «берём у: Имя ·
        // уже в плане · m10 · 3 шт.». Начало теперь -- фраза, а не ярлык.
        (pinned ? "вы выбрали продавца: " : "берём у продавца: ") +
        esc(currentLabel) +
      "</span>" +
      chips.join("") +
      (pinned
        ? '<button class="ghost tiny" data-unpin="' + esc(want) +
          '" title="Вернуть решение программе">сбросить</button>'
        : "") +
      '<button class="ghost tiny" data-alts="' + esc(want) + '">все ' +
        rows.length + " предложен" + plural(rows.length, "ие", "ия", "ий") +
      "</button>" +
      '<div class="alts" data-altlist="' + esc(want) + '" hidden></div>' +
    "</div>"
  );
}

function renderAlternatives(want, box) {
  const rows = alternativesFor(want);
  box.innerHTML =
    '<div class="altrows">' +
      rows.map((r) =>
        '<div class="altrow' + (r.chosen ? " on" : "") +
          '" data-pick="' + esc(want) + '" data-key="' + esc(r.key) + '">' +
          '<span class="p">' + rub(r.price) + "</span>" +
          '<span class="s">' + esc(r.seller_name) +
            (r.seller_kind === "shop" ? " · магазин" : "") +
            (r.in_plan ? ' · <span class="good">уже в плане</span>' : "") +
            // Запас кончился не «вообще», а потому что его забрал этот же
            // план: сказать об этом честнее, чем молча показать строку,
            // по которой ничего не произойдёт.
            (r.free === 0 && !r.chosen
              ? ' · <span class="meta">все копии уже в плане</span>' : "") +
            (r.seller_city ? " · " + esc(r.seller_city) : "") +
          "</span>" +
          '<span class="l">' + esc(plainLine(r.line)) + "</span>" +
        "</div>").join("") +
    "</div>";
}

function offerRow(item) {
  const offer = item.offer;
  const parsed = offer.parsed || {};
  const printing = offer.printing;
  const thumb = printing && printing.image_small;
  const certainty = CERTAINTY_LABEL[offer.certainty] || "";
  const ordered = orderedCounts[(item.want || "").toLowerCase()] || 0;
  return (
    '<div class="offer">' +
    (thumb
      ? '<img class="thumb big" loading="lazy" src="' + esc(thumb) + '" alt="" data-full="' +
        esc((printing && printing.image_normal) || thumb) + '" title="открыть картинку печати">'
      : '<div class="thumb big"></div>') +
    "<div>" +
      '<div class="want">' + esc(item.want) + " — " + item.quantity + " шт." +
        // Карта уже едет, а план всё равно её предлагает -- это намеренно:
        // карта в пути не лежит в коробке, и посылка может не дойти. Но
        // выглядело это как ошибка программы, поэтому причина названа тут
        // же, вместе с тем, чем её поменять.
        (ordered
          ? ' <span class="chip ordered" title="Уже заказано и едет к вам.' +
            " Предлагается всё равно: пока посылка не пришла, карты у вас" +
            " нет. Выключить — галочка «не предлагать то, что уже в пути» в" +
            ' фильтрах охоты.">заказано: ' + ordered + " шт. — всё ещё в пути</span>"
          : "") +
      "</div>" +
      '<div class="rawline">' + esc(plainLine(offer.line) || "(продавец не указал строку)") + "</div>" +
      chipsFor(parsed, certainty) +
      supplierPicker(item) +
      // Which printing we think this is, spelled out under the parse.
      (printing
        ? '<div class="printinfo' +
          (printing.match === "exact" || printing.match === "set"
            ? '">' : ' guessed">') +
          "на картинке: " +
          esc((printing.set_code || "").toUpperCase()) + " · " +
          esc(printing.set_name || "") +
          (printing.collector_number ? " #" + esc(printing.collector_number) : "") +
          // Три разных случая, и раньше о них говорилось одно и то же.
          // «Sol Ring (m10) 80» с картинкой из другого сета выглядел
          // ошибкой программы: на деле номера 80 в m10 нет, и показана
          // просто известная печать той же карты.
          (printing.match === "exact"
            ? ""
            : printing.match === "set"
              ? " — номер продавец не указал, печать выбрана по сету"
              : printing.match === "fallback"
                ? " — такой печати (" + esc(String(parsed.set_code || "").toUpperCase()) +
                  (parsed.collector_number ? " #" + esc(parsed.collector_number) : "") +
                  ") в базе нет; на картинке другая печать этой же карты"
                : " — сет продавцом не указан, версия предположительная") +
          "</div>"
        : '<div class="printinfo">печать определить не удалось</div>') +
    "</div>" +
    '<div class="price">' +
      (item.unit_price
        ? "<b>" + rub(item.subtotal) + "</b><small>" + item.quantity + " × " +
          rub(item.unit_price) + "</small>"
        : '<b class="noprice" title="topdeck не дал числа для этого ' +
          'объявления — спросите цену у продавца">цена не указана</b>') +
      (offer.url ? '<small><a href="' + esc(offer.url) + '" target="_blank" rel="noopener">объявление</a></small>' : "") +
      // Changing your mind must be possible right where the offer is shown.
      // Both buttons rebuild the plan from offers already fetched, so no new
      // request goes to topdeck and the next best listing steps in at once.
      '<div class="rowacts">' +
        '<button class="ghost tiny" data-skip-offer="' + esc(offer.key || "") +
          '" title="Взять эту карту, но у кого-то другого">не это предложение</button>' +
        '<button class="ghost tiny" data-skip-want="' + esc(item.want) +
          '" title="Убрать карту из плана целиком">не брать карту</button>' +
      "</div>" +
    "</div></div>"
  );
}

/* A shop lot is not a conversation, it is an order on the shop's own site.
   So instead of a private-message draft it gets everything needed to place
   that order: the list to paste, a direct link to each card's page, and a
   search link where there is no direct one. The program stops there -- filling
   someone's cart under their account is the same line it does not cross when
   it refuses to send messages for them. */
function shopOrderBox(order, lot, index) {
  if (!order) return "";
  const shop = order.shop || {};
  const cards = order.cards || [];
  const withLinks = cards.filter((c) => c.url);

  return (
    '<div class="orderbox">' +
      '<div class="row tight wrap">' +
        "<b>Заказ в магазине " + esc(shop.name || "") + "</b>" +
        (shop.home
          ? '<a href="' + esc(shop.home) + '" target="_blank" rel="noopener">открыть магазин</a>'
          : "") +
        (shop.known
          ? ""
          : '<span class="chip warn" title="' + esc(shop.note || "") + '">магазин незнаком</span>') +
      "</div>" +
      '<textarea class="orderlist" readonly rows="' +
        Math.min(8, Math.max(2, cards.length)) + '">' + esc(order.list_text || "") +
      "</textarea>" +
      '<div class="row tight wrap">' +
        '<button class="copy-order">Скопировать список</button>' +
        (order.priced_text
          ? '<button class="copy-priced ghost" title="Тот же список с ценами — ' +
            'чтобы сверить с корзиной магазина">Скопировать с ценами</button>'
          : "") +
        (withLinks.length
          ? '<button class="copy-links ghost">Скопировать ссылки на карточки</button>'
          : "") +
        orderControls(lot, index) +
        '<span class="meta">Корзину собираете вы — программа ничего не заказывает от вашего имени.</span>' +
      "</div>" +
      '<div class="orderlinks">' +
        cards.map((c) =>
          '<span class="olink">' +
            "<b>" + c.quantity + "×</b> " + esc(c.name) +
            (c.unit_price
              ? ' <span class="rub">' + rub(c.unit_price) +
                (c.quantity > 1 ? " × " + c.quantity + " = " + rub(c.subtotal) : "") +
                "</span>"
              : ' <span class="meta">цена не известна</span>') +
            (c.url
              ? ' <a href="' + esc(c.url) + '" target="_blank" rel="noopener">карточка товара</a>'
              : c.search_url
                ? ' <a href="' + esc(c.search_url) + '" target="_blank" rel="noopener">найти в магазине</a>'
                : ' <span class="meta">ссылки нет</span>') +
          "</span>").join("") +
      "</div>" +
    "</div>"
  );
}

function lotBlock(lot, index) {
  const isShop = lot.seller_kind === "shop";
  const sellerLabel = lot.seller_url
    ? '<a href="' + esc(lot.seller_url) + '" target="_blank" rel="noopener">' + esc(lot.seller_name) + "</a>"
    : esc(lot.seller_name);
  return (
    '<div class="lot" data-lot="' + index + '">' +
      '<div class="lot-head">' +
        '<span class="lot-seller">' + sellerLabel + "</span>" +
        '<span class="badge ' + (isShop ? "shop" : "user") + '">' + (isShop ? "магазин" : "частный") + "</span>" +
        (lot.seller_city ? '<span class="badge">' + esc(lot.seller_city) + "</span>" : "") +
        (lot.seller_refs != null ? '<span class="badge">' + lot.seller_refs + " отзывов</span>" : "") +
        '<span class="badge">' + lot.distinct_cards + " назв. / " + lot.total_copies + " шт.</span>" +
        '<span class="lot-total">' + rub(lot.total) + "</span>" +
      "</div>" +
      lot.items.map(offerRow).join("") +
      (isShop ? shopOrderBox(lot.order, lot, index) : "") +
      '<div class="msgbox"' + (isShop ? " hidden" : "") + ">" +
        // Editable: it is your message. Edits survive a re-plan for as long as
        // this seller stays in it.
        '<textarea data-seller="' + esc(lot.seller_name) + '">' + esc(lot.message || "") + "</textarea>" +
        '<div class="row">' +
          '<button class="copy-msg">Скопировать сообщение</button>' +
          (lot.message_edited
            ? '<button class="ghost tiny reset-msg">вернуть черновик</button>'
            : "") +
          orderControls(lot, index) +
          '<span class="meta">' + (isShop
            ? "Это магазин — заказ оформляется у него на сайте, не через ЛС."
            : "Отправьте сообщение продавцу в личку на topdeck сами.") +
          "</span>" +
        "</div>" +
      "</div>" +
    "</div>"
  );
}

let lastPlan = null;
let lastHuntResult = null;
let savedOrders = [];
let orderedCounts = {};
let orderHistory = [];
let orderSpent = null;

function sameOrderAsLot(order, lot) {
  if (!order || !lot || order.seller_name.toLowerCase() !== lot.seller_name.toLowerCase()) {
    return false;
  }
  const shape = (items, nameKey) => {
    const counts = {};
    items.forEach((item) => {
      const name = String(item[nameKey] || "").toLowerCase();
      counts[name] = (counts[name] || 0) + Number(item.quantity || 0);
    });
    return Object.keys(counts).sort().map((name) => name + ":" + counts[name]).join("|");
  };
  return shape(order.items || [], "name") === shape(lot.items || [], "want");
}

/* Which pending order this lot belongs to.

   Identifying it by the exact composition is too strict for the badge: refuse
   one card after marking the order and the lot looks unordered again, with a
   "mark it" button that would file a second, nearly identical order with the
   same seller. So the badge follows the seller plus at least one shared card,
   and says out loud when the plan has since drifted from what was ordered.
   The server keeps its own exact fingerprint -- that is for de-duplication,
   not for deciding what to show. */
function orderForLot(lot) {
  if (!lot) return null;
  const seller = String(lot.seller_name || "").toLowerCase();
  const wants = new Set(
    (lot.items || []).map((item) => String(item.want || "").toLowerCase()));
  const order = savedOrders.find((saved) =>
    String(saved.seller_name || "").toLowerCase() === seller &&
    (saved.items || []).some((item) => wants.has(String(item.name || "").toLowerCase())));
  if (!order) return null;
  return { order: order, exact: sameOrderAsLot(order, lot) };
}

/* Чем оформленное отличается от сегодняшнего плана.

   Приписки «состав в плане изменился» мало: человек видит «✓ заказ оформлен»
   и сумму заказа из плана -- 375 ₽ за три позиции, -- а продавцу он на самом
   деле написал про две позиции на 215 ₽. Писать ли ещё раз и про что,
   приходилось вычислять, сличая строки глазами.

   Поэтому разница называется прямо: что заказано тогда и что в плане
   сейчас. */
function orderDiff(order, lot) {
  const ordered = new Map();
  for (const item of order.items || []) {
    ordered.set(String(item.name || "").toLowerCase(),
                item.quantity || 0);
  }
  const planned = new Map();
  for (const item of lot.items || []) {
    planned.set(String(item.want || "").toLowerCase(), item.quantity || 0);
  }
  const added = [];
  const changed = [];
  for (const [name, qty] of planned) {
    if (!ordered.has(name)) added.push(name);
    else if (ordered.get(name) !== qty) changed.push(name);
  }
  const removed = [];
  for (const name of ordered.keys()) {
    if (!planned.has(name)) removed.push(name);
  }
  const orderedCopies = Array.from(ordered.values())
    .reduce((n, q) => n + q, 0);
  return {
    ordered_total: order.total || 0,
    ordered_copies: orderedCopies,
    plan_total: lot.total || 0,
    added: added, removed: removed, changed: changed,
  };
}

function orderDiffNote(order, lot) {
  const d = orderDiff(order, lot);
  const parts = [];
  if (d.added.length) parts.push("в плане добавилось: " + d.added.length);
  if (d.removed.length) parts.push("ушло из плана: " + d.removed.length);
  if (d.changed.length) parts.push("изменилось количество: " + d.changed.length);
  const what = parts.length ? parts.join(", ") : "состав тот же, сумма другая";
  return '<span class="meta" title="Продавцу вы написали про то, что слева.' +
    ' Справа -- что в плане сейчас, после ваших отказов и пересчётов.">' +
    "заказано: " + rub(d.ordered_total) + " за " + d.ordered_copies +
    " шт. · в плане сейчас: " + rub(d.plan_total) + " · " + esc(what) +
    "</span>";
}

function orderControls(lot, index) {
  const match = orderForLot(lot);
  if (!match) {
    return (
      '<span class="order-total">Сумма заказа: <b>' + rub(lot.total) + "</b></span>" +
      '<button class="ghost tiny mark-order" data-mark-order="' + index +
        '">Отметить заказанным</button>'
    );
  }
  return (
    '<span class="order-total">Сумма заказа: <b>' + rub(lot.total) + "</b></span>" +
    '<span class="chip ordered">✓ заказ оформлен' +
      (match.exact ? "" : " · состав в плане изменился") + "</span>" +
    (match.exact ? "" : orderDiffNote(match.order, lot)) +
    '<button class="ghost tiny" data-receive-order="' + esc(match.order.id) +
      '" title="Добавить карты в коллекцию">получено → в коллекцию</button>' +
    (match.exact
      ? ""
      : '<button class="ghost tiny" data-update-order="' + esc(match.order.id) +
        '" data-update-lot="' + index +
        '" title="Заменить отметку тем, что сейчас в плане">обновить отметку</button>') +
    // Опасная из трёх: две соседние добавляют, эта забывает заказ. Выглядели
    // все три одинаково -- тусклая второстепенная кнопка, -- и человек,
    // неделю ждущий посылку, терял запись о ней, целясь в соседнюю.
    '<button class="ghost tiny danger" data-remove-order="' + esc(match.order.id) +
      '" title="Забыть, что этот заказ сделан. Отменить можно сразу после' +
      ' нажатия">снять отметку</button>'
  );
}

function applyOrderState(state) {
  savedOrders = (state && state.orders) || [];
  orderedCounts = (state && state.ordered) || {};
  // History rides along with the pending list, so the panel is right the
  // moment an order is received instead of after a second request.
  if (state && state.history) orderHistory = state.history;
  if (state && state.spent) orderSpent = state.spent;
  renderOrdersPanel();
}

async function loadOrders() {
  applyOrderState(await api("/api/orders"));
}

/* --------------------------------------------------------- уже приехало ----

   Заказы со статусом «получено» и так лежали в базе, но их никто не читал.
   Это единственное место, где программа знает не «сколько карта стоит сейчас
   на topdeck», а сколько вы за неё заплатили и кому. */

function orderDate(text) {
  // "2026-09-08 10:52:07" -> "08.09.2026". Дата без времени: в истории важен
  // день, а не секунды.
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(text || ""));
  return m ? m[3] + "." + m[2] + "." + m[1] : "";
}

function orderHistoryHtml() {
  if (!orderHistory.length) return "";
  const s = orderSpent || {};
  const span = s.first && s.last && orderDate(s.first) !== orderDate(s.last)
    ? " · с " + orderDate(s.first) + " по " + orderDate(s.last)
    : "";
  return '<details class="order-history"><summary>Получено — ' +
      orderHistory.length + " " + plural(orderHistory.length, "заказ", "заказа", "заказов") +
      (s.total ? " на " + rub(s.total) : "") + "</summary>" +
      '<div class="meta spent">' +
        (s.cards ? "карт: <b>" + s.cards + "</b> · " : "") +
        (s.sellers ? "продавцов: <b>" + s.sellers + "</b>" : "") + span +
        " · это то, что вы действительно заплатили, а не сегодняшняя цена" +
      "</div>" +
      orderHistory.map((order) =>
        '<div class="got-order">' +
          "<div><b>" + esc(order.seller_name) + "</b> · " + rub(order.total) +
            ' <span class="meta">' +
            (order.received
              ? "получено " + orderDate(order.received)
              : "получено (дата не записана)") +
            " · заказан " + orderDate(order.created) + "</span></div>" +
          '<div class="meta">' + (order.items || []).map((item) =>
            item.quantity + "× " + esc(item.name) +
            (item.unit_price ? " по " + rub(item.unit_price) : "")
          ).join(" · ") + "</div>" +
        "</div>").join("") +
    "</details>";
}

function renderOrdersPanel() {
  const box = $("#hunt-orders");
  if (!box) return;
  if (!savedOrders.length) {
    box.innerHTML = orderHistoryHtml();
    return;
  }
  box.innerHTML =
    '<details class="pending-orders" open><summary>Заказано, ожидает получения — ' +
      savedOrders.length + "</summary>" +
      savedOrders.map((order) =>
        '<div class="pending-order">' +
          '<div><b>' + esc(order.seller_name) + "</b> · " + rub(order.total) +
            ' <span class="meta">' + esc(order.created) + "</span></div>" +
          '<div class="meta">' + (order.items || []).map((item) =>
            item.quantity + "× " + esc(item.name)).join(" · ") + "</div>" +
          '<div class="row tight">' +
            '<button class="tiny" data-receive-order="' + esc(order.id) +
              '">Получено → в коллекцию</button>' +
            '<button class="ghost tiny danger" data-remove-order="' + esc(order.id) +
              '" title="Забыть, что этот заказ сделан. Отменить можно сразу' +
              ' после нажатия">Снять отметку</button>' +
          "</div>" +
        "</div>"
      ).join("") +
    "</details>" + orderHistoryHtml();
}

function huntPlanHtml(plan) {
  let html = "";
  /* Закрепление, которое не удалось применить. Человек нажал «беру здесь»,
     видел на своём выборе замок -- а план покупал у другого и дороже, не
     сказав ни слова. Отменённое решение без объяснения хуже, чем отказ. */
  if ((plan.ignored_pins || []).length) {
    html += '<div class="unfilled"><h3>Ваш выбор не удалось применить</h3>' +
      plan.ignored_pins.map((p) =>
        esc(p.want) + " — " + esc(p.why)).join("<br>") +
      '<p class="meta">Это объявление в план не вошло, и карта взята у ' +
      "другого продавца. Можно выбрать заново в «все предложения».</p></div>";
  }
  if (plan.unfilled && plan.unfilled.length) {
    html += '<div class="unfilled"><h3>Не нашлось в продаже</h3>' +
      plan.unfilled.map((u) => esc(u.name) + " — не хватает " + u.still_missing + " шт.").join("<br>") +
      "</div>";
  }
  html += plan.lots.map(lotBlock).join("");
  return html || '<p class="meta">' + (huntStateEmpty()
    ? "Ничего не найдено под эти фильтры."
    : "В плане ничего не осталось — вы отказались от всего. Можно вернуть.") + "</p>";
}

function refreshOrderViews() {
  renderOrdersPanel();
  if (lastPlan) {
    // Marking an order must not cost you your place: the plan is re-rendered
    // whole, so the scroll position and any open list of alternatives go back
    // where they were, the same way a re-plan restores them.
    const view = huntViewState();
    $("#hunt-plan").innerHTML = huntPlanHtml(lastPlan);
    restoreHuntView(view);
  }
  if (currentDeck && typeof renderDeckList === "function") renderDeckList();
}

/* Уведомление с «Отменить», когда отмена возможна, и обычное, когда нет. */
function undoable(msg, kind) {
  if (typeof toastUndo === "function") toastUndo(msg, kind, afterUndo);
  else toast(msg);
}

function orderPayload(lot) {
  return {
    seller_name: lot.seller_name,
    seller_kind: lot.seller_kind,
    items: lot.items.map((item) => ({
      name: item.want,
      quantity: item.quantity,
      unit_price: item.unit_price,
    })),
  };
}

async function handleOrderClick(target) {
  const data = target.dataset || {};
  const mark = data.markOrder;
  const update = data.updateOrder;
  const remove = data.removeOrder;
  const receive = data.receiveOrder;
  if (mark == null && !update && !remove && !receive) return false;
  target.disabled = true;
  try {
    let state;
    if (mark != null || update) {
      const which = mark != null ? mark : data.updateLot;
      const lot = lastPlan && lastPlan.lots[Number(which)];
      if (!lot) throw new Error("Заказ больше не найден в плане");
      // The new mark is filed before the old one is dropped: if the second
      // call fails you are left with a duplicate you can see and remove, not
      // with the record of your order silently gone.
      state = await post("/api/orders", orderPayload(lot));
      if (update) {
        state = await post(
          "/api/orders/" + encodeURIComponent(update) + "/remove", {});
      }
      toast(update
        ? "Отметка заказа обновлена по текущему плану"
        : "Заказ отмечен — карты остались в охоте и колоде");
    } else if (remove) {
      state = await post("/api/orders/" + encodeURIComponent(remove) + "/remove", {});
      undoable("Отметка заказа снята", "orders");
    } else {
      state = await post("/api/orders/" + encodeURIComponent(receive) + "/receive", {});
      // Получение меняет две вещи сразу -- список заказов и коллекцию, --
      // поэтому и отменяется целиком.
      undoable("Карты добавлены в коллекцию", "receive");
      refreshStatus();
    }
    applyOrderState(state);
    refreshOrderViews();
  } catch (e) {
    toast(e.message, true);
    target.disabled = false;
  }
  return true;
}

/* ---------------------------------------------------------- changing your mind

   A hunt costs a polite 1.5s request per batch, so the offers it found stay on
   the server under `huntId`. Refusing an offer or a card therefore rebuilds the
   plan from what we already have -- instantly, and without asking topdeck
   anything again. Refusals are kept here as plain state and sent in full every
   time, which is what makes "вернуть" work: it just stops sending one. */

let huntId = null;
let huntWants = [];              // what the server says we still need
// How many copies were needed when the hunt ran. The quantity control has to
// keep THIS as its ceiling: after "take 1 of 4" the server reports a want of 1,
// and reading the ceiling from that would trap you at one copy for good.
let huntNeeded = new Map();      // card name (lowercased) -> copies needed
const skipOffers = new Map();    // offer key -> {want, line}
const skipWants = new Map();     // card name -> true
const huntQty = new Map();       // card name -> how many copies to take
const pinnedOffers = new Map();  // card name -> the offer key chosen by hand
let preferSeller = "";           // a seller to buy everything from
const editedMessages = new Map(); // seller name -> text the user rewrote
const huntNames = new Map();      // lowercased name -> as the card is written

function huntStateEmpty() {
  return !skipOffers.size && !skipWants.size && !huntQty.size
    && !pinnedOffers.size && !preferSeller;
}

function resetHuntChoices() {
  skipOffers.clear();
  skipWants.clear();
  huntQty.clear();
  pinnedOffers.clear();
  preferSeller = "";
}

/* Editing a plan means re-rendering it, and a re-render that loses your place
   is why editing felt unusable: you picked a supplier and the row you were
   working on jumped somewhere else. So the scroll position and the card whose
   offer list was open are put back afterwards. */
function huntViewState() {
  const open = document.querySelector("#hunt-plan .alts:not([hidden])");
  return {
    scroll: window.scrollY,
    openWant: open ? open.dataset.altlist : null,
  };
}

function restoreHuntView(state) {
  if (!state) return;
  if (state.openWant) {
    const box = document.querySelector(
      '#hunt-plan .alts[data-altlist="' + (window.CSS && CSS.escape
        ? CSS.escape(state.openWant) : state.openWant) + '"]');
    if (box) {
      renderAlternatives(state.openWant, box);
      box.hidden = false;
      const btn = box.parentElement.querySelector("[data-alts]");
      if (btn) btn.textContent = "свернуть";
    }
  }
  window.scrollTo({ top: state.scroll });
}

/* Во что обходится лишний продавец. План тратит эту сумму, чтобы обойтись без
   него, и ни рубля сверх -- пустое поле значит «как обычно», а не «даром». */
function huntSellerFee() {
  const raw = parseInt(($("#f-sellerfee") || {}).value, 10);
  if (!Number.isFinite(raw) || raw < 0) return 250;
  return Math.min(raw, 5000);
}

/* Пересчёт плана покупки -- единственное место, где гонка портит то, за что
   платят деньги. Защиты не было никакой: занят помечался только `#hunt-choices`,
   а кнопки выбора поставщика, отказа от предложения и количества живут в
   `#hunt-plan`, который не блокировался ничем. Два быстрых клика по разным
   поставщикам давали два параллельных пересчёта, и побеждал вернувшийся
   последним, а не нажатый последним: план и запомненные решения расходились
   молча.

   Тикет -- тот же приём, что в поиске: ответ, пришедший не последним, просто
   выбрасывается. Плюс на время расчёта гасятся клики и по самому плану. */
let replanTicket = 0;

async function replanHunt() {
  if (!huntId) return;
  const ticket = ++replanTicket;
  const view = huntViewState();
  const quantities = {};
  huntQty.forEach((v, k) => { quantities[k] = v; });
  const bar = $("#hunt-choices");
  const plan = $("#hunt-plan");
  bar.classList.add("busy");
  if (plan) plan.classList.add("busy");
  try {
    const pins = {};
    pinnedOffers.forEach((v, k) => { pins[k] = v; });
    const r = await post("/api/hunt/replan", {
      hunt_id: huntId,
      strategy: $("#f-strategy").value,
      seller_fee: huntSellerFee(),
      skip_offers: Array.from(skipOffers.keys()),
      skip_wants: Array.from(skipWants.keys()),
      quantities,
      pins,
      prefer_seller: preferSeller,
    });
    // Опоздавший ответ не трогает ни экран, ни запомненные решения.
    if (ticket !== replanTicket) return;
    await renderHuntResult(r, { replanned: true });
    restoreHuntView(view);
  } catch (e) {
    // The hunt fell out of the server's memory (restart, or four hunts later).
    if (ticket === replanTicket) toast(e.message, true);
  } finally {
    if (ticket === replanTicket) {
      bar.classList.remove("busy");
      if (plan) plan.classList.remove("busy");
    }
  }
}

/* Что было до последнего отказа.

   Отказ от одного предложения перетасовывает весь план: «итог: 750 ₽ у 3
   прод., не хватает 2» превращался в «итог: 725 ₽ у 2 прод., не хватает 3».
   Сумма стала меньше -- выглядит как улучшение, -- а привезут при этом
   меньше карт. Ни то, ни другое не было подсвечено: человек видел два
   снимка разных планов и должен был сам заметить разницу.

   Запоминаем форму плана и показываем изменение рядом с числами. Живёт до
   следующей охоты: после новой охоты сравнивать не с чем. */
let planShape = null;
let planDelta = null;

function rememberPlanShape(copies, plan) {
  const now = { taken: copies.taken, wanted: copies.wanted,
                total: plan.total, sellers: plan.sellers };
  planShape = now;
}

function notePlanChange(copies, plan) {
  if (!planShape) return;
  const now = { taken: copies.taken, wanted: copies.wanted,
                total: plan.total, sellers: plan.sellers };
  const parts = [];
  const dCards = now.taken - planShape.taken;
  const dMoney = now.total - planShape.total;
  const dSellers = now.sellers - planShape.sellers;
  if (dCards) {
    parts.push("карт " + (dCards > 0 ? "больше на " : "меньше на ") +
               Math.abs(dCards) + " шт.");
  }
  if (dMoney) {
    parts.push("итог " + (dMoney > 0 ? "больше на " : "меньше на ") +
               rub(Math.abs(dMoney)));
  }
  if (dSellers) {
    parts.push("продавцов " + (dSellers > 0 ? "больше на " : "меньше на ") +
               Math.abs(dSellers));
  }
  planDelta = parts.length ? parts.join(", ") : null;
}

function planDeltaNote() {
  if (!planDelta) return "";
  return ' · <span class="chip warn" title="По сравнению с планом до вашего' +
    ' последнего отказа">после отказа: ' + esc(planDelta) + "</span>";
}

/* Сколько копий этой карты план вправду берёт. Считается по заказам, а не по
   желаниям: желание -- это «хочу четыре», план -- «нашлось две у одного и
   одна у другого». */
function planFoundFor(key) {
  if (!lastPlan || !lastPlan.lots) return 0;
  let n = 0;
  for (const lot of lastPlan.lots) {
    for (const item of lot.items || []) {
      if ((item.want || "").toLowerCase() === key) n += item.quantity || 0;
    }
  }
  return n;
}

/* Главное число результата: сколько карт привезут против того, сколько
   хотели. До сих пор его на экране не было вовсе -- были «назв.»,
   «предложений» и сумма, а «привезут 7 из 10 шт.» приходилось складывать
   самому из красного блока внизу. */
function planCopies() {
  let wanted = 0;
  huntNeeded.forEach((needed, key) => {
    if (skipWants.has(key)) return;
    wanted += huntQty.has(key) ? huntQty.get(key) : needed;
  });
  let taken = 0;
  if (lastPlan && lastPlan.lots) {
    for (const lot of lastPlan.lots) {
      for (const item of lot.items || []) taken += item.quantity || 0;
    }
  }
  return { wanted: wanted, taken: taken };
}

/* The card-level decisions live in one strip above the plan: how many copies of
   each card you actually want, and which cards you dropped. Offer-level
   refusals stay down in the rows next to the offer they concern. */
function renderHuntChoices() {
  const bar = $("#hunt-choices");
  if (!huntId || !huntNeeded.size) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;

  /* Поле в чипе -- это «сколько хочу взять», а не «сколько нашлось», и
     подпись «из 4» рядом с ним читалась ровно наоборот: сверху стояло
     «Lightning Bolt [4] из 4», а ниже красным -- «не нашлось, не хватает
     2 шт.». Два числа об одном и том же спорили на одном экране.

     Теперь у поля написано, что оно значит, а сколько план вправду закрыл --
     отдельной подписью, и только когда это меньше желаемого. */
  const chip = (name, needed, dropped) => {
    const key = name.toLowerCase();
    const qty = dropped ? 0 : (huntQty.has(key) ? huntQty.get(key) : needed);
    const found = planFoundFor(key);
    const short = !dropped && found < qty;
    return '<span class="wantchip' + (dropped ? " off" : "") + '">' +
      '<b>' + esc(name) + "</b>" +
      (dropped
        ? '<span class="meta">не берём</span>' +
          '<button class="ghost tiny" data-undrop="' + esc(name) + '">вернуть</button>'
        : '<span class="meta">брать</span>' +
          '<input type="number" class="qty" min="1" max="' + needed +
            '" value="' + qty + '" data-qty="' + esc(name) + '" title="сколько штук брать">' +
          '<span class="meta">из ' + needed + " нужных</span>" +
          (short
            ? '<span class="meta bad">нашлось ' + found + "</span>"
            : "") +
          '<button class="ghost tiny" data-skip-want="' + esc(name) + '">не брать</button>') +
      "</span>";
  };

  // Every card the hunt was for stays on the strip, whatever the current plan
  // says, so a card you dropped or trimmed can always be adjusted again.
  const live = [];
  const dropped = [];
  huntNeeded.forEach((needed, key) => {
    const name = huntNames.get(key) || key;
    if (skipWants.has(key)) dropped.push(chip(name, needed, true));
    else live.push(chip(name, needed, false));
  });

  // Who could supply the whole order, for "I would rather buy it all here".
  const cover = (lastPlan && lastPlan.coverage) || [];
  const coverRow = cover.length
    ? '<div class="row tight wrap"><span class="meta">Купить всё у одного:</span>' +
      '<select id="hunt-prefer">' +
        '<option value="">— как выгоднее —</option>' +
        cover.map((c) =>
          '<option value="' + esc(c.key) + '"' +
            (c.key === preferSeller ? " selected" : "") + ">" +
            esc(c.name) + (c.kind === "shop" ? " (магазин)" : "") +
            " — " + c.cards + " из " + huntNeeded.size +
          "</option>").join("") +
      "</select>" +
      (preferSeller
        ? '<span class="meta">остальное — где найдётся</span>'
        : "") +
      "</div>"
    : "";

  bar.innerHTML =
    '<div class="row tight wrap">' +
      '<span class="meta">Берём:</span>' + live.join("") + dropped.join("") +
    "</div>" +
    coverRow +
    (skipOffers.size
      ? '<div class="row tight wrap"><span class="meta">Отказались от предложений:</span>' +
        Array.from(skipOffers.entries()).map(([key, info]) =>
          '<span class="wantchip off"><b>' + esc(info.want) + "</b>" +
          '<span class="meta">' + esc(plainLine(info.line).slice(0, 46)) + "</span>" +
          '<button class="ghost tiny" data-unskip="' + esc(key) + '">вернуть</button></span>'
        ).join("") + "</div>"
      : "") +
    (huntStateEmpty()
      ? ""
      : '<div class="row tight"><button class="ghost tiny" id="hunt-reset-choices">' +
        "вернуть всё как было</button>" +
        '<span class="hint">пересчёт мгновенный — новые запросы к topdeck не идут</span></div>');
}

async function renderHuntResult(r, opts) {
  lastHuntResult = r;
  const plan = r.plan;
  huntWants = r.wants || [];
  if (!opts || !opts.replanned) {
    huntNeeded = new Map();
    huntNames.clear();
  }
  // Ceilings are remembered, never lowered: a card taken 1-of-4 comes back from
  // the server as a want of 1, and reading the ceiling from that would trap it.
  // New cards -- ones added to an order that already existed -- get their
  // ceiling here, which is how they reach the "Берём" strip at all.
  huntWants.forEach((w) => {
    const key = w.name.toLowerCase();
    huntNames.set(key, w.name);
    if (!huntNeeded.has(key)) huntNeeded.set(key, w.quantity);
  });

  const answer = await post("/api/messages", { plan });
  const drafts = answer.drafts;
  // Orders come back only for shop lots, in their own order, so they are
  // matched by seller rather than by index.
  const orders = {};
  (answer.orders || []).forEach((o) => { orders[o.seller_name] = o; });
  plan.lots.forEach((lot) => { lot.order = orders[lot.seller_name] || null; });
  plan.lots.forEach((lot, i) => {
    const fresh = drafts[i] ? drafts[i].message : "";
    // A message the user rewrote is theirs; a re-plan must not silently
    // overwrite it while that seller is still in the plan.
    if (editedMessages.has(lot.seller_name)) {
      lot.message = editedMessages.get(lot.seller_name);
      lot.message_edited = true;
    } else {
      lot.message = fresh;
    }
    lot.message_fresh = fresh;
  });
  lastPlan = plan;

  // The improvement pass is worth showing: it is the difference between the
  // plan the greedy pass produced and the one you are looking at.
  const moved = (plan.moves || []).length;
  const movedNote = moved
    ? " · <span class=\"good\">перенесено к тем, кто уже в плане: " + moved +
      (plan.saved ? ", дешевле на " + rub(plan.saved) : "") + "</span>"
    : "";

  // И обратное: продавец, который стоил дороже собственной пересылки, свёрнут
  // в остальной план. Доплата тут честная -- её видно.
  const folded = new Set((plan.merges || []).map((m) => m.from_seller)).size;
  const foldedNote = folded
    ? " · <span class=\"good\">продавцов убрано: " + folded +
      (plan.extra_paid ? ", доплата " + rub(plan.extra_paid) : "") + "</span>"
    : "";

  /* Цена известна не всегда, и «итого» без оговорки -- это неправда.
     Объявление без цены входило в сумму нулём: план писал «итого 0 ₽» за две
     карты и молчал. Ноль в цене значит «topdeck не дал числа», а не «даром»,
     и сказать об этом надо там же, где стоит сумма. */
  // Набор продавцов пересмотрен целиком -- не «перенесли карту», а «весь
  // список оказалось дешевле взять у других». Молча менять план нельзя:
  // человек видит другие числа и должен знать, откуда они.
  const rs = plan.resettled;
  const resettledNote = rs && rs.saved
    ? " · <span class=\"good\">набор продавцов пересобран: " +
      (rs.sellers_after === rs.sellers_before
        ? "те же " + rs.sellers_after
        : rs.sellers_before + " → " + rs.sellers_after) +
      ", дешевле на " + rub(rs.saved) + "</span>"
    : "";

  const noPrice = plan.unpriced_copies
    ? ' <span class="chip warn">+ ' + plan.unpriced_copies +
      " шт. без известной цены</span>"
    : "";

  /* Шапка отвечает на один вопрос: что привезут и сколько это стоит.
     Остальное -- работа поиска -- стоит после него и помельче.

     Было: «нужно докупить: 4 назв. · предложений: 11 · отфильтровано: 0 ·
     итог: 670 ₽ у 2 прод.» Сколько карт из желаемых план закрывает, не
     говорилось нигде, кроме красного блока внизу; «итог» читался как «столько
     заплачу», хотя это цена карт без пересылки; а «вы отказались: 4» после
     отказа от одной карты считало её объявления, не называя единицы. */
  const copies = planCopies();
  if (opts && opts.replanned) notePlanChange(copies, plan);
  else planDelta = null;
  const shortfall = Math.max(0, copies.wanted - copies.taken);
  const takeNote = copies.wanted
    ? "<b>берём " + copies.taken + " из " + copies.wanted + " шт.</b>" +
      (shortfall
        ? ' <span class="bad">не нашлось ' + shortfall + " шт.</span>"
        : "")
    : "";

  /* «Итог» -- это карты. Пересылку каждый продавец считает сам, и
     подставлять сюда оценку лишнего продавца из фильтров нельзя: это не цена
     посылки, а порог, до которого план готов доплатить, чтобы её избежать.
     Поэтому честно говорим, чего в сумме нет. */
  const money = "<b>итог за карты: " + rub(plan.total) + "</b> у " +
    plan.sellers + " " + plural(plan.sellers, "продавца", "продавцов", "продавцов") +
    ' <span class="meta" title="Пересылку каждый продавец считает сам:' +
    " программа её не знает и в сумму не включает. В фильтрах вы оценили" +
    ' лишнего продавца в ' + rub(plan.seller_fee || 0) + ' — это порог, до' +
    ' которого план доплачивает, чтобы обойтись без него.">без пересылки</span>';

  const refused = r.refused_count
    ? " · вы отказались от " + r.refused_count + " " +
      offersWordOf(r.refused_count)
    : "";

  $("#hunt-meta").innerHTML =
    takeNote + (takeNote ? " · " : "") + money + noPrice +
    movedNote + foldedNote + resettledNote + planDeltaNote() +
    '<div class="meta">нужно докупить: ' + (r.wants || []).length +
    " назв. · предложений: " + r.candidates.length +
    " · отфильтровано: " + r.rejected_count + refused + "</div>";

  rememberPlanShape(copies, plan);

  renderHuntChoices();

  $("#hunt-plan").innerHTML = huntPlanHtml(plan);
  $("#hunt-actions").hidden = !plan.lots.length;
  $("#hunt-addbox").hidden = !huntId;

  if (r.rejected_count) {
    const reasons = {};
    r.candidates.forEach((c) => {
      if (c.rejected) reasons[c.rejected] = (reasons[c.rejected] || 0) + 1;
    });
    $("#hunt-rejected").innerHTML =
      '<details class="help"><summary>Почему отброшено ' + r.rejected_count +
      " " + offersWord(r.rejected_count) + "</summary><div class=\"meta\">" +
      Object.keys(reasons).sort((a, b) => reasons[b] - reasons[a])
        .map((why) => reasons[why] + " × " + esc(why)).join("<br>") +
      "</div></details>";
  } else {
    $("#hunt-rejected").innerHTML = "";
  }

  if (opts && opts.replanned) toast("План пересчитан");
}

/* Показать последнюю охоту, не спрашивая магазин заново.

   Поиск ходит к чужому сайту по полторы секунды на карту, и программа сама
   объясняет, что это вежливость. Результат такого действия нельзя терять от
   закрытия вкладки: повторить его -- значит дёрнуть магазин ради того, что
   уже спрашивали, и заново ждать.

   Поэтому сервер держит последний ответ на диске, а здесь он предлагается
   одной строкой с датой: насколько он свежий, человек решает сам. */
async function offerLastHunt() {
  const box = $("#hunt-meta");
  if (!box || huntId) return;
  let kept = null;
  try {
    kept = await api("/api/hunt/last");
  } catch (e) {
    return;                       // нет так нет, это не повод ругаться
  }
  if (!kept || !kept.known) return;
  box.innerHTML =
    '<span class="meta">Прошлый поиск от ' + esc(kept.at || "") + ". </span>" +
    '<button type="button" class="ghost small" id="hunt-show-last">' +
    "Показать его</button>";
  $("#hunt-show-last").addEventListener("click", async () => {
    box.textContent = "";
    const r = kept.answer;
    huntId = r.hunt_id || null;
    resetHuntChoices();
    editedMessages.clear();
    await renderHuntResult(r);
    $("#hunt-source").textContent =
      "Показан прошлый поиск от " + (kept.at || "") +
      ". Магазин не спрашивали заново.";
  });
}

$("#hunt-btn").addEventListener("click", async (ev) => {
  const wants = parseWants($("#hunt-wants").value);
  if (!wants.length) return toast("Список пуст", true);

  store.set("hunt", $("#hunt-wants").value);
  store.set("huntFilters", readHuntFilters());

  ev.target.disabled = true;
  const started = Date.now();
  const tick = setInterval(() => {
    // Сколько это займёт -- видно заранее: по восемь имён на запрос и полторы
    // секунды между запросами, чтобы не грузить topdeck. Человеку важно
    // понимать, ждать ему десять секунд или минуту.
    const wait = Math.ceil(wants.length / 8) * 1.5;
    $("#hunt-meta").innerHTML = '<span class="spinner">ищу ' + wants.length +
      " назв. на topdeck… " + Math.round((Date.now() - started) / 1000) +
      " с из примерно " + Math.round(wait) + "</span>";
  }, 500);
  $("#hunt-plan").innerHTML = "";
  $("#hunt-rejected").innerHTML = "";
  $("#hunt-actions").hidden = true;

  try {
    const r = await post("/api/hunt", {
      wants,
      filters: readHuntFilters(),
      strategy: $("#f-strategy").value,
      seller_fee: huntSellerFee(),
      use_collection: $("#f-collection").checked,
      skip_ordered: huntSkipOrdered(),
    });
    clearInterval(tick);

    if (r.note) { $("#hunt-meta").textContent = r.note; return; }

    huntId = r.hunt_id || null;
    resetHuntChoices();
    editedMessages.clear();
    await renderHuntResult(r);
  } catch (e) {
    clearInterval(tick);
    $("#hunt-meta").textContent = "";
    toast(e.message, true);
  } finally {
    clearInterval(tick);
    ev.target.disabled = false;
  }
});

$("#hunt-plan").addEventListener("click", async (ev) => {
  if (await handleOrderClick(ev.target)) return;
  if (ev.target.classList.contains("copy-priced")) {
    // Список для вставки в магазин остаётся без цен -- массовый ввод у
    // магазина понимает только «количество имя», -- поэтому цены копируются
    // отдельной кнопкой.
    const box = ev.target.closest(".lot");
    const lot = lastPlan && box && lastPlan.lots[Number(box.dataset.lot)];
    const order = lot && lot.order;
    if (order && order.priced_text) {
      copyText(order.priced_text, "Список с ценами скопирован");
    } else {
      toast("Цены для этого лота не известны", true);
    }
    return;
  }
  if (ev.target.classList.contains("copy-order")) {
    const box = ev.target.closest(".orderbox").querySelector(".orderlist");
    copyText(box.value, "Список для магазина скопирован");
    return;
  }

  if (ev.target.classList.contains("copy-links")) {
    const links = $$(".orderlinks a", ev.target.closest(".orderbox"))
      .map((a) => a.href);
    copyText(links.join("\n"), "Ссылки скопированы: " + links.length);
    return;
  }

  if (ev.target.classList.contains("copy-msg")) {
    const box = ev.target.closest(".msgbox").querySelector("textarea");
    copyText(box.value, "Сообщение скопировано");
    return;
  }

  if (ev.target.classList.contains("reset-msg")) {
    const box = ev.target.closest(".msgbox").querySelector("textarea");
    const seller = box.dataset.seller;
    editedMessages.delete(seller);
    const lot = (lastPlan && lastPlan.lots || []).find((l) => l.seller_name === seller);
    if (lot) {
      lot.message = lot.message_fresh || "";
      lot.message_edited = false;
      box.value = lot.message;
    }
    ev.target.remove();
    return;
  }

  const dropOffer = ev.target.dataset.skipOffer;
  if (dropOffer) {
    const row = ev.target.closest(".offer");
    const want = ev.target.parentElement.querySelector("[data-skip-want]");
    skipOffers.set(dropOffer, {
      want: (want && want.dataset.skipWant) || "",
      line: (row && (row.querySelector(".rawline") || {}).textContent) || "",
    });
    replanHunt();
    return;
  }

  // Opening the full list of offers for one card.
  const alts = ev.target.closest("[data-alts]");
  if (alts) {
    const want = alts.dataset.alts;
    const box = ev.target.closest(".picker").querySelector("[data-altlist]");
    if (box.hidden) {
      renderAlternatives(want, box);
      box.hidden = false;
      alts.textContent = "свернуть";
    } else {
      box.hidden = true;
      box.innerHTML = "";
      alts.textContent = "все " + alternativesFor(want).length + " предложений";
    }
    return;
  }

  // Choosing a supplier: from a suggestion chip or from the full list.
  const pick = ev.target.closest("[data-pick]");
  if (pick) {
    const want = pick.dataset.pick;
    const key = pick.dataset.key;
    // Нажатие переключает именно закрепление, а не «выбрано ли это сейчас».
    // Раньше нажатие на уже выбранное объявление снимало закрепление — и если
    // у продавца брали одну копию из четырёх, нажатие «беру у него» выглядело
    // так, будто кнопка мёртвая: план оставался прежним.
    if (pinnedOffers.get(want) === key) pinnedOffers.delete(want);
    else pinnedOffers.set(want, key);
    replanHunt();
    return;
  }

  const unpin = ev.target.dataset.unpin;
  if (unpin) {
    pinnedOffers.delete(unpin);
    replanHunt();
    return;
  }

  const dropWant = ev.target.dataset.skipWant;
  if (dropWant) {
    skipWants.set(dropWant.toLowerCase(), { name: dropWant });
    huntQty.delete(dropWant.toLowerCase());
    replanHunt();
  }
});

$("#hunt-orders").addEventListener("click", async (ev) => {
  await handleOrderClick(ev.target);
});

/* The card-level strip: quantity, dropping a card, taking a refusal back. */
$("#hunt-choices").addEventListener("click", (ev) => {
  const t = ev.target;

  if (t.id === "hunt-reset-choices") {
    resetHuntChoices();
    replanHunt();
    return;
  }
  if (t.dataset.skipWant) {
    skipWants.set(t.dataset.skipWant.toLowerCase(), { name: t.dataset.skipWant });
    huntQty.delete(t.dataset.skipWant.toLowerCase());
    replanHunt();
    return;
  }
  if (t.dataset.undrop) {
    skipWants.delete(t.dataset.undrop.toLowerCase());
    replanHunt();
    return;
  }
  if (t.dataset.unskip) {
    skipOffers.delete(t.dataset.unskip);
    replanHunt();
  }
});

$("#hunt-choices").addEventListener("change", (ev) => {
  if (ev.target.id === "hunt-prefer") {
    preferSeller = ev.target.value;
    replanHunt();
    return;
  }
  const name = ev.target.dataset.qty;
  if (!name) return;
  const max = Number(ev.target.max) || 1;
  const want = Math.max(1, Math.min(max, Number(ev.target.value) || 1));
  ev.target.value = want;
  if (want === max) huntQty.delete(name.toLowerCase());
  else huntQty.set(name.toLowerCase(), want);
  replanHunt();
});

/* Your edits to a draft are remembered per seller, so a re-plan keeps them. */
$("#hunt-plan").addEventListener("input", (ev) => {
  const seller = ev.target.dataset && ev.target.dataset.seller;
  if (!seller) return;
  const lot = (lastPlan && lastPlan.lots || []).find((l) => l.seller_name === seller);
  if (lot && ev.target.value === (lot.message_fresh || "")) {
    editedMessages.delete(seller);
    return;
  }
  editedMessages.set(seller, ev.target.value);
  if (lot) { lot.message = ev.target.value; lot.message_edited = true; }
});

$("#hunt-copy-all").addEventListener("click", () => {
  if (!lastPlan) return;
  const text = lastPlan.lots.map((lot) =>
    "=== " + lot.seller_name + " (" + (lot.seller_kind === "shop" ? "магазин" : "частный") +
    ", " + lot.total + " руб.) ===\n" + lot.message).join("\n\n");
  copyText(text, "Все сообщения скопированы");
});

$("#hunt-export").addEventListener("click", () => {
  if (!lastPlan) return;
  const lines = ["План покупки — итого " + lastPlan.total + " руб. у " + lastPlan.sellers + " продавцов", ""];
  lastPlan.lots.forEach((lot) => {
    lines.push("--- " + lot.seller_name + " (" + (lot.seller_city || "город не указан") +
      ") — " + lot.total + " руб.");
    lot.items.forEach((it) => {
      lines.push("   " + it.quantity + " x " + it.want + " @ " + it.unit_price + " руб.");
      lines.push("      как записано у продавца: " + plainLine(it.offer.line));
    });
    lines.push("");
  });
  if (lastPlan.unfilled.length) {
    lines.push("Не нашлось:");
    lastPlan.unfilled.forEach((u) => lines.push("   " + u.name + " — " + u.still_missing + " шт."));
  }
  copyText(lines.join("\n"), "План скопирован");
});

/* ------------------------------------------------- adding one more card ----

   The useful part is the order of the answer: a card at 300 from someone
   already in the plan costs no extra postage and
   usually beats 250 from a stranger, so the sellers already in the order come
   first, then everyone else. Nothing joins the order until a listing is
   chosen: the lookup is one polite topdeck request and it changes nothing.
*/

let huntAddTicket = 0;

async function huntSuggest(text) {
  const ticket = ++huntAddTicket;
  if (!text) { $("#hunt-suggest").innerHTML = ""; return; }
  try {
    const r = await api("/api/search?limit=10&q=" + encodeURIComponent(text));
    if (ticket !== huntAddTicket) return;
    $("#hunt-suggest").innerHTML = (r.cards || []).map((c) =>
      '<div class="setrow" data-name="' + esc(c.name) + '">' +
        '<span class="code">' + esc((c.set_code || "").toUpperCase()) + "</span>" +
        '<span class="nm">' + esc(c.display_name || c.name) + "</span>" +
        '<span class="yr">' + esc(c.ru_name || "") + "</span>" +
      "</div>").join("");
  } catch (e) { /* keep the previous suggestions */ }
}

function huntOfferRow(row, name) {
  const marks = [row.set_code, row.language, row.condition].filter(Boolean).join(" ");
  return (
    '<div class="lookrow" data-add="' + esc(name) + '" data-key="' + esc(row.key) + '">' +
      '<span class="p">' + rub(row.price) + "</span>" +
      '<span class="s">' + esc(row.seller_name) +
        (row.seller_kind === "shop" ? " · магазин" : "") +
        (row.seller_city ? " · " + esc(row.seller_city) : "") +
        (row.qty > 1 ? " · " + row.qty + " шт." : "") +
      "</span>" +
      '<span class="l">' + esc(plainLine(row.line)) +
        (marks ? " · " + esc(marks) : "") + "</span>" +
      '<button class="ghost tiny">взять здесь</button>' +
    "</div>"
  );
}

async function huntLookup(name) {
  if (!huntId) return toast("Сначала запустите охоту", true);
  const qty = Math.max(1, parseInt($("#hunt-add-qty").value, 10) || 1);
  $("#hunt-suggest").innerHTML = "";
  $("#hunt-add").value = name;

  const box = $("#hunt-lookup");
  const started = Date.now();
  const tick = setInterval(() => {
    box.innerHTML = '<div class="meta spinner">спрашиваю topdeck про «' + esc(name) +
      "»… " + Math.round((Date.now() - started) / 1000) + " с</div>";
  }, 400);
  try {
    const r = await post("/api/hunt/lookup", { hunt_id: huntId, name: name,
                                               quantity: qty,
                                               filters: readHuntFilters() });
    clearInterval(tick);
    const here = r.with_sellers_in_plan || [];
    const there = r.elsewhere || [];

    if (!here.length && !there.length) {
      box.innerHTML = '<div class="lookbox"><div class="meta">«' + esc(r.name) +
        "» сейчас никто не продаёт — по крайней мере под ваши фильтры." +
        "</div></div>";
      return;
    }

    box.innerHTML =
      '<div class="lookbox">' +
        '<div class="row tight wrap"><b>' + esc(r.name) + "</b>" +
          '<span class="meta">' + qty + " шт. · предложений " + r.offers +
          (r.rejected ? " · отброшено " + r.rejected : "") + "</span>" +
          '<span style="flex:1"></span>' +
          '<button class="ghost tiny" id="hunt-look-cancel">не надо</button>' +
        "</div>" +
        (here.length
          ? '<div class="lookgroup"><h5>Есть у тех, у кого уже покупаем ' +
            '<span class="meta">— без второй пересылки</span></h5>' +
            here.map((x) => huntOfferRow(x, r.name)).join("") + "</div>"
          : '<div class="meta">Ни у кого из тех, кто уже в заказе, этой карты нет.</div>') +
        (there.length
          ? '<div class="lookgroup"><h5>У остальных ' +
            '<span class="meta">— это ещё одна посылка и ещё один разговор</span></h5>' +
            there.slice(0, 12).map((x) => huntOfferRow(x, r.name)).join("") +
            (there.length > 12
              ? '<div class="meta">…и ещё ' + (there.length - 12) + "</div>"
              : "") +
            "</div>"
          : "") +
      "</div>";
  } catch (e) {
    clearInterval(tick);
    box.innerHTML = '<div class="lookbox"><div class="meta">' + esc(e.message) +
      "</div></div>";
  } finally {
    clearInterval(tick);
  }
}

async function huntAddConfirmed(name, offerKey) {
  const qty = Math.max(1, parseInt($("#hunt-add-qty").value, 10) || 1);
  try {
    await post("/api/hunt/add", { hunt_id: huntId, name: name, quantity: qty,
                                  offer_key: offerKey });
  } catch (e) {
    toast(e.message, true);
    return;
  }
  // The card is now part of the order, and the pin the user chose is kept
  // server-side, so later re-plans do not quietly move it.
  pinnedOffers.set(name, offerKey);
  $("#hunt-lookup").innerHTML = "";
  $("#hunt-add").value = "";
  // Keep the wants box in step, so re-running the hunt includes the card.
  addToHunt(name, qty);
  await replanHunt();
  toast("«" + name + "» в заказе");
}

$("#hunt-add").addEventListener("input", debounce((ev) => {
  huntSuggest(ev.target.value.trim());
}, 250));

$("#hunt-add").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  ev.preventDefault();
  const first = $("#hunt-suggest .setrow");
  if (first) huntLookup(first.dataset.name);
  else if (ev.target.value.trim()) huntLookup(ev.target.value.trim());
});

$("#hunt-suggest").addEventListener("click", (ev) => {
  const row = ev.target.closest(".setrow");
  if (row) huntLookup(row.dataset.name);
});

$("#hunt-lookup").addEventListener("click", (ev) => {
  if (ev.target.id === "hunt-look-cancel") {
    $("#hunt-lookup").innerHTML = "";
    return;
  }
  const row = ev.target.closest(".lookrow");
  if (row) huntAddConfirmed(row.dataset.add, row.dataset.key);
});

$("#hunt-wants").addEventListener("input", debounce(() => {
  store.set("hunt", $("#hunt-wants").value);
}, 600));

/* ---------------------------------------- что ещё есть у этих продавцов

   Посылка стоит одинаково, одна в ней карта или двадцать. Продавец уже в
   плане -- значит добрать у него остальное бесплатно по доставке, и это
   самый большой выигрыш, какой в охоте вообще бывает.

   У частника на topdeck все объявления ведут на одну ссылку -- тему, где он
   держит весь склад. Её мы и читаем: одна тема -- один запрос, с той же
   задержкой 1.5 с. У магазинов ссылка ведёт на конкретный товар, поэтому
   они сюда не попадают -- так и сказано на экране.

   Запрос уходит только по нажатию. Молча лазить по чужим страницам
   программа не будет. */

function restockSellers() {
  /* Ссылки на склады -- из самого плана: их дал topdeck вместе с
     объявлениями, мы ничего не выдумываем. */
  const seen = new Map();
  for (const lot of (lastPlan && lastPlan.lots) || []) {
    for (const item of lot.items || []) {
      // Поле называется `offer` -- так его кладёт PlanItem.as_dict(). Первая
      // версия искала `candidate`, не находила ничего и честно сообщала «в
      // плане одни магазины» на плане из десяти частников.
      const offer = item.offer || item;
      const url = (offer.url || "").trim();
      const kind = ((offer.seller || {}).kind) || lot.seller_kind;
      if (!url || kind === "shop") continue;
      if (!url.startsWith("https://topdeck.ru/")) continue;
      if (!seen.has(url)) seen.set(url, lot.seller_name || "продавец");
    }
  }
  return [...seen.entries()].map(([url, name]) => ({ url, name }));
}

function restockRow(row, name) {
  /* Что мы вправе сказать про цену.

     Был один процент -- «дешевле медианы на столько». Мерка оказалась
     негодной: цены в кеше сведены по ИМЕНИ карты, без печати и фойла, и у
     трети карт под одним именем лежат вещи, отличающиеся в десятки раз.
     Обычный Swords за 15 ₽ против медианы 400 ₽ подписывался «дешевле на
     96%» и шёл первой находкой -- хотя сравнивали его с фойлами.

     Теперь вывод делается только там, где его можно сделать честно, а в
     остальных случаях показываются сами числа рынка. */
  /* С чем сравнили. «По этой же версии» -- это фойл против фойла и убитая
     копия против убитой: цены теперь пишутся по версиям, и сравнение по
     имени осталось запасным путём для старых записей. */
  const span = row.basis === "version"
    ? "эту же версию (" + esc(row.version) + ") видели от " +
      rub(row.market_min) +
      (row.market_max && row.market_max > row.market_min
        ? " до " + rub(row.market_max) : "") +
      (row.market_offers ? " · " + row.market_offers + " объявл." : "")
    : row.market_min
    ? "на рынке от " + rub(row.market_min) +
      (row.median ? ", медиана " + rub(row.median) : "") +
      (row.market_offers ? " · " + row.market_offers + " объявл." : "")
    : "рыночной цены ещё не знаем";

  let market;
  if (row.verdict === "below-floor") {
    market = '<b class="good">дешевле всего, что видели' +
      (row.basis === "version" ? " у этой версии" : "") + ", на " +
      row.cheaper_by + "%</b> · " + span;
  } else if (row.verdict === "in-range") {
    market = "обычная цена · " + span;
  } else if (row.verdict === "above") {
    market = '<b class="bad">дороже рынка на ' + Math.abs(row.cheaper_by) +
      "%</b> · " + span;
  } else if (row.verdict === "incomparable") {
    market = '<span class="meta">' + esc(row.why || "сравнивать не с чем") +
      "</span> · " + span;
  } else {
    market = '<span class="meta">' + span + "</span>";
  }

  /* Второе число -- про саму карту, а не про сегодня.

     «На рынке от 180 ₽» отвечает только на вопрос «сколько просят
     сейчас». Дёшево это или так всегда -- видно по замерам: если цену
     спрашивали хотя бы трижды, известен коридор, в котором она ходила.
     Меньше трёх замеров -- тут пусто, и никто ничего не обещает. */
  const band = row.band || {};
  let history = "";
  if (band.verdict === "cheap") {
    history = '<span class="good">дешевле, чем когда-либо видели: низ был ' +
      rub(band.low) + "</span>";
  } else if (band.verdict === "usual") {
    history = '<span class="meta">обычная для неё цена: ходила от ' +
      rub(band.low) + " до " + rub(band.high) + "</span>";
  } else if (band.verdict === "dear") {
    history = '<span class="bad">дороже, чем её видели: верх был ' +
      rub(band.high) + "</span>";
  } else if (band.verdict === "flat") {
    history = '<span class="meta">цена не менялась: ' + rub(band.low) +
      " во всех " + band.points + " замерах</span>";
  }

  const marks = [];
  if (row.foil) marks.push("фойл");
  if (row.set_code) marks.push(String(row.set_code).toUpperCase());
  if (row.condition) marks.push(row.condition);

  return (
    '<div class="restockrow' + (row.verdict === "above" ? " pricey" : "") + '">' +
      // Имя и пометки -- разными узлами: пометки «фойл · MPS · NM» это не
      // часть названия карты, и ни на экране, ни в проверках они не должны
      // с ним слипаться.
      '<b class="rwant">' + esc(row.want) + "</b>" +
      (marks.length
        ? '<span class="meta rmarks">' + esc(marks.join(" · ")) + "</span>"
        : '<span class="rmarks"></span>') +
      '<span class="price">' + (row.price ? rub(row.price) : "цена не видна") +
        "</span>" +
      '<span class="meta rmarket">' + market +
        (history ? " · " + history : "") + "</span>" +
      // plainLine -- потому что topdeck оборачивает искомое имя в <b>, и
      // сырая строка показала бы человеку теги. Это уже было однажды.
      '<span class="rawline">' + esc(plainLine(row.line).slice(0, 80)) + "</span>" +
      '<button class="ghost tiny" data-restock-add="' + esc(row.want) +
        '" data-restock-seller="' + esc(name) + '">+ в охоту</button>' +
    "</div>"
  );
}

/* На чём стоит сравнение с рынком -- и где оно грубое.

   Цена, записанная одним числом на имя, смешивает в себе фойл, убитую копию
   и обычную карту: разница между ними бывает в десятки раз. Сравнение с
   таким числом -- не ответ, а вид ответа, и до сих пор он выглядел на экране
   точно так же, как честное сравнение версии с версией.

   Молчать об этом было особенно некстати потому, что лечится оно одним
   выключателем: разбор по версиям появляется сам, когда цену спрашивают
   заново. На живых данных таких цен было двести шестьдесят восемь из
   двухсот восьмидесяти восьми -- то есть почти всё. */
function restockVersionNote(data, sellers) {
  const v = data.versions || {};
  const rough = sellers.reduce((n, s) => n + (s.found || []).filter(
    (r) => r.basis !== "version" && r.verdict !== "no-price").length, 0);
  if (!rough) return "";
  const left = Math.max(0, (v.priced || 0) - (v.split || 0));
  return '<p class="meta">Строк, сравненных по имени, а не по версии: <b>' +
    rough + "</b>. Для них цена записана одним числом, в котором фойл и " +
    "убитая копия смешаны, — сравнение по ним грубое." +
    (left
      ? " Таких цен " + left + " из " + (v.priced || 0) +
        ": включите «дополнять цены понемногу» в учёте коллекции, и они " +
        "разберутся по версиям сами."
      : "") +
    "</p>";
}

function restockRender(data, names) {
  const box = $("#hunt-restock-box");
  const sellers = (data.sellers || []).filter((s) => (s.found || []).length);
  if (!sellers.length) {
    const miss = ((data.archetype || {}).need_sample || []);
    box.innerHTML =
      '<p class="meta">У этих продавцов из вашего списка больше ничего нет. ' +
      "Искали " + data.wants + " назв. — то, чего нет в коллекции." +
      (miss.length
        ? " Похожие колоды не учитывались: выборка не собрана (" +
          esc(miss.join(", ")) + ")."
        : "") +
      "</p>";
    return;
  }
  /* Источник «похожие колоды» бывает пуст не потому, что ничего не нашлось,
     а потому, что выборка чужих колод ещё не собрана. Молчать об этом --
     значит оставить человека с мыслью, что флажок сломан. */
  const arch = data.archetype || {};
  const needs = arch.need_sample || [];
  const archNote = needs.length
    ? '<p class="meta">Похожие колоды в поиск не вошли: выборка не собрана ' +
      "для форматов — " + esc(needs.join(", ")) +
      ". Соберите её в предложке, вкладка «Под ваш состав»: она читается с " +
      "диска и новых запросов к продавцам не делает.</p>"
    : (arch.names
       ? '<p class="meta">Из похожих колод добавлено названий: <b>' +
         arch.names + "</b> (по " + (arch.decks_used || 0) + " колодам).</p>"
       : "");

  box.innerHTML =
    '<h3>Что ещё есть у продавцов из плана</h3>' + archNote +
    '<p class="meta">Посылка им уже оплачена: эти карты приедут без второй ' +
    "пересылки. Искали " + data.wants + " назв. · " + esc(data.note || "") +
    "</p>" + restockVersionNote(data, sellers) +
    sellers.map((seller) => {
      const name = names.get(seller.url) || "продавец";
      // Сколько из найденного дешевле всего, что мы видели, -- это и есть
      // ответ на вопрос «стоит ли сюда смотреть». Считаются только честные
      // находки: несравнимое (фойл, разнобой цен) сюда не попадает.
      const cheap = seller.found.filter(
        (r) => r.verdict === "below-floor").length;
      return '<div class="restockbox">' +
        "<h4>" + esc(name) + ' <span class="meta">' +
          (seller.lines || 0) + " строк в складе, нашлось " +
          seller.found.length +
          (cheap ? ' · <b class="good">дешевле всего виденного: ' + cheap +
                   "</b>" : "") +
        "</span></h4>" +
        seller.found.map((row) => restockRow(row, name)).join("") +
      "</div>";
    }).join("");
}

async function restockRun() {
  const sellers = restockSellers();
  const box = $("#hunt-restock-box");
  if (!sellers.length) {
    box.innerHTML =
      '<p class="meta">В плане нет частников с темой на topdeck: у магазинов ' +
      "ссылка ведёт на отдельный товар, и склад так не прочитать.</p>";
    return;
  }

  const button = $("#hunt-restock");
  button.disabled = true;
  box.innerHTML = '<p class="meta spinner">читаю склады: ' + sellers.length +
    " шт., по одному запросу с задержкой 1.5 с…</p>";
  try {
    const names = new Map(sellers.map((s) => [s.url, s.name]));
    const sources = ["fav", "decks"];
    const arch = $("#hunt-restock-archetype");
    if (arch && arch.checked) sources.push("archetype");
    const data = await post("/api/hunt/restock",
                            { sellers: sellers.map((s) => s.url),
                              sources: sources });
    restockRender(data, names);
  } catch (e) {
    box.innerHTML = '<p class="meta">не вышло: ' + esc(e.message) + "</p>";
  } finally {
    button.disabled = false;
  }
}

$("#hunt-restock").addEventListener("click", restockRun);

$("#hunt-restock-box").addEventListener("click", (ev) => {
  const add = ev.target.closest("[data-restock-add]");
  if (!add) return;
  addToHunt(add.dataset.restockAdd, 1);
  toast("В охоту: " + add.dataset.restockAdd +
        " — ищите его у «" + add.dataset.restockSeller + "»");
});
