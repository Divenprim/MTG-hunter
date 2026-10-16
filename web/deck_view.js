"use strict";

/* The deck workbench.

   Importing a decklist is only step one. What you actually do next is decide
   what to buy: narrow the list down, see what you are short and what it costs,
   tick those cards, and file them into a list. So every row carries the two
   facts that drive that decision -- how many copies you are missing and the
   price of one -- and selection drives bulk actions.

   Loaded after app.js and favourites.js; uses their helpers. */

const DECK_SECTIONS = ["commander", "main", "side", "maybe"];
let deckSel = new Set();   // indices into currentDeck.entries
let deckLastClicked = null;  // anchor for shift-click ranges

function deckEntries() {
  return (currentDeck && currentDeck.entries) || [];
}

/* ------------------------------------------------------------- filtering */

function deckVisibleIndices() {
  const needle = ($("#deck-search").value || "").trim().toLowerCase();
  const mode = $("#deck-filter").value;
  const sort = $("#deck-sort").value;

  const rows = deckEntries()
    .map((entry, index) => ({ entry: entry, index: index }))
    .filter((row) => {
      const e = row.entry;
      if (mode === "missing" && !e.missing) return false;
      if (mode === "owned" && !e.owned) return false;
      if (mode === "unknown" && e.card) return false;
      if (!needle) return true;
      const hay = [
        e.name,
        e.card && e.card.ru_name,
        e.card && e.card.flavor_name,
        e.card && e.card.type_line,
      ].filter(Boolean).join(" ").toLowerCase();
      return hay.indexOf(needle) >= 0;
    });

  const price = (row) => row.entry.unit_usd || 0;
  if (sort === "price_desc") rows.sort((a, b) => price(b) - price(a));
  else if (sort === "price_asc") rows.sort((a, b) => price(a) - price(b));
  else if (sort === "name") rows.sort((a, b) => a.entry.name.localeCompare(b.entry.name));
  else if (sort === "cmc") {
    rows.sort((a, b) => ((a.entry.card || {}).cmc || 0) - ((b.entry.card || {}).cmc || 0));
  } else if (sort === "missing") rows.sort((a, b) => b.entry.missing - a.entry.missing);

  return rows;
}

/* ------------------------------------------------------------- rendering */

function deckRowHtml(row) {
  const e = row.entry;
  const c = e.card;
  const selected = deckSel.has(row.index);
  const img = c && c.image_small;
  const sub = c
    ? [c.ru_name, c.flavor_name ? "«" + c.flavor_name + "»" : null,
       (c.set_code || "").toUpperCase()].filter(Boolean).join(" · ")
    : "не найдена в базе";
  const have = e.missing
    ? '<span class="have need">не хватает ' + e.missing +
      (e.owned ? " (есть " + e.owned + ")" : "") + "</span>"
    : (e.owned ? '<span class="have ok">есть все</span>' : "");
  const ordered = (typeof orderedCounts !== "undefined" &&
    orderedCounts[(e.name || "").toLowerCase()]) || 0;

  return (
    '<div class="deckrow' + (selected ? " sel" : "") + (c ? "" : " unknown") +
      '" data-index="' + row.index + '">' +
      '<input type="checkbox"' + (selected ? " checked" : "") + ' tabindex="-1">' +
      '<span class="qty">' + e.quantity + "×</span>" +
      (img
        ? '<img loading="lazy" src="' + esc(img) + '" alt=""' +
          (c && c.image_normal ? ' data-preview="' + esc(c.image_normal) + '"' : "") + ">"
        : "<span></span>") +
      '<span class="nm"><b>' + esc(e.name) + "</b>" +
        '<div class="sub">' + esc(sub) + "</div></span>" +
      have +
      (ordered ? '<span class="have ordered">заказано ' + ordered + "</span>" : "") +
      '<span class="pr">' + (e.unit_usd ? dollars(e.unit_usd) : "") + "</span>" +
    "</div>"
  );
}

