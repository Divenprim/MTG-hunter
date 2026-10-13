"use strict";

/* Окно карты: картинка, печати, цены, предложения и покупки.

   Уехало из app.js, где лежало вперемешку с поиском. В файле оно было
   разорвано пополам приветствием и пустой выдачей -- те остались там, где и
   должны быть, рядом с поиском; сюда переехали обе половины окна.

   Загружается после app.js и пользуется его помощниками. Ничего отсюда не
   зовётся при загрузке: окно открывают нажатием.
*/

/* ============================================================= card modal */

let modalCard = null;
let modalFace = 0;
let modalPrinting = null;  // printing picked from the table, if any

function faceImage(card, faceIndex) {
  const faces = card.faces || [];
  const f = faces[faceIndex];
  // Adventure / split / flip cards are one physical card: Scryfall gives no
  // per-face image, so fall back to the card-level art.
  if (f && f.image_normal) return f.image_normal;
  return card.image_normal || card.image_small || "";
}

function legalityChips(legalities) {
  const order = ["standard", "pioneer", "modern", "legacy", "vintage", "commander", "pauper", "premodern"];
  return order
    .filter((f) => legalities && legalities[f])
    .map((f) => {
      const ok = legalities[f] === "legal";
      return '<span class="chip ' + (ok ? "ok" : "no") + '">' + esc(f) +
        (ok ? "" : ": " + esc(legalities[f])) + "</span>";
    })
    .join("");
}

function renderModal() {
  const c = modalCard;
  const faces = c.faces || [];
  const face = faces[modalFace] || {};
  const name = faces.length > 1 ? (face.name || c.name) : c.name;
  const typeLine = (faces.length > 1 ? face.type_line : c.type_line) || c.type_line || "";
  const rules = (faces.length > 1 ? face.oracle_text : c.oracle_text) || c.oracle_text || "";
  const mana = (faces.length > 1 ? face.mana_cost : c.mana_cost) || "";
  const pt = face.power || c.power
    ? ((face.power || c.power) + "/" + (face.toughness || c.toughness))
    : "";

  const canFlip = faces.length > 1;

  $("#modal-body").innerHTML =
    '<div class="cardview">' +
      '<div class="art">' +
        '<img id="modal-art" src="' + esc(faceImage(c, modalFace)) + '" alt="' + esc(name) + '">' +
        (canFlip
          ? '<div class="row tight"><button id="modal-flip" class="ghost">Перевернуть → ' +
            esc((faces[(modalFace + 1) % faces.length] || {}).name || "") + "</button></div>"
          : "") +
      "</div>" +
      "<div>" +
        "<h2>" + esc(name) + "</h2>" +
        (c.flavor_name
          ? '<div class="runame">напечатана как «' + esc(c.flavor_name) + "»</div>"
          : "") +
        (c.ru_name ? '<div class="runame">' + esc(c.ru_name) + "</div>" : "") +
        '<div class="typeline">' + esc(typeLine) +
          (mana ? " · " + esc(mana) : "") +
          (pt ? " · " + esc(pt) : "") +
        "</div>" +
        (rules ? '<div class="rules">' + esc(rules) + "</div>" : "") +
        '<div class="legal">' + legalityChips(c.legalities) + "</div>" +
        '<div class="qtyadd">' +
          "<span>В охоту:</span>" +
          [1, 2, 3, 4].map((n) => '<button class="add-hunt" data-n="' + n + '">' + n + " шт.</button>").join("") +
          '<button id="modal-prices" class="ghost">Цены на topdeck</button>' +
          '<button id="modal-combos-btn" class="ghost">Комбо с этой картой</button>' +
        "</div>" +
        '<div class="qtyadd">' +
          "<span>В избранное:</span>" +
          [1, 2, 3, 4].map((n) => '<button class="add-fav" data-n="' + n + '">' + n + " шт.</button>").join("") +
          '<span class="meta" id="modal-fav-hint">в текущую папку</span>' +
        "</div>" +
        // Окно карты открывается отовсюду -- из поиска, из предложений, из
        // комбо, -- и до сих пор из него карту можно было положить куда угодно,
        // кроме открытой колоды. То есть ровно туда, зачем её и смотрели.
        (typeof bdDeck !== "undefined" && bdDeck
          ? '<div class="qtyadd">' +
              "<span>В колоду «" + esc(bdDeck.name) + "»:</span>" +
              '<button class="add-deck" data-section="main">основная</button>' +
              '<button class="add-deck" data-section="side">сайдборд</button>' +
              '<button class="add-deck" data-section="maybe">возможно</button>' +
              '<span class="meta">одну копию</span>' +
            "</div>"
          : "") +
        '<div class="bought" id="modal-bought"></div>' +
        '<div class="pricetrack" id="modal-pricetrack" hidden></div>' +
        '<div class="flabel">Все печати</div>' +
        '<div class="printings" id="modal-printings"><div class="meta">загружаю…</div></div>' +
        '<div class="offerlist" id="modal-offers"></div>' +
        '<div class="combolist" id="modal-combos"></div>' +
      "</div>" +
    "</div>";

  if (canFlip) {
    $("#modal-flip").addEventListener("click", () => {
      modalFace = (modalFace + 1) % faces.length;
      renderModal();
    });
  }
  $$(".add-hunt").forEach((b) => b.addEventListener("click", () => {
    addToHunt(c.name, parseInt(b.dataset.n, 10));
  }));
  $$(".add-fav").forEach((b) => b.addEventListener("click", () => {
    // If a printing was picked in the table, pin it: a Secret Lair foil is a
    // different want from the cheap reprint.
    addToFavourites(c, parseInt(b.dataset.n, 10), modalPrinting);
  }));
  $$(".add-deck").forEach((b) => b.addEventListener("click", async () => {
    if (typeof bdAddByName !== "function" || !bdDeck) return;
    await bdAddByName(c.name, 1, b.dataset.section);
  }));
  $("#modal-prices").addEventListener("click", () => loadCardOffers(c));
  loadPriceTrack(c.name);
  $("#modal-combos-btn").addEventListener("click", () => {
    if (typeof loadCardCombos === "function") loadCardCombos(c);
    else toast("Комбо пока не подключены", true);
  });
  loadPrintings(c);
  loadPurchases(c);
}

