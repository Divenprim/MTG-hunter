"use strict";

/* Suggestions for a commander.

   The data is EDHREC's -- what people actually put in decks with this
   commander -- but the numbers a builder needs are local: do I own it, is it
   already in the deck, what does it cost in roubles. So every row carries all
   four, and the two things you do with a suggestion (put it in the deck, put it
   on the shopping list) are one click away.

   No topdeck requests happen here. A commander page is 250 cards; asking
   topdeck for each at 1.5s would be six minutes. Rouble prices shown are the
   ones already cached by «Обновить цены с topdeck».

   Loaded after builder.js; uses its helpers and bdDeck. */

let recData = null;
let recBusy = false;
const recPicked = new Set();

function recFind(name) {
  for (const section of (recData && recData.sections) || []) {
    const hit = section.cards.find((c) => c.name === name);
    if (hit) return hit;
  }
  return null;
}

function recShare(x) {
  return x.share == null ? "" : Math.round(x.share * 100) + "%";
}

function recSynergy(x) {
  if (x.synergy == null) return "";
  const pct = Math.round(x.synergy * 100);
  return (pct > 0 ? "+" : "") + pct + "%";
}

/* The order rows are shown in. EDHREC's own order mixes share and synergy;
   for a Russian-market tool the useful extra is "cheapest first", which is why
   rouble price is a sort key at all. Cards with no price known sink to the
   bottom rather than pretending to be free. */
function recSort(cards) {
  const mode = $("#rec-sort").value;
  if (mode === "edhrec") return cards;
  const rows = cards.slice();
  const far = Number.MAX_SAFE_INTEGER;
  if (mode === "share") rows.sort((a, b) => (b.share || 0) - (a.share || 0));
  else if (mode === "synergy") rows.sort((a, b) => (b.synergy || 0) - (a.synergy || 0));
  else if (mode === "rub") {
    rows.sort((a, b) => ((a.rub && a.rub.min) || far) - ((b.rub && b.rub.min) || far));
  } else if (mode === "usd") {
    rows.sort((a, b) => (a.usd == null ? far : a.usd) - (b.usd == null ? far : b.usd));
  }
  return rows;
}

/* Which rows the filters let through. */
function recVisible(cards) {
  const hideDeck = $("#rec-hide-deck").checked;
  const onlyMissing = $("#rec-only-missing").checked;
  const minShare = parseFloat($("#rec-min-share").value) || 0;
  return cards.filter((c) => {
    if (hideDeck && c.in_deck > 0) return false;
    if (onlyMissing && (c.owned > 0 || c.in_deck > 0)) return false;
    if (minShare && (c.share == null || c.share < minShare)) return false;
    return true;
  });
}

function recRow(x) {
  const card = x.card || {};
  const img = card.image_small;
  const big = card.image_normal;
  const rub = x.rub && x.rub.min
    ? '<span class="rub"><b>' + Number(x.rub.min).toLocaleString("ru") + " ₽</b></span>"
    : '<span class="rub none" title="цена с topdeck ещё не запрашивалась">—</span>';

  const marks = [];
  if (x.in_deck > 0) marks.push('<span class="chip ok">в колоде ' + x.in_deck + "</span>");
  if (x.owned > 0) marks.push('<span class="chip ok">есть ' + x.owned + "</span>");
  if (x.staple) marks.push('<span class="chip">стейпл</span>');
  if (x.off_identity) marks.push('<span class="chip warn">вне идентичности</span>');
  if (!x.known) marks.push('<span class="chip warn">нет в локальной базе</span>');

  return (
    '<div class="recrow" data-name="' + esc(x.name) + '">' +
      '<input type="checkbox"' + (recPicked.has(x.name) ? " checked" : "") + ">" +
      (img
        ? '<img loading="lazy" src="' + esc(img) + '" alt=""' +
          (big ? ' data-preview="' + esc(big) + '"' : "") + ">"
        : "<span></span>") +
      '<span class="nm">' + esc(x.name) +
        (card.ru_name ? '<div class="sub">' + esc(card.ru_name) + "</div>" : "") +
      "</span>" +
      // The share is the headline number, so it gets a bar you can read across
      // rows without doing arithmetic.
      '<span class="share" title="в ' + x.decks + " колодах из " + x.pool + '">' +
        '<span class="bar"><i style="width:' +
          Math.round(Math.min(1, x.share || 0) * 100) + '%"></i></span>' +
        "<b>" + recShare(x) + "</b>" +
      "</span>" +
      '<span class="syn" title="во столько раз чаще, чем в колодах вообще">' +
        recSynergy(x) + "</span>" +
      '<span class="usd">' + (x.usd != null ? "$" + x.usd.toFixed(2) : "") + "</span>" +
      rub +
      '<span class="marks">' + marks.join("") + "</span>" +
      '<span class="acts">' +
        '<button class="ghost tiny" data-rec="deck">в колоду</button>' +
        '<button class="ghost tiny" data-rec="hunt">в охоту</button>' +
      "</span>" +
    "</div>"
  );
}

