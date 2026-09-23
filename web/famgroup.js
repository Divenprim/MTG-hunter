"use strict";

/* Группа исполнений целиком: спеки рядом, руки рядом, покупки на всех.

   Матрица отвечает на вопрос «какие карты общие». Но у группы есть ещё три
   вопроса, и матрица на них не отвечает:

     1. чем эти колоды отличаются как колоды -- земли, кривая, средняя мана.
        Один и тот же замысел в пионере и в модерне расходится не списком, а
        формой, и увидеть это можно только рядом;

     2. как они стартуют. Сравнивать руки по очереди бессмысленно: разница
        между двадцатью четырьмя землями и двадцатью шестью видна, когда обе
        руки лежат друг под другом и сданы одним нажатием;

     3. сколько стоит их завести. И тут два разных ответа: «пусть лежат
        собранными одновременно» -- это одно, «играю по очереди, пересобираю
        между играми» -- совсем другое, потому что общие карты кочуют.

   Загружается после family.js; пользуется его состоянием (famData) и общими
   помощниками. */

let fgView = null;        // "specs" | "hands" | "buy" | null
let fgSpecs = null;
let fgSim = null;
let fgHands = null;
let fgBuy = null;
let fgMode = store.get("fam.buymode", "byturn");
let fgBasics = false;     // базовые земли в списке покупок: лес есть у всех
let fgHandSize = 7;
let fgBusy = false;

function fgBox() { return $("#fam-group"); }

/* Чью группу смотрим. Семейство -- по имени, разовое сравнение -- по списку
   колод: на сервере это один и тот же запрос. */
function fgWhat(extra) {
  const body = Object.assign({}, extra || {});
  if (typeof famName !== "undefined" && famName) body.family = famName;
  else body.deck_ids = ((famData || {}).variants || []).map((v) => v.id);
  return body;
}

function fgReady() {
  return !!(famData && (famData.variants || []).length);
}

async function fgAsk(path, extra) {
  return post("/api/family/" + path, fgWhat(extra));
}

function fgShow(view) {
  fgView = fgView === view ? null : view;
  $$("#fam-groupbar [data-group]").forEach((b) =>
    b.classList.toggle("on", b.dataset.group === fgView));
  fgBox().hidden = !fgView;
  if (!fgView) return;
  fgRender();
  fgLoad();
}

async function fgLoad() {
  if (fgBusy || !fgReady()) return;
  fgBusy = true;
  try {
    if (fgView === "specs" && !fgSpecs) fgSpecs = await fgAsk("specs");
    if (fgView === "hands" && !fgHands) {
      fgHands = await fgAsk("hands", { hand_size: fgHandSize });
    }
    if (fgView === "buy" && !fgBuy) {
      fgBuy = await fgAsk("shopping", { mode: fgMode, basics: fgBasics });
    }
  } catch (e) {
    toast(e.message, true);
  } finally {
    fgBusy = false;
    fgRender();
  }
}

/* Всё пересчитывается заново, когда группа сменилась или колоды правили: цифры
   про другую группу выглядят точно так же, как про эту. */
function fgReset() {
  fgSpecs = null;
  fgSim = null;
  fgHands = null;
  fgBuy = null;
  if (fgView) { fgRender(); fgLoad(); }
}

/* ------------------------------------------------------------- спеки ----- */

function fgBar(curve, buckets, max) {
  return '<span class="fgcurve">' + buckets.map((b) => {
    const n = curve[b] || 0;
    return '<i style="height:' + Math.round((n / Math.max(1, max)) * 100) +
      '%" title="' + b + (b >= 7 ? "+" : "") + " мана: " + n + ' шт."></i>';
  }).join("") + "</span>";
}

function fgEdge(value, span, lowerIsBetter) {
  // Крайнее значение в столбце: не «хорошо/плохо», а «здесь больше всех».
  if (!span || span.min === span.max || value == null) return "";
  if (value === span.max) return lowerIsBetter ? " low" : " high";
  if (value === span.min) return lowerIsBetter ? " high" : " low";
  return "";
}

