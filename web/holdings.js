/* Коллекция как учёт: что есть, что занято и что свободно.

   Список «сколько каких карт у меня» не отвечает на вопрос, ради которого его
   и ведут: можно ли собрать вот эту колоду прямо сейчас. Ответ зависит не
   только от коллекции, но и от того, что уже разобрано по собранным колодам --
   четыре Молнии, лежащие в собранной колоде, для остальных колод не
   существуют.

   Поэтому у колоды есть признак «собрана», а у каждой карты три числа: есть,
   занято, свободно. Считает всё сервер (app/holdings.py), здесь -- показ. */

let holdData = null;
let holdSort = store.get("coll.sort", "name");
let holdOnly = "all";
let holdView = store.get("coll.view", "tiles");

/* Отбор. Те же вопросы, что и к поиску -- какого цвета, какого типа, какой
   редкости, -- но отвечает на них не сервер: у коллекции всё это уже под
   рукой. Цвета, тип, редкость, стоимость и сет приходят вместе с карточными
   данными, поэтому отбор мгновенный и не стоит ни одного запроса. */
let holdFilters = Object.assign(
  { colors: [], types: [], rarity: [], cmcMin: "", cmcMax: "", set: "",
    unknown: false },
  store.get("coll.filters", {}));

function holdFiltersOn() {
  const f = holdFilters;
  return !!(f.colors.length || f.types.length || f.rarity.length
            || f.cmcMin !== "" || f.cmcMax !== "" || f.set || f.unknown);
}

function holdSaveFilters() {
  store.set("coll.filters", holdFilters);
}

/* Цвет карты: «WU» -- две буквы, пусто -- бесцветная. Кнопка C спрашивает
   именно про бесцветные, а не про «безразлично». */
function holdColorOk(card) {
  const want = holdFilters.colors;
  if (!want.length) return true;
  const has = (card.colors || "").toUpperCase();
  return want.some((c) => (c === "C" ? !has : has.indexOf(c) >= 0));
}

function holdTypeOk(card) {
  const want = holdFilters.types;
  if (!want.length) return true;
  const line = (card.type_line || "").toLowerCase();
  return want.every((t) => line.indexOf(t.toLowerCase()) >= 0);
}

function holdRarityOk(card) {
  const want = holdFilters.rarity;
  return !want.length || want.indexOf(card.rarity) >= 0;
}

function holdCmcOk(card) {
  const f = holdFilters;
  if (f.cmcMin === "" && f.cmcMax === "") return true;
  const cmc = card.cmc == null ? -1 : Number(card.cmc);
  if (f.cmcMin !== "" && cmc < Number(f.cmcMin)) return false;
  if (f.cmcMax !== "" && cmc > Number(f.cmcMax)) return false;
  return true;
}

/* Сет ищется среди ваших печатей, а не среди всех, какие бывают: вопрос
   «что у меня из Модерн Хорайзонс» -- про то, что лежит в коробке. */
function holdSetOk(card) {
  const want = (holdFilters.set || "").trim().toUpperCase();
  if (!want) return true;
  const mine = (card.printings || []).map((p) => (p.set_code || "").toUpperCase());
  if (mine.some((s) => s && s.indexOf(want) >= 0)) return true;
  return !mine.length && (card.set_code || "").toUpperCase().indexOf(want) >= 0;
}

function holdUnknownOk(card) {
  if (!holdFilters.unknown) return true;
  const mine = card.printings || [];
  return !mine.length || mine.some((p) => !p.set_code);
}

async function holdLoad() {
  try {
    holdData = await api("/api/holdings");
  } catch (e) {
    $("#coll-list").innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
    return;
  }
  holdRenderSummary();
  holdRenderWorth();
  holdRenderCards();
  holdRenderDecks();
  holdRenderConflicts();
}

/* Во сколько всё это оценивается -- и как менялось.

   Долларовая цена есть в локальной базе почти у каждой карты, поэтому она
   считается по всей коллекции сразу и ничего не качает. Рублёвая известна
   только по тем картам, цену которых спрашивали у topdeck, -- и написано, по
   скольким именно: оценка, выданная за полную, была бы враньём.

   Какая именно печать лежит у вас, программа не знает (коллекция ведётся по
   именам), поэтому берётся самая дешёвая -- это нижняя граница. */
