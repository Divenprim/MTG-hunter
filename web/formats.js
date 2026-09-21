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
    fmtState = { survey: survey, open: open, repl: {}, theme: null, deckId: bdDeck.id };
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

function fmtCardTile(c, action, label, extra) {
  // Плитка шириной 72 px: small (146 px) тут не мылит, а грузится втрое легче,
  // чем normal, -- а плиток на экране может быть три десятка.
  const img = c.image_small || c.image_normal;
  return (
    '<div class="fmtcard">' +
      (img ? '<img loading="lazy" draggable="false" src="' + esc(img) +
             '" alt="' + esc(c.name) + '">' : "") +
      '<div class="fmtcardbody">' +
        "<b>" + esc(c.ru_name || c.name) + "</b>" +
        (c.ru_name ? '<span class="meta">' + esc(c.name) + "</span>" : "") +
        '<span class="meta">' + esc(c.mana_cost || "") + " · " +
          esc((c.type_line || "").split("//")[0]) + "</span>" +
        (extra ? '<span class="meta">' + extra + "</span>" : "") +
        '<button type="button" class="ghost" data-' + action + '="' + esc(c.name) +
          '">' + label + "</button>" +
      "</div>" +
    "</div>"
  );
}

function fmtBlockerRow(b) {
  const key = b.name;
  const repl = fmtState.repl[key];
  let html =
    '<div class="fmtblock">' +
      '<div class="fmtblockhead">' +
        "<b>" + b.quantity + "× " + esc(b.name) + "</b>" +
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
      html += '<p class="meta">по назначению: ' +
        esc((repl.tags || []).join(", ")) + "</p>" +
        '<div class="fmtcards">' +
        repl.cards.map((c) => fmtCardTile(
          c, "swap", "поставить вместо",
          "общих тегов: " + c.shared_tags)).join("") +
        "</div>";
    }
  }
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
