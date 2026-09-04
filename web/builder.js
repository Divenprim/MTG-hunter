"use strict";

/* The deck builder.

   What makes it worth building rather than using Archidekt: it shows what the
   deck costs **in roubles on topdeck**, per card and in total, plus what you
   are still short. Nothing else does that for the Russian market.

   Prices are cached with a timestamp and refreshed only when asked -- every
   topdeck query is a deliberate 1.5s request, so a 100-card deck is about
   twenty seconds and must never happen silently on every edit.

   Loaded after app.js; uses its helpers. */

const BD_FORMATS = ["commander", "modern", "pioneer", "legacy", "vintage",
                    "standard", "pauper", "premodern", "brawl", "duel"];
const BD_SECTION_TITLES = {
  commander: "Командир", main: "Основная колода", side: "Сайдборд", maybe: "Под вопросом",
};

let bdDecks = [];
let bdDeck = null;

const rubShort = (n) => Number(n || 0).toLocaleString("ru") + " ₽";

/* ------------------------------------------------------------- deck list */

function bdRenderDeckList() {
  $("#bd-decks").innerHTML = bdDecks.map((d) =>
    '<div class="bddeck' + (bdDeck && d.id === bdDeck.id ? " on" : "") +
      '" data-id="' + esc(d.id) + '">' +
      '<span class="nm">' + esc(d.name) + "</span>" +
      '<span class="fmt">' + esc(d.format || "") + " · " + d.cards + "</span>" +
    "</div>").join("") ||
    '<p class="meta">пока нет колод</p>';
}

async function bdLoadDecks() {
  try {
    const r = await api("/api/decks");
    bdDecks = r.decks || [];
    bdRenderDeckList();
    if (!bdDecks.length) {
      bdDeck = null;
      $("#bd-editor").hidden = true;
      $("#bd-empty").hidden = false;
    }
  } catch (e) { /* the panel stays empty */ }
}

async function bdOpen(deckId) {
  try {
    const r = await api("/api/decks/" + deckId);
    bdShow(r.deck);
  } catch (e) {
    toast(e.message, true);
  }
}

/* -------------------------------------------------------------- rendering */

function bdShow(deck) {
  bdDeck = deck;
  $("#bd-editor").hidden = false;
  $("#bd-empty").hidden = true;

  $("#bd-name").value = deck.name;
  $("#bd-format").innerHTML = BD_FORMATS
    .map((f) => '<option value="' + f + '"' +
      (f === deck.format ? " selected" : "") + ">" + f + "</option>").join("");

  const playable = deck.stats ? deck.stats.copies : 0;
  $("#bd-count").textContent =
    playable + " карт · " + deck.missing_copies + " не хватает";

  bdRenderPriceStatus();
  bdRenderStats();
  bdRenderProblems();
  bdRenderCards();
  bdRenderVersions();
  bdRenderDeckList();
}

function bdRenderPriceStatus() {
  const deck = bdDeck;
  const total = deck.cards.length;
  const known = deck.priced_cards;
  const newest = deck.cards
    .map((c) => c.rub && c.rub.checked_at)
    .filter(Boolean)
    .sort()
    .pop();
  const bits = ["цены известны для " + known + " из " + total];
  if (deck.total_rub) bits.push("колода ≈ " + rubShort(deck.total_rub));
  if (deck.missing_rub) bits.push("докупить ≈ " + rubShort(deck.missing_rub));
  if (newest) bits.push("проверено " + newest.slice(0, 16));
  $("#bd-pricestat").textContent = bits.join(" · ");
}

function bdRenderStats() {
  const s = bdDeck.stats || {};
  const curve = s.curve || {};
  const max = Math.max(1, ...Object.values(curve));
  const curveHtml = [0, 1, 2, 3, 4, 5, 6, 7].map((mv) => {
    const n = curve[mv] || 0;
    return '<div class="bar" style="height:' + Math.round((n / max) * 100) + '%">' +
      (n ? "<span>" + n + "</span>" : "") +
      "<em>" + (mv === 7 ? "7+" : mv) + "</em></div>";
  }).join("");

  const colorTotal = Object.values(s.colors || {}).reduce((a, b) => a + b, 0) || 1;
  const colorBar = Object.keys(COLOR_HEX)
    .filter((ch) => (s.colors || {})[ch])
    .map((ch) => '<div style="width:' + ((s.colors[ch] / colorTotal) * 100).toFixed(1) +
      "%;background:" + COLOR_HEX[ch] + '"></div>').join("");

  const types = Object.keys(s.types || {})
    .sort((a, b) => s.types[b] - s.types[a])
    .map((t) => t + " " + s.types[t]).join(" · ");

  $("#bd-stats").innerHTML = '<div class="statgrid">' +
    '<div class="statbox"><h4>Кривая маны (без земель)</h4><div class="curve">' +
      curveHtml + "</div></div>" +
    '<div class="statbox"><h4>Земель</h4><div class="statbig">' + (s.lands || 0) +
      '</div><div class="meta">средняя МС ' + (s.avg_mv == null ? "—" : s.avg_mv) +
      "</div></div>" +
    '<div class="statbox"><h4>Цвета</h4><div class="colorbar">' + colorBar +
      '</div><div class="colorlegend">' + esc(types) + "</div></div>" +
    '<div class="statbox"><h4>Цена на topdeck</h4><div class="statbig">' +
      rubShort(bdDeck.total_rub) + '</div><div class="meta">докупить ' +
      rubShort(bdDeck.missing_rub) + "</div></div>" +
    '<div class="statbox"><h4>Оценка Scryfall</h4><div class="statbig">$' +
      (bdDeck.total_usd || 0).toFixed(2) + '</div><div class="meta">мировая, для сверки</div></div>' +
  "</div>";
}