/* Что вы за эту карту в действительности заплатили. Другой вопрос, чем «сколько
   она стоит на topdeck»: цены двигаются, а заплаченное — факт. Если карту не
   покупали, блок молчит: пустая строка «покупок нет» никому не нужна. */
async function loadPurchases(card) {
  const box = $("#modal-bought");
  if (!box) return;
  box.innerHTML = "";
  try {
    const r = await api("/api/orders/purchases?name=" + encodeURIComponent(card.name));
    if (!r.purchases || !r.purchases.length) return;
    box.innerHTML =
      "<b>Вы её покупали:</b> " + r.copies + " " +
        plural(r.copies, "шт.", "шт.", "шт.") + " за " + rub(r.spent) +
      '<div class="meta">' + r.purchases.map((p) =>
        orderDate(p.when_received) + " — " + esc(p.seller_name) + ", " +
        p.quantity + "× по " + rub(p.unit_price)).join("<br>") + "</div>";
  } catch (e) {
    // История покупок -- приятное дополнение, а не причина ломать окно карты.
  }
}

async function loadPrintings(card) {
  /* Печати подгружаются отдельным запросом, а окно карты можно закрыть
     раньше, чем он вернётся: тогда писать уже некуда -- closeModal() вычищает
     всё содержимое окна. Поэтому перед каждой записью проверяем, что окно с
     той же картой ещё открыто. Ошибка была тихой -- падала в консоль и
     оставляла окно без списка печатей. */
  const target = () => (modalCard === card ? $("#modal-printings") : null);
  const box = target();
  if (!card.oracle_id) {
    if (box) box.innerHTML = '<div class="meta">нет данных о печатях</div>';
    return;
  }
  try {
    const r = await api("/api/printings/" + encodeURIComponent(card.oracle_id));
    const rows = r.printings.map((p) => {
      const usd = (p.prices && p.prices.usd) || "";
      return '<tr data-img="' + esc(p.image_normal || "") + '" data-set="' +
        esc(p.set_code || "") + '" data-cn="' + esc(p.collector_number || "") + '">' +
        "<td>" + esc((p.set_code || "").toUpperCase()) + "</td>" +
        "<td>" + esc(p.set_name || "") + "</td>" +
        "<td>#" + esc(p.collector_number || "") + "</td>" +
        "<td>" + esc(p.rarity || "") + "</td>" +
        "<td>" + esc(p.flavor_name || (p.ru_name ? "рус" : "")) + "</td>" +
        "<td>" + (usd ? dollars(usd) : "") + "</td>" +
        "</tr>";
    }).join("");
    const live = target();
    if (!live) return;
    live.innerHTML = "<table>" + rows + "</table>";
    live.addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr");
      if (!tr || !tr.dataset.img) return;
      $$("#modal-printings tr").forEach((r2) => r2.classList.remove("sel"));
      tr.classList.add("sel");
      $("#modal-art").src = tr.dataset.img;
      modalPrinting = { set_code: tr.dataset.set, collector_number: tr.dataset.cn };
      const hint = $("#modal-fav-hint");
      if (hint) {
        hint.textContent = "печать " + (tr.dataset.set || "").toUpperCase() +
          " #" + (tr.dataset.cn || "");
      }
    });
  } catch (e) {
    const live = target();
    if (live) live.innerHTML = '<div class="meta">не удалось загрузить печати</div>';
  }
}

