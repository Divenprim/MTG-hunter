/* Коллекция как учёт: что есть, что занято и что свободно.

   Список «сколько каких карт у меня» не отвечает на вопрос, ради которого его
   и ведут: можно ли собрать вот эту колоду прямо сейчас. Ответ зависит не
   только от коллекции, но и от того, что уже разобрано по собранным колодам --
   четыре Молнии, лежащие в собранной колоде, для остальных колод не
   существуют.

   Поэтому у колоды есть признак «собрана», а у каждой карты три числа: есть,
   занято, свободно. Считает всё сервер (app/holdings.py), здесь -- показ. */

let holdData = null;
let holdSort = "name";
let holdOnly = "all";

async function holdLoad() {
  try {
    holdData = await api("/api/holdings");
  } catch (e) {
    $("#coll-list").innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
    return;
  }
  holdRenderSummary();
  holdRenderCards();
  holdRenderDecks();
  holdRenderConflicts();
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
    if (!needle) return true;
    if (c.name.toLowerCase().indexOf(needle) >= 0) return true;
    return c.decks.some((d) => d.deck.toLowerCase().indexOf(needle) >= 0);
  });
}

function holdRenderCards() {
  const rows = holdVisible();
  const order = {
    name: (a, b) => a.name.localeCompare(b.name),
    owned: (a, b) => b.owned - a.owned || a.name.localeCompare(b.name),
    free: (a, b) => b.free - a.free || a.name.localeCompare(b.name),
    listed: (a, b) => b.listed - a.listed || a.name.localeCompare(b.name),
    price: (a, b) => b.price - a.price || a.name.localeCompare(b.name),
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

  $("#coll-list").innerHTML = head + (shown.map((c) => {
    const freeClass = c.free < 0 ? " short" : (c.free > 0 ? " spare" : "");
    return '<div class="holdrow">' +
      '<span class="nm">' + esc(c.name) + "</span>" +
      '<span class="num">' + c.owned + "</span>" +
      '<span class="num">' + (c.committed || "") + "</span>" +
      '<span class="num' + freeClass + '">' + c.free + "</span>" +
      "<span>" + holdDeckChips(c) + "</span>" +
      '<span class="num">' + (c.price ? rub(c.price) : "") + "</span>" +
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
  holdRenderCards();
});

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