function holdRenderWorth() {
  const t = holdData.totals;
  const box = $("#coll-worth");
  if (!t.copies) { box.hidden = true; return; }
  box.hidden = false;

  const hist = (holdData.history || []).filter((h) => h.usd > 0);
  const first = hist[0];
  const last = hist[hist.length - 1];
  const grew = first && last && hist.length > 1 ? last.usd - first.usd : 0;

  box.innerHTML =
    '<div class="worthnums">' +
      '<div class="worthbox"><span class="meta">' +
        (t.copies_blind ? "оценка, не меньше" : "оценка") + "</span>" +
        "<b>$" + t.usd.toLocaleString("ru") + "</b>" +
        '<span class="meta">' +
          (t.copies_exact
            ? t.copies_exact + " шт. посчитано по своей печати"
            : "") +
          (t.copies_exact && t.copies_blind ? ", " : "") +
          (t.copies_blind
            ? t.copies_blind + " шт. — по самой дешёвой: печать у них " +
              "неизвестна"
            : "") +
          "</span></div>" +
      '<div class="worthbox"><span class="meta">в рублях, по известным</span>' +
        "<b>" + rub(t.rub) + "</b>" +
        '<span class="meta">цена спрошена у topdeck для ' + t.rub_known +
          " из " + t.cards + " назв.</span></div>" +
      '<div class="worthbox"><span class="meta">в коллекции</span>' +
        "<b>" + t.copies.toLocaleString("ru") + " шт.</b>" +
        '<span class="meta">' + t.cards.toLocaleString("ru") +
          " назв., свободно " + t.free + "</span></div>" +
    "</div>" +
    (hist.length > 1
      ? '<div class="worthchart' + (hist.length > 6 ? " many" : "") + '">' +
        holdChart(hist) + "</div>" +
        '<p class="meta">Оценка записывается раз в день, когда вы открываете ' +
        "учёт. За " + hist.length + " дн. " +
        (grew >= 0 ? "прибавилось $" : "убавилось $") +
        Math.abs(grew).toFixed(2) + ".</p>"
      : '<p class="meta">История наберётся сама: оценка записывается раз в ' +
        "день, когда вы сюда заходите.</p>");
}

/* График без библиотек: точек мало, а рисовать их куда-то надо. */
function holdChart(hist) {
  const w = 560;
  const h = 120;
  const pad = 6;
  const vals = hist.map((p) => p.usd);
  let low = Math.min.apply(null, vals);
  let high = Math.max.apply(null, vals);
  // Пока коллекция не менялась, низ и верх совпадают, и линия ложится ровно
  // на нижний край -- выглядит как обрыв. Раздвигаем на десятую часть, тогда
  // ровная линия идёт посередине, как ей и положено.
  if (high - low < 0.01) {
    const pad2 = Math.max(0.5, high * 0.1);
    low -= pad2;
    high += pad2;
  }
  const span = high - low || 1;
  const x = (i) => pad + (w - pad * 2) * (hist.length === 1 ? 0.5 : i / (hist.length - 1));
  const y = (v) => h - pad - (h - pad * 2) * ((v - low) / span);
  const line = hist.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " +
    y(p.usd).toFixed(1)).join(" ");
  const area = line + " L" + x(hist.length - 1).toFixed(1) + " " + (h - pad) +
    " L" + x(0).toFixed(1) + " " + (h - pad) + " Z";
  return (
    '<svg viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" ' +
        'role="img" aria-label="стоимость коллекции по дням">' +
      '<path class="wortharea" d="' + area + '"></path>' +
      '<path class="worthline" d="' + line + '"></path>' +
      hist.map((p, i) =>
        '<circle class="worthdot" cx="' + x(i).toFixed(1) + '" cy="' +
        y(p.usd).toFixed(1) + '" r="2.5"><title>' + esc(p.at) + ": $" +
        p.usd.toFixed(2) + "</title></circle>").join("") +
    "</svg>" +
    '<div class="worthaxis"><span>' + esc(hist[0].at) + "</span>" +
      "<span>$" + Math.min.apply(null, vals).toFixed(2) + " — $" +
        Math.max.apply(null, vals).toFixed(2) + "</span>" +
      "<span>" + esc(hist[hist.length - 1].at) + "</span></div>"
  );
}