async function loadCardOffers(card) {
  const box = $("#modal-offers");
  box.innerHTML = '<div class="meta spinner">спрашиваю topdeck…</div>';
  try {
    const r = await post("/api/offers", { names: [card.name] });
    if (!r.offers.length) {
      box.innerHTML = '<div class="meta">на topdeck сейчас нет предложений</div>';
      return;
    }

    // topdeck labels every result with the name we searched for, even when the
    // seller is selling a different card -- "Burgeoning" comes back with
    // "Urban Burgeoning" at a tenth of the price. Only verified lines are
    // priced here; the rest are counted, named and kept out of the way.
    // Сортировка и «от X ₽» -- по цене, которой можно верить: иначе список
    // возглавляет самое неверно разобранное число, а заголовок обещает цену,
    // по которой карту никто не продаёт.
    const far = Number.MAX_SAFE_INTEGER;
    const mine = r.offers.filter((o) => o.verdict === "match")
      .sort((a, b) => (trustedPrice(a) || far) - (trustedPrice(b) || far));
    const others = r.other_cards || {};
    const otherCount = Object.keys(others)
      .reduce((n, k) => n + others[k], 0);
    const unclear = r.offers.filter((o) => o.verdict === "unclear");

    let html = "";
    if (mine.length) {
      const cheapest = mine.map(trustedPrice).filter(Boolean)[0];
      const disputed = mine.filter((o) => o.price_disputed).length;
      html += '<div class="flabel">Предложения на topdeck — ' + mine.length +
        " шт." + (cheapest ? ", от " + rub(cheapest) : "") +
        (disputed
          ? ' <span class="chip warn" title="topdeck дал одно число, а ' +
            'продавец написал другое — берём то, что в строке">' +
            "спорная цена: " + disputed + "</span>"
          : "") +
        "</div>" +
        mine.slice(0, 25).map(offerLine).join("");
    } else {
      html += '<div class="meta">Ни одно предложение не подтвердилось как «' +
        esc(card.name) + '» — topdeck отдал только похожие названия.</div>';
    }

    if (otherCount) {
      html += '<details class="help"><summary>Скрыто ' + otherCount +
        " " + offersWord(otherCount) + " других карт</summary><div class=\"meta\">" +
        Object.keys(others).sort((a, b) => others[b] - others[a])
          .map((name) => others[name] + " × " + esc(name)).join("<br>") +
        "</div></details>";
    }
    if (unclear.length) {
      html += '<details class="help"><summary>' + unclear.length +
        " " + offersWord(unclear.length) + " без узнаваемого имени в строке</summary>" +
        unclear.slice(0, 10).map(offerLine).join("") + "</details>";
    }
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<div class="meta" style="color:var(--bad)">' + esc(e.message) + "</div>";
  }
}

/* Цена, которой можно верить.

   topdeck иногда берёт за цену число из строки, которое ценой не является:
   «13 Болото (#241) [11 рус, 2 eng] - 30 руб.» приезжает как 11 ₽, потому что
   «11 рус» — это количество. Программа такие расхождения ловит (price_check) и
   в план такое объявление не берёт, но показывала всё равно число topdeck — и
   в окне карты значилось «от 11 ₽» там, где карта стоит 30.

   Правило то же, что и везде: строка продавца важнее. Если числа разошлись,
   берём то, что написал сам продавец; если в строке числа нет — цены нет. */
function trustedPrice(o) {
  if (!o) return null;
  if (o.price_disputed) return o.price_in_line || null;
  return o.cost || null;
}

function offerLine(o) {
  const seller = o.seller && o.seller.name ? o.seller.name : "?";
  const price = trustedPrice(o);
  return '<div class="offer">' +
    "<div>" +
      '<div class="rawline">' + esc(plainLine(o.line)) + "</div>" +
      chipsFor(o.parsed || {}, "") +
      (o.price_disputed
        ? '<div class="printinfo"><span class="chip warn">цена под вопросом</span> ' +
          esc(o.price_reason || "") + "</div>"
        : "") +
      (o.verdict === "unclear"
        ? '<div class="printinfo">' + esc(o.verdict_reason || "") + "</div>"
        : "") +
    "</div>" +
    '<div class="price">' +
      (price
        ? "<b>" + rub(price) + "</b>"
        : '<b class="noprice">цена под вопросом</b>') +
      "<small>" + esc(seller) +
      (o.qty ? " · " + o.qty + " шт." : "") + "</small>" +
      (o.url ? '<small><a href="' + esc(o.url) +
        '" target="_blank" rel="noopener">объявление</a></small>' : "") +
    "</div></div>";
}