function bdRenderProblems() {
  const problems = bdDeck.problems || [];
  if (!problems.length) {
    $("#bd-problems").innerHTML =
      '<div class="problems"><span class="ok">Правила формата соблюдены</span></div>';
    return;
  }
  const errors = problems.filter((p) => p.level === "error");
  const warns = problems.filter((p) => p.level !== "error");
  $("#bd-problems").innerHTML = '<div class="problems">' +
    errors.concat(warns).slice(0, 40).map((p) =>
      '<div class="problem ' + p.level + '">' + esc(p.text) + "</div>").join("") +
    (problems.length > 40
      ? '<div class="meta">…и ещё ' + (problems.length - 40) + "</div>" : "") +
    "</div>";
}

function bdCardRow(card, compact) {
  const c = card.card;
  const rub = card.rub;
  const sub = c
    ? [c.ru_name, (c.type_line || "").split("—")[0].trim()].filter(Boolean).join(" · ")
    : "нет в базе";
  return (
    '<div class="bdrow' + (compact ? " compact" : "") + (c ? "" : " unknown") +
      '" data-card="' + esc(card.id) + '">' +
      '<span class="qty">' +
        '<button data-step="-1" title="меньше">−</button>' +
        "<b>" + card.quantity + "</b>" +
        '<button data-step="1" title="больше">+</button>' +
      "</span>" +
      (c && c.image_small
        ? '<img loading="lazy" src="' + esc(c.image_small) + '" alt=""' +
          (c.image_normal ? ' data-preview="' + esc(c.image_normal) + '"' : "") + ">"
        : "<span></span>") +
      '<span class="nm">' + esc(card.name) +
        '<div class="sub">' + esc(sub) +
          (card.missing ? " · не хватает " + card.missing : "") + "</div></span>" +
      '<input class="cat" type="text" value="' + esc(card.category || "") +
        '" placeholder="категория">' +
      '<span class="rub">' + (rub
        ? "<b>от " + rubShort(rub.min) + "</b><small>медиана " + rubShort(rub.median) +
          " · " + rub.offers + " предл.</small>"
        : '<small>цена не запрошена</small>') + "</span>" +
      '<span class="usd">' + (card.unit_usd ? "$" + card.unit_usd.toFixed(2) : "") + "</span>" +
      '<button class="del" title="убрать">×</button>' +
    "</div>"
  );
}

/* ---------------------------------------------------- grouping the list -- */

/* A hundred-card list in one flat column is exactly the thing that was
   unusable. So the list is grouped along whichever axis you are thinking in --
   card type by default, because that is how a decklist is read -- and can be
   shown compactly or as images. */

const BD_TYPE_ORDER = [
  ["Существа", "creature"],
  ["Мироходцы", "planeswalker"],
  ["Мгновенные", "instant"],
  ["Волшебства", "sorcery"],
  ["Артефакты", "artifact"],
  ["Чары", "enchantment"],
  ["Битвы", "battle"],
  ["Земли", "land"],
];

const BD_COLOR_NAMES = {
  W: "Белые", U: "Синие", B: "Чёрные", R: "Красные", G: "Зелёные",
};

/* Keyword groups, in the order a deck cares about them. Categories describe
   what a card is FOR, so Wall of Omens is filed under "добор" -- but a
   defender-tribal deck wants to see it as a Defender, and that is this axis. */
const BD_KEYWORDS = [
  ["Дефендеры", "defender"],
  ["Мгновенная скорость", "flash"],
  ["Полёт", "flying"],
  ["Пробивной", "trample"],
  ["Смертельное касание", "deathtouch"],
  ["Связь с жизнью", "lifelink"],
  ["Бдительность", "vigilance"],
  ["Ускорение", "haste"],
  ["Угроза", "menace"],
  ["Первый удар", "first strike"],
  ["Неразрушимый", "indestructible"],
  ["Защита от порчи", "hexproof"],
];

function bdPrimaryType(card) {
  const line = ((card && card.type_line) || "").toLowerCase();
  // Land last-but-one and creature first: an "Artifact Creature" is a creature,
  // and a "Land Creature" (Dryad Arbor) is filed as a land.
  if (line.includes("land")) return "Земли";
  for (const [label, kind] of BD_TYPE_ORDER) {
    if (kind !== "land" && line.includes(kind)) return label;
  }
  return "Прочее";
}

function bdGroupKey(row, mode) {
  const c = row.card;
  if (mode === "category") return row.category || "без категории";
  if (mode === "type") return bdPrimaryType(c);
  if (mode === "cmc") {
    if (!c) return "неизвестно";
    if ((c.type_line || "").toLowerCase().includes("land")) return "земли";
    const mv = Math.min(7, Math.floor(c.cmc || 0));
    return "МС " + (mv === 7 ? "7+" : mv);
  }
  if (mode === "color") {
    if (!c) return "неизвестно";
    const colors = c.colors || "";
    if (!colors) return "Бесцветные";
    if (colors.length > 1) return "Многоцветные";
    return BD_COLOR_NAMES[colors] || colors;
  }
  if (mode === "price") {
    const rub = row.rub && row.rub.min;
    if (!rub) return "цена неизвестна";
    if (rub < 100) return "до 100 ₽";
    if (rub < 500) return "100–500 ₽";
    if (rub < 2000) return "500–2 000 ₽";
    return "дороже 2 000 ₽";
  }
  if (mode === "rarity") return (c && c.rarity) || "неизвестно";
  if (mode === "keyword") {
    const words = new Set(
      ((c && c.keywords) || "").split(",").map((k) => k.trim().toLowerCase()).filter(Boolean)
    );
    for (const [label, kw] of BD_KEYWORDS) {
      if (words.has(kw)) return label;
    }
    return words.size ? "прочие ключевые слова" : "без ключевых слов";
  }
  return "";
}

