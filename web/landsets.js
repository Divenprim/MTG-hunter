"use strict";

/* Наборы земель: то, что покупают и играют вместе.

   Манабаза собирается не по одной карте. Десять шоковых земель -- это один
   набор, пять трайомов -- другой, шесть артефактных земель под аффинити --
   третий. И вопрос обычно стоит не «какая земля подойдёт этой колоде», а
   «что купить по четыре штуки, чтобы потом собирать что угодно». Поэтому
   цена показана двумя числами: за комплект по одной и за плейсет.

   Каталог собирается из данных: циклы размечены тегами Scryfall, комбо взяты
   из локальной базы Commander Spellbook, и только для пары случаев вроде
   Urza's tron стоит короткий список руками.

   Живёт на вкладке поиска отдельным режимом: там же язык запросов, фильтр по
   формату и то же окно карты. */

let lsData = null;
let lsBusy = false;
let lsOrder = store.get("ls.order", "value");
let lsBudget = store.get("ls.budget", "");
let lsOnlyOpen = store.get("ls.onlyopen", false);
let lsOpenKey = null;

const LS_KIND = {
  cycle: ["", "цикл"],
  known: ["ok", "известная связка"],
  combo: ["warn", "комбо"],
};
const LS_ORDERS = [
  ["value", "польза за деньги"],
  ["price", "сначала дешёвые"],
  ["quality", "сначала лучшие"],
];

function lsMode() {
  return ($("#search-mode") || {}).value === "landsets";
}

async function lsLoad() {
  if (lsBusy) return;
  lsBusy = true;
  $("#search-meta").innerHTML = '<span class="spinner">собираю наборы…</span>';
  try {
    const fmt = ($("#f-format") && $("#f-format").value) || "";
    const params = ["order=" + encodeURIComponent(lsOrder), "limit=40"];
    if (fmt) params.push("fmt=" + encodeURIComponent(fmt));
    if (lsBudget) params.push("budget=" + encodeURIComponent(lsBudget));
    if (lsOnlyOpen) params.push("only_open=true");
    lsData = await api("/api/landsets?" + params.join("&"));
    lsRender();
  } catch (e) {
    $("#search-meta").textContent = "";
    $("#search-results").innerHTML = '<div class="nothing"><b>' +
      esc(e.message) + "</b></div>";
  } finally {
    lsBusy = false;
  }
}

function lsCardRow(c) {
  const entry = { open: "развёрнутой", maybe: "по условию", tapped: "тапнутой" };
  return (
    '<div class="lscard" data-open="' + esc(c.name) + '"' +
        (c.image_normal ? ' data-preview="' + esc(c.image_normal) + '"' : "") + ">" +
      (c.image_small
        ? '<img loading="lazy" src="' + esc(c.image_small) + '" alt="">'
        : '<span class="lsnoart"></span>') +
      '<span class="lsname">' + esc(c.ru_name || c.name) + "</span>" +
      '<span class="meta">' + esc(c.produces || "—") + " · " +
        esc(entry[c.entry] || c.entry) +
        (c.usd != null ? " · $" + c.usd.toFixed(2) : "") + "</span>" +
    "</div>"
  );
}

function lsSetBlock(set) {
  const [cls, word] = LS_KIND[set.kind] || ["", set.kind];
  const open = lsOpenKey === set.key;
  const e = set.entry || {};
  return (
    '<div class="lsset' + (open ? " open" : "") + '" data-set="' + esc(set.key) + '">' +
      '<div class="lshead">' +
        "<b>" + esc(set.label) + "</b>" +
        '<span class="chip ' + cls + '">' + word + "</span>" +
        '<span class="chip">' + set.size + " карт</span>" +
        (set.colors
          ? '<span class="chip">' + esc(set.colors) + "</span>" : "") +
        (e.open ? '<span class="chip ok">развёрнутых ' + e.open + "</span>" : "") +
        (e.tapped ? '<span class="chip">тапнутых ' + e.tapped + "</span>" : "") +
        (set.fetch ? '<span class="chip">фетчей ' + set.fetch + "</span>" : "") +
      "</div>" +
      (set.why ? '<p class="meta">' + esc(set.why) + "</p>" : "") +
      '<div class="lsprice">' +
        "<span>по одной: <b>$" + set.usd_one.toFixed(2) + "</b></span>" +
        "<span>по четыре: <b>$" + set.usd_playset.toFixed(2) + "</b></span>" +
        (set.unpriced
          ? '<span class="meta">у ' + set.unpriced + " карт цены нет</span>" : "") +
        '<span style="flex:1"></span>' +
        '<button type="button" class="ghost tiny" data-lsshow="' + esc(set.key) +
          '">' + (open ? "скрыть карты" : "показать карты") + "</button>" +
        '<button type="button" class="ghost tiny" data-lshunt="1" data-key="' +
          esc(set.key) + '">в охоту по 1</button>' +
        '<button type="button" class="tiny" data-lshunt="4" data-key="' +
          esc(set.key) + '">в охоту по 4</button>' +
      "</div>" +
      (open
        ? '<div class="lscards">' + (set.cards || []).map(lsCardRow).join("") + "</div>"
        : "") +
    "</div>"
  );
}

