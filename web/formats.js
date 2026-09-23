/* Форматы: где этой колодой можно играть, а где мешают три карты.

   Вопрос «пойдёт ли модерновая колода в пионер» -- это не да/нет. Почти всегда
   ответ такой: пятнадцать копий вне пула, и вот чем их заменить. Поэтому панель
   устроена как разбор, а не как значок легальности: сначала все форматы разом
   и насколько до каждого далеко, потом по одному -- что мешает, чем заменить,
   и что к колоде добавить, не выходя из пула.

   Сервер считает всё по локальной базе Scryfall (app/formats.py); наружу
   ничего не уходит, и панель можно открывать сколько угодно. */

let fmtState = null;      // {survey, open, repl: {}, theme: null, deckId}

const FMT_VERDICT = {
  fits: ["ok", "играет", "все карты в пуле, правила соблюдены"],
  shape: ["near", "почти", "все карты в пуле — не сходится форма колоды"],
  no: ["no", "", "есть карты вне пула формата"],
};

function fmtPanel() { return $("#bd-formats"); }

async function fmtOpen() {
  if (!bdDeck) return;
  const panel = fmtPanel();
  if (!panel.hidden && fmtState && fmtState.deckId === bdDeck.id) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  panel.innerHTML = '<p class="meta">считаю…</p>';
  await fmtLoad();
}

async function fmtLoad(keepOpen) {
  if (!bdDeck) return;
  const open = keepOpen && fmtState ? fmtState.open : null;
  try {
    const survey = await api("/api/decks/" + bdDeck.id + "/formats");
    fmtState = { survey: survey, open: open, repl: {}, theme: null,
                 plan: null, deckId: bdDeck.id };
    if (!fmtState.open) {
      // Открываем сам собой тот формат, который колода объявила о себе: про
      // него и спрашивают в первую очередь.
      const declared = survey.declared;
      const has = (survey.formats || []).some((f) => f.format === declared);
      fmtState.open = has ? declared : (survey.formats[0] || {}).format || null;
    }
    fmtRender();
  } catch (e) {
    fmtPanel().innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
  }
}

function fmtChip(f) {
  const [cls, note, why] = FMT_VERDICT[f.verdict] || ["no", "", ""];
  const detail = f.verdict === "no" ? f.blocked_copies + " вне пула" : note;
  return (
    '<button type="button" class="fmtchip ' + cls +
      (fmtState.open === f.format ? " on" : "") +
      '" title="' + esc(why) + '" data-fmt="' + esc(f.format) + '">' +
      "<b>" + esc(f.title) + "</b>" +
      (detail ? '<span class="meta">' + esc(detail) + "</span>" : "") +
    "</button>"
  );
}

/* Плитка предложения.

   Картинка шириной 72 px -- это опознавательный знак, а не карта: по ней не
   прочесть ни текста, ни цены, а решение принимается именно по тексту.
   Поэтому плитка целиком нажимается и открывает обычное окно карты, где есть
   всё: правила, обе стороны, легальность во всех форматах, печати, цены и
   кнопки «в колоду», «в избранное», «в охоту». Кнопка «…» -- то же меню, что
   у карты колоды, только для карты, которой в колоде ещё нет. */
function fmtCardTile(c, action, label, extra) {
  const img = c.image_small || c.image_normal;
  return (
    '<div class="fmtcard" data-open="' + esc(c.name) +
        '" title="Открыть карту: текст, печати, цены">' +
      (img ? '<img loading="lazy" draggable="false" src="' + esc(img) +
             '" alt="' + esc(c.name) + '">' : "") +
      '<div class="fmtcardbody">' +
        "<b>" + esc(c.ru_name || c.name) + "</b>" +
        (c.ru_name ? '<span class="meta">' + esc(c.name) + "</span>" : "") +
        '<span class="meta">' + esc(c.mana_cost || "") + " · " +
          esc((c.type_line || "").split("//")[0]) + "</span>" +
        (extra ? '<span class="meta">' + extra + "</span>" : "") +
        '<div class="fmtcardacts">' +
          '<button type="button" class="ghost" data-' + action + '="' + esc(c.name) +
            '">' + label + "</button>" +
          '<button type="button" class="dots" data-suggest="' + esc(c.name) +
            '" title="Что сделать с картой">…</button>' +
        "</div>" +
      "</div>" +
    "</div>"
  );
}

/* Что карта делает -- её назначение, разобранное по делам.

   Тег Scryfall -- английский, и переводить четыре тысячи тегов программа не
   станет; зато у каждого есть описание, и оно показывается подсказкой. Рядом
   -- сколько карт с этим назначением есть в пуле формата: ответ на «не верю,
   что в пионере нет ни одной карты с imprint». Если их и правда нет, так и
   написано. */
