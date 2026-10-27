"use strict";

/* Чего колоде не хватает — и чем добрать, не выходя из билдера.

   Два вопроса, которые обычно задают вслух: «мало ли у меня добора» и «а что
   вообще поставить». Первый решается счётом, второй — поиском по назначению;
   и то и другое программа уже умела, не хватало только связать.

   Правило раздела то же, что и везде: число без слагаемых — не ответ. Поэтому
   у каждой нехватки видно, какие карты посчитаны. «У тебя пять карт добора»
   звучит одинаково и когда это правда, и когда программа посчитала добором
   что-то своё, — а со списком можно не согласиться по существу.

   Предложение кладётся в колоду одной кнопкой: раздел, из которого надо
   выходить в поиск и вспоминать название, не стоит и открывать.

   Загружается после builder.js; пользуется его колодой и общими помощниками. */

let gapData = null;
let gapBusy = false;

function gapPanel() { return $("#bd-gaps"); }

async function gapOpen() {
  if (!bdDeck) return toast("Сначала откройте колоду", true);
  const panel = gapPanel();
  if (!panel.hidden && gapData && gapData.deckId === bdDeck.id) {
    bdHidePanel("#bd-gaps");
    return;
  }
  bdShowPanel("#bd-gaps");
  panel.innerHTML = '<p class="meta">смотрю…</p>';
  await gapLoad();
}

async function gapLoad() {
  if (!bdDeck || gapBusy) return;
  gapBusy = true;
  try {
    const r = await api("/api/decks/" + bdDeck.id + "/gaps");
    r.deckId = bdDeck.id;
    gapData = r;
  } catch (e) {
    gapPanel().innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
    gapBusy = false;
    return;
  }
  gapBusy = false;
  gapRender();
}

function gapFollowDeck() {
  gapData = null;
  if (!gapPanel().hidden) {
    gapPanel().innerHTML = '<p class="meta">смотрю…</p>';
    gapLoad();
  }
}

function gapMoney(card) {
  const usd = (card.prices || {}).usd;
  return usd ? ' <span class="meta">' + dollars(usd) + "</span>" : "";
}

function gapCard(card, section) {
  const where = section === "side" ? "side" : "main";
  return '<li class="gapcard">' +
    '<button type="button" class="gaplink" data-card="' + esc(card.name) + '">' +
    esc(card.name) + "</button>" +
    ' <span class="meta">' + esc(card.mana_cost || "земля") + "</span>" +
    gapMoney(card) +
    '<button type="button" class="ghost small gapadd" data-add="' +
    esc(card.name) + '" data-section="' + where + '">+ в ' +
    (where === "side" ? "сайд" : "колоду") + "</button>" +
    // Рядом, потому что желание ровно то же и возникает в ту же секунду:
    // «эту возьму -- найди её у продавцов». Без кнопки путь шёл через окно
    // карты: щёлкнуть имя, дождаться окна, нажать «В охоту: 1 шт.».
    '<button type="button" class="ghost small gaphunt" data-hunt="' +
    esc(card.name) + '" title="Искать эту карту у продавцов">+ в охоту</button>' +
    "</li>";
}

function gapCounted(block) {
  if (!block.counted || !block.counted.length) {
    // «Ни одной карты не сосчитано» читалось как «подсчёт сломался».
    // На деле это про колоду: под эту мерку в ней нет ни одной карты.
    return '<p class="meta">под эту мерку в колоде нет ни одной карты</p>';
  }
  return '<p class="meta">сюда посчитаны: ' + block.counted.map((c) =>
    '<button type="button" class="gaplink" data-card="' + esc(c.name) + '">' +
    esc(c.name) + (c.copies > 1 ? " ×" + c.copies : "") + "</button>"
  ).join(", ") + "</p>";
}

/* Цветная мана, которая нужна способности, а не розыгрышу. Манабаза её не
   видит -- она считает значки в стоимости, -- и колода с четырьмя такими
   картами при одном источнике выглядит здоровой, хотя половина плана не
   включается. */
