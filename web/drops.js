"use strict";

/* Secret Lair drop picker.

   Why this exists: `sld` is ONE set holding thousands of cards from hundreds of
   products, and Scryfall has no drop field at all. So "find the Sonic cards"
   cannot be done by name -- "Amy Rose" and "Knuckles the Echidna" contain no
   "sonic", while "Sonic Screwdriver" is a Doctor Who card.

   The backend splits the set into contiguous collector-number runs and lets you
   search a drop by ANY card inside it. Picking one pins the range
   ("s:sld cn>=2081 cn<=2087") onto the query.

   Loaded after app.js and uses its helpers. */

function renderDropChips() {
  const box = $("#f-drop-chips");
  if (!box) return;
  box.innerHTML = selectedDrop
    ? '<span class="chip removable set" data-drop="1">дроп ' +
      esc(selectedDrop.label) + " ×</span>"
    : "";
  $$("#f-drop-list .droprow").forEach((row) => {
    row.classList.toggle("on", !!selectedDrop && row.dataset.query === selectedDrop.query);
  });
}

function dropLabel(drop) {
  return (drop.released || "") + " · #" + drop.first +
    (drop.last !== drop.first ? "-" + drop.last : "");
}

function renderDropList(drops, needle) {
  $("#f-drop-list").innerHTML = drops.map((drop) => {
    const matched = drop.matched || [];
    const rest = drop.names.filter((n) => matched.indexOf(n) < 0);
    const shown = matched.map((n) => '<span class="hit">' + esc(n) + "</span>")
      .concat(rest.slice(0, Math.max(0, 8 - matched.length)).map((n) => esc(n)));
    const more = drop.names.length - Math.min(drop.names.length, shown.length);
    return (
      '<div class="droprow" data-query="' + esc(drop.query) + '" data-label="' +
        esc(dropLabel(drop)) + '">' +
        '<div class="head">' +
          '<span class="rng">#' + drop.first +
            (drop.last !== drop.first ? "-" + drop.last : "") + "</span>" +
          '<span class="dt">' + esc(drop.released || "") + "</span>" +
          '<span class="dt">' + esc((drop.set_code || "").toUpperCase()) + "</span>" +
          '<span class="n">' + drop.count + " карт</span>" +
        "</div>" +
        '<div class="names">' + shown.join(", ") +
          (more > 0 ? " и ещё " + more : "") + "</div>" +
      "</div>"
    );
  }).join("");
  renderDropChips();
}

async function searchDrops(needle) {
  try {
    const r = await api("/api/drops?limit=40&q=" + encodeURIComponent(needle || ""));
    renderDropList(r.drops || [], needle);
    if (needle && !r.total) {
      $("#f-drop-list").innerHTML =
        '<div class="droprow"><div class="names">Ни в одном дропе нет карты с «' +
        esc(needle) + "»</div></div>";
    }
  } catch (e) {
    $("#f-drop-list").innerHTML =
      '<div class="droprow"><div class="names">не удалось загрузить дропы</div></div>';
  }
}

$("#f-drop-input").addEventListener("input", debounce((ev) => {
  searchDrops(ev.target.value.trim());
}, 300));

$("#f-drop-list").addEventListener("click", (ev) => {
  const row = ev.target.closest(".droprow");
  if (!row || !row.dataset.query) return;
  // Clicking the pinned drop again unpins it.
  if (selectedDrop && selectedDrop.query === row.dataset.query) {
    selectedDrop = null;
  } else {
    selectedDrop = { query: row.dataset.query, label: row.dataset.label };
  }
  renderDropChips();
  applyFilterPanel();
});

$("#f-drop-chips").addEventListener("click", () => {
  selectedDrop = null;
  renderDropChips();
  applyFilterPanel();
});

// Show the newest drops straight away, so the list is not an empty box.
searchDrops("");