function fmtJobs(repl) {
  const jobs = (repl.jobs || []).filter((j) => j.defining);
  if (!jobs.length) return "";
  const empty = jobs.filter((j) => !j.in_pool);
  return (
    '<div class="fmtjobs"><span class="meta">карта делает:</span>' +
    jobs.map((j) =>
      '<span class="jobchip' + (j.in_pool ? "" : " none") + '" title="' +
        esc((j.note || j.label) + " · всего карт: " + j.cards +
            " · в пуле формата: " + j.in_pool) + '">' +
        esc(j.label) +
        '<span class="meta">' + j.in_pool + "</span>" +
      "</span>").join("") +
    (empty.length
      ? '<span class="meta bad">в пуле формата нет карт с назначением: ' +
        empty.map((j) => esc(j.label)).join(", ") + "</span>"
      : "") +
    "</div>"
  );
}

/* Чего замена не умеет. Ради этой строки всё и затевалось: «Blessed Respite»
   -- это туман И возврат кладбища в библиотеку, и замена одним туманом должна
   об этом говорить, а не молчать. */
function fmtCoverage(c) {
  if (!c.misses) return c.shared_tags != null ? "общих тегов: " + c.shared_tags : "";
  const covered = Math.round((c.coverage || 0) * 100);
  if (c.full) return '<b class="good">делает всё то же</b> · ' + covered + "%";
  return covered + "% · <b>не делает:</b> " +
    c.misses.map((m) => esc(m.label)).join(", ");
}

function fmtBlockerRow(b) {
  const key = b.name;
  const repl = fmtState.repl[key];
  let html =
    '<div class="fmtblock">' +
      '<div class="fmtblockhead">' +
        '<button type="button" class="linkish" data-open="' + esc(b.name) + '">' +
          b.quantity + "× " + esc(b.name) + "</button>" +
        '<span class="meta">' + esc(b.text) + "</span>" +
        (b.why === "unknown" ? "" :
          '<button type="button" class="ghost" data-replace="' + esc(b.name) +
          '">чем заменить</button>') +
      "</div>";
  if (repl) {
    if (repl.loading) {
      html += '<p class="meta">подбираю…</p>';
    } else if (!repl.cards || !repl.cards.length) {
      html += '<p class="meta">' + esc(repl.note || "нечем заменить") + "</p>";
    } else {
      html += fmtJobs(repl) +
        '<div class="fmtcards">' +
        repl.cards.map((c) => fmtCardTile(
          c, "swap", "поставить вместо", fmtCoverage(c))).join("") +
        "</div>";
    }
  }
  return html + "</div>";
}

/* Отдельное исполнение той же колоды под другой формат.

   Колода живёт дольше одного формата, и «тот же турбофог, но в пионере» -- это
   не другая колода, а другое исполнение того же замысла. Поэтому вариант
   заводится ответвлением: обе колоды остаются в одном семействе и дальше
   сравниваются в «Версиях» -- что у них общего, что сменное.

   Сначала показывается план, и только потом кнопка. Исходная колода при этом
   не меняется ни на карту: правки уходят в новую. */
function fmtVariantBlock(open) {
  const plan = fmtState.plan;
  let html = '<div class="fmtvariant">';

  if (!plan) {
    html += '<button type="button" class="ghost" data-adapt="1">' +
      "Что нужно, чтобы играть этим в «" + esc(open.title) + "»</button>" +
      '<span class="meta">подберу замены всем мешающим картам разом</span>';
    return html + "</div>";
  }
  if (plan.loading) {
    return html + '<p class="meta">подбираю замены…</p></div>';
  }
  if (plan.format !== open.format) {
    // План смотрели для другого формата -- показывать его здесь нельзя.
    html += '<button type="button" class="ghost" data-adapt="1">' +
      "Что нужно, чтобы играть этим в «" + esc(open.title) + "»</button>";
    return html + "</div>";
  }

  html += "<h4>Вариант под «" + esc(plan.title) + "»</h4>";
  if (plan.ready) {
    html += '<p class="good">Менять нечего: колода проходит как есть.</p>';
  }
  if ((plan.swaps || []).length) {
    html += '<p class="meta">Замены — по назначению карты, ' +
      "в цвете колоды и в пуле формата:</p>" +
      '<ul class="fmtplan">' + plan.swaps.map((sw) =>
        "<li>" + sw.quantity + "× " +
          '<button type="button" class="linkish" data-open="' + esc(sw.name) +
          '">' + esc(sw.name) + "</button> → " +
          '<button type="button" class="linkish" data-open="' + esc(sw.to.name) +
          '">' + esc(sw.to.ru_name || sw.to.name) + "</button>" +
          '<button type="button" class="dots" data-suggest="' + esc(sw.to.name) +
          '" title="Что сделать с картой">…</button>' +
          '<span class="meta">' + esc(sw.text || "") + "</span>" +
          '<div class="meta">' + fmtCoverage(sw.to) + "</div></li>").join("") +
      "</ul>";
  }
  if ((plan.trims || []).length) {
    html += '<p class="meta">Срежется копий:</p><ul class="fmtplan">' +
      plan.trims.map((t) => "<li>" + esc(t.name) + " — " + esc(t.text) +
        "</li>").join("") + "</ul>";
  }
  if ((plan.shelve || []).length) {
    html += '<p class="meta">Замены не нашлось — эти уйдут в «возможно», ' +
      "а не пропадут:</p><ul class=\"fmtplan\">" +
      plan.shelve.map((x) => "<li>" + x.quantity + "× " +
        '<button type="button" class="linkish" data-open="' + esc(x.name) + '">' +
        esc(x.name) + "</button> <span class=\"meta\">" + esc(x.note || "") +
        "</span></li>").join("") + "</ul>";
  }
  if ((plan.shape || []).length) {
    html += '<p class="meta">Это останется на вас — форму колоды программа ' +
      "за вас не выдумывает:</p><ul class=\"fmtplan\">" +
      plan.shape.map((r) => "<li>" + esc(r.text) + "</li>").join("") + "</ul>";
  }
  html += '<div class="row tight">' +
    '<button type="button" data-variant="1">Завести вариант под «' +
      esc(plan.title) + "»</button>" +
    '<span class="meta">новая колода в том же семействе; ' +
      "эта останется как есть</span></div>";
  return html + "</div>";
}

