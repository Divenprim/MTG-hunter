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
  // Both tabs render the same rows, so a click has to find the card in
  // whichever of the two datasets it came from.
  for (const data of [recData, coData]) {
    for (const section of (data && data.sections) || []) {
      const hit = section.cards.find((c) => c.name === name);
      if (hit) return hit;
    }
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
        // Only offered when there is a sample to answer from.
        (coState && coState.decks
          ? '<button class="ghost tiny" data-rec="pairs" ' +
            'title="что стоит рядом с этой картой в выборке">с чем идёт</button>'
          : "") +
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
  const query = recQuery(refresh);
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
    recData = await api("/api/recommend?" + query);
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

function recRowClick(ev) {
  const row = ev.target.closest(".recrow");
  if (!row) return;
  const name = row.dataset.name;

  const act = ev.target.dataset && ev.target.dataset.rec;
  if (act === "deck") { recAddToDeck([name]); return; }
  if (act === "hunt") { recAddToHunt([name]); return; }
  if (act === "pairs") { coPairs(name, row); return; }

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
}

$("#rec-body").addEventListener("click", recRowClick);
$("#rec-cooccur-body").addEventListener("click", recRowClick);

$("#rec-add-picked").addEventListener("click", () => recAddToDeck(Array.from(recPicked)));
$("#rec-hunt-picked").addEventListener("click", () => recAddToHunt(Array.from(recPicked)));

/* ------------------------------------------------- вкладки: форма колоды ----

   Первая вкладка отвечает «что ещё добавляют», вторая — «нормальная ли форма
   колоды». Это разные вопросы: список карт не скажет, что рампы вдвое меньше,
   чем в средней колоде на этом командире, а именно это чаще всего и не так.

   Данные берутся из /api/deckshape: тот же кешированный лист EDHREC, прочитанный
   не ради списков карт, а ради средних. Один лишний запрос на командира — за
   усреднённой колодой, из которой считается рампа/добор/удаление нашими же
   функциональными тегами. */

let recShapeData = null;
let recShapeBusy = false;
// Kept so re-rendering the builder line does not flash "считаю..." at every
// card you add: the previous answer stays visible while the new one arrives.
let bdAdviceText = "";
let bdAdviceFor = null;
let recTabName = "cards";

function recQuery(refresh) {
  const typed = $("#rec-commander").value.trim();
  const params = [];
  if (typed) params.push("commander=" + encodeURIComponent(typed));
  if (typeof bdDeck !== "undefined" && bdDeck) {
    params.push("deck_id=" + encodeURIComponent(bdDeck.id));
  }
  if (refresh) params.push("refresh=true");
  return params.join("&");
}

function recTab(name) {
  recTabName = name;
  $$("#rec-tabs .subtab").forEach((b) => {
    b.classList.toggle("active", b.dataset.rectab === name);
  });
  $("#rec-pane-cards").hidden = name !== "cards";
  $("#rec-pane-shape").hidden = name !== "shape";
  $("#rec-pane-themes").hidden = name !== "themes";
  $("#rec-pane-cooccur").hidden = name !== "cooccur";

  if (name === "cooccur") {
    // Reads the cache on disk and draws what is there. Nothing is fetched
    // from Archidekt until the button is pressed.
    coStatus().then(() => {
      if (coState && coState.decks && !coData) coLoad();
      else coRender();
    }).catch((e) => {
      $("#rec-cooccur-body").innerHTML = '<p class="meta">' + esc(e.message) + "</p>";
    });
    return;
  }
  if (name === "cards") return;
  // The builder strip may have loaded this already; then there is nothing to
  // fetch and everything to draw.
  if (recShapeData) {
    recRenderShape();
    recRenderThemes();
  } else if (!recShapeBusy) {
    recLoadShape(false);
  }
}

$("#rec-tabs").addEventListener("click", (ev) => {
  const tab = ev.target.closest("[data-rectab]");
  if (tab) recTab(tab.dataset.rectab);
});

/* Two bars per row: yours above, the average below, both to the same scale. */
function recBars(yours, average, max) {
  const w = (v) => Math.max(0, Math.round((100 * (v || 0)) / (max || 1))) + "%";
  return '<span class="sbar" title="сверху ваша колода, снизу средняя">' +
    '<i class="you" style="width:' + w(yours) + '"></i>' +
    '<i class="avg" style="width:' + w(average) + '"></i></span>';
}

function recShapeTable(rows, hasDeck) {
  if (!rows.length) return '<p class="meta">нечего сравнивать</p>';
  const max = rows.reduce((m, r) => Math.max(m, r.yours, r.average), 1);
  return '<table class="shape"><tr><th class="lbl"></th>' +
    (hasDeck ? "<th>у вас</th>" : "") + "<th>в средней</th><th></th></tr>" +
    rows.map((r) =>
      "<tr" + (hasDeck && r.notable ? ' class="notable"' : "") + ">" +
        '<td class="lbl">' + esc(r.label) + "</td>" +
        (hasDeck ? '<td class="num you">' + r.yours + "</td>" : "") +
        '<td class="num">' + r.average + "</td>" +
        '<td class="bar">' + recBars(hasDeck ? r.yours : 0, r.average, max) + "</td>" +
      "</tr>").join("") +
    "</table>";
}

/* The sentences worth saying: only where the gap is big, biggest first, and
   phrased without declining Russian nouns -- "Рампа: 4 против 13" reads right
   whatever the word is. */
function recAdvice(data) {
  const rows = (data.functions || []).concat(data.types || [])
    .filter((r) => r.notable)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  if (!rows.length) {
    return '<p class="meta">Форма колоды близка к средней — по крупным ' +
      "категориям расхождений нет.</p>";
  }
  return '<ul class="shape-advice">' + rows.map((r) =>
    "<li><b>" + esc(r.label) + "</b>: " + r.yours + " против " + r.average +
    " — " + (r.delta < 0
      ? "добавить " + Math.abs(r.delta)
      : "на " + r.delta + " больше среднего") +
    "</li>").join("") + "</ul>";
}

function recCurve(data) {
  const mine = data.curve.yours || {};
  const avg = data.curve.average || {};
  const rows = [];
  for (let i = 0; i <= 7; i++) {
    if (!mine[i] && !avg[i]) continue;
    rows.push({
      key: String(i),
      label: i >= 7 ? "7+" : String(i),
      yours: mine[i] || 0,
      average: avg[i] || 0,
      delta: (mine[i] || 0) - (avg[i] || 0),
      notable: false,
    });
  }
  if (!rows.length) return "";
  return "<h3>Кривая маны</h3>" + recShapeTable(rows, data.has_deck);
}

function recRenderShape() {
  const data = recShapeData;
  const box = $("#rec-pane-shape");
  if (!data) { box.innerHTML = ""; return; }
  const source = '<p class="meta">Средние — по ' + data.decks.toLocaleString("ru-RU") +
    " колодам на этом командире (EDHREC). Средняя колода — это среднее, а не " +
    "цель: смысл только в крупных расхождениях." +
    (data.unknown ? " Карт вне нашей базы: " + data.unknown + "." : "") + "</p>";

  box.innerHTML =
    (data.has_deck
      ? "<h3>Что стоит подправить</h3>" + recAdvice(data)
      : '<p class="meta">Колода не открыта — показана только средняя.</p>') +
    "<h3>Типы карт</h3>" + recShapeTable(data.types, data.has_deck) +
    "<h3>Функции</h3>" +
    '<p class="meta">Считается по функциональным тегам — тем же, что и ' +
      "автоматические категории. Карта попадает в каждую функцию, которой " +
      "служит, кроме одного: карта, ускоряющая ману, считается рампой, а не " +
      "тутором. Земли тут не считаются вовсе — земля это земля, иначе девять " +
      "фетчлендов выглядели бы как девять туторов.</p>" +
    recShapeTable(data.functions, data.has_deck) +
    recCurve(data) +
    source;
}

function recRenderThemes() {
  const data = recShapeData;
  const box = $("#rec-pane-themes");
  if (!data) { box.innerHTML = ""; return; }
  const ru = (n) => Number(n).toLocaleString("ru-RU");

  const themes = (data.themes || []).length
    ? '<div class="row tight wrap themechips">' + data.themes.map((t) =>
        '<span class="chip">' + esc(t.label) +
        '<span class="meta"> ' + ru(t.decks) + "</span></span>"
      ).join("") + "</div>"
    : '<p class="meta">EDHREC не выделил тем для этого командира.</p>';

  const brackets = Object.keys(data.brackets || {}).sort().map((k) =>
    '<span class="chip">брекет ' + esc(k) + '<span class="meta"> ' +
    ru(data.brackets[k]) + "</span></span>").join("");

  const budgetNames = { budget: "бюджетных", middle: "средних", expensive: "дорогих" };
  const budget = Object.keys(data.budget || {}).map((k) =>
    '<span class="chip">' + esc(budgetNames[k] || k) + '<span class="meta"> ' +
    ru(data.budget[k]) + "</span></span>").join("");

  const combos = (data.combos || []).length
    ? '<ul class="shape-advice">' + data.combos.map((c) =>
        "<li>" + (c.cards || []).map((n) => esc(n)).join(" + ") + "</li>").join("") +
      "</ul>" +
      '<p class="meta">Это самые частые комбо на этом командире по EDHREC. ' +
      "Что из них уже собрано у вас — на «Комбо в колоде»: там считает наша " +
      "локальная база, а не эта страница.</p>"
    : '<p class="meta">Частых комбо на этом командире EDHREC не показывает.</p>';

  box.innerHTML =
    "<h3>С чем его собирают</h3>" + themes +
    "<h3>Уровень и бюджет</h3>" +
    '<div class="row tight wrap themechips">' + brackets + budget + "</div>" +
    '<p class="meta">Числа — сколько колод EDHREC отнёс к каждой группе.</p>' +
    "<h3>Частые комбо</h3>" + combos;
}

async function recLoadShape(refresh) {
  if (recShapeBusy) return;
  if (!$("#rec-commander").value.trim() && !recCommanderOfDeck()) {
    $("#rec-pane-shape").innerHTML =
      '<p class="meta">Не выбран командир — вписать его можно в поле выше.</p>';
    return;
  }
  recShapeBusy = true;
  $("#rec-pane-shape").innerHTML = '<span class="spinner">считаю форму колоды…</span>';
  try {
    recShapeData = await api("/api/deckshape?" + recQuery(refresh));
    recRenderShape();
    recRenderThemes();
  } catch (e) {
    $("#rec-pane-shape").innerHTML = '<p class="meta">' + esc(e.message) + "</p>";
    $("#rec-pane-themes").innerHTML = "";
  } finally {
    recShapeBusy = false;
  }
}

/* --------------------------------------------- режим предложений в билдере ---

   Просьба была «чтобы не надоедало»: спрашиваем один раз на колоду, запоминаем
   ответ, дальше это одна строка под статистикой. Пока режим не включён, за
   данными никто не ходит — ни одного запроса к EDHREC. */

function bdAdviceKey() {
  return typeof bdDeck !== "undefined" && bdDeck ? "bdAdvice." + bdDeck.id : null;
}

function bdAdvicePref() {
  const key = bdAdviceKey();
  return key ? store.get(key, null) : null;
}

let bdAdviceShown = "";

function recAdviceShow(box, html) {
  // Rebuilding identical markup would blink the strip on every card you add
  // -- the builder re-renders after each change -- and would detach the very
  // button under the pointer.
  if (bdAdviceShown !== html) {
    bdAdviceShown = html;
    box.innerHTML = html;
  }
  box.hidden = false;
}

function recSuggestHint() {
  const box = $("#bd-advice");
  if (!box) return;
  const commander = recCommanderOfDeck();
  const pref = bdAdvicePref();
  if (!commander || pref === false) {
    box.hidden = true;
    bdAdviceShown = "";
    box.innerHTML = "";
    return;
  }

  if (pref !== true) {
    recAdviceShow(box,
      '<div class="row tight wrap suggestbar">' +
        "<b>Подсказывать карты по командиру?</b>" +
        '<span class="meta">сравню колоду со средней на «' + esc(commander) +
          '» и покажу, чего не хватает</span>' +
        '<span style="flex:1"></span>' +
        '<button type="button" class="tiny" data-advice="on">Включить</button>' +
        '<button type="button" class="ghost tiny" data-advice="off">Не сейчас</button>' +
      "</div>");
    return;
  }

  recAdviceShow(box,
    '<div class="row tight wrap suggestbar">' +
      '<span class="meta">Форма колоды: <span id="bd-advice-line">' +
        esc(bdAdviceText || "считаю…") + "</span></span>" +
      '<span style="flex:1"></span>' +
      '<button type="button" class="ghost tiny" data-advice="open">Предложить карты</button>' +
      '<button type="button" class="ghost tiny" data-advice="off">Не подсказывать</button>' +
    "</div>");
  bdAdviceLine();
}

async function bdAdviceLine() {
  const target = $("#bd-advice-line");
  if (!target) return;
  const deckId = (typeof bdDeck !== "undefined" && bdDeck) ? bdDeck.id : null;
  if (bdAdviceFor !== deckId) { bdAdviceText = ""; bdAdviceFor = deckId; }
  try {
    const data = await api("/api/deckshape?" + recQuery(false));
    recShapeData = data;
    const gaps = (data.functions || [])
      .filter((r) => r.notable && r.delta < 0)
      .sort((a, b) => a.delta - b.delta)
      .slice(0, 3);
    bdAdviceText = gaps.length
      ? gaps.map((r) => r.label.toLowerCase() + " " + r.delta).join(" · ") +
        " от средней колоды"
      : "по крупным категориям расхождений нет";
    target.textContent = bdAdviceText;
  } catch (e) {
    target.textContent = bdAdviceText || "не удалось посчитать";
  }
}

$("#bd-advice").addEventListener("click", (ev) => {
  const act = ev.target.dataset && ev.target.dataset.advice;
  if (!act) return;
  const key = bdAdviceKey();
  if (act === "on") {
    if (key) store.set(key, true);
    recSuggestHint();
  } else if (act === "off") {
    if (key) store.set(key, false);
    recSuggestHint();
    toast("Не буду. Вернуть — кнопкой «Предложка по командиру»");
  } else if (act === "open") {
    recOpen();
    recTab("shape");
  }
});

/* ------------------------------------------- под ваш состав: выборка колод ---

   Вкладка отвечает на то, чего агрегированные числа не знают: не «сколько
   колод вообще играет эту карту», а «сколько из тех колод, что похожи на вашу».
   Для этого нужны сами колоды, поэтому выборка скачивается с Archidekt — и
   только по кнопке.

   Про вежливость: 1.5 с на запрос, колода скачивается один раз и остаётся в
   кеше, работа идёт порциями. Пока панель открыта и вы смотрите — просим
   следующую порцию; закрыли или нажали «остановить» — трафик прекращается. */

let coData = null;
let coState = null;
let coBusy = false;
let coStop = false;

function coHead() {
  const box = $("#rec-sample");
  if (!box) return;
  const st = coState || {};
  const have = st.decks || 0;
  const target = Number($("#rec-target") ? $("#rec-target").value : 150);

  box.innerHTML =
    '<label class="inline">выборка' +
      '<select id="rec-target"' + (coBusy ? " disabled" : "") + ">" +
        [[60, "60 колод · ~1.5 мин"], [150, "150 колод · ~4 мин"],
         [300, "300 колод · ~8 мин"]].map(([v, label]) =>
          '<option value="' + v + '"' + (v === target ? " selected" : "") + ">" +
          label + "</option>").join("") +
      "</select></label>" +
    '<span class="meta" id="rec-sample-state">скачано колод: <b>' + have +
      "</b>" + (target ? " из " + target : "") + "</span>" +
    '<span style="flex:1"></span>' +
    (coBusy
      ? '<button class="ghost tiny" id="rec-sample-stop">Остановить</button>'
      : '<button class="tiny" id="rec-sample-go">' +
        (have ? "Собрать ещё" : "Собрать выборку") + "</button>") +
    (have && !coBusy
      ? '<button class="ghost tiny" id="rec-sample-calc">Пересчитать</button>'
      : "");
}

function coNote() {
  const st = coState || {};
  const parts = [
    "Колоды берутся с <b>Archidekt</b>, по 1.5 с на запрос, и складываются в " +
    "кеш на диске (<code>data/archidekt/</code>) — повторный сбор докачивает " +
    "только новые.",
  ];
  if (st.failed) {
    parts.push("Пропущено колод: " + st.failed +
      " (закрытые, удалённые или недособранные).");
  }
  parts.push(
    "Это <b>выборка</b>, а не вся правда: Archidekt отдаёт самые просматриваемые " +
    "колоды, и списки в интернете — не случайная выборка из всех колод мира. " +
    "Числа описывают выборку.");
  return '<p class="meta">' + parts.join(" ") + "</p>";
}

function coRender() {
  const box = $("#rec-cooccur-body");
  if (!box) return;
  const st = coState || {};

  if (!st.decks) {
    box.innerHTML = coNote() +
      '<p class="meta">Выборки пока нет. Нажмите «Собрать выборку» — и ' +
      "появится ответ на вопрос, которого нет ни у EDHREC, ни в билдере: что " +
      "стоит в колодах, похожих на вашу.</p>";
    return;
  }
  if (!coData) {
    box.innerHTML = coNote() +
      '<p class="meta">Выборка есть (' + st.decks + "), но ещё не посчитана — " +
      "нажмите «Пересчитать».</p>";
    return;
  }

  const cards = (coData.sections && coData.sections[0]
    ? coData.sections[0].cards : []);
  const head =
    '<p class="meta">' +
      (coData.fallback
        ? "Похожих колод пока мало, поэтому взята <b>вся выборка</b> из " +
          coData.sample.decks + " колод — числа ниже про неё."
        : "Взято <b>" + coData.near + "</b> колод, наиболее похожих на вашу " +
          "(у самой близкой совпало " + coData.overlap + " карт из " +
          coData.sample.decks + " скачанных).") +
    " Колонка после доли — насколько карта тут чаще, чем в выборке целиком: " +
    "у стейпла там около нуля, у особенности вашей сборки — заметный плюс.</p>";

  if (!cards.length) {
    box.innerHTML = coNote() + head +
      '<p class="meta">Ничего нового: всё, что стоит у похожих колод, у вас ' +
      "уже есть.</p>";
    return;
  }

  box.innerHTML = coNote() + head +
    '<div class="recgroup"><h4>' + esc(coData.sections[0].title) +
      ' <span class="meta">' + cards.length + "</span></h4>" +
      recSort(recVisible(cards)).map(recRow).join("") +
    "</div>";
}

async function coStatus() {
  const target = $("#rec-target") ? Number($("#rec-target").value) : 150;
  coState = await api("/api/cooccur/status?" + recQuery(false) +
    "&target=" + target);
  coHead();
}

async function coLoad() {
  const box = $("#rec-cooccur-body");
  box.innerHTML = '<span class="spinner">считаю по выборке…</span>';
  try {
    coData = await api("/api/cooccur?" + recQuery(false) + "&near=30&limit=60");
    coState = Object.assign({}, coState, coData.sample);
    coHead();
    coRender();
  } catch (e) {
    box.innerHTML = '<p class="meta">' + esc(e.message) + "</p>";
  }
}

/* One chunk per request, in a loop we can stop. The traffic ends within one
   chunk of the user pressing «Остановить» -- never mid-request, because a
   half-fetched deck would just have to be fetched again. */
async function coCollect() {
  if (coBusy) return;
  coBusy = true;
  coStop = false;
  const target = Number($("#rec-target").value);
  coHead();

  try {
    while (!coStop) {
      const st = await post("/api/cooccur/collect", {
        commander: $("#rec-commander").value.trim(),
        deck_id: (typeof bdDeck !== "undefined" && bdDeck) ? bdDeck.id : "",
        target: target,
      });
      coState = st;
      const line = $("#rec-sample-state");
      if (line) {
        line.innerHTML = "скачано колод: <b>" + st.decks + "</b> из " + target +
          (coStop ? " · останавливаюсь" : " · качаю…");
      }
      if (st.done || st.exhausted) break;
    }
  } catch (e) {
    toast(e.message, true);
  } finally {
    coBusy = false;
    coHead();
    await coLoad();
  }
}

$("#rec-sample").addEventListener("click", (ev) => {
  if (ev.target.id === "rec-sample-go") coCollect();
  else if (ev.target.id === "rec-sample-stop") {
    coStop = true;
    toast("Останавливаюсь — докачаю начатую порцию и всё");
  } else if (ev.target.id === "rec-sample-calc") coLoad();
});

$("#rec-sample").addEventListener("change", (ev) => {
  if (ev.target.id === "rec-target") coStatus();
});

/* Что ходит вместе с картой: та же выборка, но вопрос про пару, а не про
   колоду целиком. Раскрывается под строкой, чтобы не уводить со списка. */
async function coPairs(name, row) {
  let box = row.nextElementSibling;
  if (box && box.classList.contains("copairs")) {
    box.remove();
    return;
  }
  box = document.createElement("div");
  box.className = "copairs";
  box.innerHTML = '<span class="spinner">смотрю пары…</span>';
  row.insertAdjacentElement("afterend", box);
  try {
    const r = await api("/api/cooccur/pairs?card=" + encodeURIComponent(name) +
      "&" + recQuery(false) + "&limit=12");
    if (!r.with_card) {
      box.innerHTML = '<span class="meta">В выборке этой карты нет.</span>';
      return;
    }
    box.innerHTML =
      '<span class="meta">В выборке карта стоит в ' + r.with_card + " колодах из " +
        r.decks + ". " + (r.ubiquitous
          ? "Она есть почти в каждой колоде выборки, так что пары говорят мало: " +
            "рядом с ней оказывается всё. "
          : "") + "Рядом с ней чаще всего:</span>" +
      '<div class="pairlist">' + r.cards.map((c) =>
        '<span class="chip" title="вместе ' + c.together + " из " + c.of +
          ", в выборке вообще " + Math.round(c.base_share * 100) + '%">' +
        esc(c.name) + ' <b>' + Math.round(c.share * 100) + "%</b>" +
        (c.lift ? '<span class="meta"> ×' + c.lift + "</span>" : "") +
        "</span>").join("") +
      "</div>";
  } catch (e) {
    box.innerHTML = '<span class="meta">' + esc(e.message) + "</span>";
  }
}
