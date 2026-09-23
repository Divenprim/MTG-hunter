"use strict";

/* Плейтест: рука, поле, тапы, розыгрыши.

   Голдфишинг рядом отвечает на вопрос «как часто рука играбельна» -- это
   статистика по тысяче раздач. Здесь другое: одна партия, которую вы играете
   руками. Разложить землю, тапнуть её, разыграть заклинание, сбросить лишнее,
   взять карту, начать новый ход. Так проверяют не цифры, а замысел: сходится
   ли колода к четвёртому ходу и чем занят второй.

   Соперника нет и правил программа не знает: она не проверяет, хватает ли
   маны, и не считает урон. Это стол, а не судья -- всё, что можно сделать с
   картой, делает человек. Зато состояние честное: карта лежит ровно там, куда
   её положили, а «отменить» возвращает предыдущий ход мысли.

   Колода приходит перемешанной с сервера (/api/decks/{id}/deal): та же
   раздача, что и в голдфишинге, только целиком -- рука и библиотека по
   порядку. Дальше всё происходит в браузере и никуда не уходит. */

const PT_ZONES = {
  hand: "рука",
  field: "поле",
  grave: "кладбище",
  exile: "изгнание",
  library: "библиотека",
  command: "командная зона",
};

let ptState = null;
let ptHistory = [];
let ptUid = 0;

function ptBox() { return $("#pt-body"); }

function ptSnapshot() {
  // Состояние маленькое -- десятки карт, -- поэтому «отменить» это просто
  // снимок целиком. Никаких обратных операций писать не нужно, и ни одна из
  // них не может разойтись с прямой.
  if (!ptState) return;
  ptHistory.push(JSON.stringify({
    zones: ptState.zones, turn: ptState.turn, life: ptState.life,
    played: ptState.played,
  }));
  if (ptHistory.length > 60) ptHistory.shift();
}

function ptUndo() {
  const last = ptHistory.pop();
  if (!last) return toast("Отменять нечего", true);
  const back = JSON.parse(last);
  ptState.zones = back.zones;
  ptState.turn = back.turn;
  ptState.life = back.life;
  ptState.played = back.played;
  ptRender();
}

function ptCard(entry) {
  return {
    uid: "c" + (++ptUid),
    name: entry.name,
    image_small: entry.image_small || null,
    image_normal: entry.image_normal || null,
    is_land: !!entry.is_land,
    cmc: entry.cmc || 0,
    type_line: entry.type_line || "",
    tapped: false,
    counters: 0,
  };
}

async function ptOpen(deckId) {
  const id = deckId || (typeof bdDeck !== "undefined" && bdDeck ? bdDeck.id : null);
  if (!id) return toast("Сначала откройте колоду", true);
  $("#pt-overlay").hidden = false;
  ptBox().innerHTML = '<p class="meta">тасую…</p>';
  try {
    const deck = (await api("/api/decks/" + id)).deck;
    const dealt = await post("/api/decks/" + id + "/deal", { hand_size: 7 });
    if (dealt.error) throw new Error(dealt.error);
    ptUid = 0;
    ptHistory = [];
    ptState = {
      deckId: id,
      name: deck.name,
      format: deck.format,
      turn: 1,
      life: (deck.format || "").toLowerCase() === "commander" ? 40 : 20,
      played: 0,
      hand_size: 7,
      zones: {
        hand: dealt.hand.map(ptCard),
        library: dealt.library.map(ptCard),
        field: [],
        grave: [],
        exile: [],
        // Командир начинает не в колоде, и в библиотеке его нет -- значит,
        // ему нужно своё место, иначе им просто нельзя сыграть.
        command: (deck.cards || [])
          .filter((c) => c.section === "commander")
          .flatMap((c) => Array.from({ length: c.quantity || 1 }, () => ptCard({
            name: (c.card || {}).name || c.name,
            image_small: (c.card || {}).image_small,
            image_normal: (c.card || {}).image_normal,
            type_line: (c.card || {}).type_line,
            cmc: (c.card || {}).cmc,
            is_land: (((c.card || {}).type_line) || "").toLowerCase().includes("land"),
          }))),
      },
    };
    ptRender();
  } catch (e) {
    ptBox().innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
  }
}

function ptClose() {
  $("#pt-overlay").hidden = true;
}

/* ------------------------------------------------------- действия с картой */

