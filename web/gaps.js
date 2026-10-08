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
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
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
  return usd ? ' <span class="meta">$' + usd + "</span>" : "";
}

function gapCard(card) {
  return '<li class="gapcard">' +
    '<button type="button" class="gaplink" data-card="' + esc(card.name) + '">' +
    esc(card.name) + "</button>" +
    ' <span class="meta">' + esc(card.mana_cost || "земля") + "</span>" +
    gapMoney(card) +
    '<button type="button" class="ghost small gapadd" data-add="' +
    esc(card.name) + '">+ в колоду</button></li>';
}

function gapCounted(block) {
  if (!block.counted || !block.counted.length) {
    return '<p class="meta">ни одной карты не сосчитано</p>';
  }
  return '<p class="meta">сосчитано: ' + block.counted.map((c) =>
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

function gapRender() {
  const a = gapData;
  if (!a) return;
  const short = (a.short || []).map((b) =>
    '<div class="gapbox gapshort"><h4>' + esc(b.title) +
    ' <span class="meta">' + b.have + " из " + b.expect + "</span></h4>" +
    '<p class="meta">' + esc(b.why) + "</p>" +
    gapCounted(b) +
    ((b.candidates || []).length
      ? '<ul class="gaplist">' + b.candidates.map(gapCard).join("") + "</ul>"
      : '<p class="meta">подходящего в цвета колоды не нашлось</p>') +
    "</div>").join("");

  const enough = (a.enough || []).map((b) =>
    "<li><b>" + esc(b.title) + "</b> " + b.have + " из " + b.expect +
    gapCounted(b) + "</li>").join("");

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
      await api("/api/decks/" + bdDeck.id + "/cards", {
        method: "POST",
        body: JSON.stringify({ cards: [{ name: name, quantity: 1,
                                         section: "main" }] }),
      });
      toast(name + " в колоде");
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
  const open = ev.target.closest(".gaplink");
  if (open && typeof openCardByName === "function") {
    openCardByName(open.dataset.card);
  }
});