function holdRenderSummary() {
  const t = holdData.totals;
  $("#coll-summary").innerHTML =
    "в коллекции <b>" + t.copies.toLocaleString("ru") + "</b> шт. (" +
    t.cards.toLocaleString("ru") + " назв.) · занято собранными колодами <b>" +
    t.committed + "</b> · свободно <b>" + t.free + "</b> · колод " + t.decks +
    ", из них собрано " + t.assembled +
    (t.rows > t.cards
      ? ' · <span class="meta">в таблице ещё ' + (t.rows - t.cards) +
        " назв. из колод, которых на руках нет</span>"
      : "");
}

/* ------------------------------------------------------------- все карты */

function holdDeckChips(card) {
  return card.decks.map((d) =>
    '<span class="deckchip' + (d.assembled ? " built" : "") +
      '" data-open="' + esc(d.deck_id) + '" title="' +
      (d.assembled ? "Колода собрана: эти карты заняты"
                   : "Колода на бумаге: карты не заняты") + '">' +
      esc(d.deck) + " <b>" + d.quantity + "</b></span>").join("");
}

function holdVisible() {
  const needle = ($("#coll-filter").value || "").trim().toLowerCase();
  return (holdData.cards || []).filter((c) => {
    if (holdOnly === "free" && c.free <= 0) return false;
    if (holdOnly === "committed" && c.committed <= 0) return false;
    if (holdOnly === "missing" && !(c.listed > c.owned)) return false;
    if (!holdColorOk(c) || !holdTypeOk(c) || !holdRarityOk(c)
        || !holdCmcOk(c) || !holdSetOk(c) || !holdUnknownOk(c)) return false;
    if (!needle) return true;
    if (c.name.toLowerCase().indexOf(needle) >= 0) return true;
    if ((c.ru_name || "").toLowerCase().indexOf(needle) >= 0) return true;
    if ((c.type_line || "").toLowerCase().indexOf(needle) >= 0) return true;
    return c.decks.some((d) => d.deck.toLowerCase().indexOf(needle) >= 0);
  });
}

/* Кнопки отбора: нажатая -- включена, нажатая ещё раз -- выключена. */
function holdRenderFilterButtons() {
  $$("#cf-colors .cbtn").forEach((b) =>
    b.classList.toggle("on", holdFilters.colors.indexOf(b.dataset.c) >= 0));
  $$("#cf-types .tbtn").forEach((b) =>
    b.classList.toggle("on", holdFilters.types.indexOf(b.dataset.t) >= 0));
  $$("#cf-rarity .tbtn").forEach((b) =>
    b.classList.toggle("on", holdFilters.rarity.indexOf(b.dataset.r) >= 0));
  $("#cf-cmc-min").value = holdFilters.cmcMin;
  $("#cf-cmc-max").value = holdFilters.cmcMax;
  $("#cf-set").value = holdFilters.set;
  $("#cf-unknown").checked = !!holdFilters.unknown;
  $("#coll-filters-toggle").classList.toggle("on", holdFiltersOn());
}

function holdToggleIn(list, value) {
  const at = list.indexOf(value);
  if (at >= 0) list.splice(at, 1);
  else list.push(value);
}

const RARITY_ORDER = { common: 1, uncommon: 2, rare: 3, mythic: 4, special: 5,
                       bonus: 5 };
const RARITY_WORD = { common: "обычная", uncommon: "необычная", rare: "редкая",
                      mythic: "мифическая", special: "особая", bonus: "бонусная" };

/* Плитка -- это сама карта.

   Первая попытка была «картинка сбоку, числа рядом», и она выглядела грустно:
   карта размером с ноготь, а половину плитки занимал текст, который и так
   написан на карте. Поэтому теперь картинка занимает плитку целиком, а
   программа дописывает поверх только то, чего на карте нет: сколько её у вас,
   сколько занято собранными колодами и почём она.

   Счётчик -- в левом верхнем углу, на «шапке» карты, где у самой карты нет
   ничего важного. Он же и есть ручка: при наведении (или нажатии пальцем) из
   него разворачивается подробность -- где именно и сколько занято. */
