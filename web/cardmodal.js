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

/* Куда положить карту, не уходя с экрана.

   Прежде окно карты умело класть в охоту и в избранное, а в колоду -- только
   в ту, что уже открыта в билдере. Если открытой не было, строки «в колоду»
   не появлялось вовсе: при девяти заведённых колодах человек видел ноль
   кнопок. Чтобы положить карту, надо было закрыть окно, уйти в билдер,
   открыть там колоду, вернуться в поиск, снова найти карту и снова её
   открыть. Шесть действий ради одного.

   Теперь выбор здесь же. Выбранная колода и количество помнятся: карты в
   колоду кладут подряд, и переспрашивать каждый раз -- то же самое, что
   спрашивать дважды. */

let modalDecks = [];

/* Перелистывание: сосед слева и сосед справа.

   Открыв карту из выдачи, дальше смотрят следующую, и следующую -- а для
   этого приходилось закрывать окно, вести мышь к соседней плитке и открывать
   снова. На полсотни карт это полторы сотни лишних действий.

   Лента -- это не список карт, а способ открыть карту по месту в списке:
   выдача поиска, колода и «все печати» устроены по-разному, и тащить их
   содержимое сюда значило бы знать про каждую. Тот, кто открывает окно,
   знает свой список сам и даёт две вещи: где мы сейчас и как открыть N-ю.

   Кнопки живут внутри окна, а не поверх фона: нажатие по фону закрывает
   окно, и стрелка, стоящая на фоне, закрывала бы его при каждом промахе. */
let modalStrip = null;

function modalStripSet(strip) {
  if (!strip || typeof strip.open !== "function") {
    modalStrip = null;
    return;
  }
  const total = Math.max(0, strip.total | 0);
  const at = Math.min(Math.max(0, strip.at | 0), Math.max(0, total - 1));
  modalStrip = total > 1 ? { total: total, at: at, open: strip.open } : null;
}

function modalStep(delta) {
  if (!modalStrip) return;
  // По кругу: с последней вперёд -- к первой. Упираться в край в ленте из
  // полусотни карт раздражает сильнее, чем проскочить начало.
  const total = modalStrip.total;
  const next = ((modalStrip.at + delta) % total + total) % total;
  const strip = modalStrip;
  strip.open(next);
}

/* Стрелки -- на самой картинке, крупные и всегда видные.

   Первая версия ставила их строкой над именем: кнопки 30 на 28 рядом с
   рядами крупных жёлтых кнопок действий. Формально всё было на месте, а на
   деле человек их не находил -- мелкое и тусклое рядом с крупным и ярким
   глаз не замечает. Снимок это показал сразу.

   На картинке у них своё место, которое ни с чем не спорит, и там их ждут:
   так листают всё, где есть «предыдущая-следующая». */
function modalFlipButtons() {
  if (!modalStrip) return "";
  return (
    '<button type="button" class="flip prev" title="Предыдущая карта (←)"' +
      ' aria-label="Предыдущая карта">‹</button>' +
    '<button type="button" class="flip next" title="Следующая карта (→)"' +
      ' aria-label="Следующая карта">›</button>'
  );
}

function modalStripRow() {
  if (!modalStrip) return "";
  return (
    '<div class="flipstrip">' +
      "карта " + (modalStrip.at + 1) + " из " + modalStrip.total +
      '<span class="hint">листать: ← → или стрелки на картинке</span>' +
    "</div>"
  );
}

function modalDeckId() {
  // Открытая в билдере -- по умолчанию: раз её открыли, скорее всего в неё и
  // кладут. Иначе -- та, в которую клали в прошлый раз.
  const open = (typeof bdDeck !== "undefined" && bdDeck) ? bdDeck.id : null;
  const saved = store.get("modalDeck", null);
  const known = (id) => modalDecks.some((d) => d.id === id);
  if (open && known(open)) return open;
  if (saved && known(saved)) return saved;
  return modalDecks.length ? modalDecks[0].id : null;
}

function modalDeckRow() {
  if (!modalDecks.length) {
    return '<div class="qtyadd"><span>В колоду:</span>' +
      '<span class="meta">колод пока нет — их заводят на вкладке ' +
      "«Билдер»</span></div>";
  }
  const chosen = modalDeckId();
  const qty = Number(store.get("modalDeckQty", 1)) || 1;
  return (
    '<div class="qtyadd"><span>В колоду:</span>' +
      '<select id="modal-deck">' +
        modalDecks.map((d) =>
          '<option value="' + esc(d.id) + '"' +
          (d.id === chosen ? " selected" : "") + ">" + esc(d.name) +
          (d.format ? " · " + esc(d.format) : "") + "</option>").join("") +
      "</select>" +
      '<select id="modal-deck-qty">' +
        [1, 2, 3, 4].map((n) => '<option value="' + n + '"' +
          (n === qty ? " selected" : "") + ">×" + n + "</option>").join("") +
      "</select>" +
      '<button class="add-deck" data-section="main">основная</button>' +
      '<button class="add-deck" data-section="side">сайдборд</button>' +
      '<button class="add-deck" data-section="maybe">под вопросом</button>' +
    "</div>"
  );
}

