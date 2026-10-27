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
    ? '<span class="rub"><b>' + Number(x.rub.min).toLocaleString("ru") + " ₽</b>" +
      wasPrice(x.rub) + "</span>"
    : '<span class="rub none" title="цена с topdeck ещё не запрашивалась">—</span>';

  const marks = [];
  if (x.in_deck > 0) marks.push('<span class="chip ok">в колоде ' + x.in_deck + "</span>");
  if (x.owned > 0) marks.push('<span class="chip ok">есть ' + x.owned + "</span>");
  if (x.staple) marks.push('<span class="chip">стейпл</span>');
  if (x.off_identity) marks.push('<span class="chip warn">вне идентичности</span>');
  /* Чужие списки пишутся не вчера, и в них попадается то, что с тех пор
     забанили. Карта не прячется -- колоду могут играть и на кухне, -- но
     молча предлагать забаненное нельзя. */
  if (x.illegal_label) {
    marks.push('<span class="chip mixed">' + esc(x.illegal_label) + "</span>");
  }
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
      '<span class="usd">' + (x.usd != null ? dollars(x.usd) : "") + "</span>" +
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

/* Предложка кеширует ответ (recData), форму колоды (recShapeData) и выборку
   реальных колод (coData) -- всё это про одну конкретную колоду. При смене
   колоды кеш становится не «старым», а чужим: recOpen() показывал бы его без
   единого слова о том, что он не отсюда. */
function recFollowDeck() {
  recData = null;
  recShapeData = null;
  coData = null;
  coState = null;
  bdAdviceText = "";
  bdAdviceFor = null;
  if (!$("#rec-overlay").hidden) recOpen();
}