function ptFind(uid) {
  for (const zone of Object.keys(ptState.zones)) {
    const at = ptState.zones[zone].findIndex((c) => c.uid === uid);
    if (at >= 0) return { zone: zone, at: at, card: ptState.zones[zone][at] };
  }
  return null;
}

function ptMove(uid, to, opts) {
  const found = ptFind(uid);
  if (!found) return;
  ptSnapshot();
  const card = ptState.zones[found.zone].splice(found.at, 1)[0];
  card.tapped = !!(opts || {}).tapped;
  if (to !== "field") card.counters = 0;
  if (to === "library") {
    if ((opts || {}).top) ptState.zones.library.unshift(card);
    else ptState.zones.library.push(card);
  } else {
    ptState.zones[to].push(card);
  }
  if (to === "field" && found.zone === "hand") ptState.played += 1;
  ptRender();
}

function ptTap(uid) {
  const found = ptFind(uid);
  if (!found || found.zone !== "field") return;
  ptSnapshot();
  found.card.tapped = !found.card.tapped;
  ptRender();
}

function ptCounter(uid, delta) {
  const found = ptFind(uid);
  if (!found) return;
  ptSnapshot();
  found.card.counters = Math.max(0, (found.card.counters || 0) + delta);
  ptRender();
}

/* --------------------------------------------------------------- действия */

function ptDraw(n) {
  if (!ptState.zones.library.length) return toast("Библиотека кончилась", true);
  ptSnapshot();
  for (let i = 0; i < (n || 1) && ptState.zones.library.length; i++) {
    ptState.zones.hand.push(ptState.zones.library.shift());
  }
  ptRender();
}

function ptUntapAll() {
  ptSnapshot();
  ptState.zones.field.forEach((c) => { c.tapped = false; });
  ptRender();
}

function ptNewTurn() {
  ptSnapshot();
  ptState.turn += 1;
  ptState.zones.field.forEach((c) => { c.tapped = false; });
  if (ptState.zones.library.length) {
    ptState.zones.hand.push(ptState.zones.library.shift());
  }
  ptRender();
}

function ptShuffle() {
  ptSnapshot();
  const lib = ptState.zones.library;
  for (let i = lib.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [lib[i], lib[j]] = [lib[j], lib[i]];
  }
  ptRender();
  toast("Библиотека перемешана");
}

/* Мулиган по-лондонски: рука уходит в библиотеку, тасуем, сдаём семь и
   столько же откладываем вниз. Программа сдаёт семь и говорит, сколько надо
   убрать, -- выбирать, что именно оставить, ваше дело. */
function ptMulligan() {
  ptSnapshot();
  const lib = ptState.zones.library;
  ptState.zones.hand.forEach((c) => lib.push(c));
  ptState.zones.hand = [];
  for (let i = lib.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [lib[i], lib[j]] = [lib[j], lib[i]];
  }
  ptState.hand_size = Math.max(0, (ptState.hand_size || 7) - 1);
  for (let i = 0; i < 7 && lib.length; i++) ptState.zones.hand.push(lib.shift());
  ptRender();
  const put = 7 - ptState.hand_size;
  toast(put > 0
    ? "Мулиган: сдано семь, вниз колоды уберите " + put
    : "Сдана новая рука");
}

async function ptRestart() {
  await ptOpen(ptState.deckId);
}

/* ------------------------------------------------------------- рисование */

function ptCardHtml(card, zone) {
  const menuable = zone !== "library";
  return (
    '<div class="ptcard' + (card.tapped ? " tapped" : "") +
      (card.is_land ? " land" : "") + '" data-uid="' + card.uid +
      '" data-zone="' + zone + '" title="' + esc(card.name) + '"' +
      (card.image_normal ? ' data-preview="' + esc(card.image_normal) + '"' : "") +
      ">" +
      (card.image_small
        ? '<img loading="lazy" draggable="false" src="' + esc(card.image_small) +
          '" alt="' + esc(card.name) + '">'
        : '<span class="ptnoart">' + esc(card.name) + "</span>") +
      (card.counters
        ? '<span class="ptcounter">+' + card.counters + "</span>" : "") +
      (menuable
        ? '<button type="button" class="dots ptmore" data-more="' + card.uid +
          '" title="Что сделать">…</button>'
        : "") +
    "</div>"
  );
}