function fmtRender() {
  const panel = fmtPanel();
  const s = fmtState.survey;
  const open = (s.formats || []).find((f) => f.format === fmtState.open)
    || (s.formats || [])[0];

  let html =
    '<div class="fmthead">' +
      "<b>Форматы</b>" +
      '<span class="meta">легальность из локальной базы Scryfall — ' +
      "ничего не спрашивается наружу</span>" +
      '<button type="button" class="ghost" data-fmtclose="1">Закрыть</button>' +
    "</div>" +
    '<div class="fmtchips">' + (s.formats || []).map(fmtChip).join("") + "</div>";

  if (open) {
    html += '<div class="fmtbody">';
    if (open.verdict === "fits") {
      html += '<p class="good">Колода проходит в «' + esc(open.title) +
        "» как есть: все " + open.copies + " копий в пуле, правила соблюдены.</p>";
    } else {
      html += "<p>В «" + esc(open.title) + "»: " + open.legal_copies + " из " +
        open.copies + " копий в пуле" +
        (open.blocked_copies
          ? ", мешают " + open.blocked_copies + " " +
            plural(open.blocked_copies, "копия", "копии", "копий")
          : "") + ".</p>";
    }
    if (open.rules && open.rules.length) {
      html += '<ul class="fmtrules">' +
        open.rules.map((r) => "<li>" + esc(r.text) + "</li>").join("") + "</ul>";
    }
    if (open.blockers && open.blockers.length) {
      html += open.blockers.map(fmtBlockerRow).join("");
    }

    html += fmtVariantBlock(open);

    // Тематика и добавки -- по кнопке: это отдельный проход по базе, и
    // навязывать его тому, кто зашёл только за легальностью, незачем.
    html += '<div class="fmttheme">';
    if (!fmtState.theme) {
      html += '<button type="button" class="ghost" data-theme="1">' +
        "О чём колода и что к ней добавить</button>";
    } else if (fmtState.theme.loading) {
      html += '<p class="meta">смотрю…</p>';
    } else {
      const t = fmtState.theme;
      html += "<p><b>Тематика:</b> " +
        (t.themes || []).map((x) => esc(x.label) + " (" + x.cards + ")").join(" · ") +
        "</p>";
      if ((t.add || []).length) {
        html += '<p class="meta">Из пула «' + esc(t.title) +
          "», в цвете колоды, того же назначения:</p>" +
          '<div class="fmtcards">' +
          t.add.map((c) => fmtCardTile(c, "add", "+ в колоду")).join("") +
          "</div>";
      } else {
        html += '<p class="meta">Добавить нечего — всё подходящее уже в колоде.</p>';
      }
    }
    html += "</div></div>";
  }

  panel.innerHTML = html;
}