function recOpen() {
  $("#rec-overlay").hidden = false;
  // The deck knows its commander; the field is only for looking at others.
  const own = recCommanderOfDeck();
  if (own) $("#rec-commander").value = own;

  /* Открываемся на той вкладке, которая отвечает на вопрос «что добавить в
     эту колоду» без всяких условий. Командирская -- первой только для
     командирской колоды: там она и правда лучший ответ. */
  const commanderDeck = !!own ||
    ((typeof bdDeck !== "undefined" && bdDeck &&
      (bdDeck.format || "").toLowerCase() === "commander"));

  /* У 60-карточной колоды лучший ответ -- «Под ваш состав», когда выборка
     по её формату уже собрана: там настоящие списки, а не темы по тегам.
     Пока выборки нет, показывать нечего, и первой идёт «По смыслу колоды».
     Состояние выборки лежит на диске -- вопрос к серверу без единого
     запроса наружу. */
  if (!commanderDeck) {
    recTab("ideas");
    coStatus().then(() => {
      if (coState && coState.decks) recTab("cooccur");
    }).catch(() => {});
    return;                          // вкладку наполнит ideas.js
  }
  recTab("cards");

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
  /* Строки блоков «по сколько копий» и «что в сайде» устроены проще, чем
     строка предложки: в них нет картинки и отметки, зато есть кнопка с
     нужным количеством -- добрать до обычного числа копий. */
  const copies = ev.target.closest("[data-copies]");
  if (copies) {
    addToHunt(copies.dataset.copies, Number(copies.dataset.qty) || 1);
    toast("В охоту: " + copies.dataset.copies + " ×" + copies.dataset.qty);
    return;
  }
  const side = ev.target.closest("[data-hunt-card]");
  if (side) {
    addToHunt(side.dataset.huntCard, Number(side.dataset.qty) || 1);
    toast("В охоту: " + side.dataset.huntCard + " ×" + side.dataset.qty);
    return;
  }
  const plain = ev.target.closest("[data-card]");
  if (plain && typeof openCardByName === "function") {
    openCardByName(plain.dataset.card);
    return;
  }

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
  $("#rec-pane-ideas").hidden = name !== "ideas";
  $("#rec-pane-cards").hidden = name !== "cards";
  $("#rec-pane-shape").hidden = name !== "shape";
  $("#rec-pane-themes").hidden = name !== "themes";
  $("#rec-pane-cooccur").hidden = name !== "cooccur";

  // Поле командира нужно трём вкладкам из пяти -- тем, что спрашивают
  // EDHREC. На «по смыслу колоды» оно только мешает: там командир не при чём.
  const row = $("#rec-commander-row");
  if (row) row.hidden = name === "ideas" || name === "themes";

  if (name === "ideas") {
    // Живёт в ideas.js, который грузится следом за этим файлом.
    if (typeof ideasOpen === "function") ideasOpen();
    return;
  }

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

/* Почему вкладка просит командира. Один текст на три вкладки: он объясняет
   не «что нажать», а почему без командира ответа не будет -- и куда идти
   тому, кто собирает модерн. Молчаливая пустая вкладка на этот вопрос не
   отвечает вовсе. */
function recWhyCommander() {
  return '<p class="meta">Эти три вкладки спрашивают EDHREC, а он знает только командирские колоды: без командира ему нечего ответить. Для колоды любого другого формата есть вкладка «По смыслу колоды» — она читает, чем колода занята, и предлагает карты сама.</p>';
}

function recRenderThemes() {
  const data = recShapeData;
  const box = $("#rec-pane-themes");
  if (!data) {
    box.innerHTML =
      '<p class="meta">Темы и комбо берутся со страницы командира на ' +
      "EDHREC — пока командир не назван, показывать нечего.</p>" +
      recWhyCommander();
    return;
  }
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
    // Обе вкладки питаются одним ответом EDHREC, поэтому и молчат обе. Пустая
    // вкладка не говорит человеку ничего -- особенно тому, кто пришёл с
    // колодой модерна и ищет, куда нажать.
    const why =
      '<p class="meta">Не выбран командир — вписать его можно в поле выше.</p>'
      + recWhyCommander();
    $("#rec-pane-shape").innerHTML = why;
    $("#rec-pane-themes").innerHTML = why;
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

/* Опознавательные карты: по ним выборка сужается с «весь модерн» до «колоды
   вашего архетипа». Поиск Archidekt понимает повторённый фильтр по карте как
   И, так что две карты из вашего списка дают полсотни колод из тысячи — и это
   те самые полсотни. Без них вкладка сравнивала 8-Rack с эльфами и бёрном. */
let coSign = null;       // кандидаты: что предложить человеку отметить
let coPicked = [];       // что отмечено сейчас
let coPickedAuto = false; // отметки предложены программой, человек их не трогал

function coQuery() {
  const parts = [recQuery(false)];
  /* Пустой `cards=` -- это «по всему формату», отсутствие параметра --
     «как выбрано для этой колоды раньше». Пока картинка выбора на экране,
     говорим явно, иначе числа разойдутся с отметками. */
  if (coSign && coSign.supported) {
    parts.push("cards=" + encodeURIComponent(coPicked.join("|")));
  }
  return parts.filter(Boolean).join("&");
}

async function coSignLoad() {
  const deckId = (typeof bdDeck !== "undefined" && bdDeck) ? bdDeck.id : "";
  const typed = $("#rec-commander") ? $("#rec-commander").value.trim() : "";
  if (!deckId || typed) {
    coSign = null;
    coPicked = [];
    return;
  }
  try {
    coSign = await api("/api/cooccur/signature?deck_id=" +
      encodeURIComponent(deckId));
    coPicked = (coSign.saved || []).slice(0, coSign.max || 3);
    /* Ничего не выбрано -- предлагаем две карты сами. Пустой экран с
       вопросом «а чем вы узнаёте свою колоду» человек закрывает, и выборка
       опять собирается по всему формату, то есть по чужим архетипам.
       Предложенное не записывается, пока он не нажмёт «собрать»: это
       подсказка, а не решение за него. */
    coPickedAuto = false;
    if (!coPicked.length && (coSign.cards || []).length) {
      coPicked = coSign.cards.slice(0, 2).map((c) => c.name);
      coPickedAuto = true;
    }
  } catch (e) {
    coSign = null;
    coPicked = [];
  }
}

function coSignRow() {
  if (!coSign) return "";
  if (!coSign.supported) {
    return '<div class="cochips"><span class="meta">Для формата «' +
      esc(coSign.format_title || "") + "» Archidekt не отдаёт колоды по " +
      "формату, поэтому выборки по нему нет.</span></div>";
  }
  const chips = (coSign.cards || []).map((c) =>
    '<button class="chip' + (coPicked.indexOf(c.name) >= 0 ? " on" : "") +
      '" data-sign="' + esc(c.name) +
      '" title="в колоде ' + c.qty + " шт., печаталась " + c.reprints +
      ' раз">' + esc(c.shown) +
      '<span class="meta"> ×' + c.qty + "</span></button>").join("");
  return '<div class="cochips">' +
    (coPickedAuto
      ? '<p class="meta">Две карты отмечены по догадке — самые частые в ' +
        "вашем списке из тех, что реже печатали. Узнаёте колоду по другим — " +
        "переставьте отметки.</p>"
      : "") +
    '<span class="meta">Какой архетип искать: отметьте до ' +
      (coSign.max || 3) + " карт, по которым вашу колоду узнают. Берутся " +
      "колоды, где стоят <b>все</b> отмеченные. Без отметок — весь формат " +
      "целиком (" + esc(coSign.format_title || "") + "), все архетипы " +
      "вперемешку." + (coPicked.length
        ? ' <button class="linkish" data-sign-clear="1">снять отметки</button>'
        : "") + "</span>" +
    '<div class="chiprow">' + chips + "</div></div>";
}

function coHead() {
  const box = $("#rec-sample");
  if (!box) return;
  const st = coState || {};
  const have = st.decks || 0;
  const target = Number($("#rec-target") ? $("#rec-target").value : 150);

  /* По чему собрана выборка. У командирской колоды это командир, у
     60-карточной -- формат или архетип: «что вообще играют в модерне» и
     «что играют в колодах с этими картами» -- разные вопросы. Без подписи
     человек видит числа и не знает, с чем его колоду сравнили. */
  const about = st.kind === "cards"
    ? '<span class="meta">по картам: <b>' +
      esc(st.title || st.commander || "") + "</b></span>"
    : st.kind === "format"
    ? '<span class="meta">по формату: <b>' + esc(st.title || st.commander || "") +
      "</b></span>"
    : (st.title || st.commander
       ? '<span class="meta">по командиру: <b>' +
         esc(st.title || st.commander) + "</b></span>"
       : "");

  box.innerHTML = coSignRow() + about +
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
      ? '<button class="ghost tiny" id="rec-sample-calc">Пересчитать</button>' +
        '<button class="ghost tiny" id="rec-sample-refresh" ' +
        'title="Выбросить устаревшие колоды и дочитать поиск заново">' +
        "Обновить</button>"
      : "");
}

function coAge(days) {
  if (days === null || days === undefined) return "";
  if (days < 60) return days + " дн.";
  if (days < 400) return Math.round(days / 30) + " мес.";
  return (Math.round(days / 36.5) / 10).toFixed(1).replace(".", ",") + " года";
}

function coNote() {
  const st = coState || {};
  const parts = [
    "Колоды берутся с <b>Archidekt</b>, по 1.5 с на запрос, и складываются в " +
    "кеш на диске (<code>data/archidekt/</code>) — повторный сбор докачивает " +
    "только новые.",
  ];

  /* Возраст списков. Поиск сортирует по просмотрам, а самые
     просматриваемые модерн-колоды — это списки позапрошлого сезона: по ним
     числа считаются так же бодро, стоят они другого. Поэтому возраст
     говорится прямо, а совсем старое не качается вовсе. */
  const fresh = st.fresh || {};
  if (fresh.known) {
    parts.push("Списки не самые свежие: половине из них больше " +
      coAge(fresh.median_days) + ", самому старому " +
      coAge(fresh.oldest_days) + "; за последний год обновляли " +
      fresh.fresh_year + " из " + fresh.known + ".");
  }

  const skip = st.skipped || {};
  const why = [];
  if (skip.old) why.push(skip.old + " давно заброшенных");
  if (skip.small) why.push(skip.small + " огрызков");
  if (skip.private) why.push(skip.private + " закрытых");
  if (why.length) {
    parts.push("Не скачивалось вовсе: " + why.join(", ") +
      " — это видно прямо в выдаче поиска, и запроса они не стоят.");
  }
  if (st.failed) {
    parts.push("Скачано и отброшено: " + st.failed +
      " (закрытые, удалённые или недособранные).");
  }
  if (st.with_side) {
    parts.push("Сайдборд известен у " + st.with_side + " колод.");
  }
  if (st.exhausted) {
    parts.push("Больше колод по этому запросу Archidekt не отдаёт — выборка " +
      "собрана целиком.");
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
      "уже есть.</p>" + coCopies() + coSide() + coNeighbours();
    return;
  }

  box.innerHTML = coNote() + head +
    '<div class="recgroup"><h4>' + esc(coData.sections[0].title) +
      ' <span class="meta">' + cards.length + "</span></h4>" +
      recSort(recVisible(cards)).map(recRow).join("") +
    "</div>" + coCopies() + coSide() + coNeighbours();
}

/* На чём стоят проценты. Список колод-соседей со ссылками: без него «71%
   соседей» нечем проверить, а проверять такие числа человек имеет право. */
function coNeighbours() {
  const rows = (coData && coData.neighbours) || [];
  if (!rows.length) return "";
  return '<details class="conear"><summary>На чём это посчитано: ' +
    rows.length + " ближайших колод</summary>" +
    rows.map((d) =>
      '<div class="corow"><a href="' + esc(d.url) + '" target="_blank" ' +
        'rel="noreferrer">' + esc(d.name || ("колода " + d.id)) + "</a>" +
      '<span class="meta">общих карт: ' + d.shared + " из " + d.cards +
        "</span>" +
      '<span class="meta">' + (d.updated ? "обновлена " + esc(d.updated)
                                         : "дата неизвестна") + "</span>" +
      "</div>").join("") + "</details>";
}

/* По сколько копий. Вопрос не «что добавить», а «чего мало»: карта в одном
   экземпляре попадается примерно в трети игр, и если у соседей она стоит по
   четыре — это не мелочь, а другой расчёт колоды. В командирской выборке
   вопроса нет, там всё по одной, и блок молчит. */
function coCopies() {
  const data = coData && coData.copies;
  if (!data || data.flat || !(data.cards || []).length) return "";
  const rows = data.cards.map((c) => {
    const more = c.diff > 0;
    return '<div class="corow' + (more ? " up" : " down") + '">' +
      '<b class="linkish" data-card="' + esc(c.name) + '">' + esc(c.name) +
        "</b>" +
      '<span class="meta">у вас ' + c.mine + " → обычно " + c.usual +
        " (" + c.decks + " из " + c.of + " соседей)</span>" +
      (more
        ? '<button class="ghost tiny" data-copies="' + esc(c.name) +
          '" data-qty="' + c.diff + '">добрать ' + c.diff + "</button>"
        : '<span class="meta">лишних ' + (-c.diff) + "</span>") +
      "</div>";
  }).join("");
  return '<div class="recgroup"><h4>По сколько копий ' +
    '<span class="meta">' + data.cards.length + "</span></h4>" +
    '<p class="meta">Медиана по тем соседям, кто карту играет: считать её ' +
    "по всей округе значит получить ноль на любой карте, которой нет в " +
    "каждой второй колоде.</p>" + rows + "</div>";
}

/* Сайдборд. Пятнадцать карт, которых не было ни в подсказках, ни в «чего не
   хватает», ни в покупках: программа смотрела только в мейн. */
function coSide() {
  const data = coData && coData.side;
  if (!data) return "";
  if (!data.known) {
    return '<div class="recgroup"><h4>Сайдборд</h4><p class="meta">' +
      "Ни у одной похожей колоды сайдборд не скачан: старые выборки его не " +
      "сохраняли. Соберите выборку заново — у новых колод он есть.</p></div>";
  }
  const rows = (data.cards || []).map((c) =>
    '<div class="corow' + (c.mine ? " have" : "") + '">' +
      '<b class="linkish" data-card="' + esc(c.name) + '">' + esc(c.name) +
        "</b>" +
      '<span class="meta">' + Math.round(c.share * 100) + "% сайдов (" +
        c.decks + " из " + c.of + "), обычно по " + c.usual + "</span>" +
      (c.mine
        ? '<span class="meta">уже в вашем сайде</span>'
        : c.in_main
        ? '<span class="meta">у вас в мейне</span>'
        : '<button class="ghost tiny" data-hunt-card="' + esc(c.name) +
          '" data-qty="' + c.usual + '">в охоту</button>') +
    "</div>").join("");
  return '<div class="recgroup"><h4>Что держат в сайде ' +
    '<span class="meta">' + (data.cards || []).length + "</span></h4>" +
    '<p class="meta">По ' + data.known + " соседям, у кого сайд известен. " +
    "У вас в сайде " + data.yours + " назв.</p>" + rows + "</div>";
}

async function coStatus() {
  const target = $("#rec-target") ? Number($("#rec-target").value) : 150;
  if (!coSign) await coSignLoad();
  coState = await api("/api/cooccur/status?" + coQuery() +
    "&target=" + target);
  coHead();
}

async function coLoad() {
  const box = $("#rec-cooccur-body");
  box.innerHTML = '<span class="spinner">считаю по выборке…</span>';
  try {
    coData = await api("/api/cooccur?" + coQuery() + "&near=30&limit=60");
    coState = Object.assign({}, coState, coData.sample);
    coHead();
    coRender();
  } catch (e) {
    box.innerHTML = '<p class="meta">' + esc(e.message) + "</p>";
  }
}

/* Обновить выборку. Сама по себе наружу не ходит: выбрасывает устаревшие
   колоды и отматывает поиск на первую страницу, а качать или нет -- решает
   человек. Поэтому сперва говорим, что выброшено, и только потом, если он
   согласен, идём за свежими. */
async function coRefresh() {
  if (coBusy) return;
  let r;
  try {
    r = await post("/api/cooccur/refresh", {
      commander: $("#rec-commander").value.trim(),
      deck_id: (typeof bdDeck !== "undefined" && bdDeck) ? bdDeck.id : "",
      cards: (coSign && coSign.supported) ? coPicked : null,
    });
  } catch (e) {
    return toast(e.message, true);
  }
  coState = Object.assign({}, coState, r);
  coData = null;
  coHead();
  const said = r.dropped
    ? "Выброшено устаревших: " + r.dropped
    : "Устаревших колод не нашлось";
  const rest = r.undated
    ? " · у " + r.undated + " колод дата неизвестна — это записи старых " +
      "сборов, они остались"
    : "";
  toast(said + rest + ". Качаю свежие…");
  await coCollect();
}

/* One chunk per request, in a loop we can stop. The traffic ends within one
   chunk of the user pressing «Остановить» -- never mid-request, because a
   half-fetched deck would just have to be fetched again. */
async function coCollect() {
  if (coBusy) return;
  // Отметки, предложенные программой, становятся выбором колоды в тот
  // момент, когда по ним пошли качать: иначе добор у продавцов и покупки
  // считали бы по другой выборке, чем эта вкладка.
  if (coPickedAuto) {
    coPickedAuto = false;
    await coSave();
  }
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
        cards: (coSign && coSign.supported) ? coPicked : null,
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

/* Отметить карту архетипа. Выбор сохраняется сразу: по нему считают не
   только эта вкладка, но и добор у продавцов, и «что купить первым», и
   держать его в голове у одной панели было бы враньём остальным. */
async function coPick(name) {
  const max = (coSign && coSign.max) || 3;
  const at = coPicked.indexOf(name);
  if (coPickedAuto) {
    // Первое же нажатие по предложенному -- это его решение, и дальше
    // отметки живут как его, а не как подсказка.
    coPickedAuto = false;
  }
  if (at >= 0) coPicked.splice(at, 1);
  else if (coPicked.length >= max) {
    return toast("Больше " + max + " карт — это уже не архетип, а ваш " +
      "собственный список: таких колод найдётся две", true);
  } else coPicked.push(name);
  await coSave();
}

async function coSave() {
  const deckId = (typeof bdDeck !== "undefined" && bdDeck) ? bdDeck.id : "";
  if (!deckId) return;
  try {
    await post("/api/cooccur/cards", { deck_id: deckId, cards: coPicked });
  } catch (e) {
    toast(e.message, true);
  }
  coData = null;
  await coStatus();
  if (coState && coState.decks) await coLoad();
  else coRender();
}

$("#rec-sample").addEventListener("click", (ev) => {
  const chip = ev.target.closest("[data-sign]");
  if (chip) return coPick(chip.dataset.sign);
  if (ev.target.closest("[data-sign-clear]")) {
    coPicked = [];
    return coSave();
  }
  if (ev.target.id === "rec-sample-go") coCollect();
  else if (ev.target.id === "rec-sample-refresh") coRefresh();
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