function fgSpecsHtml() {
  if (!fgSpecs) return '<p class="meta">считаю…</p>';
  const rows = fgSpecs.decks || [];
  const span = fgSpecs.span || {};
  const buckets = fgSpecs.buckets || [0, 1, 2, 3, 4, 5, 6, 7];
  const max = Math.max(1, ...rows.map((r) =>
    Math.max(0, ...Object.values(r.curve || {}))));
  const sim = {};
  ((fgSim || {}).runs || []).forEach((r) => { sim[r.deck_id] = r.goldfish; });

  return (
    '<table class="fgtable"><thead><tr>' +
      "<th>исполнение</th><th>формат</th><th>карт</th><th>земель</th>" +
      "<th>ср. мана</th><th>кривая</th><th>цена</th><th>не хватает</th>" +
      (fgSim ? "<th>играбельных рук</th><th>земель в руке</th><th>3 земли к ходу</th>" : "") +
    "</tr></thead><tbody>" +
    rows.map((r) => {
      const g = sim[r.id];
      return "<tr>" +
        '<td><button type="button" class="linkish" data-fgopen="' + esc(r.id) +
          '">' + esc(r.name) + "</button>" +
          (r.assembled ? ' <span class="chip ok">собрана</span>' : "") + "</td>" +
        "<td>" + esc(r.format || "") + "</td>" +
        "<td>" + r.copies + (r.side ? ' <span class="meta">+' + r.side + " сб</span>" : "") + "</td>" +
        '<td class="num' + fgEdge(r.lands, span.lands) + '">' + r.lands +
          ' <span class="meta">' + Math.round(r.land_share * 100) + "%</span></td>" +
        '<td class="num' + fgEdge(r.avg_mv, span.avg_mv, true) + '">' +
          (r.avg_mv == null ? "—" : r.avg_mv) + "</td>" +
        "<td>" + fgBar(r.curve, buckets, max) + "</td>" +
        '<td class="num">' + rub(r.total_rub) + "</td>" +
        '<td class="num' + fgEdge(r.missing_copies, span.missing_copies, true) +
          '">' + r.missing_copies + " шт." +
          (r.missing_rub ? ' <span class="meta">' + rub(r.missing_rub) + "</span>" : "") +
        "</td>" +
        (fgSim
          ? (g
            ? '<td class="num">' + Math.round(g.keepable_pct) + "%</td>" +
              '<td class="num">' + g.avg_lands_in_hand + "</td>" +
              '<td class="num">' + (g.reach_3_lands
                ? Math.round(g.reach_3_lands.pct) + "% · ход " +
                  g.reach_3_lands.avg_turn
                : "—") + "</td>"
            : '<td colspan="3" class="meta">не считается</td>')
          : "") +
      "</tr>";
    }).join("") +
    "</tbody></table>" +
    '<div class="row tight">' +
      '<button type="button" class="ghost" data-fgsim="1">' +
        (fgSim ? "Прогнать ещё раз" : "Прогнать по 1000 рук каждой") + "</button>" +
      '<span class="meta">одна и та же прогонка для всех: голдфишинг без ' +
        "соперника, выводы — про старт, а не про матч</span>" +
    "</div>"
  );
}

/* -------------------------------------------------------------- руки ----- */

function fgHandsHtml() {
  if (!fgHands) return '<p class="meta">сдаю…</p>';
  return (
    '<div class="row tight">' +
      '<button type="button" data-fgdeal="1">Сдать заново всем</button>' +
      '<label class="inline">карт в руке' +
        '<select id="fg-handsize">' +
          [7, 6, 5, 4].map((n) => '<option value="' + n + '"' +
            (n === fgHandSize ? " selected" : "") + ">" + n + "</option>").join("") +
        "</select></label>" +
      '<span class="meta">мулиган — это та же рука на карту меньше: ' +
        "поставьте 6 и сдайте заново</span>" +
    "</div>" +
    '<div class="fghands">' + (fgHands.hands || []).map((h) =>
      '<div class="fghand">' +
        '<div class="fghandhead"><b>' + esc(h.name) + "</b>" +
          '<span class="meta">' + esc(h.format || "") + "</span>" +
          (h.error
            ? '<span class="bad">' + esc(h.error) + "</span>"
            : '<span class="meta">земель <b>' + h.lands + "</b> · ср. мана " +
              h.avg_mv + " · в колоде " + h.library_size + "</span>") +
        "</div>" +
        '<div class="fgcards">' + (h.hand || []).map((c) =>
          '<div class="fgcard' + (c.is_land ? " land" : "") +
              '" title="' + esc(c.name + " · " + (c.type_line || "")) + '"' +
              (c.image_normal
                ? ' data-preview="' + esc(c.image_normal) + '"' : "") + ">" +
            (c.image_small
              ? '<img loading="lazy" src="' + esc(c.image_small) + '" alt="' +
                esc(c.name) + '">'
              : '<span class="fgnoart">' + esc(c.name) + "</span>") +
            '<span class="fgname">' + esc(c.name) + "</span>" +
          "</div>").join("") +
        "</div>" +
      "</div>").join("") +
    "</div>"
  );
}