/* Папки избранного -- тот же вопрос, что и колоды: куда положить.

   Строка «В избранное» говорила «в текущую папку» и не называла её. Текущая
   при свежей загрузке -- просто первая в списке, так что карта молча падала
   в неё; при пяти папках это пять раз из шести не туда. Путь в нужную папку
   выходил в девять действий: закрыть окно, уйти в «Избранное», щёлкнуть
   папку, вернуться, снова найти карту, снова открыть и только тогда нажать.

   Теперь папка выбирается здесь, а выбор помнится и становится текущим: то
   же самое, что человек сделал бы руками на вкладке. */

function modalFavFolders() {
  return (typeof favDoc !== "undefined" && favDoc && favDoc.folders) || [];
}

function modalFavId() {
  const folders = modalFavFolders();
  const known = (id) => folders.some((f) => f.id === id);
  const current = (typeof favCurrent !== "undefined") ? favCurrent : null;
  const saved = store.get("modalFav", null);
  if (current && known(current)) return current;
  if (saved && known(saved)) return saved;
  return folders.length ? folders[0].id : null;
}

function modalFavRow() {
  const folders = modalFavFolders();
  if (!folders.length) {
    return '<div class="qtyadd"><span>В избранное:</span>' +
      '<span class="meta">папок пока нет — их заводят на вкладке ' +
      "«Избранное»</span></div>";
  }
  const chosen = modalFavId();
  return (
    '<div class="qtyadd"><span>В избранное:</span>' +
      '<select id="modal-fav">' +
        folders.map((f) =>
          '<option value="' + esc(f.id) + '"' +
          (f.id === chosen ? " selected" : "") + ">" + esc(f.name) +
          "</option>").join("") +
      "</select>" +
      [1, 2, 3, 4].map((n) =>
        '<button class="add-fav" data-n="' + n + '">' + n + " шт.</button>").join("") +
      '<span class="meta" id="modal-print-hint"></span>' +
    "</div>"
  );
}

/* «Карта пришла по почте» -- самое частое, что человек делает после охоты, и
   до сих пор единственным способом это записать было открыть вкладку
   «Коллекция», подвкладку «Список текстом», дописать строку в список из
   восьмидесяти семи и нажать «Сохранить коллекцию», то есть перезаписать всё
   целиком. Сервер при этом умеет добавлять по одной: `/api/collection/add`,
   им пользуется сканер. Не хватало кнопки. */

function modalCollRow(card) {
  const have = (typeof ownedOf === "function") ? ownedOf(card) : 0;
  return (
    '<div class="qtyadd"><span>В коллекцию:</span>' +
      [1, 2, 3, 4].map((n) =>
        '<button class="add-coll" data-n="' + n + '">' + n + " шт.</button>").join("") +
      '<span class="meta" id="modal-have">' +
        (have ? "у вас " + have + " шт." : "у вас этой карты нет") +
      "</span>" +
    "</div>"
  );
}

/* Список колод нужен окну карты, а оно открывается раньше, чем человек
   заходит в билдер. Берём готовый, если он уже загружен, иначе спрашиваем
   сами -- один раз за сеанс. */