function recRender() {
  if (!recData) return;
  const c = recData.commander || {};
  $("#rec-title").textContent = "Предложка: " + (c.name || recData.asked || "");

  const when = recData.fetched
    ? new Date(recData.fetched * 1000).toLocaleString("ru")
    : "";
  const t = recData.totals || {};
  $("#rec-meta").innerHTML =
    "по <b>" + Number(c.decks || 0).toLocaleString("ru") + "</b> колодам с EDHREC · " +
    "предложено " + (t.cards || 0) + " карт · уже в колоде " + (t.in_deck || 0) +
    " · есть у вас " + (t.owned || 0) +
    " · цена в рублях известна для " + (t.priced || 0) +
    (recData.cached ? " · данные из кеша от " + esc(when) : " · данные только что получены") +
    (recData.stale ? ' · <span class="warn">EDHREC не ответил, показаны прошлые данные</span>' : "");

  let html = "";
  let shown = 0;
  (recData.sections || []).forEach((section) => {
    const cards = recSort(recVisible(section.cards));
    if (!cards.length) return;
    shown += cards.length;
    html += '<div class="recgroup"><h4>' + esc(section.title) +
      ' <span class="meta">' + cards.length + "</span></h4>" +
      cards.map(recRow).join("") + "</div>";
  });

  $("#rec-body").innerHTML = html ||
    '<p class="meta">Под эти фильтры ничего не осталось — ослабьте условия.</p>';
  if (shown) {
    $("#rec-meta").innerHTML += " · показано " + shown;
  }
}

async function recLoad(refresh) {
  if (recBusy) return;
  const typed = $("#rec-commander").value.trim();
  const params = [];
  if (typed) params.push("commander=" + encodeURIComponent(typed));
  if (typeof bdDeck !== "undefined" && bdDeck) params.push("deck_id=" + encodeURIComponent(bdDeck.id));
  if (refresh) params.push("refresh=true");
  if (!typed && !recCommanderOfDeck()) {
    toast("Впишите имя командира — в открытой колоде он не выбран", true);
    $("#rec-commander").focus();
    return;
  }

  recBusy = true;
  $("#rec-run").disabled = true;
  $("#rec-refresh").disabled = true;
  $("#rec-meta").innerHTML = '<span class="spinner">спрашиваю EDHREC…</span>';
  $("#rec-body").innerHTML = "";
  try {
    recData = await api("/api/recommend?" + params.join("&"));
    recPicked.clear();
    if (!$("#rec-commander").value.trim() && recData.commander) {
      $("#rec-commander").value = recData.commander.name || "";
    }
    recRender();
  } catch (e) {
    recData = null;
    $("#rec-meta").textContent = "";
    $("#rec-body").innerHTML = '<p class="meta">' + esc(e.message) + "</p>";
  } finally {
    recBusy = false;
    $("#rec-run").disabled = false;
    $("#rec-refresh").disabled = false;
  }
}

function recCommanderOfDeck() {
  if (typeof bdDeck === "undefined" || !bdDeck) return "";
  const cmd = (bdDeck.cards || []).find((c) => c.section === "commander");
  return cmd ? cmd.name : "";
}

function recOpen() {
  $("#rec-overlay").hidden = false;
  // The deck knows its commander; the field is only for looking at others.
  const own = recCommanderOfDeck();
  if (own) $("#rec-commander").value = own;

  if (recData) { recRender(); return; }

  if (!$("#rec-commander").value.trim()) {
    // No point asking the server a question it cannot answer.
    $("#rec-meta").textContent = "";
    $("#rec-body").innerHTML =
      '<p class="meta">В колоде не выбран командир. Впишите имя в поле выше — ' +
      "или назначьте карту командиром в колоде, и предложка подхватит его сама.</p>";
    $("#rec-commander").focus();
    return;
  }
  recLoad(false);
}

function recClose() {
  $("#rec-overlay").hidden = true;
}