function gapPips(a) {
  const rows = (a.hidden_pips || []).filter((h) => h.copies > 1 || h.sources < 4);
  if (!rows.length) return "";
  return '<div class="gapbox"><h4>Цветная мана для способностей</h4>' +
    '<p class="meta">Этим картам цвет нужен не для розыгрыша, а чтобы ' +
    "включиться. Манабаза такого не считает.</p><ul>" +
    rows.map((h) => {
      const thin = h.lands <= 1;
      return "<li>" + h.copies + "× <b>" + esc(h.name) + "</b>" +
        ' <span class="meta">за ' + esc(h.mana_cost || "—") +
        ", способность просит " + esc(h.needs) + "</span>" +
        '<div class="' + (thin ? "bad" : "meta") + '">источников ' + h.sources +
        ", земель " + h.lands + (thin ? " — этого мало" : "") + ": " +
        (h.from || []).map((g) => esc(g.name) + "×" + g.copies +
          (g.land ? "" : " (не земля)")).join(", ") + "</div></li>";
    }).join("") + "</ul></div>";
}

/* Сайдборд. Мерка у него другая, чем у мейна: не «сколько карт добора», а
   «есть ли хоть один ответ». Одна карта против кладбища — мало, но это не
   ноль; ноль значит, что вторую партию против такой колоды играют тем же,
   чем первую. */
function gapSide(a) {
  const s = a.sideboard;
  if (!s) return "";
  if (!s.applies) {
    return '<div class="gapbox"><h4>Сайдборд</h4><p class="meta">' +
      esc(s.why_not || "в этом формате сайдборда нет") + ".</p></div>";
  }

  const blocks = (s.blocks || []).map((b) => {
    if (b.in_side) {
      return '<li><b>' + esc(b.title) + "</b> — есть: " +
        (b.counted || []).map((c) =>
          '<button type="button" class="gaplink" data-card="' + esc(c.name) +
          '">' + esc(c.name) + (c.copies > 1 ? " ×" + c.copies : "") +
          "</button>").join(", ") + "</li>";
    }
    /* Что держат в сайде соседи по архетипу. Без этого семь вопросов
       одинаковы для всех форматов: в одном без ответа на кладбище не
       выходят из дома, в другом его не боится никто. */
    const others = b.others || {};
    const theirs = others.known
      ? (others.decks
          ? '<span class="gapothers" title="колоды вашего архетипа из ' +
            'собранной выборки">у соседей: ' + others.decks + " из " +
            others.known + "</span>"
          : '<span class="gapothers off">у соседей этого нет ни у кого — ' +
            "в этом формате такого, похоже, не боятся</span>")
      : "";
    /* Свой класс, а не класс нехваток мейна: мерка тут другая («есть ли
       ответ», а не «сколько карт»), и у блока нет строки «сосчитано», по
       которой проверяется нехватка. */
    return '<div class="gapbox gapask' +
      (others.known && !others.decks ? " gapquiet" : "") + '"><h4>' +
      esc(b.title) +
      ' <span class="meta">в сайде нет' +
      (b.in_main ? ", но в мейне " + b.in_main + " шт." : "") + "</span>" +
      theirs + "</h4>" +
      '<p class="meta">' + esc(b.why) + "</p>" +
      ((b.candidates || []).length
        ? '<ul class="gaplist">' +
          b.candidates.map((c) => gapCard(c, "side")).join("") + "</ul>"
        : '<p class="meta">в цвета колоды ничего не нашлось — у этих цветов ' +
          "такого ответа почти нет</p>") +
      "</div>";
  });

  const inside = blocks.filter((x) => x.indexOf("<li>") === 0).join("");
  const outside = blocks.filter((x) => x.indexOf("<li>") !== 0).join("");

  return '<div class="gapwrap-side"><h3>Сайдборд</h3>' +
    '<p class="meta">Занято ' + s.size + " из " + s.max + " карт" +
    (s.free ? ", свободно " + s.free : "") +
    (s.over ? " — это на " + s.over + " больше, чем можно" : "") +
    ". Без ответа: " + s.missing + " из " + (s.blocks || []).length +
    /* «Ответ есть в мейне» -- не полный сайдборд, но и не «ответа нет»:
       колода с сорока пятью картами дискарда получала «без ответа 7 из 7»,
       и это читалось как враньё. */
    (s.by_main ? ", ещё " + s.by_main + " закрыто мейном" : "") +
    ((s.others || {}).known
      ? ". Сверено с сайдбордами " + s.others.known +
        " колод вашего архетипа" +
        (s.nobody ? ", и " + s.nobody + " из этих вопросов не задаёт никто " +
          "из них" : "")
      : ". Выборка чужих колод не собрана — вопросы общие для формата") +
    ". Во второй и третьей партии матча играют именно эти карты.</p>" +
    outside +
    (inside ? "<details><summary class='meta'>На что ответ есть</summary>" +
      "<ul>" + inside + "</ul></details>" : "") +
    "</div>";
}