function holdMark(c) {
  if (!c.owned) return '<span class="holdmark wanted">0</span>';
  const cls = c.free < 0 ? " short" : (c.committed ? " partly" : "");
  return (
    '<span class="holdmark' + cls + '">' +
      "<b>" + c.owned + "</b>" +
      (c.committed ? "<i>" + c.committed + "</i>" : "") +
    "</span>"
  );
}

function holdWhere(c) {
  const lines = (c.decks || []).map((d) =>
    '<div class="holdwhererow' + (d.assembled ? " built" : "") + '">' +
      '<span class="n">' + d.quantity + "</span>" +
      "<span>" + esc(d.deck) + "</span>" +
      '<span class="meta">' + (d.assembled ? "собрана" : "на бумаге") + "</span>" +
    "</div>").join("");
  return (
    '<div class="holdinfo">' +
      "<b>" + esc(c.ru_name || c.name) + "</b>" +
      '<div class="holdinfonums">' +
        "<span>есть <b>" + c.owned + "</b></span>" +
        "<span>занято <b>" + (c.committed || 0) + "</b></span>" +
        '<span>свободно <b class="' +
          (c.free < 0 ? "bad" : (c.free ? "good" : "")) + '">' + c.free +
          "</b></span>" +
      "</div>" +
      (lines
        ? '<div class="holdwhere">' + lines + "</div>"
        : '<p class="meta">Ни в одной колоде не числится.</p>') +
      (c.listed > c.owned
        ? '<p class="meta">Колодам нужно ' + c.listed + " — не хватает " +
          (c.listed - c.owned) + ".</p>"
        : "") +
      '<p class="meta">' +
        esc((c.set_code || "").toUpperCase()) +
        (c.collector_number ? " #" + esc(c.collector_number) : "") +
        (c.rarity ? " · " + esc(RARITY_WORD[c.rarity] || c.rarity) : "") +
      "</p>" +
    "</div>"
  );
}

function holdTile(c) {
  const money = [];
  if (c.usd != null) money.push("$" + c.usd.toFixed(2));
  if (c.price) money.push(rub(c.price));
  return (
    '<div class="holdcard' + (c.owned ? "" : " ghostly") + '"' +
        ' data-card="' + esc(c.name) + '">' +
      (c.image_normal || c.image_small
        ? '<img loading="lazy" src="' + esc(c.image_normal || c.image_small) +
          '" alt="' + esc(c.ru_name || c.name) + '">'
        : '<span class="holdnoart">' + esc(c.ru_name || c.name) + "</span>") +
      holdMark(c) +
      holdWhere(c) +
      (money.length
        ? '<span class="holdprice">' + money.join(" · ") + "</span>"
        : "") +
    "</div>"
  );
}