fmtPanel().addEventListener("click", async (ev) => {
  const t = ev.target;
  if (!fmtState || !bdDeck) return;

  if (t.dataset.fmtclose) { fmtPanel().hidden = true; return; }

  const chip = t.closest("[data-fmt]");
  if (chip) {
    fmtState.open = chip.dataset.fmt;
    fmtState.repl = {};
    fmtState.theme = null;
    fmtState.plan = null;
    fmtRender();
    return;
  }

  if (t.dataset.replace) {
    const name = t.dataset.replace;
    fmtState.repl[name] = { loading: true };
    fmtRender();
    try {
      fmtState.repl[name] = await api(
        "/api/decks/" + bdDeck.id + "/formats/" + fmtState.open +
        "/replacements?name=" + encodeURIComponent(name));
    } catch (e) {
      fmtState.repl[name] = { cards: [], note: e.message };
    }
    fmtRender();
    return;
  }

  if (t.dataset.theme) {
    fmtState.theme = { loading: true };
    fmtRender();
    try {
      fmtState.theme = await api(
        "/api/decks/" + bdDeck.id + "/formats/" + fmtState.open + "/theme");
    } catch (e) {
      fmtState.theme = { themes: [], add: [], title: "" };
      toast(e.message, true);
    }
    fmtRender();
    return;
  }

  const open_ = t.closest("[data-open]");
  if (open_ && !t.closest("button[data-suggest]") &&
      !t.closest("button[data-swap], button[data-add]")) {
    openCardByName(open_.dataset.open);
    return;
  }

  const more = t.closest("[data-suggest]");
  if (more) {
    const box = more.getBoundingClientRect();
    const block = more.closest(".fmtblock");
    const old = block ? block.querySelector("[data-replace]") : null;
    const name = more.dataset.suggest;
    bdSuggestMenu(name, box.left, box.bottom + 4, old ? [{
      label: "Поставить вместо «" + old.dataset.replace + "»",
      on: () => fmtSwap(old.dataset.replace, name),
    }] : []);
    return;
  }

  if (t.dataset.adapt) {
    fmtState.plan = { loading: true };
    fmtRender();
    try {
      fmtState.plan = await api("/api/decks/" + bdDeck.id + "/formats/" +
        fmtState.open + "/adapt");
    } catch (e) {
      fmtState.plan = null;
      toast(e.message, true);
    }
    fmtRender();
    return;
  }

  if (t.dataset.variant) {
    t.disabled = true;
    try {
      const r = await api("/api/decks/" + bdDeck.id + "/formats/" +
        fmtState.open + "/variant", bdBody("POST", { name: "" }));
      const done = r.applied || {};
      toast("Вариант готов: заменено " + (done.swapped || []).length +
        ", отложено " + (done.shelved || []).length);
      if (r.decks) { bdDecks = r.decks; bdRenderDeckList(); }
      await bdLoadDecks();
      if (r.deck) bdShow(r.deck);
      fmtState = null;
      await fmtLoad();
    } catch (e) {
      toast(e.message, true);
      t.disabled = false;
    }
    return;
  }

  if (t.dataset.swap) {
    const block = t.closest(".fmtblock");
    const old = block ? block.querySelector("[data-replace]") : null;
    if (!old) return;
    await fmtSwap(old.dataset.replace, t.dataset.swap);
    return;
  }

  if (t.dataset.add) {
    await bdCall("/api/decks/" + bdDeck.id + "/cards",
      bdBody("POST", { cards: [{ name: t.dataset.add, quantity: 1, section: "main" }] }),
      "Добавлено: " + t.dataset.add);
    await fmtLoad(true);
  }
});

fmtPanel().addEventListener("contextmenu", (ev) => {
  const tile = ev.target.closest("[data-open]");
  if (!tile) return;
  ev.preventDefault();
  const block = tile.closest(".fmtblock");
  const old = block ? block.querySelector("[data-replace]") : null;
  const name = tile.dataset.open;
  const extra = old && old.dataset.replace !== name ? [{
    label: "Поставить вместо «" + old.dataset.replace + "»",
    on: () => fmtSwap(old.dataset.replace, name),
  }] : [];
  bdSuggestMenu(name, ev.clientX, ev.clientY, extra);
});

/* Замена -- это две правки колоды, и порядок важен: сначала кладём новую
   карту, потом убираем старую. Если что-то сорвётся посередине, колода
   останется с лишней картой, а не без нужной. */
async function fmtSwap(oldName, newName) {
  const rows = bdDeck.cards.filter(
    (c) => ((c.card && c.card.name) || c.name) === oldName && c.section !== "maybe");
  if (!rows.length) return toast("Этой карты в колоде уже нет", true);
  const quantity = rows.reduce((n, r) => n + r.quantity, 0);

  const r = await bdCall("/api/decks/" + bdDeck.id + "/cards",
    bdBody("POST", {
      cards: [{
        name: newName,
        quantity: quantity,
        section: rows[0].section,
        category: rows[0].category || "",
      }],
    }));
  if (!r) return;
  for (const row of rows) {
    await bdCall("/api/decks/" + bdDeck.id + "/cards/" + row.id, { method: "DELETE" });
  }
  toast(quantity + "× «" + oldName + "» → «" + newName + "»");
  await fmtLoad(true);
}