$("#rec-close").addEventListener("click", recClose);
$("#rec-overlay").addEventListener("click", (ev) => {
  if (ev.target === $("#rec-overlay")) recClose();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("#rec-overlay").hidden) recClose();
});

$("#rec-run").addEventListener("click", () => recLoad(false));
$("#rec-refresh").addEventListener("click", () => recLoad(true));
$("#rec-commander").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") recLoad(false);
});

["#rec-hide-deck", "#rec-only-missing", "#rec-min-share", "#rec-sort"].forEach((sel) => {
  $(sel).addEventListener("change", recRender);
});

/* Rouble prices for the ticked cards. Every name is a 1.5s request to topdeck,
   so this is a deliberate act with a ceiling, never something that happens on
   its own while you browse. */
async function recPrices(names) {
  if (!names.length) return toast("Ничего не отмечено", true);
  const btn = $("#rec-prices-picked");
  btn.disabled = true;
  const started = Date.now();
  const tick = setInterval(() => {
    $("#rec-meta").innerHTML = '<span class="spinner">спрашиваю topdeck про ' +
      names.length + " карт… " + Math.round((Date.now() - started) / 1000) + " с</span>";
  }, 500);
  try {
    const r = await post("/api/prices", { names: names, only_missing: true });
    clearInterval(tick);
    const got = r.prices || {};
    // Fold the answers into the rows we already have, so nothing is re-fetched
    // from EDHREC just to show a price.
    (recData.sections || []).forEach((section) => {
      section.cards.forEach((c) => {
        const hit = got[c.name.toLowerCase()];
        if (hit) {
          c.rub = { min: hit.rub_min, median: hit.rub_median,
                    offers: hit.offers, checked_at: hit.checked_at };
        }
      });
    });
    recRender();
    const rep = r.report || {};
    toast("Цены обновлены: " + (rep.updated || 0) +
          (rep.not_found && rep.not_found.length
            ? " · не нашлось: " + rep.not_found.length : ""));
  } catch (e) {
    clearInterval(tick);
    toast(e.message, true);
    recRender();
  } finally {
    clearInterval(tick);
    btn.disabled = false;
  }
}

$("#rec-prices-picked").addEventListener("click", () => recPrices(Array.from(recPicked)));

/* Adding: one card, or everything ticked. */

async function recAddToDeck(names) {
  if (!names.length) return toast("Ничего не отмечено", true);
  if (typeof bdDeck === "undefined" || !bdDeck) {
    return toast("Сначала откройте колоду в билдере", true);
  }
  const r = await bdCall("/api/decks/" + bdDeck.id + "/cards", bdBody("POST", {
    cards: names.map((n) => ({ name: n, quantity: 1, section: "main", category: "" })),
  }));
  if (r) {
    toast(names.length === 1 ? "«" + names[0] + "» в колоде"
                             : "В колоду добавлено: " + names.length);
    recPicked.clear();
    // The deck changed, so "уже в колоде" has to change with it.
    await recLoad(false);
  }
}

function recAddToHunt(names) {
  if (!names.length) return toast("Ничего не отмечено", true);
  names.forEach((n) => addToHunt(n, 1));
  toast(names.length === 1 ? "«" + names[0] + "» — в списке охоты"
                           : "В охоту добавлено: " + names.length);
}

$("#rec-body").addEventListener("click", (ev) => {
  const row = ev.target.closest(".recrow");
  if (!row) return;
  const name = row.dataset.name;

  const act = ev.target.dataset && ev.target.dataset.rec;
  if (act === "deck") { recAddToDeck([name]); return; }
  if (act === "hunt") { recAddToHunt([name]); return; }

  if (ev.target.tagName === "INPUT") {
    if (ev.target.checked) recPicked.add(name);
    else recPicked.delete(name);
    return;
  }

  // Clicking the thumbnail opens the card, the same as in the deck lists.
  if (ev.target.tagName === "IMG") {
    const found = recFind(name);
    const card = found && found.card;
    if (card && card.oracle_id) {
      openCard({
        id: "rec-" + name,
        name: card.name || name,
        oracle_id: card.oracle_id,
        image_normal: card.image_normal,
        image_small: card.image_small,
        ru_name: card.ru_name,
        type_line: card.type_line,
        mana_cost: card.mana_cost,
        cmc: card.cmc,
        prices: {},
        legalities: {},
        faces: [],
      });
    }
  }
});

$("#rec-add-picked").addEventListener("click", () => recAddToDeck(Array.from(recPicked)));
$("#rec-hunt-picked").addEventListener("click", () => recAddToHunt(Array.from(recPicked)));
