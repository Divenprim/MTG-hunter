"use strict";

/* Разбор колоды: сила, соль, цена, командирский бракет.

   Главное правило этого раздела -- ни одного числа без слагаемых. Балл,
   который нельзя развернуть, нельзя и оспорить: он выглядит одинаково
   убедительно и когда посчитан, и когда выдуман. Поэтому каждая метрика здесь
   раскрывается в строки «что и на сколько», а строки -- в карты, которые это
   набрали.

   Веса -- суждение, а не измерение. Данных о том, какая колода «сильнее», у
   программы нет и взяться им неоткуда, поэтому шкала объявлена прямым
   текстом: пятьдесят -- как у обычной колоды формата, сто -- вдвое
   перекрыто. Это не процентиль и не место среди колод.

   Соль названа тем, чем является: это про то, насколько колода портит игру
   другим, по нашим меркам, а не про силу. Поэтому рядом с ней всегда видно,
   какие карты её набрали, -- иначе получается приговор чужому вкусу без
   доказательств.

   Загружается после builder.js; пользуется его колодой и общими помощниками. */

let anData = null;
let anBusy = false;
let anOpenParts = {};        // какие метрики человек развернул

function anPanel() { return $("#bd-analysis"); }

async function anOpen() {
  if (!bdDeck) return toast("Сначала откройте колоду", true);
  const panel = anPanel();
  if (!panel.hidden && anData && anData.deckId === bdDeck.id) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  panel.innerHTML = '<p class="meta">считаю…</p>';
  await anLoad();
}

async function anLoad() {
  if (!bdDeck || anBusy) return;
  anBusy = true;
  try {
    const r = await api("/api/decks/" + bdDeck.id + "/analysis");
    r.deckId = bdDeck.id;
    anData = r;
  } catch (e) {
    anPanel().innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
    anBusy = false;
    return;
  }
  anBusy = false;
  anRender();
}

/* Колода сменилась или изменился состав -- разбор пересчитывается: он весь
   про то, что в колоде лежит. */
function anFollowDeck() {
  anData = null;
  if (!anPanel().hidden) {
    anPanel().innerHTML = '<p class="meta">считаю…</p>';
    anLoad();
  }
}

function anCards(cards) {
  if (!cards || !cards.length) return "";
  return ' <span class="anwho">' + cards.map((c) =>
    '<button type="button" class="anlink" data-card="' + esc(c.name) + '">' +
    esc(c.name) + (c.copies > 1 ? " ×" + c.copies : "") + "</button>"
  ).join(", ") + "</span>";
}

/* Один балл: полоса, число и слагаемые. Слагаемые всегда сходятся с числом --
   это проверяется тестами, и именно поэтому им можно верить. */
function anScore(key, block, extra) {
  const open = !!anOpenParts[key];
  const parts = (block.parts || []).map((p) =>
    '<li class="' + (p.adds < 0 ? "anminus" : "") + '">' +
      '<span class="anwhat">' + esc(p.what) + "</span>" +
      '<span class="anadds">' + (p.adds > 0 ? "+" : "") + p.adds + "</span>" +
      anCards(p.cards) +
    "</li>").join("");
  return (
    '<div class="anscore" data-score="' + esc(key) + '">' +
      '<div class="anhead">' +
        '<span class="antitle">' + esc(block.title) + "</span>" +
        '<span class="anvalue">' + block.value + "</span>" +
      "</div>" +
      '<div class="anbar"><i style="width:' + Math.max(0, Math.min(100, block.value)) + '%"></i></div>' +
      '<p class="meta anbasis">' + esc(block.basis || "") + "</p>" +
      (extra || "") +
      (parts
        ? '<button type="button" class="ghost small antoggle" data-parts="' + esc(key) + '">' +
            (open ? "свернуть слагаемые" : "из чего сложено") + "</button>" +
          '<ul class="anparts"' + (open ? "" : " hidden") + ">" + parts + "</ul>"
        : '<p class="meta">слагаемых нет: ничего из этого в колоде не нашлось</p>') +
    "</div>");
}

function anMoney(a) {
  const p = a.price || {};
  const sd = a.salt_per_dollar || {};
  const cover = Math.round((p.coverage || 0) * 100);
  let line = "$" + (p.usd || 0).toFixed(2) +
    ' <span class="meta">(' + esc(p.basis || "") + "; цена известна у " +
    cover + "% карт)</span>";
  if (sd.known) {
    line += '<div class="anperdollar">Соли на $100: <b>' + sd.per_100 + "</b>" +
      ' <span class="meta">— сколько раздражающей игры покупается за сотню</span></div>';
  } else if (sd.why) {
    line += '<div class="meta">Соль на доллар не считаю: ' + esc(sd.why) + "</div>";
  }
  const left = (p.unpriced || []).length
    ? '<p class="meta">без цены: ' + (p.unpriced || []).map((u) =>
        esc(u.name) + (u.copies > 1 ? " ×" + u.copies : "")).join(", ") + "</p>"
    : "";
  return '<div class="anmoney"><h4>Цена колоды</h4><div>' + line + "</div>" + left + "</div>";
}