/* Groups appear in a meaningful order, not alphabetically: mana value ascends,
   card types follow decklist convention, price buckets go cheap to dear. */
function bdGroupOrder(mode) {
  if (mode === "type") return BD_TYPE_ORDER.map(([label]) => label).concat(["Прочее"]);
  if (mode === "cmc") {
    return ["МС 0", "МС 1", "МС 2", "МС 3", "МС 4", "МС 5", "МС 6", "МС 7+",
            "земли", "неизвестно"];
  }
  if (mode === "color") {
    return ["Белые", "Синие", "Чёрные", "Красные", "Зелёные", "Многоцветные",
            "Бесцветные", "неизвестно"];
  }
  if (mode === "price") {
    return ["до 100 ₽", "100–500 ₽", "500–2 000 ₽", "дороже 2 000 ₽", "цена неизвестна"];
  }
  if (mode === "rarity") {
    return ["mythic", "rare", "uncommon", "common", "special", "bonus", "неизвестно"];
  }
  if (mode === "keyword") {
    return BD_KEYWORDS.map(([label]) => label)
      .concat(["прочие ключевые слова", "без ключевых слов"]);
  }
  return null;   // alphabetical
}

function bdSortRows(rows, mode) {
  const price = (r) => (r.rub && r.rub.min) || 0;
  if (mode === "cmc") {
    rows.sort((a, b) => ((a.card || {}).cmc || 0) - ((b.card || {}).cmc || 0) ||
      a.name.localeCompare(b.name));
  } else if (mode === "price_desc") {
    rows.sort((a, b) => price(b) - price(a) || a.name.localeCompare(b.name));
  } else if (mode === "missing") {
    rows.sort((a, b) => b.missing - a.missing || a.name.localeCompare(b.name));
  } else {
    rows.sort((a, b) => a.name.localeCompare(b.name));
  }
  return rows;
}

function bdGridCard(row) {
  const c = row.card;
  const img = c && c.image_small;
  return '<div class="gcard' + (row.missing ? " need" : "") +
    '" data-card="' + esc(row.id) + '" title="' + esc(row.name) + '">' +
    (img
      ? '<img loading="lazy" src="' + esc(img) + '" alt=""' +
        (c.image_normal ? ' data-preview="' + esc(c.image_normal) + '"' : "") + ">"
      : '<img alt="">') +
    '<span class="badge2">' + row.quantity + "×</span>" +
    (row.rub ? '<span class="pricetag">от ' + rubShort(row.rub.min) + "</span>" : "") +
    "</div>";
}

function bdRenderCards() {
  const mode = $("#bd-group").value;
  const sortMode = $("#bd-sortin").value;
  const view = $("#bd-view").value;
  const needle = ($("#bd-filter").value || "").trim().toLowerCase();

  const visible = bdDeck.cards.filter((row) => {
    if (!needle) return true;
    const hay = [row.name, row.category,
                 row.card && row.card.ru_name,
                 row.card && row.card.type_line].filter(Boolean).join(" ").toLowerCase();
    return hay.indexOf(needle) >= 0;
  });

  const bySection = {};
  visible.forEach((row) => {
    (bySection[row.section] = bySection[row.section] || []).push(row);
  });

  let html = "";
  ["commander", "main", "side", "maybe"].forEach((sec) => {
    const rows = bySection[sec];
    if (!rows || !rows.length) return;
    const copies = rows.reduce((n, r) => n + r.quantity, 0);
    html += '<div class="bdgroup"><h4>' + esc(BD_SECTION_TITLES[sec] || sec) +
      " <span>— " + rows.length + " назв. / " + copies + " шт.</span></h4>";

    if (mode === "none") {
      html += bdRenderRowSet(bdSortRows(rows.slice(), sortMode), view);
      html += "</div>";
      return;
    }

    const groups = {};
    rows.forEach((row) => {
      const key = bdGroupKey(row, mode);
      (groups[key] = groups[key] || []).push(row);
    });

    const order = bdGroupOrder(mode);
    const keys = order
      ? order.filter((k) => groups[k]).concat(
          Object.keys(groups).filter((k) => order.indexOf(k) < 0).sort())
      : Object.keys(groups).sort();

    if (view === "columns") {
      const byCategory = mode === "category";
      // Under grouping by category the columns are yours to arrange, so one
      // column can hold several categories; otherwise it is one each.
      const layout = byCategory ? bdColumnsOf(keys) : keys.map((k) => [k]);
      html += '<div class="bdcolumns' + (byCategory ? " draggable" : "") + '">' +
        layout.map((col) => col.length === 1
          ? bdColumn(col[0], groups[col[0]], sortMode)
          : '<div class="bdcolumn multi">' +
            col.map((key) => bdColumn(key, groups[key], sortMode)).join("") +
            "</div>").join("") +
        (byCategory
          ? '<div class="bdcolumn newcol" data-newgroup="1">' +
            '<div class="colhead"><b>+ новая категория</b>' +
            '<span class="meta">перетащите карту сюда</span></div>' +
            '<div class="bdstack empty"></div></div>'
          : "") +
      "</div>";
      // The note belongs above the columns, not stranded beside them.
      if (!byCategory) {
        html += '<p class="meta colhint">колонки здесь считаются из самих ' +
          "карт — чтобы раскладывать перетаскиванием, сгруппируйте по " +
          "категориям</p>";
      }
      html += "</div>";
      return;
    }

    keys.forEach((key) => {
      const set = bdSortRows(groups[key].slice(), sortMode);
      const n = set.reduce((acc, r) => acc + r.quantity, 0);
      html += '<h4 style="border:0;margin:8px 0 2px;color:var(--text-dim)">' +
        esc(key) + " <span>(" + n + ")</span></h4>" +
        bdRenderRowSet(set, view);
    });
    html += "</div>";
  });

  bdRenderLayoutPanel();
  $("#bd-cards").className = view === "columns"
    ? "ascolumns"
    : ((mode !== "none" && view === "compact") ? "bdcols" : "");
  $("#bd-cards").innerHTML = html ||
    (needle
      ? '<p class="meta">Под этот фильтр в колоде ничего не подходит.</p>'
      : '<p class="meta">Колода пуста. Добавьте карты через поле выше.</p>');
}

