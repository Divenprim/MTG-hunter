"use strict";

/* Combos, from Commander Spellbook.

   Two questions, and the second is the interesting one:

     1. what combos does this deck already have;
     2. which is it ONE CARD short of.

   The second turns into a shopping list, which is what the rest of this program
   is for -- so a missing card shows its rouble price (if known) and goes into
   the hunt with one click.

   The combo database is local: 108k combos in data/combos.sqlite, built from a
   27 MB bulk file. Nothing downloads on its own; the first use asks.

   Loaded after builder.js and app.js; uses their helpers. */

let cbData = null;
let cbBusy = false;

function cbSteps(text) {
  // Spellbook writes the steps as one newline-separated block; numbering them
  // is what makes a combo readable rather than a wall.
  const lines = String(text || "").split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return "";
  return "<ol>" + lines.map((l) => "<li>" + esc(l) + "</li>").join("") + "</ol>";
}

function cbCardChip(name, info, missing) {
  const i = info || {};
  const rub = i.rub && i.rub.min
    ? '<span class="rub">' + Number(i.rub.min).toLocaleString("ru") + " ₽</span>"
    : "";
  return (
    '<span class="cbcard' + (missing ? " miss" : "") + '" data-name="' + esc(name) + '"' +
      (i.image_normal ? ' data-preview="' + esc(i.image_normal) + '"' : "") + ">" +
      (i.image_small
        ? '<img loading="lazy" src="' + esc(i.image_small) + '" alt="">'
        : "") +
      "<b>" + esc(name) + "</b>" +
      (i.owned > 0 ? '<span class="chip ok">есть ' + i.owned + "</span>" : "") +
      rub +
      (missing
        ? '<button class="ghost tiny" data-cb="hunt">в охоту</button>'
        : "") +
    "</span>"
  );
}

/* The cards that would finish this combo, cheapest first.

   Spellbook generates a separate variant for every card that can fill an
   interchangeable slot, so a deck holding the shared piece used to get nine
   near-identical rows: "buy Felidar Guardian", "buy Kiki-Jiki", "buy Wispweaver
   Angel". They are one combo, and any one of those cards completes it -- so
   they belong on one row, sorted by price, because the useful answer is "buy
   the cheapest of these". */
function cbOneOf(combo, info) {
  const options = (combo.one_of || []).slice();
  if (options.length < 2) return "";
  options.sort((a, b) => {
    const pa = (info[a] && info[a].rub && info[a].rub.min) || Number.MAX_SAFE_INTEGER;
    const pb = (info[b] && info[b].rub && info[b].rub.min) || Number.MAX_SAFE_INTEGER;
    return pa - pb;
  });
  return (
    '<div class="cbalts"><span class="meta">достроит любая одна из ' +
      options.length + ":</span>" +
      options.map((n) => cbCardChip(n, info[n], true)).join("") +
    "</div>"
  );
}

function cbBlock(combo, info) {
  // Only a deck can tell us what is missing. In the card window there is no
  // deck, so `missing` is absent -- and then saying "собрано" would be a lie.
  const known = Array.isArray(combo.missing);
  const missing = combo.missing || [];
  const cards = combo.cards || [];
  const templates = combo.templates || [];

  return (
    '<div class="cbcombo' + (!known ? "" : missing.length ? " near" : " done") + '">' +
      '<div class="cbhead">' +
        (!known
          ? '<span class="chip">' + cards.length + " карт" +
            (templates.length ? " + " + templates.length : "") + "</span>"
          : missing.length
            ? '<span class="chip warn">не хватает ' + missing.length +
              (templates.length ? " + условие" : "") + "</span>"
            : templates.length
              // All the named cards are here, but the combo also needs "any
              // sacrifice outlet" -- which a card list cannot confirm, so
              // calling it "собрано" would be a lie.
              ? '<span class="chip warn">карты есть, нужно условие</span>'
              : '<span class="chip ok">собрано</span>') +
        '<span class="cbresults">' + esc(combo.results || "—") + "</span>" +
        (combo.popularity
          ? '<span class="meta" title="столько колод с этим комбо на Spellbook">' +
            Number(combo.popularity).toLocaleString("ru") + " колод</span>"
          : "") +
      "</div>" +
      '<div class="cbcards">' +
        cards.map((n) => cbCardChip(n, info[n], missing.indexOf(n) >= 0)).join("") +
        templates.map((t) =>
          '<span class="cbcard tmpl" title="подойдёт любая карта с таким эффектом">' +
          esc(t) + "</span>").join("") +
      "</div>" +
      cbOneOf(combo, info) +
      (templates.length
        ? '<div class="meta cbneed">нужна ещё карта под условие: <b>' +
          templates.map(esc).join("</b>, <b>") + "</b></div>"
        : "") +
      (combo.variants > 1
        ? '<div class="meta">у этой связки ещё ' + (combo.variants - 1) +
          " вариант" + plural(combo.variants - 1, "", "а", "ов") +
          " с другими картами</div>"
        : "") +
      (combo.mana_needed
        ? '<div class="meta">мана: ' + esc(combo.mana_needed) + "</div>" : "") +
      (combo.prereq
        ? '<div class="meta">условия: ' + esc(combo.prereq) + "</div>" : "") +
      (combo.steps
        ? '<details class="help"><summary>Как это работает</summary>' +
          cbSteps(combo.steps) + "</details>"
        : "") +
    "</div>"
  );
}