function holdRenderCards() {
  const rows = holdVisible();
  const num = (v) => (v == null ? -1 : v);
  const order = {
    name: (a, b) => a.name.localeCompare(b.name),
    owned: (a, b) => b.owned - a.owned || a.name.localeCompare(b.name),
    free: (a, b) => b.free - a.free || a.name.localeCompare(b.name),
    listed: (a, b) => b.listed - a.listed || a.name.localeCompare(b.name),
    price: (a, b) => b.price - a.price || a.name.localeCompare(b.name),
    usd: (a, b) => num(b.usd) - num(a.usd) || a.name.localeCompare(b.name),
    // Стопка из четырёх копеечных карт может стоить дороже одной дорогой:
    // это другой вопрос, чем «какая карта дороже», и своя сортировка.
    worth: (a, b) => num(b.usd_total) - num(a.usd_total)
      || a.name.localeCompare(b.name),
    rarity: (a, b) => (RARITY_ORDER[b.rarity] || 0) - (RARITY_ORDER[a.rarity] || 0)
      || a.name.localeCompare(b.name),
    set: (a, b) => (a.set_code || "я").localeCompare(b.set_code || "я")
      || Number(a.collector_number || 0) - Number(b.collector_number || 0)
      || a.name.localeCompare(b.name),
  };
  rows.sort(order[holdSort] || order.name);

  const head =
    '<div class="holdrow head">' +
      "<span>карта</span>" +
      '<span class="num">есть</span>' +
      '<span class="num">занято</span>' +
      '<span class="num">свободно</span>' +
      "<span>в колодах</span>" +
      '<span class="num">цена</span>' +
    "</div>";

  // Больше трёхсот строк никто глазами не читает, а рисовать их -- заметная
  // задержка на каждое нажатие в фильтре. Остальное достаётся фильтром.
  const shown = rows.slice(0, 300);
  const more = rows.length > shown.length
    ? '<p class="meta">Показаны первые ' + shown.length + " из " +
      rows.length + " — уточните фильтр.</p>"
    : "";

  // Сравнивать надо с тем же, что показано без отбора: в таблице есть и
  // карты, которых на руках нет, -- они тоже строки.
  const total = (holdData.cards || []).length;
  $("#cf-count").textContent = holdFiltersOn()
    ? "под отбор подходит " + rows.length + " назв. из " + total
    : "";

  if (holdView === "tiles") {
    $("#coll-list").innerHTML =
      '<div class="holdcards">' + shown.map(holdTile).join("") + "</div>" +
      (shown.length ? "" :
        '<p class="meta">Ничего не подходит под фильтр.</p>') + more;
    return;
  }

  $("#coll-list").innerHTML = head + (shown.map((c) => {
    const freeClass = c.free < 0 ? " short" : (c.free > 0 ? " spare" : "");
    // Подписи столбцов нужны не только шапке: на узком экране строка
    // разворачивается в карточку, и тогда подпись встаёт рядом со значением.
    return '<div class="holdrow" data-card="' + esc(c.name) + '"' +
        (c.image_normal ? ' data-preview="' + esc(c.image_normal) + '"' : "") + ">" +
      '<span class="nm">' +
        (c.image_small
          ? '<img class="holdmini" loading="lazy" src="' + esc(c.image_small) +
            '" alt="">'
          : "") +
        "<span>" + esc(c.ru_name || c.name) +
        (c.set_code
          ? ' <span class="meta">' + esc(c.set_code.toUpperCase()) + "</span>"
          : "") + "</span></span>" +
      '<span class="num" data-label="есть">' + c.owned + "</span>" +
      '<span class="num" data-label="занято">' + (c.committed || "") + "</span>" +
      '<span class="num' + freeClass + '" data-label="свободно">' + c.free +
        "</span>" +
      '<span data-label="в колодах">' + holdDeckChips(c) + "</span>" +
      '<span class="num" data-label="цена">' +
        (c.usd != null ? "$" + c.usd.toFixed(2) : "") +
        (c.price ? '<span class="rubprice">' + rub(c.price) + "</span>" : "") +
        "</span>" +
    "</div>";
  }).join("") ||
    '<p class="meta">Ничего не подходит под фильтр. Если коллекция пуста — ' +
    "вкладка «Список текстом», или отсканируйте карты камерой.</p>") + more;
}

/* -------------------------------------------------------------- по колодам */