function gapRender() {
  const a = gapData;
  if (!a) return;
  /* «Защита 0 из 9» -- ноль из девяти чего? Счёт идёт в картах колоды, и это
     единственное, чего в подписи не было. */
  const short = (a.short || []).map((b) =>
    '<div class="gapbox gapshort"><h4>' + esc(b.title) +
    ' <span class="meta">' + b.have + " из " + b.expect +
    " карт в колоде</span></h4>" +
    '<p class="meta">' + esc(b.why) + "</p>" +
    gapCounted(b) +
    ((b.candidates || []).length
      ? '<ul class="gaplist">' + b.candidates.map(gapCard).join("") + "</ul>"
      : '<p class="meta">подходящего в цвета колоды не нашлось</p>') +
    "</div>").join("");

  const enough = (a.enough || []).map((b) =>
    "<li><b>" + esc(b.title) + "</b> " + b.have + " из " + b.expect +
    " карт" + gapCounted(b) + "</li>").join("");

  gapPanel().innerHTML =
    '<div class="gapwrap">' +
      '<p class="meta">Колода на ' + a.cards + " карт, цвета: " +
      esc(a.colors) + "." +
      ((a.stray || []).length
        ? " Вне цветов: " + a.stray.map((c) => esc(c.name) + "×" + c.copies)
            .join(", ") + "."
        : "") + "</p>" +
      gapPips(a) +
      (short || '<p class="ok">По всем меркам формата всё на месте.</p>') +
      gapSide(a) +
      (enough
        ? "<details><summary class='meta'>Чего хватает</summary><ul>" +
          enough + "</ul></details>"
        : "") +
      "<details><summary class='meta'>Как это считано</summary><ul class='anhow'>" +
      (a.basis || []).map((x) => "<li>" + esc(x) + "</li>").join("") +
      "</ul></details>" +
    "</div>";
}

gapPanel().addEventListener("click", async (ev) => {
  const add = ev.target.closest(".gapadd");
  if (add) {
    const name = add.dataset.add;
    add.disabled = true;
    try {
      // Через общий post(): он ставит Content-Type, без которого сервер не
      // разбирает тело и отвечает 422. Первая версия этой кнопки звала api()
      // напрямую, заголовок не ставила -- и не работала ни разу, хотя панель
      // на снимке выглядела прекрасно. Снимок кнопку не нажимает.
      const where = add.dataset.section === "side" ? "side" : "main";
      await post("/api/decks/" + bdDeck.id + "/cards",
                 { cards: [{ name: name, quantity: 1, section: where }] });
      toast(name + (where === "side" ? " в сайде" : " в колоде"));
      // Колода перечитывается тем же путём, что и после любой правки: иначе
      // на экране останется список без только что добавленной карты.
      if (typeof bdOpen === "function") await bdOpen(bdDeck.id);
      gapFollowDeck();
    } catch (e) {
      toast(e.message, true);
      add.disabled = false;
    }
    return;
  }
  const hunt = ev.target.closest(".gaphunt");
  if (hunt && typeof addToHunt === "function") {
    addToHunt(hunt.dataset.hunt, 1);
    toast("В охоту: " + hunt.dataset.hunt);
    return;
  }
  const open = ev.target.closest(".gaplink");
  if (open && typeof openCardByName === "function") {
    openCardByName(open.dataset.card);
  }
});