function cbRender() {
  if (!cbData) return;
  const info = cbData.cards || {};
  const complete = cbData.complete || [];
  const near = cbData.near || [];
  const needsTemplate = cbData.needs_template || [];

  $("#cb-meta").innerHTML =
    "проверено карт: " + (cbData.checked || 0) +
    " · собранных комбо: <b>" + complete.length + "</b>" +
    (needsTemplate.length
      ? " · ждут условия: <b>" + needsTemplate.length + "</b>" : "") +
    " · не хватает карты: <b>" + near.length + "</b>" +
    (cbData.min_popularity
      ? " · только те, что кто-то играет"
      : " · включая никем не игранные") +
    (cbData.built_at ? ' · база комбо от ' + esc(cbData.built_at) : "");

  let html = "";
  if (complete.length) {
    html += '<div class="cbgroup"><h4>Уже собрано</h4>' +
      complete.map((c) => cbBlock(c, info)).join("") + "</div>";
  }
  if (needsTemplate.length) {
    html += '<div class="cbgroup"><h4>Все карты есть — нужно условие</h4>' +
      needsTemplate.map((c) => cbBlock(c, info)).join("") + "</div>";
  }
  if (near.length) {
    html += '<div class="cbgroup"><h4>Не хватает карт</h4>' +
      near.map((c) => cbBlock(c, info)).join("") + "</div>";
  }
  $("#cb-body").innerHTML = html ||
    '<p class="meta">Ни одного комбо не нашлось. Это нормально: у большинства ' +
    "колод их и нет — попробуйте разрешить «не хватает двух».</p>";
}

/* The database has to exist before anything can be asked of it. */
async function cbEnsureDatabase() {
  const st = await api("/api/combos/status");
  if (st.ready) return st;

  $("#cb-meta").textContent = "";
  $("#cb-body").innerHTML =
    '<p class="meta">База комбо ещё не скачана. Commander Spellbook отдаёт её ' +
    "одним файлом — 27 МБ, разбор занимает около минуты. Скачивается один раз " +
    "и лежит локально.</p>" +
    '<div class="row tight"><button id="cb-download">Скачать базу комбо</button></div>';
  return null;
}

async function cbDownload() {
  const btn = $("#cb-download") || $("#cb-rebuild");
  if (btn) btn.disabled = true;
  const started = Date.now();
  const tick = setInterval(() => {
    $("#cb-meta").innerHTML = '<span class="spinner">скачиваю и разбираю базу комбо… ' +
      Math.round((Date.now() - started) / 1000) + " с</span>";
  }, 500);
  try {
    const r = await post("/api/combos/build", {});
    clearInterval(tick);
    toast("База комбо готова: " + (r.report.combos || 0).toLocaleString("ru") + " комбо");
    cbData = null;
    await cbLoad();
  } catch (e) {
    clearInterval(tick);
    $("#cb-meta").textContent = "";
    toast(e.message, true);
  } finally {
    clearInterval(tick);
    if (btn) btn.disabled = false;
  }
}