/* The view Archidekt is recognised by: one column per group, cards stacked so
   only each title bar shows, and you drag a card from column to column to file
   it. Reading a stack is faster than reading a list -- the art tells you what
   the card is before the name does -- and moving a card is a drag rather than
   typing into a field.

   Dragging only means something when the columns ARE the filing: with grouping
   by category, dropping a card into a column puts it in that category. Grouped
   by mana value or colour the columns are derived from the cards themselves and
   cannot be rearranged, so dragging is switched off and the header says why. */

function bdStackCard(row, index) {
  const c = row.card;
  const img = c && c.image_small;
  const draggable = $("#bd-group").value === "category";
  return (
    '<div class="stackcard' + (row.missing ? " need" : "") + '"' +
      ' data-card="' + esc(row.id) + '"' +
      ' style="z-index:' + (index + 1) + '"' +
      (draggable ? ' draggable="true"' : "") +
      (c && c.image_normal ? ' data-preview="' + esc(c.image_normal) + '"' : "") +
      ' title="' + esc(row.name) + '">' +
      (img
        ? '<img loading="lazy" src="' + esc(img) + '" alt="' + esc(row.name) + '">'
        : '<div class="noart">' + esc(row.name) + "</div>") +
      (row.quantity > 1 ? '<span class="qty">' + row.quantity + "×</span>" : "") +
      (row.rub && row.rub.min
        ? '<span class="tag">' + rubShort(row.rub.min) + "</span>"
        : "") +
    "</div>"
  );
}

function bdColumn(title, rows, sortMode) {
  const set = bdSortRows(rows.slice(), sortMode);
  const copies = set.reduce((n, r) => n + r.quantity, 0);
  const rub = set.reduce((n, r) => n + ((r.rub && r.rub.min) || 0) * r.quantity, 0);
  return (
    '<div class="bdcolumn" data-group="' + esc(title) + '">' +
      '<div class="colhead">' +
        '<b>' + esc(title) + "</b>" +
        '<span class="meta">' + copies + " шт." +
          (rub ? " · " + rubShort(rub) : "") + "</span>" +
      "</div>" +
      '<div class="bdstack">' +
        set.map(bdStackCard).join("") +
      "</div>" +
    "</div>"
  );
}

function bdRenderRowSet(rows, view) {
  if (view === "grid") {
    return '<div class="bdgrid">' + rows.map(bdGridCard).join("") + "</div>";
  }
  if (view === "text") {
    // Plain "N Name" lines, the format every deck site and shop understands.
    return '<pre class="bdtext">' + rows.map((row) =>
      esc(row.quantity + " " + row.name)).join("\n") + "</pre>";
  }
  return rows.map((row) => bdCardRow(row, view === "compact")).join("");
}

function bdRenderVersions() {
  const versions = bdDeck.versions || [];
  $("#bd-versions").innerHTML = versions.length
    ? versions.map((v) =>
        '<div class="bdversion" data-version="' + esc(v.id) + '">' +
          '<span class="lbl">' + esc(v.label || "без метки") + "</span>" +
          '<span class="meta">' + esc(v.created) + "</span>" +
          '<button data-vact="restore">откатить</button>' +
          '<button data-vact="delete" class="ghost">×</button>' +
        "</div>").join("")
    : '<p class="meta">версий пока нет</p>';
}

/* ---------------------------------------------------------------- actions */