function ptPile(zone) {
  const cards = ptState.zones[zone];
  const top = cards[cards.length - 1];
  return (
    '<div class="ptpile" data-pile="' + zone + '">' +
      '<div class="ptpilehead"><b>' + esc(PT_ZONES[zone]) + "</b>" +
        '<span class="meta">' + cards.length + "</span></div>" +
      (top && top.image_small
        ? '<img class="ptpiletop" src="' + esc(top.image_small) + '" alt=""' +
          (top.image_normal ? ' data-preview="' + esc(top.image_normal) + '"' : "") +
          ">"
        : '<div class="ptpileempty">пусто</div>') +
      '<button type="button" class="ghost tiny" data-open-pile="' + zone +
        '">посмотреть</button>' +
    "</div>"
  );
}

function ptRender() {
  if (!ptState) return;
  const z = ptState.zones;
  const lands = z.field.filter((c) => c.is_land);
  const rest = z.field.filter((c) => !c.is_land);
  const untapped = lands.filter((c) => !c.tapped).length;

  ptBox().innerHTML =
    '<div class="ptbar">' +
      "<b>" + esc(ptState.name) + "</b>" +
      '<span class="meta">' + esc(ptState.format || "") + "</span>" +
      '<span class="ptturn">ход <b>' + ptState.turn + "</b></span>" +
      '<span class="ptlife">жизни ' +
        '<button type="button" class="ghost tiny" data-life="-1">−</button>' +
        "<b>" + ptState.life + "</b>" +
        '<button type="button" class="ghost tiny" data-life="1">+</button>' +
      "</span>" +
      '<span class="meta">земель развёрнуто ' + untapped + " из " +
        lands.length + "</span>" +
      '<span style="flex:1"></span>' +
      '<button type="button" data-act="turn">Новый ход</button>' +
      '<button type="button" class="ghost" data-act="draw">Взять карту</button>' +
      '<button type="button" class="ghost" data-act="untap">Развернуть всё</button>' +
      '<button type="button" class="ghost" data-act="mulligan">Мулиган</button>' +
      '<button type="button" class="ghost" data-act="shuffle">Перемешать</button>' +
      '<button type="button" class="ghost" data-act="undo">Отменить</button>' +
      '<button type="button" class="ghost" data-act="restart">Заново</button>' +
    "</div>" +

    '<div class="ptfield">' +
      '<div class="ptrow"><span class="ptlabel">не земли</span>' +
        '<div class="ptcards">' +
          (rest.length
            ? rest.map((c) => ptCardHtml(c, "field")).join("")
            : '<span class="meta">пусто — разыграйте карту из руки</span>') +
        "</div></div>" +
      '<div class="ptrow"><span class="ptlabel">земли</span>' +
        '<div class="ptcards">' +
          (lands.length
            ? lands.map((c) => ptCardHtml(c, "field")).join("")
            : '<span class="meta">пусто</span>') +
        "</div></div>" +
    "</div>" +

    '<div class="ptpiles">' +
      ptPile("library") + ptPile("grave") + ptPile("exile") +
      (z.command.length ? ptPile("command") : "") +
    "</div>" +

    '<div class="pthand"><span class="ptlabel">рука ' + z.hand.length +
      "</span>" +
      '<div class="ptcards">' +
        (z.hand.length
          ? z.hand.map((c) => ptCardHtml(c, "hand")).join("")
          : '<span class="meta">рука пуста</span>') +
      "</div>" +
    "</div>" +
    '<p class="meta">Нажатие по карте на поле — тапнуть и развернуть, по карте ' +
      "в руке — разыграть. Правая кнопка или «…» — всё остальное. " +
      "Соперника нет, правил программа не знает: это стол, а не судья.</p>";
}

/* ------------------------------------------------------------- управление */