function renderDeckList() {
  const rows = deckVisibleIndices();
  const bySection = {};
  rows.forEach((row) => {
    const sec = row.entry.section || "main";
    (bySection[sec] = bySection[sec] || []).push(row);
  });

  let html = '<div class="decklist">';
  let shown = 0;
  DECK_SECTIONS.forEach((sec) => {
    const list = bySection[sec];
    if (!list || !list.length) return;
    shown += list.length;
    const copies = list.reduce((n, row) => n + row.entry.quantity, 0);
    html += '<div class="decksection"><h3>' + esc(SECTION_TITLES[sec] || sec) +
      " — " + list.length + " назв. / " + copies + " шт.</h3>" +
      list.map(deckRowHtml).join("") + "</div>";
  });
  html += "</div>";

  if (!shown) {
    html = '<p class="meta">Под этот фильтр в колоде ничего не подходит.</p>';
  }
  $("#deck-view").innerHTML = html;
  renderDeckSelbar();
}

function renderDeckSelbar() {
  const chosen = deckEntries().filter((e, i) => deckSel.has(i));
  const bar = $("#deck-selbar");
  bar.classList.toggle("armed", chosen.length > 0);

  if (!chosen.length) {
    $("#deck-selinfo").textContent = "ничего не выбрано";
    return;
  }
  let copies = 0;
  let usd = 0;
  chosen.forEach((e) => {
    const n = e.missing > 0 ? e.missing : e.quantity;
    copies += n;
    usd += (e.unit_usd || 0) * n;
  });
  $("#deck-selinfo").textContent =
    "выбрано " + chosen.length + " назв. · " + copies + " шт. ≈ " + dollars(usd) +
    " (берём столько, сколько не хватает)";
}

function renderDeckFolderOptions() {
  const sel = $("#deck-target-folder");
  const previous = sel.value;
  const folders = (typeof favDoc !== "undefined" && favDoc.folders) || [];
  sel.innerHTML = folders.length
    ? folders.map((f) => '<option value="' + esc(f.id) + '">' + esc(f.name) +
        " (" + f.cards.length + ")</option>").join("")
    : '<option value="">нет списков</option>';
  if (previous && folders.some((f) => f.id === previous)) sel.value = previous;
}

/* ---------------------------------------------------------------- events */

$("#deck-view").addEventListener("click", (ev) => {
  const row = ev.target.closest(".deckrow");
  if (!row) return;
  const index = parseInt(row.dataset.index, 10);

  // The thumbnail opens the card; the rest of the row toggles selection.
  if (ev.target.tagName === "IMG") {
    const entry = deckEntries()[index];
    if (entry && entry.card && entry.card.oracle_id) {
      openCard({
        id: "deck-" + index,
        name: entry.card.name || entry.name,
        oracle_id: entry.card.oracle_id,
        image_normal: entry.card.image_normal,
        image_small: entry.card.image_small,
        ru_name: entry.card.ru_name,
        flavor_name: entry.card.flavor_name,
        type_line: entry.card.type_line,
        mana_cost: entry.card.mana_cost,
        prices: entry.card.prices,
        legalities: entry.card.legalities || {},
        faces: [],
      });
    }
    return;
  }

  // Shift-click selects the run between the last click and this one, in the
  // order the rows are DISPLAYED -- so it follows the current sort and filter
  // rather than the underlying deck order.
  if (ev.shiftKey && deckLastClicked !== null && deckLastClicked !== index) {
    const visible = deckVisibleIndices().map((r) => r.index);
    const from = visible.indexOf(deckLastClicked);
    const to = visible.indexOf(index);
    if (from >= 0 && to >= 0) {
      const [lo, hi] = from < to ? [from, to] : [to, from];
      // Extend, never shrink: shift-click is "also take these".
      for (let i = lo; i <= hi; i++) deckSel.add(visible[i]);
      deckLastClicked = index;
      renderDeckList();
      return;
    }
  }

  if (deckSel.has(index)) deckSel.delete(index);
  else deckSel.add(index);
  deckLastClicked = index;
  row.classList.toggle("sel", deckSel.has(index));
  const box = row.querySelector("input[type=checkbox]");
  if (box) box.checked = deckSel.has(index);
  renderDeckSelbar();
});