function holdRenderDecks() {
  const decks = (holdData.decks || []).slice()
    .sort((a, b) => (b.assembled ? 1 : 0) - (a.assembled ? 1 : 0)
      || a.missing - b.missing || a.name.localeCompare(b.name));

  $("#coll-decks").innerHTML = decks.map((d) =>
    '<div class="deckcard">' +
      '<div class="head">' +
        "<b>" + esc(d.name) + "</b>" +
        '<span class="meta">' + esc(d.format || "") + " · " + d.copies +
          " шт. / " + d.distinct + " назв.</span>" +
        (d.ready
          ? '<span class="chip ok">хватает на сборку</span>'
          : '<span class="chip">не хватает ' + d.missing + " шт." +
            (d.missing_rub ? " — " + rub(d.missing_rub) : "") + "</span>") +
        '<span class="grow-right"></span>' +
        '<label class="builtbox" title="Собрана — её карты заняты и другим ' +
          'колодам не достанутся">' +
          '<input type="checkbox" data-built="' + esc(d.id) + '"' +
          (d.assembled ? " checked" : "") + "> собрана</label>" +
        '<button type="button" class="ghost tiny" data-open="' + esc(d.id) +
          '">открыть</button>' +
        (d.missing
          ? '<button type="button" class="ghost tiny" data-hunt="' + esc(d.id) +
            '">недостающее в охоту</button>'
          : "") +
      "</div>" +
      (d.short && d.short.length
        ? '<div class="short">' + d.short.slice(0, 12).map((s) =>
            "<div>не хватает <b>" + s.lack + "</b> × " + esc(s.name) +
            (s.price ? " · " + rub(s.price * s.lack) : "") + "</div>").join("") +
          (d.short.length > 12
            ? '<div class="meta">…и ещё ' + (d.short.length - 12) + "</div>"
            : "") +
          "</div>"
        : "") +
    "</div>").join("") ||
    '<p class="meta">Колод пока нет — они создаются в билдере.</p>';
}

/* ---------------------------------------------------------- несоответствия */

function holdRenderConflicts() {
  const rows = holdData.conflicts || [];
  $("#coll-conflicts").innerHTML = rows.length
    ? '<p class="meta">Собранные колоды претендуют на карты, которых столько ' +
      "нет. Либо одна из колод собрана только на бумаге, либо коллекция " +
      "неполная.</p>" +
      rows.map((c) =>
        '<div class="conflict"><b>' + esc(c.name) + "</b> — " +
          (c.owned
            ? "в собранных колодах " + c.committed + " шт., а есть " + c.owned
            : "в собранных колодах " + c.committed + " шт., а в коллекции нет вовсе") +
          "<div>" + c.decks.map((d) =>
            '<span class="deckchip built" data-open="' + esc(d.deck_id) + '">' +
            esc(d.deck) + " <b>" + d.quantity + "</b></span>").join("") +
          "</div>" +
        "</div>").join("")
    : '<p class="good">Несоответствий нет: собранные колоды укладываются в ' +
      "коллекцию.</p>";
}

/* ------------------------------------------------------------- управление */

$("#coll-tabs").addEventListener("click", (ev) => {
  const tab = ev.target.closest("[data-coll]");
  if (!tab) return;
  const name = tab.dataset.coll;
  $$("#coll-tabs .subtab").forEach((t) =>
    t.classList.toggle("active", t === tab));
  ["cards", "decks", "conflicts", "text"].forEach((key) => {
    $("#coll-" + key).hidden = key !== name;
  });
});

$("#coll-refresh").addEventListener("click", holdLoad);
$("#coll-filter").addEventListener("input", debounce(holdRenderCards, 200));
$("#coll-only").addEventListener("change", (ev) => {
  holdOnly = ev.target.value;
  holdRenderCards();
});
$("#coll-sort").addEventListener("change", (ev) => {
  holdSort = ev.target.value;
  store.set("coll.sort", holdSort);
  holdRenderCards();
});

/* Вид -- вопрос задачи, а не вкуса: плитками ищут карту глазами, строками
   считают числа. Поэтому оба, и выбор запоминается. */
function holdSetView(view) {
  holdView = view;
  store.set("coll.view", view);
  $$("#coll-view button").forEach((b) =>
    b.classList.toggle("on", b.dataset.view === view));
  if (holdData) holdRenderCards();
}

$("#coll-view").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-view]");
  if (btn) holdSetView(btn.dataset.view);
});

/* Подробность разворачивается наведением -- это делают стили. Пальцем навести
   нельзя, поэтому по нажатию на счётчик она открывается и закрывается. */
$("#coll-list").addEventListener("click", (ev) => {
  const mark = ev.target.closest(".holdmark");
  if (mark) {
    const card = mark.closest(".holdcard");
    const was = card.classList.contains("open");
    $$("#coll-list .holdcard.open").forEach((c) => c.classList.remove("open"));
    card.classList.toggle("open", !was);
    ev.stopPropagation();
    return;
  }
  // Нажатие по самой карте открывает её так же, как в поиске.
  const tile = ev.target.closest("#coll-list [data-card]");
  if (tile && typeof openCardByName === "function") {
    openCardByName(tile.dataset.card);
  }
});