function anBracket(a) {
  const b = a.bracket;
  if (!b) {
    return '<div class="anbracket"><h4>Командирский бракет</h4>' +
      '<p class="meta">Не для этого формата. Бракеты есть только в Commander, ' +
      'и выдавать их в другие форматы значило бы выдумывать.</p></div>';
  }
  const levels = Object.keys(b.levels).map((lv) => {
    const d = b.levels[lv];
    const why = (d.violations || []).map((v) =>
      "<li>" + esc(v.what) + anCards(v.cards) + "</li>").join("");
    return '<li class="' + (d.fits ? "anfits" : "anno") + '">' +
      "<b>" + esc(d.title) + "</b> " +
      (d.fits ? "— подходит" : "— не подходит") +
      (why ? "<ul>" + why + "</ul>" : "") + "</li>";
  }).join("");
  const gc = (b.game_changers || []).length
    ? "<p>Game Changers в колоде: " + anCards(b.game_changers) + "</p>"
    : '<p class="meta">Game Changers нет</p>';
  const warn = (b.warnings || []).map((w) =>
    '<li class="meta">' + esc(w) + "</li>").join("");
  return '<div class="anbracket"><h4>Командирский бракет: ' + esc(b.title) + "</h4>" +
    gc + '<ul class="anlevels">' + levels + "</ul>" +
    (warn ? "<ul>" + warn + "</ul>" : "") +
    '<p class="meta anrules">Правила не наши: ' + esc(b.rules.game_changers) +
    "; пометки комбо — " + esc(b.rules.combo_brackets) + ".</p></div>";
}

function anCombos(a) {
  const c = a.combos || {};
  if (!c.known) {
    return '<div class="ancombos"><h4>Комбо</h4><p class="meta">' +
      esc(c.why || "не знаю") + "</p></div>";
  }
  if (!c.count) {
    return '<div class="ancombos"><h4>Комбо</h4><p class="meta">Собранных нет' +
      (c.near ? ", но есть " + c.near + " в одной-двух картах" : "") + ".</p></div>";
  }
  const rows = (c.complete || []).map((x) =>
    "<li>" + anCards((x.cards || []).map((n) => ({ name: n, copies: 1 }))) +
    ' <span class="meta">' + esc(x.means) + "</span></li>").join("");
  return '<div class="ancombos"><h4>Собранные комбо: ' + c.count + "</h4>" +
    "<ul>" + rows + "</ul>" +
    (c.near ? '<p class="meta">ещё ' + c.near + " в одной-двух картах</p>" : "") +
    "</div>";
}

function anImpact(a) {
  const side = (key, title) => {
    const rows = (a.impact[key] || []).map((c) =>
      "<li>" + '<button type="button" class="anlink" data-card="' + esc(c.name) + '">' +
      esc(c.name) + "</button>" +
      '<span class="anadds">+' + c.adds + "</span>" +
      '<span class="meta"> через ' + esc((c.through || []).join(", ")) + "</span></li>").join("");
    return "<div><h4>" + title + "</h4>" +
      (rows ? '<ul class="anpull">' + rows + "</ul>"
            : '<p class="meta">ничего заметного</p>') + "</div>";
  };
  return '<div class="animpact">' +
    side("power", "Что держит силу") + side("salt", "Что набирает соль") +
    "</div>";
}

function anRender() {
  const a = anData;
  if (!a) return;
  const metrics = Object.keys(a.metrics).map((key) =>
    anScore("m:" + key, a.metrics[key], "")).join("");
  anPanel().innerHTML =
    '<div class="anwrap">' +
      '<div class="antop">' +
        anScore("power", a.power, "") +
        anScore("salt", a.salt, "") +
        anScore("confidence", a.confidence, "") +
      "</div>" +
      anMoney(a) +
      anBracket(a) +
      anCombos(a) +
      anImpact(a) +
      "<details class='anmetrics'><summary>Все метрики по отдельности</summary>" +
      '<div class="angrid">' + metrics + "</div></details>" +
      '<p class="meta anfoot">Веса — наше суждение, а не измерение: они ' +
      'написаны руками и лежат в коде. Шкала: 50 — как у обычной колоды ' +
      'формата, 100 — вдвое перекрыто. Это не процентиль и не место среди ' +
      'колод: таких данных у программы нет.</p>' +
    "</div>";
}

anPanel().addEventListener("click", (ev) => {
  const toggle = ev.target.closest(".antoggle");
  if (toggle) {
    const key = toggle.dataset.parts;
    const box = toggle.closest(".anscore");
    const list = box && box.querySelector(".anparts");
    if (!list) return;
    anOpenParts[key] = list.hidden;
    list.hidden = !list.hidden;
    toggle.textContent = list.hidden ? "из чего сложено" : "свернуть слагаемые";
    return;
  }
  const card = ev.target.closest(".anlink");
  if (card && typeof openCardByName === "function") {
    openCardByName(card.dataset.card);
  }
});