["#deck-search", "#deck-filter", "#deck-sort"].forEach((sel) => {
  const el = $(sel);
  const handler = () => renderDeckList();
  el.addEventListener("change", handler);
  el.addEventListener("input", debounce(handler, 200));
});

$("#deck-quickselect").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (!btn || !currentDeck) return;
  const mode = btn.dataset.sel;
  // Quick selects act on what is VISIBLE, so a filter plus a quick select
  // compose instead of fighting each other.
  const visible = deckVisibleIndices().map((row) => row.index);
  const entries = deckEntries();

  if (mode === "none") { deckSel.clear(); deckLastClicked = null; }
  else if (mode === "all") visible.forEach((i) => deckSel.add(i));
  else if (mode === "invert") {
    visible.forEach((i) => (deckSel.has(i) ? deckSel.delete(i) : deckSel.add(i)));
  } else if (mode === "missing") {
    deckSel.clear();
    visible.filter((i) => entries[i].missing > 0).forEach((i) => deckSel.add(i));
  } else if (mode === "expensive") {
    deckSel.clear();
    visible.filter((i) => (entries[i].unit_usd || 0) >= 5).forEach((i) => deckSel.add(i));
  } else if (mode === "rares") {
    deckSel.clear();
    visible
      .filter((i) => {
        const r = (entries[i].card || {}).rarity;
        return r === "rare" || r === "mythic";
      })
      .forEach((i) => deckSel.add(i));
  }
  renderDeckList();
});

function selectedDeckCards() {
  return deckEntries()
    .map((e, i) => ({ entry: e, index: i }))
    .filter((row) => deckSel.has(row.index))
    .map((row) => {
      const e = row.entry;
      return {
        // Prefer the canonical name: the deck may spell a face or a flavour
        // name, and the shopping list should hold something resolvable.
        name: (e.card && e.card.name) || e.name,
        quantity: e.missing > 0 ? e.missing : e.quantity,
      };
    });
}

