"use strict";

/* Goldfishing.

   Two halves, because they answer different questions:

   * "does this deck function on turns 1-4" is a shuffling question, and a
     thousand simulated games answer it far better than dealing one hand.
     Computed on the server.
   * "what does a hand actually look like" wants a real hand you can stare at,
     draw from and mulligan. Done here.

   The simulation's assumptions are printed under the numbers on purpose: a
   simulation that hides them is worse than none. */

let gfDeck = null;
let gfHand = [];
let gfLibrary = [];
let gfHandSize = 7;

function openGoldfish(deck) {
  gfDeck = deck;
  gfHand = [];
  gfLibrary = [];
  gfHandSize = 7;
  $("#gf-title").textContent = "Голдфишинг — " + deck.name;
  $("#gf-hand").innerHTML = "";
  $("#gf-stats").innerHTML = "";
  $("#gf-handinfo").textContent = "";
  $("#gf-overlay").hidden = false;
}

function gfClose() {
  $("#gf-overlay").hidden = true;
  gfDeck = null;
}

$("#gf-close").addEventListener("click", gfClose);
$("#gf-overlay").addEventListener("click", (ev) => {
  if (ev.target === $("#gf-overlay")) gfClose();
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("#gf-overlay").hidden) gfClose();
});

/* ------------------------------------------------------------- the hand -- */

function gfRenderHand() {
  const lands = gfHand.filter((c) => c.is_land).length;
  $("#gf-handinfo").textContent = gfHand.length
    ? "в руке " + gfHand.length + " (земель " + lands + ") · в колоде " + gfLibrary.length
    : "";
  $("#gf-hand").innerHTML = gfHand.map((c) =>
    '<div class="card' + (c.is_land ? " land" : "") + '">' +
      (c.image_small
        ? '<img loading="lazy" src="' + esc(c.image_small) + '" alt="">'
        : '<img alt="">') +
      '<div class="cardname">' + esc(c.name) + "</div>" +
      '<div class="cardfoot"><span>' + esc(c.mana_cost || "") + "</span>" +
      "<span>" + (c.is_land ? "земля" : "МС " + c.cmc) + "</span></div>" +
    "</div>").join("");
}

async function gfDeal(handSize) {
  if (!gfDeck) return;
  try {
    const r = await api("/api/decks/" + gfDeck.id + "/deal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hand_size: handSize }),
    });
    gfHand = r.hand;
    gfLibrary = r.library;
    gfHandSize = handSize;
    gfRenderHand();
  } catch (e) {
    toast(e.message, true);
  }
}

$("#gf-deal").addEventListener("click", () => gfDeal(7));

$("#gf-draw").addEventListener("click", () => {
  if (!gfLibrary.length) return toast("Колода кончилась", true);
  gfHand.push(gfLibrary.shift());
  gfRenderHand();
});

$("#gf-mull").addEventListener("click", () => {
  // London mulligan: always draw seven, then put cards back. We deal the seven
  // and note how many would go to the bottom, which is the decision the player
  // makes -- so the hand shown is the raw seven.
  const next = Math.max(1, gfHandSize - 1);
  gfDeal(7).then(() => {
    gfHandSize = next;
    toast("Муллиган: раздали 7, на дно уйдёт " + (7 - next));
  });
});

/* ------------------------------------------------------------ statistics -- */

$("#gf-run").addEventListener("click", async (ev) => {
  if (!gfDeck) return;
  ev.target.disabled = true;
  $("#gf-stats").innerHTML = '<p class="meta spinner">считаю…</p>';
  try {
    const r = await api("/api/decks/" + gfDeck.id + "/goldfish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ games: parseInt($("#gf-games").value, 10) }),
    });
    gfRenderStats(r.goldfish);
  } catch (e) {
    $("#gf-stats").innerHTML = "";
    toast(e.message, true);
  } finally {
    ev.target.disabled = false;
  }
});

function gfRenderStats(g) {
  const dist = g.land_distribution || {};
  const max = Math.max(1, ...Object.values(dist));
  const bars = Object.keys(dist).map((n) => {
    const count = dist[n];
    const pct = (100 * count / g.games).toFixed(0);
    const keepable = Number(n) >= 2 && Number(n) <= 5;
    return '<div class="b' + (keepable ? " good" : "") + '" style="height:' +
      Math.round((count / max) * 100) + '%">' +
      (count ? "<span>" + pct + "%</span>" : "") +
      "<em>" + n + "</em></div>";
  }).join("");

  const turns = g.playable_by_turn || {};
  const turnRows = Object.keys(turns)
    .map((t) => "ход " + t + " — " + turns[t] + "%")
    .join(" · ");

  $("#gf-stats").innerHTML = '<div class="statgrid">' +
    '<div class="statbox"><h4>Играбельных рук</h4><div class="statbig">' +
      g.keepable_pct + '%</div><div class="meta">2–5 земель в семёрке</div></div>' +
    '<div class="statbox"><h4>Земель в руке</h4><div class="statbig">' +
      g.avg_lands_in_hand + '</div><div class="meta">в колоде ' + g.lands_in_library +
      " из " + g.library + "</div></div>" +
    '<div class="statbox"><h4>Распределение земель в семёрке</h4>' +
      '<div class="gfbar">' + bars + "</div></div>" +
    '<div class="statbox"><h4>3 земли к ходу</h4><div class="statbig">' +
      (g.reach_3_lands.avg_turn == null ? "—" : g.reach_3_lands.avg_turn) +
      '</div><div class="meta">успевает в ' + g.reach_3_lands.pct + '% партий</div></div>' +
    '<div class="statbox"><h4>4 земли к ходу</h4><div class="statbig">' +
      (g.reach_4_lands.avg_turn == null ? "—" : g.reach_4_lands.avg_turn) +
      '</div><div class="meta">успевает в ' + g.reach_4_lands.pct + '% партий</div></div>' +
    '<div class="statbox"><h4>Средняя МС в руке</h4><div class="statbig">' +
      (g.avg_hand_mv == null ? "—" : g.avg_hand_mv) +
      '</div><div class="meta">без земель</div></div>' +
  "</div>" +
  '<p class="meta">Есть что разыграть: ' + esc(turnRows) + "</p>" +
  '<div class="gfnote">Допущения расчёта: ' +
    (g.assumptions || []).map(esc).join("; ") + ".</div>";
}