async function bdCall(path, options, okMsg) {
  try {
    const r = await api(path, options);
    if (r.deck) bdShow(r.deck);
    if (r.decks) { bdDecks = r.decks; bdRenderDeckList(); }
    await bdLoadDecks();
    if (okMsg) toast(okMsg);
    return r;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

const bdBody = (method, body) => ({
  method: method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

$("#bd-decks").addEventListener("click", (ev) => {
  const row = ev.target.closest(".bddeck");
  if (row) bdOpen(row.dataset.id);
});

$("#bd-newdeck-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const name = $("#bd-newdeck").value.trim();
  if (!name) return;
  const r = await bdCall("/api/decks",
    bdBody("POST", { name: name, format: $("#bd-newformat").value }), "Колода создана");
  if (r) $("#bd-newdeck").value = "";
});

$("#bd-name").addEventListener("change", () => {
  if (!bdDeck) return;
  bdCall("/api/decks/" + bdDeck.id, bdBody("PATCH", { name: $("#bd-name").value }));
});

$("#bd-format").addEventListener("change", () => {
  if (!bdDeck) return;
  bdCall("/api/decks/" + bdDeck.id, bdBody("PATCH", { format: $("#bd-format").value }),
    "Формат изменён — проверки пересчитаны");
});

$("#bd-delete").addEventListener("click", async () => {
  if (!bdDeck) return;
  if (!confirm("Удалить колоду «" + bdDeck.name + "»?")) return;
  // Capture the id BEFORE clearing state: reading it off the DOM afterwards
  // was a null dereference waiting to happen.
  const deckId = bdDeck.id;
  bdDeck = null;
  $("#bd-editor").hidden = true;
  $("#bd-empty").hidden = false;
  await bdCall("/api/decks/" + deckId, { method: "DELETE" }, "Колода удалена");
});

/* --------------------------------------------------------- add-card box -- */

let bdSuggestTicket = 0;

async function bdSuggest(text) {
  const ticket = ++bdSuggestTicket;
  if (!text) { $("#bd-suggest").innerHTML = ""; return; }
  try {
    const r = await api("/api/search?limit=12&q=" + encodeURIComponent(text));
    if (ticket !== bdSuggestTicket) return;
    $("#bd-suggest").innerHTML = (r.cards || []).map((c) =>
      '<div class="setrow" data-name="' + esc(c.name) + '">' +
        '<span class="code">' + esc((c.set_code || "").toUpperCase()) + "</span>" +
        '<span class="nm">' + esc(c.display_name || c.name) + "</span>" +
        '<span class="yr">' + esc(c.ru_name || "") + "</span>" +
        '<span class="cnt">' + esc(c.rarity || "") + "</span>" +
      "</div>").join("");
  } catch (e) { /* leave the previous suggestions */ }
}

$("#bd-add").addEventListener("input", debounce((ev) => {
  bdSuggest(ev.target.value.trim());
}, 250));

$("#bd-add").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  ev.preventDefault();
  const first = $("#bd-suggest .setrow");
  if (first) bdAddCard(first.dataset.name);
});

$("#bd-suggest").addEventListener("click", (ev) => {
  const row = ev.target.closest(".setrow");
  if (row) bdAddCard(row.dataset.name);
});

async function bdAddCard(name) {
  if (!bdDeck) return toast("Сначала выберите колоду", true);
  await bdCall("/api/decks/" + bdDeck.id + "/cards", bdBody("POST", {
    cards: [{
      name: name,
      quantity: 1,
      section: $("#bd-section").value,
      category: $("#bd-category").value.trim(),
    }],
  }));
  $("#bd-add").value = "";
  $("#bd-suggest").innerHTML = "";
  $("#bd-add").focus();
}

/* ------------------------------------------------------------ card rows -- */

$("#bd-cards").addEventListener("click", (ev) => {
  const row = ev.target.closest(".bdrow, .gcard, .stackcard");
  if (!row || !bdDeck) return;
  const cardId = row.dataset.card;
  const card = bdDeck.cards.find((c) => c.id === cardId);
  if (!card) return;

  if ((ev.target.tagName === "IMG" || row.classList.contains("gcard")
       || row.classList.contains("stackcard")) &&
      card.card && card.card.oracle_id) {
    openCard({
      id: "bd-" + cardId,
      name: card.card.name || card.name,
      oracle_id: card.card.oracle_id,
      image_normal: card.card.image_normal,
      image_small: card.card.image_small,
      ru_name: card.card.ru_name,
      flavor_name: card.card.flavor_name,
      type_line: card.card.type_line,
      mana_cost: card.card.mana_cost,
      prices: card.card.prices,
      legalities: card.card.legalities || {},
      faces: [],
    });
    return;
  }

  if (ev.target.classList.contains("del")) {
    bdCall("/api/decks/" + bdDeck.id + "/cards/" + cardId, { method: "DELETE" });
    return;
  }

  const step = ev.target.dataset && ev.target.dataset.step;
  if (step) {
    const next = card.quantity + parseInt(step, 10);
    if (next < 1) {
      bdCall("/api/decks/" + bdDeck.id + "/cards/" + cardId, { method: "DELETE" });
    } else {
      bdCall("/api/decks/" + bdDeck.id + "/cards/" + cardId,
        bdBody("PATCH", { quantity: next }));
    }
  }
});

$("#bd-cards").addEventListener("change", (ev) => {
  if (!ev.target.classList.contains("cat") || !bdDeck) return;
  const row = ev.target.closest(".bdrow");
  bdCall("/api/decks/" + bdDeck.id + "/cards/" + row.dataset.card,
    bdBody("PATCH", { category: ev.target.value.trim() }));
});

/* ------------------------------------------------- dragging between columns

   Dropping a card into a column files it under that category -- the same edit
   the text field does, without the typing. The card being dragged is held in a
   variable rather than in dataTransfer, because reading dataTransfer during
   dragover (to decide whether a drop is allowed) is not permitted. */

let bdDragging = null;

$("#bd-cards").addEventListener("dragstart", (ev) => {
  const card = ev.target.closest(".stackcard");
  if (!card) return;
  bdDragging = card.dataset.card;
  card.classList.add("dragging");
  if (ev.dataTransfer) {
    ev.dataTransfer.effectAllowed = "move";
    // Firefox refuses to start a drag without any payload.
    ev.dataTransfer.setData("text/plain", card.dataset.card);
  }
});

$("#bd-cards").addEventListener("dragend", () => {
  bdDragging = null;
  $$("#bd-cards .stackcard.dragging").forEach((el) => el.classList.remove("dragging"));
  $$("#bd-cards .bdcolumn.over").forEach((el) => el.classList.remove("over"));
});

$("#bd-cards").addEventListener("dragover", (ev) => {
  if (!bdDragging) return;
  const col = ev.target.closest(".bdcolumn");
  if (!col) return;
  ev.preventDefault();
  if (ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
  $$("#bd-cards .bdcolumn.over").forEach((el) => {
    if (el !== col) el.classList.remove("over");
  });
  col.classList.add("over");
});

$("#bd-cards").addEventListener("dragleave", (ev) => {
  const col = ev.target.closest(".bdcolumn");
  if (col && !col.contains(ev.relatedTarget)) col.classList.remove("over");
});

$("#bd-cards").addEventListener("drop", async (ev) => {
  const col = ev.target.closest(".bdcolumn");
  if (!col || !bdDragging || !bdDeck) return;
  ev.preventDefault();
  const cardId = bdDragging;
  bdDragging = null;
  col.classList.remove("over");

  let category = col.dataset.group || "";
  if (col.dataset.newgroup) {
    category = (window.prompt("Название новой категории") || "").trim();
    if (!category) return;
  }
  // "без категории" is what an empty category is called, not a category.
  if (category === "без категории") category = "";

  const card = bdDeck.cards.find((c) => c.id === cardId);
  if (card && (card.category || "") === category) return;

  await bdCall("/api/decks/" + bdDeck.id + "/cards/" + cardId,
    bdBody("PATCH", { category: category }),
    category ? "Перенесено в «" + category + "»" : "Категория снята");
});

/* -------------------------------------------------------------- prices -- */

async function bdRefreshPrices(onlyMissing) {
  if (!bdDeck) return;
  const btn = onlyMissing ? $("#bd-prices-missing") : $("#bd-prices");
  const count = onlyMissing
    ? bdDeck.cards.filter((c) => !c.rub).length
    : bdDeck.cards.length;
  if (!count) return toast("Нечего обновлять", true);

  btn.disabled = true;
  const started = Date.now();
  const tick = setInterval(() => {
    $("#bd-pricestat").textContent =
      "спрашиваю topdeck про " + count + " карт… " +
      Math.round((Date.now() - started) / 1000) + " с";
  }, 500);
  try {
    const r = await api("/api/decks/" + bdDeck.id + "/prices",
      bdBody("POST", { only_missing: !!onlyMissing }));
    clearInterval(tick);
    if (r.deck) bdShow(r.deck);
    const rep = r.report || {};
    if (rep.error) toast(rep.error, true);
    else {
      toast("Цены обновлены: " + rep.updated + " из " + rep.total +
        (rep.not_found && rep.not_found.length
          ? ", не найдено " + rep.not_found.length : ""));
    }
  } catch (e) {
    clearInterval(tick);
    toast(e.message, true);
  } finally {
    clearInterval(tick);
    btn.disabled = false;
  }
}

$("#bd-prices").addEventListener("click", () => bdRefreshPrices(false));
$("#bd-prices-missing").addEventListener("click", () => bdRefreshPrices(true));

/* ------------------------------------------------------------- versions -- */

$("#bd-save-version").addEventListener("click", async () => {
  if (!bdDeck) return;
  await bdCall("/api/decks/" + bdDeck.id + "/versions",
    bdBody("POST", { label: $("#bd-version-label").value.trim() }), "Версия сохранена");
  $("#bd-version-label").value = "";
});

$("#bd-versions").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-vact]");
  if (!btn || !bdDeck) return;
  const row = btn.closest(".bdversion");
  const vid = row.dataset.version;
  if (btn.dataset.vact === "restore") {
    if (!confirm("Откатить колоду к этой версии? Текущее состояние сохранится отдельной версией.")) return;
    await bdCall("/api/decks/" + bdDeck.id + "/versions/" + vid + "/restore",
      { method: "POST" }, "Откатано");
  } else {
    await bdCall("/api/decks/" + bdDeck.id + "/versions/" + vid,
      { method: "DELETE" }, "Версия удалена");
  }
});