function ptMenu(uid, x, y) {
  const found = ptFind(uid);
  if (!found) return;
  const card = found.card;
  const zone = found.zone;
  const items = [];

  if (zone === "hand") {
    items.push({ label: "Разыграть", on: () => ptMove(uid, "field") });
    items.push({ label: "Разыграть тапнутой",
                 on: () => ptMove(uid, "field", { tapped: true }) });
  }
  if (zone === "field") {
    items.push({ label: card.tapped ? "Развернуть" : "Тапнуть",
                 on: () => ptTap(uid) });
    items.push({ label: "Жетон +1", on: () => ptCounter(uid, 1) });
    if (card.counters) {
      items.push({ label: "Жетон −1", on: () => ptCounter(uid, -1) });
    }
    items.push({ label: "В руку", on: () => ptMove(uid, "hand") });
  }
  if (zone === "command") {
    items.push({ label: "Разыграть", on: () => ptMove(uid, "field") });
  }
  if (zone === "grave" || zone === "exile") {
    items.push({ label: "В руку", on: () => ptMove(uid, "hand") });
    items.push({ label: "На поле", on: () => ptMove(uid, "field") });
  }

  items.push("-");
  if (zone !== "grave") {
    items.push({ label: "В кладбище", on: () => ptMove(uid, "grave") });
  }
  if (zone !== "exile") {
    items.push({ label: "Изгнать", on: () => ptMove(uid, "exile") });
  }
  items.push({ label: "Наверх колоды",
               on: () => ptMove(uid, "library", { top: true }) });
  items.push({ label: "Вниз колоды", on: () => ptMove(uid, "library") });
  items.push("-");
  items.push({ label: "Открыть карту", hint: "текст, печати, цены",
               on: () => openCardByName(card.name) });

  showCardMenu(x, y, esc(card.name) + ' <span class="meta">' +
    esc(PT_ZONES[zone]) + "</span>", items);
}

function ptShowPile(zone) {
  const cards = ptState.zones[zone];
  if (!cards.length) return toast("Тут пусто", true);
  // Библиотеку показываем по порядку: это не подглядывание, а проверка --
  // «что придёт, если возьму три карты».
  ptBox().insertAdjacentHTML("beforeend",
    '<div class="ptlook"><div class="ptbar"><b>' + esc(PT_ZONES[zone]) +
      "</b><span class=\"meta\">" + cards.length + " карт" +
      (zone === "library" ? " — сверху вниз" : "") + "</span>" +
      '<span style="flex:1"></span>' +
      '<button type="button" class="ghost tiny" data-closelook="1">Закрыть</button>' +
    "</div>" +
    '<div class="ptcards">' +
      cards.map((c) => ptCardHtml(c, zone)).join("") +
    "</div></div>");
}

$("#pt-overlay").addEventListener("click", (ev) => {
  if (ev.target === $("#pt-overlay")) { ptClose(); return; }
  if (!ptState) return;
  const t = ev.target;

  if (t.dataset.closelook) {
    const look = t.closest(".ptlook");
    if (look) look.remove();
    return;
  }

  const more = t.closest("[data-more]");
  if (more) {
    const box = more.getBoundingClientRect();
    ptMenu(more.dataset.more, box.left, box.bottom + 4);
    return;
  }

  const pile = t.closest("[data-open-pile]");
  if (pile) { ptShowPile(pile.dataset.openPile); return; }

  if (t.dataset.life) {
    ptSnapshot();
    ptState.life += parseInt(t.dataset.life, 10);
    ptRender();
    return;
  }

  const act = t.dataset.act;
  if (act === "turn") return ptNewTurn();
  if (act === "draw") return ptDraw(1);
  if (act === "untap") return ptUntapAll();
  if (act === "mulligan") return ptMulligan();
  if (act === "shuffle") return ptShuffle();
  if (act === "undo") return ptUndo();
  if (act === "restart") return ptRestart();

  const card = t.closest(".ptcard");
  if (!card) return;
  // Нажатие по карте -- самое частое действие в зоне, и оно должно быть одним
  // нажатием: на поле это тап, в руке -- розыгрыш.
  if (card.dataset.zone === "field") ptTap(card.dataset.uid);
  else if (card.dataset.zone === "hand") ptMove(card.dataset.uid, "field");
});

$("#pt-overlay").addEventListener("contextmenu", (ev) => {
  const card = ev.target.closest(".ptcard");
  if (!card || !ptState) return;
  ev.preventDefault();
  ptMenu(card.dataset.uid, ev.clientX, ev.clientY);
});

document.addEventListener("keydown", (ev) => {
  if ($("#pt-overlay").hidden || !ptState) return;
  if (ev.target.matches("input, textarea, select")) return;
  const keys = {
    Escape: ptClose, d: () => ptDraw(1), в: () => ptDraw(1),
    u: ptUntapAll, г: ptUntapAll,
    n: ptNewTurn, т: ptNewTurn,
    m: ptMulligan, ь: ptMulligan,
    z: ptUndo, я: ptUndo,
  };
  const run = keys[ev.key] || keys[(ev.key || "").toLowerCase()];
  if (run) { ev.preventDefault(); run(); }
});

$("#pt-close").addEventListener("click", ptClose);