async function cbLoad() {
  if (cbBusy) return;
  if (typeof bdDeck === "undefined" || !bdDeck) {
    $("#cb-body").innerHTML = '<p class="meta">Сначала откройте колоду в билдере.</p>';
    return;
  }
  const ready = await cbEnsureDatabase();
  if (!ready) return;

  cbBusy = true;
  $("#cb-meta").innerHTML = '<span class="spinner">ищу комбо…</span>';
  $("#cb-body").innerHTML = "";
  try {
    cbData = await api("/api/combos/deck?deck_id=" + encodeURIComponent(bdDeck.id) +
      "&missing=" + $("#cb-missing").value +
      "&commander_only=" + ($("#cb-commander").checked ? "true" : "false") +
      "&include_unplayed=" + ($("#cb-unplayed").checked ? "true" : "false"));
    cbData.built_at = ready.built_at;
    $("#cb-title").textContent = "Комбо в колоде: " + (cbData.deck_name || "");
    cbRender();
  } catch (e) {
    cbData = null;
    $("#cb-meta").textContent = "";
    $("#cb-body").innerHTML = '<p class="meta">' + esc(e.message) + "</p>";
  } finally {
    cbBusy = false;
  }
}

function cbOpen() {
  $("#cb-overlay").hidden = false;
  cbLoad();
}

function cbClose() {
  $("#cb-overlay").hidden = true;
}

$("#cb-close").addEventListener("click", cbClose);
$("#cb-overlay").addEventListener("click", (ev) => {
  if (ev.target === $("#cb-overlay")) cbClose();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("#cb-overlay").hidden) cbClose();
});

$("#cb-missing").addEventListener("change", () => { cbData = null; cbLoad(); });
$("#cb-commander").addEventListener("change", () => { cbData = null; cbLoad(); });
$("#cb-unplayed").addEventListener("change", () => { cbData = null; cbLoad(); });
$("#cb-rebuild").addEventListener("click", cbDownload);

$("#cb-body").addEventListener("click", (ev) => {
  if (ev.target.id === "cb-download") { cbDownload(); return; }

  const chip = ev.target.closest(".cbcard");
  if (!chip || !chip.dataset.name) return;
  if (ev.target.dataset && ev.target.dataset.cb === "hunt") {
    addToHunt(chip.dataset.name, 1);
    return;
  }
});

/* Every card the deck is short of, in one go: that is the shopping list. */
$("#cb-hunt-missing").addEventListener("click", () => {
  if (!cbData) return;
  const names = [];
  (cbData.near || []).forEach((c) => {
    (c.missing || []).forEach((n) => {
      if (names.indexOf(n) < 0) names.push(n);
    });
  });
  if (!names.length) return toast("Недостающих карт нет", true);
  names.forEach((n) => addToHunt(n, 1));
  toast("В охоту добавлено: " + names.length);
});

/* ------------------------------------------------- combos of a single card

   In the card window, next to its prices: what this card combos with. */

async function loadCardCombos(card) {
  const box = $("#modal-combos");
  if (!box) return;
  box.innerHTML = '<div class="meta spinner">ищу комбо…</div>';
  try {
    const st = await api("/api/combos/status");
    if (!st.ready) {
      box.innerHTML = '<div class="meta">База комбо не скачана — её можно ' +
        "получить в билдере, кнопкой «Комбо в колоде».</div>";
      return;
    }
    const r = await api("/api/combos/card?name=" + encodeURIComponent(card.name) +
      "&include_unplayed=" + ($("#cb-unplayed") && $("#cb-unplayed").checked
        ? "true" : "false"));
    if (!r.combos.length) {
      box.innerHTML = '<div class="meta">Комбо с этой картой не найдено.</div>';
      return;
    }
    box.innerHTML = '<div class="flabel">Комбо с этой картой — ' + r.combos.length +
      "</div>" + r.combos.map((c) => cbBlock(c, r.cards)).join("");
  } catch (e) {
    box.innerHTML = '<div class="meta">' + esc(e.message) + "</div>";
  }
}