/* ----------------------------------------------------------- покупки ----- */

const FG_MODES = [
  ["together", "все сразу", "чтобы все колоды лежали собранными одновременно"],
  ["byturn", "по очереди", "играю ими по очереди и пересобираю между играми"],
];

function fgBuyHtml() {
  if (!fgBuy) return '<p class="meta">считаю…</p>';
  const t = fgBuy.totals || {};
  const other = FG_MODES.find((m) => m[0] === t.other_mode) || ["", "", ""];

  return (
    '<div class="row tight wrap fgmodes">' +
      "<b>Собирать:</b>" +
      FG_MODES.map(([key, title, why]) =>
        '<button type="button" class="ghost' + (fgMode === key ? " on" : "") +
          '" data-fgmode="' + key + '" title="' + esc(why) + '">' +
          esc(title) + "</button>").join("") +
      '<span class="meta">' +
        esc((FG_MODES.find((m) => m[0] === fgMode) || ["", "", ""])[2]) +
      "</span>" +
      '<label class="inline"><input type="checkbox" id="fg-basics"' +
        (fgBasics ? " checked" : "") + "> считать базовые земли</label>" +
    "</div>" +
    "<p>Нужно <b>" + t.copies + "</b> карт " + t.names + " названий; " +
      "своих — " + t.owned + ". Докупить <b>" + t.missing_copies + " шт.</b> " +
      "(" + t.missing_names + " назв.) на <b>" + rub(t.cost) + "</b>." +
      (t.unpriced
        ? ' <span class="meta">у ' + t.unpriced +
          " карт цены нет — они в сумму не вошли</span>"
        : "") +
    "</p>" +
    (t.basic_copies
      ? '<p class="meta">Базовых земель нужно ещё <b>' + t.basic_copies +
        " шт.</b>" + (t.basic_cost ? " (" + rub(t.basic_cost) + ")" : "") +
        " — они не в счёте и не уйдут в охоту: лес есть у всех. " +
        "Нужны — поставьте галочку.</p>"
      : "") +
    (t.other_cost !== t.cost
      ? '<p class="meta">Тех же колод «' + esc(other[1]) + "» — " +
        rub(t.other_cost) + ". Разница из-за <b>" + t.shared_names +
        "</b> общих карт: они кочуют из колоды в колоду, если не держать все " +
        "собранными разом.</p>"
      : "") +
    '<div class="row tight">' +
      '<button type="button" data-fghunt="1">Всё недостающее в охоту</button>' +
      '<button type="button" class="ghost" data-fgcopy="1">Скопировать списком</button>' +
      '<span class="meta">охота ищет по всем продавцам сразу и считает ' +
        "доставку; ничего не отправляется и не покупается само</span>" +
    "</div>" +
    '<table class="fgtable"><thead><tr>' +
      "<th>карта</th><th>нужно</th><th>своих</th><th>купить</th>" +
      "<th>цена</th><th>итого</th><th>кому</th>" +
    "</tr></thead><tbody>" +
    (fgBuy.buy || []).map((r) =>
      '<tr class="' + (r.shared ? "shared" : "") + '">' +
        '<td class="fgnamecell"' +
          (r.image_normal ? ' data-preview="' + esc(r.image_normal) + '"' : "") +
          ">" +
          (r.image_small
            ? '<img class="fgthumb" loading="lazy" src="' + esc(r.image_small) +
              '" alt="">'
            : '<span class="fgthumb empty"></span>') +
          '<button type="button" class="linkish" data-fgcard="' + esc(r.name) +
          '">' + esc(r.name) + "</button></td>" +
        '<td class="num">' + r.needed + "</td>" +
        '<td class="num">' + (r.owned || "") + "</td>" +
        '<td class="num"><b>' + r.missing + "</b></td>" +
        '<td class="num">' + (r.price ? rub(r.price) : '<span class="meta">нет цены</span>') + "</td>" +
        '<td class="num">' + (r.cost ? rub(r.cost) : "") + "</td>" +
        '<td class="meta">' + (fgBuy.decks || []).filter(
          (d) => (r.per_deck || {})[d.id]).map(
          (d) => esc(d.name) + " ×" + r.per_deck[d.id]).join(", ") + "</td>" +
      "</tr>").join("") +
    "</tbody></table>" +
    (!(fgBuy.buy || []).length
      ? '<p class="good">Докупать нечего: всё уже есть в коллекции.</p>' : "")
  );
}