function lsRender() {
  if (!lsData) return;
  const sets = lsData.sets || [];
  $("#search-meta").innerHTML =
    "наборов: <b>" + sets.length + "</b> из " + lsData.total +
    " · цена долларовая, за самую дешёвую печать" +
    (lsData.format ? " · только те, где все карты легальны" : "");

  $("#search-results").innerHTML =
    '<div class="lstools row tight wrap">' +
      '<label class="inline">порядок' +
        '<select id="ls-order">' +
          LS_ORDERS.map(([key, title]) => '<option value="' + key + '"' +
            (lsOrder === key ? " selected" : "") + ">" + title + "</option>").join("") +
        "</select></label>" +
      '<label class="inline">плейсет не дороже, $' +
        '<input type="number" id="ls-budget" min="0" step="5" value="' +
          esc(lsBudget) + '" style="width:90px" placeholder="любой"></label>' +
      '<label class="inline"><input type="checkbox" id="ls-open"' +
        (lsOnlyOpen ? " checked" : "") + "> без таплендов</label>" +
      '<span class="meta">формат берётся из фильтров слева</span>' +
    "</div>" +
    (sets.length
      ? '<div class="lssets">' + sets.map(lsSetBlock).join("") + "</div>"
      : '<div class="nothing"><b>Ничего не нашлось</b>' +
        '<p class="meta">Под этот формат и бюджет наборов нет. Уберите ' +
        "ограничение по цене или снимите «без таплендов».</p></div>");
}

/* Набор -- это покупка целиком, поэтому и в охоту он уходит целиком: по одной
   карте посмотреть или по четыре, чтобы играть. */
function lsToHunt(key, each) {
  const set = ((lsData || {}).sets || []).find((s) => s.key === key);
  if (!set) return;
  (set.cards || []).forEach((c) => setInHunt(c.name, each));
  showTab("hunt");
  const box = $("#hunt-wants");
  if (box) box.scrollIntoView({ block: "center" });
  toast("В охоте: " + set.label + " — " + set.cards.length + " назв. по " +
        each + " шт.");
}

$("#search-results").addEventListener("click", (ev) => {
  const show = ev.target.closest("[data-lsshow]");
  if (show) {
    lsOpenKey = lsOpenKey === show.dataset.lsshow ? null : show.dataset.lsshow;
    lsRender();
    return;
  }
  const hunt = ev.target.closest("[data-lshunt]");
  if (hunt) {
    lsToHunt(hunt.dataset.key, parseInt(hunt.dataset.lshunt, 10) || 1);
    return;
  }
  const card = ev.target.closest(".lscard[data-open]");
  if (card) openCardByName(card.dataset.open);
});

$("#search-results").addEventListener("contextmenu", (ev) => {
  const card = ev.target.closest(".lscard[data-open]");
  if (!card) return;
  ev.preventDefault();
  bdSuggestMenu(card.dataset.open, ev.clientX, ev.clientY);
});

$("#search-results").addEventListener("change", (ev) => {
  if (ev.target.id === "ls-order") {
    lsOrder = ev.target.value;
    store.set("ls.order", lsOrder);
    lsLoad();
  }
  if (ev.target.id === "ls-budget") {
    lsBudget = ev.target.value;
    store.set("ls.budget", lsBudget);
    lsLoad();
  }
  if (ev.target.id === "ls-open") {
    lsOnlyOpen = ev.target.checked;
    store.set("ls.onlyopen", lsOnlyOpen);
    lsLoad();
  }
});

$("#search-mode").addEventListener("change", () => {
  store.set("searchMode", $("#search-mode").value);
  if (lsMode()) {
    lsOpenKey = null;
    lsLoad();
  } else {
    $("#search-results").innerHTML = "";
    runSearch(true);
  }
});