/* --------------------------------------------------------------- import -- */

$("#bd-import").addEventListener("click", async () => {
  if (!bdDeck) return;
  const url = $("#bd-import-url").value.trim();
  const text = $("#bd-import-text").value.trim();
  if (!url && !text) return toast("Дайте ссылку или список", true);
  const r = await bdCall("/api/decks/" + bdDeck.id + "/import",
    bdBody("POST", url ? { url: url } : { text: text }));
  if (r) {
    $("#bd-import-url").value = "";
    $("#bd-import-text").value = "";
    toast("Влито позиций: " + r.added);
  }
});

/* -------------------------------------------------------------- actions -- */

function bdMissingCards() {
  return bdDeck.cards
    .filter((c) => c.missing > 0 && c.section !== "maybe")
    .map((c) => ({ name: (c.card && c.card.name) || c.name, quantity: c.missing }));
}

$("#bd-actions").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button");
  if (!btn || !bdDeck) return;
  const act = btn.dataset.act;

  if (act === "hunt") {
    const cards = bdMissingCards();
    if (!cards.length) return toast("Всё уже есть в коллекции", true);
    const text = cards.map((c) => c.quantity + " " + c.name).join("\n");
    $("#hunt-wants").value = text;
    store.set("hunt", text);
    $("#hunt-source").textContent = "Недостающее из колоды «" + bdDeck.name + "».";
    showTab("hunt");
    toast("В охоту: " + cards.length + " назв.");
    return;
  }

  if (act === "fav") {
    const cards = bdMissingCards();
    if (!cards.length) return toast("Всё уже есть в коллекции", true);
    try {
      const r = await api("/api/favourites/cards/bulk",
        bdBody("POST", { cards: cards, folder_name: bdDeck.name }));
      favDoc = r.favourites;
      favCurrent = r.report.folder_id;
      renderFavourites();
      if (typeof renderDeckFolderOptions === "function") renderDeckFolderOptions();
      toast("В «" + r.report.folder_name + "»: " + r.report.added);
    } catch (e) {
      toast(e.message, true);
    }
    return;
  }

  if (act === "export") {
    const secs = { commander: "Commander", main: "Deck", side: "Sideboard", maybe: "Maybeboard" };
    const out = [];
    Object.keys(secs).forEach((sec) => {
      const rows = bdDeck.cards.filter((c) => c.section === sec);
      if (!rows.length) return;
      out.push(secs[sec]);
      rows.forEach((c) => out.push(c.quantity + " " + ((c.card && c.card.name) || c.name)));
      out.push("");
    });
    copyText(out.join("\n"), "Колода скопирована");
    return;
  }

  if (act === "autocat") {
    await bdAutoCategorise();
    return;
  }

  if (act === "goldfish") {
    if (typeof openGoldfish === "function") openGoldfish(bdDeck);
    else toast("Голдфишинг пока не подключён", true);
    return;
  }

  if (act === "recommend") {
    if (typeof recOpen === "function") recOpen();
    else toast("Предложка пока не подключена", true);
    return;
  }

  if (act === "combos") {
    if (typeof cbOpen === "function") cbOpen();
    else toast("Комбо пока не подключены", true);
  }
});