async function modalLoadDecks() {
  if (typeof bdDecks !== "undefined" && bdDecks && bdDecks.length) {
    modalDecks = bdDecks;
    return;
  }
  if (modalDecks.length) return;
  try {
    const r = await api("/api/decks");
    modalDecks = r.decks || [];
  } catch (e) {
    modalDecks = [];
  }
}

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
      '<div class="art' + (modalStrip ? " flipping" : "") + '">' +
        '<img id="modal-art" src="' + esc(faceImage(c, modalFace)) + '" alt="' + esc(name) + '">' +
        modalFlipButtons() +
        (canFlip
          ? '<div class="row tight"><button id="modal-flip" class="ghost">Перевернуть → ' +
            esc((faces[(modalFace + 1) % faces.length] || {}).name || "") + "</button></div>"
          : "") +
      "</div>" +
      "<div>" +
        modalStripRow() +
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
        modalFavRow() +
        modalDeckRow() +
        modalCollRow(c) +
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
  $$(".flip").forEach((b) => b.addEventListener("click", (ev) => {
    // Не даём нажатию дойти до подложки: она закрывает окно.
    ev.stopPropagation();
    modalStep(b.classList.contains("prev") ? -1 : 1);
  }));
  $$(".add-hunt").forEach((b) => b.addEventListener("click", () => {
    addToHunt(c.name, parseInt(b.dataset.n, 10));
  }));
  const favPick = $("#modal-fav");
  if (favPick) {
    favPick.addEventListener("change", () => {
      store.set("modalFav", favPick.value);
      // Выбор здесь -- то же самое, что человек сделал бы на вкладке: папка
      // становится текущей, и вкладка покажет её же.
      if (typeof favCurrent !== "undefined") favCurrent = favPick.value;
      if (typeof renderFavourites === "function") renderFavourites();
    });
  }
  $$(".add-fav").forEach((b) => b.addEventListener("click", () => {
    // If a printing was picked in the table, pin it: a Secret Lair foil is a
    // different want from the cheap reprint.
    addToFavourites(c, parseInt(b.dataset.n, 10), modalPrinting,
                    favPick ? favPick.value : null);
  }));
  $$(".add-coll").forEach((b) => b.addEventListener("click", async () => {
    const n = Math.max(1, parseInt(b.dataset.n, 10) || 1);
    b.disabled = true;
    try {
      // Печать берётся выбранная в таблице, если её выбирали: коллекция
      // хранится по печатям, и «та самая из MH2» -- не то же, что любая.
      const r = await post("/api/collection/add", {cards: [{
        name: c.name, quantity: n,
        set_code: modalPrinting ? modalPrinting.set_code : null,
        collector_number: modalPrinting ? modalPrinting.collector_number : null,
      }]});
      toast(n + "× «" + c.name + "» → коллекция");
      if (typeof loadOwned === "function") await loadOwned();
      const have = $("#modal-have");
      if (have && typeof ownedOf === "function") {
        const now = ownedOf(c);
        have.textContent = now ? "у вас " + now + " шт." : "у вас этой карты нет";
      }
      if (typeof refreshStatus === "function") refreshStatus();
      // Текстовое поле коллекции -- то же хранилище с другой стороны: если
      // его не перечитать, следующее «Сохранить коллекцию» затрёт добавленное.
      const box = $("#collection-text");
      if (box && r && r.stored != null && typeof api === "function") {
        try {
          const fresh = await api("/api/collection");
          const names = Object.keys(fresh.collection || {});
          box.value = names.map((nm) => fresh.collection[nm] + " " + nm).join("\n");
        } catch (e) { /* поле не критично */ }
      }
    } catch (err) {
      toast("Не удалось добавить в коллекцию: " + err.message, true);
    } finally {
      b.disabled = false;
    }
  }));
  const deckPick = $("#modal-deck");
  const qtyPick = $("#modal-deck-qty");
  if (deckPick) {
    deckPick.addEventListener("change", () =>
      store.set("modalDeck", deckPick.value));
  }
  if (qtyPick) {
    qtyPick.addEventListener("change", () =>
      store.set("modalDeckQty", qtyPick.value));
  }
  $$(".add-deck").forEach((b) => b.addEventListener("click", async () => {
    const id = deckPick ? deckPick.value : null;
    if (!id) return;
    const n = Math.max(1, parseInt(qtyPick ? qtyPick.value : "1", 10) || 1);
    const deck = modalDecks.find((d) => d.id === id);
    const where = b.dataset.section || "main";
    b.disabled = true;
    try {
      await post("/api/decks/" + id + "/cards",
                 {cards: [{name: c.name, quantity: n, section: where}]});
      toast(n + "× «" + c.name + "» → «" + (deck ? deck.name : "колода") +
            "», " + (SECTION_TITLES[where] || where).toLowerCase());
      // Если эта колода сейчас открыта в билдере -- перечитать её, иначе
      // человек вернётся туда и не увидит того, что только что положил.
      if (typeof bdDeck !== "undefined" && bdDeck && bdDeck.id === id
          && typeof bdOpen === "function") {
        bdOpen(id);
      }
    } catch (err) {
      toast("Не удалось положить в колоду: " + err.message, true);
    } finally {
      b.disabled = false;
    }
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
      // Своё место, а не подпись у «В избранное»: та раньше отвечала за две
      // разные вещи сразу -- куда положим и какую печать выбрали.
      const hint = $("#modal-print-hint");
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
      "она или дешевеет.</p>" + priceVariants(data);
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
    (points.length > 1 ? priceChart(points) : "") +
    priceVariants(data);
}

/* Цена чего именно. Одно число на имя — это то, из-за чего «выгода» врала:
   по «700 ₽» не видно, убитая это копия, фойл или обычная карта. Здесь
   записанное разложено по версиям — так, как оно было написано у продавца. */
function variantLabel(v) {
  const parts = [];
  if (v.foil) parts.push("фойл");
  parts.push(v.set_code ? v.set_code.toUpperCase() : "печать не указана");
  if (v.condition) parts.push(v.condition);
  if (v.language) parts.push(v.language);
  return parts.join(" · ");
}

function priceVariants(data) {
  const rows = data.variants || [];
  const cur = data.current || {};
  /* Цена есть, а разбора нет — значит, её узнавали до того, как программа
     стала различать версии. Молчать об этом нельзя: пустое место читается
     как «версия одна», а на деле неизвестно, к чему относится число. Такие
     цены дополнение спрашивает заново само, второй очередью. */
  if (!rows.length) {
    return cur.rub_min
      ? '<p class="meta pricevars-none">Записано одним числом, без разбора ' +
        "на печать, фойл и состояние: цену узнавали раньше, чем программа " +
        "научилась их различать. Спросится заново — дополнение цен берёт " +
        "такие вторыми, сразу за теми, у кого цены нет вовсе.</p>"
      : "";
  }
  const now = data.current || {};
  const plain = now.rub_plain;
  /* Нижняя цена не от обычной копии — самый частый случай вранья: «от 10 ₽»
     рядом с картой, которая в нормальном состоянии стоит 900. */
  const warn = (plain && now.rub_min && plain > now.rub_min)
    ? '<p class="meta">Самое дешёвое объявление — <b>не</b> обычная копия. ' +
      "Обычная стоит " + rub(plain) + ".</p>"
    : "";
  return '<details class="pricevars"><summary class="meta">Цена чего: ' +
    rows.length + " версий</summary>" + warn +
    rows.map((v) =>
      '<div class="pricevar' + (v.foil ? " foil" : "") + '">' +
        "<b>" + rub(v.rub_min) + "</b>" +
        (v.rub_max > v.rub_min ? '<span class="meta"> — ' + rub(v.rub_max) +
          "</span>" : "") +
        '<span class="vlabel">' + esc(variantLabel(v)) + "</span>" +
        '<span class="meta">' + v.offers +
        plural(v.offers, " объявление", " объявления", " объявлений") +
        "</span>" +
      "</div>").join("") +
    '<p class="meta">Записано при последнем узнавании цены. Пустая печать ' +
    "или состояние — продавец их не написал; это не «обычная версия», это " +
    "«неизвестно».</p></details>";
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

function openCard(card, strip) {
  modalCard = card;
  modalPrinting = null;
  modalFace = card.matched_face != null ? card.matched_face : 0;
  // Лента передаётся тем, кто открывает: он один знает свой список. Без неё
  // окно ведёт себя как раньше -- просто без стрелок.
  modalStripSet(strip);
  $("#overlay").hidden = false;
  renderModal();
  // Список колод обычно уже загружен билдером; если нет -- дорисуем строку
  // «в колоду», как только он приедет. Окно при этом открывается сразу.
  if (!modalDecks.length) {
    modalLoadDecks().then(() => {
      if (modalCard === card && modalDecks.length) renderModal();
    });
  }
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

/* Свайп по картинке -- для планшета, где стрелки мелковаты для пальца.

   Считается только явно горизонтальное движение: вертикальное -- это
   прокрутка окна, и перехватывать её значит ломать чтение правил у длинной
   карты. Порог в 60 пикселей -- чтобы дрожь руки не листала страницы. */
let swipeFrom = null;

function modalSwipeStart(ev) {
  const touch = ev.touches && ev.touches[0];
  swipeFrom = touch ? { x: touch.clientX, y: touch.clientY } : null;
}

function modalSwipeEnd(ev) {
  const from = swipeFrom;
  swipeFrom = null;
  if (!from || !modalStrip) return;
  const touch = ev.changedTouches && ev.changedTouches[0];
  if (!touch) return;
  const dx = touch.clientX - from.x;
  const dy = touch.clientY - from.y;
  if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
  modalStep(dx < 0 ? 1 : -1);
}

function closeModal() {
  $("#overlay").hidden = true;
  $("#modal-body").innerHTML = "";
  modalCard = null;
  modalStrip = null;
}

$("#modal-close").addEventListener("click", closeModal);
$("#modal-body").addEventListener("touchstart", modalSwipeStart, { passive: true });
$("#modal-body").addEventListener("touchend", modalSwipeEnd, { passive: true });
$("#overlay").addEventListener("click", (ev) => {
  if (ev.target === $("#overlay")) closeModal();
});