/* Выгрузка. Список текстом -- ровно в том виде, в каком коллекция вводится:
   его можно вернуть обратно без правки. CSV -- для таблицы, там ещё и цены. */
async function holdExport(kind) {
  try {
    const r = await api("/api/collection/export?kind=" + kind);
    if (kind === "csv") {
      const blob = new Blob(["\ufeff" + r.text],
                            { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "коллекция.csv";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      toast("Выгружено: " + r.cards + " назв., " + r.copies + " шт.");
      return;
    }
    await copyText(r.text);
    toast("Скопировано: " + r.cards + " назв., " + r.copies + " шт.");
  } catch (e) {
    toast(e.message, true);
  }
}

/* --------------------------------------------------------------- отбор */

$("#coll-filters-toggle").addEventListener("click", () => {
  const panel = $("#coll-filters");
  panel.hidden = !panel.hidden;
  $("#coll-filters-toggle").setAttribute("aria-expanded", String(!panel.hidden));
});

$("#cf-colors").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-c]");
  if (!btn) return;
  holdToggleIn(holdFilters.colors, btn.dataset.c);
  holdAfterFilter();
});

$("#cf-types").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-t]");
  if (!btn) return;
  holdToggleIn(holdFilters.types, btn.dataset.t);
  holdAfterFilter();
});

$("#cf-rarity").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-r]");
  if (!btn) return;
  holdToggleIn(holdFilters.rarity, btn.dataset.r);
  holdAfterFilter();
});

["cf-cmc-min", "cf-cmc-max", "cf-set"].forEach((id) => {
  $("#" + id).addEventListener("input", debounce(() => {
    holdFilters.cmcMin = $("#cf-cmc-min").value;
    holdFilters.cmcMax = $("#cf-cmc-max").value;
    holdFilters.set = $("#cf-set").value;
    holdAfterFilter();
  }, 200));
});

$("#cf-unknown").addEventListener("change", (ev) => {
  holdFilters.unknown = ev.target.checked;
  holdAfterFilter();
});

$("#cf-clear").addEventListener("click", () => {
  holdFilters = { colors: [], types: [], rarity: [], cmcMin: "", cmcMax: "",
                  set: "", unknown: false };
  holdAfterFilter();
});

function holdAfterFilter() {
  holdSaveFilters();
  holdRenderFilterButtons();
  if (holdData) holdRenderCards();
}

$("#coll-copy").addEventListener("click", () => holdExport("text"));
$("#coll-csv").addEventListener("click", () => holdExport("csv"));
holdSetView(holdView);
holdRenderFilterButtons();

/* Одна обработка на все три вкладки: имена кнопок совпадают нарочно -- «эта
   колода» значит одно и то же, откуда бы на неё ни нажали. */
document.addEventListener("click", async (ev) => {
  const open = ev.target.closest("#panel-collection [data-open]");
  if (open) {
    showTab("builder");
    if (typeof bdOpen === "function") bdOpen(open.dataset.open);
    return;
  }

  const hunt = ev.target.closest("#panel-collection [data-hunt]");
  if (hunt) {
    const deck = (holdData.decks || []).find((d) => d.id === hunt.dataset.hunt);
    if (!deck || !deck.short) return;
    const text = deck.short.map((s) => s.lack + " " + s.name).join("\n");
    $("#hunt-wants").value = text;
    store.set("hunt", text);
    $("#hunt-source").textContent = "Недостающее из колоды «" + deck.name + "».";
    showTab("hunt");
    toast("В охоту: " + deck.short.length + " назв.");
    return;
  }

  const built = ev.target.closest("#panel-collection [data-built]");
  if (built) {
    try {
      await api("/api/decks/" + built.dataset.built, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assembled: built.checked }),
      });
      await holdLoad();
      toast(built.checked
        ? "Колода отмечена собранной: её карты заняты"
        : "Колода снова на бумаге: её карты свободны");
    } catch (e) {
      toast(e.message, true);
      built.checked = !built.checked;
    }
  }
});