/* Как менялась цена этой карты.

   Записывается каждый раз, когда цену узнают -- из колоды, отсюда же или
   медленным дополнением. Замер в день: цена на topdeck не меняется по часам,
   и полсотни строк за вторник ничего не показали бы. Старые замеры
   прореживаются до одного в месяц, так что весь график -- это десятки чисел,
   а не тысячи. */
async function loadPriceTrack(name) {
  const box = $("#modal-pricetrack");
  if (!box) return;
  let data;
  try {
    data = await api("/api/prices/history?name=" + encodeURIComponent(name));
  } catch (e) {
    return;
  }
  const points = (data.history || []).filter((p) => p.rub_min);
  const now = data.current || {};
  if (!points.length) {
    box.hidden = false;
    box.innerHTML = '<div class="flabel">Цена на topdeck</div>' +
      '<p class="meta">Цену этой карты ещё не спрашивали. Нажмите «Цены на ' +
      "topdeck» — замер запишется, и со временем здесь будет видно, дорожает " +
      "она или дешевеет.</p>";
    return;
  }

  const first = points[0];
  const last = points[points.length - 1];
  const move = last.rub_min - first.rub_min;
  box.hidden = false;
  box.innerHTML =
    '<div class="flabel">Цена на topdeck</div>' +
    '<div class="row tight wrap">' +
      "<b>" + rub(last.rub_min) + "</b>" +
      (now.checked_at
        ? '<span class="meta">проверено ' + esc(now.checked_at.slice(0, 16)) + "</span>"
        : "") +
      (points.length > 1
        ? '<span class="' + (move > 0 ? "bad" : (move < 0 ? "good" : "meta")) + '">' +
          (move > 0 ? "дороже на " : (move < 0 ? "дешевле на " : "без изменений")) +
          (move ? rub(Math.abs(move)) : "") + " с " + esc(first.at) + "</span>"
        : '<span class="meta">замер один — динамика появится со временем</span>') +
    "</div>" +
    (points.length > 1 ? priceChart(points) : "");
}

/* Тот же приём, что и у графика стоимости коллекции: точек десятки, тянуть
   ради них библиотеку незачем. */
function priceChart(points) {
  const w = 520;
  const h = 96;
  const pad = 8;
  const vals = points.map((p) => p.rub_min);
  let low = Math.min.apply(null, vals);
  let high = Math.max.apply(null, vals);
  if (high - low < 1) { low -= 1; high += 1; }
  const x = (i) => pad + (w - pad * 2) * (i / (points.length - 1));
  const y = (v) => h - pad - (h - pad * 2) * ((v - low) / (high - low));
  const line = points.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " +
    y(p.rub_min).toFixed(1)).join(" ");
  return (
    '<div class="pricechart">' +
      '<svg viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" ' +
          'role="img" aria-label="цена по дням">' +
        '<path class="worthline" d="' + line + '"></path>' +
        points.map((p, i) =>
          '<circle class="worthdot" cx="' + x(i).toFixed(1) + '" cy="' +
          y(p.rub_min).toFixed(1) + '" r="2.5"><title>' + esc(p.at) + ": " +
          rub(p.rub_min) + (p.offers ? " · предложений " + p.offers : "") +
          "</title></circle>").join("") +
      "</svg>" +
      '<div class="worthaxis"><span>' + esc(points[0].at) + "</span>" +
        "<span>" + rub(low) + " — " + rub(high) + "</span>" +
        "<span>" + esc(points[points.length - 1].at) + "</span></div>" +
    "</div>"
  );
}

function openCard(card) {
  modalCard = card;
  modalPrinting = null;
  modalFace = card.matched_face != null ? card.matched_face : 0;
  $("#overlay").hidden = false;
  renderModal();
}

/* Предложение приходит одним именем: замена в «Форматах», добавка по теме,
   кусок комбо. Карту целиком -- с текстом, легальностью, печатями и ценами --
   приходится спросить отдельно, зато дальше это то же самое окно карты, что и
   везде, со всеми его кнопками. */
async function openCardByName(name) {
  if (!name) return;
  try {
    const r = await api("/api/card?name=" + encodeURIComponent(name));
    openCard(r.card);
  } catch (e) {
    toast(e.message, true);
  }
}

function closeModal() {
  $("#overlay").hidden = true;
  $("#modal-body").innerHTML = "";
  modalCard = null;
}

$("#modal-close").addEventListener("click", closeModal);
$("#overlay").addEventListener("click", (ev) => {
  if (ev.target === $("#overlay")) closeModal();
});