function fgRender() {
  if (!fgView) return;
  const title = { specs: "Спеки рядом", hands: "Стартовые руки рядом",
                  buy: "Что докупить на всю группу" }[fgView];
  fgBox().innerHTML =
    '<div class="fghead"><h3>' + title + "</h3>" +
      '<span class="meta">' + ((famData || {}).variants || []).length +
        " исполнения</span>" +
      '<button type="button" class="ghost tiny" data-fgclose="1">Закрыть</button>' +
    "</div>" +
    (fgView === "specs" ? fgSpecsHtml()
      : fgView === "hands" ? fgHandsHtml() : fgBuyHtml());
}

/* ------------------------------------------------------------ события ---- */

$("#fam-groupbar").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-group]");
  if (!btn) return;
  if (!fgReady()) return toast("Сначала выберите семейство", true);
  fgShow(btn.dataset.group);
});

$("#fam-group").addEventListener("click", async (ev) => {
  const t = ev.target;

  if (t.dataset.fgclose) { fgShow(fgView); return; }

  const open = t.closest("[data-fgopen]");
  if (open) {
    showTab("builder");
    bdOpen(open.dataset.fgopen);
    return;
  }

  const card = t.closest("[data-fgcard]");
  if (card) { openCardByName(card.dataset.fgcard); return; }

  if (t.dataset.fgsim) {
    t.disabled = true;
    try {
      fgSim = await fgAsk("simulate", { games: 1000, hand_size: 7, turns: 5 });
    } catch (e) {
      toast(e.message, true);
    }
    fgRender();
    return;
  }

  if (t.dataset.fgdeal) {
    fgHands = null;
    fgRender();
    await fgLoad();
    return;
  }

  const mode = t.closest("[data-fgmode]");
  if (mode) {
    fgMode = mode.dataset.fgmode;
    store.set("fam.buymode", fgMode);
    fgBuy = null;
    fgRender();
    await fgLoad();
    return;
  }

  if (t.dataset.fghunt) {
    const rows = (fgBuy || {}).buy || [];
    if (!rows.length) return toast("Докупать нечего", true);
    const copies = rows.reduce((n, r) => n + r.missing, 0);
    // Молча дописать сорок пять строк в список на другой вкладке -- это и
    // выглядит как «кнопка не работает»: нажал, и ничего не произошло.
    // Поэтому после добавления показываем саму охоту.
    rows.forEach((r) => addToHunt(r.name, r.missing));
    showTab("hunt");
    const box = $("#hunt-wants");
    if (box) {
      box.scrollIntoView({ block: "center" });
      box.scrollTop = box.scrollHeight;
    }
    toast("В охоту добавлено " + rows.length + " назв. / " + copies +
          " шт. — нажмите «Искать»");
    return;
  }

  if (t.dataset.fgcopy) {
    const rows = (fgBuy || {}).buy || [];
    copyText(rows.map((r) => r.missing + " " + r.name).join("\n"),
             "Список скопирован");
  }
});

$("#fam-group").addEventListener("change", async (ev) => {
  if (ev.target.id === "fg-handsize") {
    fgHandSize = parseInt(ev.target.value, 10) || 7;
    fgHands = null;
    fgRender();
    await fgLoad();
    return;
  }
  if (ev.target.id === "fg-basics") {
    fgBasics = ev.target.checked;
    fgBuy = null;
    fgRender();
    await fgLoad();
  }
});