/* Auto-categorise using the functional tags: exactly the data the theme
   search already uses, so `otag:ramp` in the filter panel and "рампа" as a
   deck category mean the same thing. Decided server-side. */
async function bdAutoCategorise() {
  if (!bdDeck) return;
  const btn = $('#bd-actions button[data-act="autocat"]');
  btn.disabled = true;
  try {
    const r = await api("/api/decks/" + bdDeck.id + "/autocategory", { method: "POST" });
    if (r.deck) bdShow(r.deck);
    toast("Разложено: " + r.assigned + " карт");
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

/* The statistics block is 250px tall, and above the card list. Coming to a
   deck you saw almost no cards until you scrolled -- which defeats the point of
   a denser list. So it folds away, and the choice sticks. */

function bdApplyStats(show) {
  $("#bd-stats").hidden = !show;
  $("#bd-stats-toggle").setAttribute("aria-expanded", show ? "true" : "false");
  $("#bd-stats-toggle").classList.toggle("on", show);
  store.set("bdStats", !!show);
}

$("#bd-stats-toggle").addEventListener("click", () => {
  bdApplyStats($("#bd-stats").hidden);
});

bdApplyStats(store.get("bdStats", true));

/* ----------------------------------------------------------- row density

   Same control as in the card search, applied to the deck: how many cards you
   can take in without scrolling. The detailed view of a 100-card commander
   deck was four screens tall. */

const BD_DENSITIES = ["tight", "snug", "roomy"];

function bdApplyDensity(mode) {
  const use = BD_DENSITIES.indexOf(mode) >= 0 ? mode : "snug";
  document.body.dataset.bddensity = use;
  $$("#bd-density button").forEach((b) => {
    b.classList.toggle("on", b.dataset.bddensity === use);
  });
  store.set("bdDensity", use);
}

$("#bd-density").addEventListener("click", (ev) => {
  const mode = ev.target.dataset && ev.target.dataset.bddensity;
  if (mode) bdApplyDensity(mode);
});

bdApplyDensity(store.get("bdDensity", "snug"));

/* ------------------------------------------------- раскладка колонок (стопки)

   В стопочном виде колонка — это не одна категория: колонок может быть меньше,
   чем категорий, и вы сами решаете, что с чем стоит рядом. Плитки категорий
   перетаскиваются между колонками, колонки добавляются и убираются, раскладка
   запоминается для этой колоды в этом браузере.

   Работает только при группировке по категориям: в остальных случаях колонки
   считаются из самих карт, и раскладывать там нечего. */

function bdLayoutKey() {
  return bdDeck ? "bdLayout." + bdDeck.id : null;
}

function bdGetLayout() {
  const key = bdLayoutKey();
  if (!key) return null;
  const saved = store.get(key, null);
  return Array.isArray(saved) && saved.length ? saved : null;
}

function bdSetLayout(columns) {
  const key = bdLayoutKey();
  if (!key) return;
  if (columns) store.set(key, columns);
  else store.set(key, null);
}

/* Categories arranged into columns: the saved layout first, then anything new
   the deck has grown since -- a category must never vanish because the layout
   predates it. */
function bdColumnsOf(keys, keepEmpty) {
  const saved = bdGetLayout();
  if (!saved) return keys.map((k) => [k]);

  const known = new Set(keys);
  const columns = saved.map((col) => col.filter((k) => known.has(k)));
  const placed = new Set(columns.flat());
  const extra = keys.filter((k) => !placed.has(k));
  if (extra.length) columns.push(extra);
  // The arranging panel keeps empty columns -- they are what you drag into.
  // The deck itself drops them, so an empty column leaves no gap.
  return keepEmpty ? columns : columns.filter((col) => col.length);
}

function bdLayoutTile(name, count) {
  return '<span class="lay-tile" draggable="true" data-cat="' + esc(name) + '">' +
    esc(name) + '<span class="meta">' + count + "</span></span>";
}

function bdRenderLayoutPanel() {
  const box = $("#bd-layout");
  if (!bdDeck || $("#bd-view").value !== "columns"
      || $("#bd-group").value !== "category") {
    box.hidden = true;
    $("#bd-layout-btn").hidden = true;
    return;
  }
  $("#bd-layout-btn").hidden = false;
  if (box.hidden) return;

  // How many cards sit in each category, so the tiles are informative.
  const counts = {};
  (bdDeck.cards || []).forEach((row) => {
    const key = row.category || "без категории";
    counts[key] = (counts[key] || 0) + row.quantity;
  });
  const keys = Object.keys(counts).sort();
  const columns = bdColumnsOf(keys, true);

  box.innerHTML =
    '<div class="row tight wrap">' +
      "<b>Колонки</b>" +
      '<span class="meta">перетащите категорию в другую колонку</span>' +
      '<span style="flex:1"></span>' +
      '<button class="ghost tiny" id="bd-layout-add">+ колонка</button>' +
      '<button class="ghost tiny" id="bd-layout-reset">по одной на колонку</button>' +
      '<button class="ghost tiny" id="bd-layout-close">свернуть</button>' +
    "</div>" +
    '<div class="laycols">' +
      columns.map((col, i) =>
        '<div class="laycol" data-col="' + i + '">' +
          '<div class="layhead">колонка ' + (i + 1) +
            (columns.length > 1
              ? '<button class="laydrop" data-dropcol="' + i + '" title="Убрать колонку">×</button>'
              : "") +
          "</div>" +
          col.map((k) => bdLayoutTile(k, counts[k] || 0)).join("") +
        "</div>").join("") +
    "</div>";
}

function bdLayoutFromPanel() {
  return $$("#bd-layout .laycol").map((col) =>
    $$(".lay-tile", col).map((t) => t.dataset.cat));
}

$("#bd-layout-btn").addEventListener("click", () => {
  const box = $("#bd-layout");
  box.hidden = !box.hidden;
  bdRenderLayoutPanel();
});

$("#bd-layout").addEventListener("click", (ev) => {
  if (ev.target.id === "bd-layout-close") {
    $("#bd-layout").hidden = true;
    return;
  }
  if (ev.target.id === "bd-layout-add") {
    // An empty column is a legitimate saved state: it is the drop target.
    bdSetLayout(bdLayoutFromPanel().concat([[]]));
    bdRenderLayoutPanel();
    bdRenderCards();
    return;
  }
  if (ev.target.id === "bd-layout-reset") {
    bdSetLayout(null);
    bdRenderLayoutPanel();
    bdRenderCards();
    return;
  }
  const drop = ev.target.dataset && ev.target.dataset.dropcol;
  if (drop !== undefined) {
    // Removing a column keeps its categories: they move to the first one.
    const cols = bdLayoutFromPanel();
    const gone = cols.splice(parseInt(drop, 10), 1)[0] || [];
    if (!cols.length) cols.push([]);
    cols[0] = cols[0].concat(gone);
    bdSetLayout(cols);
    bdRenderLayoutPanel();
    bdRenderCards();
  }
});

let bdLayoutDrag = null;

$("#bd-layout").addEventListener("dragstart", (ev) => {
  const tile = ev.target.closest(".lay-tile");
  if (!tile) return;
  bdLayoutDrag = tile.dataset.cat;
  tile.classList.add("dragging");
  if (ev.dataTransfer) {
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", tile.dataset.cat);
  }
});

$("#bd-layout").addEventListener("dragend", () => {
  bdLayoutDrag = null;
  $$("#bd-layout .lay-tile.dragging").forEach((e) => e.classList.remove("dragging"));
  $$("#bd-layout .laycol.over").forEach((e) => e.classList.remove("over"));
});

$("#bd-layout").addEventListener("dragover", (ev) => {
  if (!bdLayoutDrag) return;
  const col = ev.target.closest(".laycol");
  if (!col) return;
  ev.preventDefault();
  if (ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
  $$("#bd-layout .laycol.over").forEach((e) => {
    if (e !== col) e.classList.remove("over");
  });
  col.classList.add("over");
});

$("#bd-layout").addEventListener("drop", (ev) => {
  const col = ev.target.closest(".laycol");
  if (!col || !bdLayoutDrag) return;
  ev.preventDefault();
  const cat = bdLayoutDrag;
  bdLayoutDrag = null;
  col.classList.remove("over");

  const target = parseInt(col.dataset.col, 10);
  const cols = bdLayoutFromPanel().map((c) => c.filter((k) => k !== cat));
  while (cols.length <= target) cols.push([]);
  cols[target].push(cat);
  bdSetLayout(cols.filter((c, i) => c.length || i <= target));
  bdRenderLayoutPanel();
  bdRenderCards();
});

/* ------------------------------------------------------- view controls */

["#bd-group", "#bd-sortin", "#bd-view"].forEach((sel) => {
  $(sel).addEventListener("change", () => {
    store.set("bdView", {
      group: $("#bd-group").value,
      sort: $("#bd-sortin").value,
      view: $("#bd-view").value,
    });
    if (bdDeck) bdRenderCards();
  });
});

$("#bd-filter").addEventListener("input", debounce(() => {
  if (bdDeck) bdRenderCards();
}, 200));

// Restore how you last liked to look at a deck.
(function bdRestoreView() {
  const saved = store.get("bdView", null);
  if (!saved) return;
  if (saved.group) $("#bd-group").value = saved.group;
  if (saved.sort) $("#bd-sortin").value = saved.sort;
  if (saved.view) $("#bd-view").value = saved.view;
})();

bdLoadDecks();