$("#deck-add-fav").addEventListener("click", async (ev) => {
  const cards = selectedDeckCards();
  if (!cards.length) return toast("Сначала отметьте карты", true);

  const newName = $("#deck-new-folder").value.trim();
  const folderId = $("#deck-target-folder").value;
  if (!newName && !folderId) return toast("Укажите список", true);

  ev.target.disabled = true;
  try {
    const body = newName ? { cards: cards, folder_name: newName }
                         : { cards: cards, folder_id: folderId };
    const r = await api("/api/favourites/cards/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    favDoc = r.favourites;
    favCurrent = r.report.folder_id;
    renderFavourites();
    renderDeckFolderOptions();
    $("#deck-target-folder").value = r.report.folder_id;
    $("#deck-new-folder").value = "";
    refreshStatus();
    const rep = r.report;
    toast("В «" + rep.folder_name + "»: добавлено " + rep.added +
      (rep.stacked ? ", объединено " + rep.stacked : ""));
  } catch (e) {
    toast(e.message, true);
  } finally {
    ev.target.disabled = false;
  }
});

$("#deck-sel-hunt").addEventListener("click", () => {
  const cards = selectedDeckCards();
  if (!cards.length) return toast("Сначала отметьте карты", true);
  huntTake(cards, null);
  $("#hunt-source").textContent =
    "Выбранное из колоды «" + (currentDeck.name || "") + "» — " + cards.length + " назв.";
  showTab("hunt");
  toast("В охоту: " + cards.length + " назв.");
});

/* ------------------------------------------- из принесённого -- своя колода

   Вкладка умела всё, кроме главного: принесённую колоду нельзя было собрать.
   Её можно было посмотреть, отфильтровать, разложить по спискам, отправить в
   охоту -- и на этом всё. Человек, притащивший список с archidekt, уходил ни
   с чем.

   Здесь два пути, потому что приходят с двумя разными намерениями: «хочу
   такую колоду» -- завести новую, и «хочу добрать идей в свою» -- влить в
   ту, что открыта в билдере. */

function deckBuildName() {
  const typed = ($("#deck-build-name").value || "").trim();
  if (typed) return typed;
  return ((currentDeck && currentDeck.name) || "").trim() || "Новая колода";
}

/* В каких форматах колода легальна. Считается по картам -- ровно так же, как
   это уже делает плашка статистики над списком: отдельного поля в ответе
   сервера нет, и выдумывать его ради одной кнопки незачем. */
function deckLegalFormats() {
  const formats = {};
  for (const entry of (currentDeck && currentDeck.entries) || []) {
    const card = entry.card;
    if (!card) continue;
    const own = card.legalities || {};
    for (const name of Object.keys(own)) {
      if (formats[name] === undefined) formats[name] = true;
      if (own[name] !== "legal") formats[name] = false;
    }
  }
  return Object.keys(formats).filter((f) => formats[f]);
}

/* Какой формат поставить новой колоде. Порядок не алфавитный: человек,
   принёсший список, чаще собирает в том формате, который у списка самый
   узкий -- в standard легальна и модерновая колода, но не наоборот. */
const FORMAT_ORDER = ["standard", "pioneer", "modern", "pauper", "legacy",
                      "vintage", "commander"];

function deckBuildFormat() {
  const picked = $("#deck-build-format").value;
  if (picked) return picked;
  const legal = deckLegalFormats();
  for (const name of FORMAT_ORDER) {
    if (legal.indexOf(name) >= 0) return name;
  }
  return legal[0] || "commander";
}

function deckCardsForBuilder() {
  return (currentDeck.entries || [])
    .filter((e) => (e.name || "").trim())
    .map((e) => ({
      name: e.name,
      quantity: Math.max(1, parseInt(e.quantity, 10) || 1),
      section: e.section || "main",
      set_code: e.set_code || null,
      collector_number: e.collector_number || null,
    }));
}

async function deckToBuilder() {
  if (!currentDeck) return toast("Сначала загрузите колоду", true);
  const cards = deckCardsForBuilder();
  if (!cards.length) return toast("В списке нет карт", true);

  const button = $("#deck-to-builder");
  button.disabled = true;
  try {
    const made = await post("/api/decks",
                            { name: deckBuildName(), format: deckBuildFormat() });
    const id = made.deck.id;
    await post("/api/decks/" + id + "/cards", { cards: cards });
    toast("Колода «" + made.deck.name + "» собрана: " + cards.length + " позиций");
    // Открыть её сразу: иначе непонятно, случилось ли что-нибудь вообще.
    if (typeof bdLoadDecks === "function") await bdLoadDecks();
    showTab("builder");
    if (typeof bdOpen === "function") await bdOpen(id);
  } catch (e) {
    toast("Не вышло собрать: " + e.message, true);
  } finally {
    button.disabled = false;
  }
}

async function deckIntoOpen() {
  if (!currentDeck) return toast("Сначала загрузите колоду", true);
  const open = (typeof bdDeck !== "undefined" && bdDeck) ? bdDeck : null;
  if (!open) {
    return toast("В билдере не открыта колода — откройте ту, в которую вливать",
                 true);
  }
  const cards = deckCardsForBuilder();
  if (!cards.length) return toast("В списке нет карт", true);

  const button = $("#deck-into-open");
  button.disabled = true;
  try {
    await post("/api/decks/" + open.id + "/cards", { cards: cards });
    toast(cards.length + " позиций влито в «" + open.name + "»");
    showTab("builder");
    if (typeof bdOpen === "function") await bdOpen(open.id);
  } catch (e) {
    toast("Не вышло влить: " + e.message, true);
  } finally {
    button.disabled = false;
  }
}

$("#deck-to-builder").addEventListener("click", deckToBuilder);
$("#deck-into-open").addEventListener("click", deckIntoOpen);
