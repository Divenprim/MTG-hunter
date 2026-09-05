"use strict";

/* ========================================================== small utilities */

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function debounce(fn, ms) {
  let t = null;
  return function () {
    const args = arguments;
    clearTimeout(t);
    t = setTimeout(() => fn.apply(null, args), ms);
  };
}

/* Persist small bits of UI state so a reload does not throw away your work. */
const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem("mtgh." + key);
      return raw == null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  },
  set(key, value) {
    try { localStorage.setItem("mtgh." + key, JSON.stringify(value)); } catch (e) { /* full or blocked */ }
  },
};

let toastTimer = null;
function toast(msg, isError) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", !!isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), isError ? 7000 : 3000);
}

async function api(path, options) {
  const resp = await fetch(path, options);
  let payload = null;
  try { payload = await resp.json(); } catch (e) { /* error page, not JSON */ }
  if (!resp.ok) {
    const detail = (payload && (payload.detail || payload.message)) || resp.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

const post = (path, body) => api(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

async function copyText(text, okMsg) {
  try {
    await navigator.clipboard.writeText(text);
    toast(okMsg || "Скопировано");
    return true;
  } catch (e) {
    toast("Браузер не дал скопировать — выделите текст и нажмите Ctrl+C", true);
    return false;
  }
}

const rub = (n) => Number(n || 0).toLocaleString("ru") + " ₽";

/* Russian counts need the right ending: 1 предложение, 2 предложения,
   5 предложений. "отброшено 1 предложений" is the kind of small wrongness that
   makes a whole interface feel unfinished. */
function plural(n, one, few, many) {
  const abs = Math.abs(Number(n) || 0) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return many;
  if (last > 1 && last < 5) return few;
  if (last === 1) return one;
  return many;
}

const offersWord = (n) => plural(n, "предложение", "предложения", "предложений");

/* topdeck wraps the searched name in <b> inside the seller's line. That markup
   is topdeck's highlighting, not something the seller typed, and escaping it for
   display shows the tags as text: "1 -<b>Lightning Bolt</b> (SP, Magic 2011)".
   So tags come off before the line is shown -- the wording itself is untouched,
   which is the whole point of showing the raw line. */
function plainLine(text) {
  // JS \s already covers the non-breaking spaces topdeck sprinkles in,
  // so collapsing whitespace normalises those too.
  return String(text == null ? "" : text)
    .replace(/<[^>]*>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/* ==================================================================== tabs */

function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + name));
  store.set("tab", name);
}
$$(".tab").forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));

/* ================================================================== status */

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const db = s.db || {};
    if (!db.built) {
      $("#status").innerHTML = '<span style="color:var(--bad)">база карт не собрана — запустите build_db.py</span>';
      return;
    }
    $("#status").textContent =
      db.printings.toLocaleString("ru") + " печатей · " +
      db.russian.toLocaleString("ru") + " рус · коллекция: " +
      (s.collection_cards || 0).toLocaleString("ru") + " шт.";
  } catch (e) {
    $("#status").textContent = "нет связи с сервером";
  }
}

/* ====================================================== query composition */

/* The filter panel writes into the same text box the user can type in, so
   there is exactly one search language. Bare words already typed are kept. */

const TOKEN_PATTERN = /^[a-z_]+(?::|=|!|>=?|<=?)/i;

function bareWords(query) {
  const out = [];
  const re = /"[^"]*"|\S+/g;
  let m;
  while ((m = re.exec(query || ""))) {
    const tok = m[0];
    if (!TOKEN_PATTERN.test(tok)) out.push(tok);
  }
  return out;
}

function readFilterPanel() {
  return {
    colors: $$("#f-colors .cbtn.on").map((b) => b.dataset.c),
    colorMode: $("#f-colormode").value,
    identity: $("#f-identity").checked,
    types: selectedTypes.slice(),
    typeMode: $("#f-typemode").value,
    cmcMin: $("#f-cmc-min").value,
    cmcMax: $("#f-cmc-max").value,
    powMin: $("#f-pow-min").value,
    touMin: $("#f-tou-min").value,
    rarity: $$("#f-rarity input:checked").map((c) => c.value),
    format: $("#f-format").value,
    sets: selectedSets.slice(),
    oracle: $("#f-oracle").value.trim(),
    foil: $("#f-foil").checked,
    flags: selectedFlags.slice(),
    drop: selectedDrop,
    tags: typeof selectedTags !== "undefined" ? selectedTags.slice() : [],
    keywords: typeof selectedKeywords !== "undefined" ? selectedKeywords.slice() : [],
  };
}

function composeQuery() {
  const f = readFilterPanel();
  const parts = bareWords($("#search-q").value);

  if (f.colors.length) {
    const key = f.identity ? "id" : "c";
    const letters = f.colors.join("").toLowerCase();
    parts.push(key + f.colorMode + letters);
  }

  if (f.types.length) {
    const types = f.types.map((t) => t.toLowerCase());
    if (f.typeMode === "or") {
      // one token, comma list -> OR
      parts.push("t:" + types.join(","));
    } else {
      // separate tokens -> AND, so "Legendary" + "Dragon" means both
      types.forEach((t) => parts.push("t:" + t));
    }
  }

  if (f.cmcMin !== "") parts.push("cmc>=" + f.cmcMin);
  if (f.cmcMax !== "") parts.push("cmc<=" + f.cmcMax);
  if (f.powMin !== "") parts.push("pow>=" + f.powMin);
  if (f.touMin !== "") parts.push("tou>=" + f.touMin);

  if (f.rarity.length) parts.push("r:" + f.rarity.join(","));
  if (f.format) parts.push("f:" + f.format);
  if (f.sets.length) parts.push("s:" + f.sets.join(","));
  if (f.oracle) parts.push('o:"' + f.oracle.replace(/"/g, "") + '"');
  if (f.foil) parts.push("is:foil");
  (f.flags || []).forEach((flag) => parts.push("is:" + flag));
  if (f.drop) parts.push(f.drop.query);
  // Purpose tags: separate tokens so several themes AND together
  // ("ramp" AND "mana-rock"), which is what picking two of them means.
  (f.tags || []).forEach((slug) => parts.push("otag:" + slug));
  // Several keywords mean "any of these", which is how a keyword filter reads.
  if ((f.keywords || []).length) parts.push("kw:" + f.keywords.join(","));

  return parts.join(" ").trim();
}

function applyFilterPanel() {
  $("#search-q").value = composeQuery();
  store.set("filters", readFilterPanel());
  runSearch(true);
}

function resetFilterPanel() {
  $$("#f-colors .cbtn").forEach((b) => b.classList.remove("on"));
  $("#f-colormode").value = ":";
  $("#f-identity").checked = false;
  selectedTypes = [];
  renderTypeChips();
  $("#f-typemode").value = "and";
  $$("#f-rarity input").forEach((c) => (c.checked = false));
  $("#f-cmc-min").value = "";
  $("#f-cmc-max").value = "";
  $("#f-pow-min").value = "";
  $("#f-tou-min").value = "";
  $("#f-format").value = "";
  $("#f-oracle").value = "";
  $("#f-foil").checked = false;
  selectedFlags = [];
  renderFlags();
  selectedDrop = null;
  if (typeof renderDropChips === 'function') renderDropChips();
  if (typeof selectedTags !== "undefined") {
    selectedTags = [];
    if (typeof renderTagChips === "function") renderTagChips();
  }
  if (typeof selectedKeywords !== "undefined") {
    selectedKeywords = [];
    if (typeof renderKeywordChips === "function") renderKeywordChips();
  }
  selectedSets = [];
  renderSetChips();
  renderSetList("");
  $("#search-q").value = bareWords($("#search-q").value).join(" ");
  store.set("filters", readFilterPanel());
  runSearch(true);
}

function restoreFilterPanel(f) {
  if (!f) return;
  (f.colors || []).forEach((c) => {
    const btn = $('#f-colors .cbtn[data-c="' + c + '"]');
    if (btn) btn.classList.add("on");
  });
  if (f.colorMode) $("#f-colormode").value = f.colorMode;
  $("#f-identity").checked = !!f.identity;
  selectedTypes = (f.types || []).slice();
  renderTypeChips();
  if (f.typeMode) $("#f-typemode").value = f.typeMode;
  $$("#f-rarity input").forEach((c) => (c.checked = (f.rarity || []).indexOf(c.value) >= 0));
  $("#f-cmc-min").value = f.cmcMin || "";
  $("#f-cmc-max").value = f.cmcMax || "";
  $("#f-pow-min").value = f.powMin || "";
  $("#f-tou-min").value = f.touMin || "";
  $("#f-oracle").value = f.oracle || "";
  $("#f-foil").checked = !!f.foil;
  selectedFlags = (f.flags || []).slice();
  renderFlags();
  selectedDrop = f.drop || null;
  if (typeof renderDropChips === 'function') renderDropChips();
  if (typeof selectedTags !== "undefined") {
    selectedTags = (f.tags || []).slice();
    if (typeof renderTagChips === "function") renderTagChips();
  }
  if (typeof selectedKeywords !== "undefined") {
    selectedKeywords = (f.keywords || []).slice();
    if (typeof renderKeywordChips === "function") renderKeywordChips();
  }
  selectedSets = (f.sets || []).slice();
  renderSetChips();
  renderSetList("");
}

/* ------------------------------------------------------------- type tokens */

/* Types are ADDED, not ticked: you type, pick from the suggestion list, and
   each type becomes a removable token. A fixed checkbox grid can only ever
   offer the handful of card types and never the 681 subtypes. */

let selectedTypes = [];
let typeVocab = { types: [], subtypes: [], all: [] };

/* A chosen Secret Lair drop, kept as a query fragment ("s:sld cn>=2081
   cn<=2087"). Held separately so touching another filter cannot silently drop
   the collector-number range. */
let selectedDrop = null;

const QUICK_TYPES = [
  ["Creature", "Существо"],
  ["Instant", "Мгновенное"],
  ["Sorcery", "Волшебство"],
  ["Artifact", "Артефакт"],
  ["Enchantment", "Чары"],
  ["Land", "Земля"],
  ["Planeswalker", "Мироходец"],
  ["Battle", "Битва"],
  ["Legendary", "Легендарное"],
];

function renderTypeChips() {
  $("#f-type-chips").innerHTML = selectedTypes
    .map((t) => '<span class="chip removable type" data-type="' + esc(t) + '">' +
      esc(t) + " ×</span>")
    .join("");
  $$("#f-type-quick button").forEach((b) => {
    b.classList.toggle("on", selectedTypes.indexOf(b.dataset.type) >= 0);
  });
}

function addType(raw) {
  const wanted = String(raw || "").trim();
  if (!wanted) return false;
  // Accept any case, but store the vocabulary's own spelling.
  const hit = typeVocab.all.find((t) => t.toLowerCase() === wanted.toLowerCase()) ||
    typeVocab.all.find((t) => t.toLowerCase().indexOf(wanted.toLowerCase()) === 0);
  const value = hit || wanted;
  if (selectedTypes.some((t) => t.toLowerCase() === value.toLowerCase())) return true;
  selectedTypes.push(value);
  renderTypeChips();
  return true;
}

function renderQuickTypes() {
  $("#f-type-quick").innerHTML = QUICK_TYPES
    .map(([en, ru]) => '<button type="button" data-type="' + esc(en) + '" title="' +
      esc(en) + '">' + esc(ru) + "</button>")
    .join("");
  renderTypeChips();
}

$("#f-type-quick").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  const value = btn.dataset.type;
  const at = selectedTypes.findIndex((t) => t.toLowerCase() === value.toLowerCase());
  if (at >= 0) selectedTypes.splice(at, 1);
  else selectedTypes.push(value);
  renderTypeChips();
  applyFilterPanel();
});

$("#f-type-chips").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip.removable");
  if (!chip) return;
  selectedTypes = selectedTypes.filter((t) => t !== chip.dataset.type);
  renderTypeChips();
  applyFilterPanel();
});

$("#f-type-input").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  ev.preventDefault();
  if (addType(ev.target.value)) {
    ev.target.value = "";
    applyFilterPanel();
  }
});

// Picking from the browser's datalist fires `change`, not Enter.
$("#f-type-input").addEventListener("change", (ev) => {
  const value = ev.target.value.trim();
  if (!value) return;
  if (typeVocab.all.some((t) => t.toLowerCase() === value.toLowerCase())) {
    addType(value);
    ev.target.value = "";
    applyFilterPanel();
  }
});

async function loadTypes() {
  try {
    const r = await api("/api/types");
    typeVocab = { types: r.types || [], subtypes: r.subtypes || [], all: r.all || [] };
    $("#typelist").innerHTML = typeVocab.all
      .map((t) => '<option value="' + esc(t) + '"></option>')
      .join("");
  } catch (e) { /* free text still works */ }
  renderQuickTypes();
}

/* -------------------------------------------------------------- set chips */

let selectedSets = [];
let setIndex = [];

function renderSetChips() {
  $("#f-set-chips").innerHTML = selectedSets
    .map((code) => {
      const group = SET_GROUPS.find(([value]) => value === code);
      const label = group ? group[1] : code.toUpperCase();
      return '<span class="chip removable set" data-set="' + esc(code) + '">' +
        esc(label) + " ×</span>";
    })
    .join("");
  syncSetQuick();
}

/* Named groups the query language understands, so "Secret Lair" is one click
   instead of remembering that it spans sld / slc / slp / slu / pssc. */
const SET_GROUPS = [
  ["secretlair", "Secret Lair"],
];

const SET_TYPE_QUICK = [
  ["expansion", "Основные сеты"],
  ["core", "Core"],
  ["masters", "Masters"],
  ["commander", "Commander"],
];

$("#f-set-chips").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip.removable");
  if (!chip) return;
  selectedSets = selectedSets.filter((c) => c !== chip.dataset.set);
  renderSetChips();
  renderSetList($("#f-set-input").value);
  applyFilterPanel();
});

function toggleSet(code) {
  const at = selectedSets.indexOf(code);
  if (at >= 0) selectedSets.splice(at, 1);
  else selectedSets.push(code);
  renderSetChips();
}

/* The list is the picker. 988 sets do not fit a dropdown, and demanding an
   exact code typed from memory is what made this filter unusable. */
function renderSetList(filter) {
  const text = String(filter || "").trim().toLowerCase();
  let rows = setIndex;
  if (text) {
    rows = setIndex.filter((s) =>
      (s.set_code || "").indexOf(text) === 0 ||
      (s.set_name || "").toLowerCase().indexOf(text) >= 0);
  }
  rows = rows.slice(0, 60);
  $("#f-set-list").innerHTML = rows.map((s) => {
    const on = selectedSets.indexOf(s.set_code) >= 0;
    const year = (s.released || "").slice(0, 4);
    return '<div class="setrow' + (on ? " on" : "") + '" data-set="' + esc(s.set_code) + '">' +
      '<span class="code">' + esc(s.set_code) + "</span>" +
      '<span class="nm">' + esc(s.set_name || "") + "</span>" +
      '<span class="yr">' + esc(year) + "</span>" +
      '<span class="cnt">' + s.cards + "</span>" +
      "</div>";
  }).join("");
}

$("#f-set-list").addEventListener("click", (ev) => {
  const row = ev.target.closest(".setrow");
  if (!row) return;
  toggleSet(row.dataset.set);
  renderSetList($("#f-set-input").value);
  applyFilterPanel();
});

$("#f-set-input").addEventListener("input", debounce((ev) => {
  renderSetList(ev.target.value);
}, 180));

$("#f-set-input").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  ev.preventDefault();
  // Enter takes the first row of the current list.
  const first = $("#f-set-list .setrow");
  if (!first) return toast("Ни один сет не подходит", true);
  toggleSet(first.dataset.set);
  ev.target.value = "";
  renderSetList("");
  applyFilterPanel();
});

function renderSetQuick() {
  const groups = SET_GROUPS.map(([value, label]) =>
    '<button type="button" data-group="' + esc(value) + '">' + esc(label) + "</button>");
  const types = SET_TYPE_QUICK
    .filter(([t]) => setIndex.some((s) => s.set_type === t))
    .map(([value, label]) =>
      '<button type="button" data-settype="' + esc(value) + '">' + esc(label) + "</button>");
  $("#f-set-quick").innerHTML = groups.concat(types).join("");
  syncSetQuick();
}

function syncSetQuick() {
  $$("#f-set-quick button[data-group]").forEach((b) => {
    b.classList.toggle("on", selectedSets.indexOf(b.dataset.group) >= 0);
  });
  $$("#f-set-quick button[data-settype]").forEach((b) => {
    b.classList.remove("on");
  });
}

$("#f-set-quick").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  if (btn.dataset.group) {
    // Groups go into the query by name; the backend expands them.
    toggleSet(btn.dataset.group);
  } else if (btn.dataset.settype) {
    // Filter the visible list to that kind of set rather than selecting 300.
    const wanted = btn.dataset.settype;
    const rows = setIndex.filter((s) => s.set_type === wanted).slice(0, 60);
    $("#f-set-list").innerHTML = rows.map((s) => {
      const on = selectedSets.indexOf(s.set_code) >= 0;
      return '<div class="setrow' + (on ? " on" : "") + '" data-set="' + esc(s.set_code) + '">' +
        '<span class="code">' + esc(s.set_code) + "</span>" +
        '<span class="nm">' + esc(s.set_name || "") + "</span>" +
        '<span class="yr">' + esc((s.released || "").slice(0, 4)) + "</span>" +
        '<span class="cnt">' + s.cards + "</span></div>";
    }).join("");
    return;
  }
  renderSetList($("#f-set-input").value);
  applyFilterPanel();
});

async function loadSets() {
  try {
    const r = await api("/api/sets");
    setIndex = r.sets || [];
  } catch (e) { /* codes can still be typed into the query box */ }
  renderSetQuick();
  renderSetList("");
}

/* ------------------------------------------------------- printing flags */

/* Secret Lair is mostly about the treatment, so these belong next to it. */
const FLAG_OPTIONS = [
  ["borderless", "без рамки"],
  ["showcase", "showcase"],
  ["extendedart", "расширенный арт"],
  ["fullart", "во всю карту"],
  ["textless", "без текста"],
  ["etched", "etched"],
  ["serialized", "серийная"],
  ["galaxyfoil", "galaxy foil"],
  ["surgefoil", "surge foil"],
  ["promo", "промо"],
];

let selectedFlags = [];

function renderFlags() {
  $("#f-flags").innerHTML = FLAG_OPTIONS
    .map(([value, label]) => '<button type="button" data-flag="' + esc(value) + '"' +
      (selectedFlags.indexOf(value) >= 0 ? ' class="on"' : "") + ">" + esc(label) + "</button>")
    .join("");
}

$("#f-flags").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  const at = selectedFlags.indexOf(btn.dataset.flag);
  if (at >= 0) selectedFlags.splice(at, 1);
  else selectedFlags.push(btn.dataset.flag);
  renderFlags();
  applyFilterPanel();
});

async function loadFormats() {
  try {
    const r = await api("/api/formats");
    const sel = $("#f-format");
    (r.formats || []).forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      sel.appendChild(opt);
    });
  } catch (e) { /* leave "любой" only */ }
}

/* ================================================================= search */

let searchOffset = 0;
let searchTotal = 0;
const PAGE = 60;
let lastCards = [];

/* Every search gets a ticket; only the newest one may touch the DOM.
   Without this, live typing / applying filters / changing the sort fire
   overlapping requests, and a slow earlier response lands after a later one
   has already cleared the grid -- appending its cards to the wrong result set
   (duplicated pages, or cards from a query the user has moved on from). */
let searchTicket = 0;

/* ============================================================== density ====

   The grid used to be fixed at 180px tiles: on a 1280x800 laptop that is six
   cards fully visible out of six hundred results, so finding the card you
   searched for meant scrolling. Now the tile size is a choice, and the default
   is dense enough to see a couple of dozen at once. The big picture is one
   hover away, which is what makes dense tiles usable at all. */

const DENSITIES = ["tight", "snug", "roomy"];

function applyDensity(mode) {
  const use = DENSITIES.indexOf(mode) >= 0 ? mode : "snug";
  document.body.dataset.density = use;
  $$("#search-density button").forEach((b) => {
    b.classList.toggle("on", b.dataset.density === use);
  });
  store.set("density", use);
}

$("#search-density").addEventListener("click", (ev) => {
  const mode = ev.target.dataset && ev.target.dataset.density;
  if (mode) applyDensity(mode);
});

applyDensity(store.get("density", "snug"));

/* ======================================================== hover preview ====

   Reading a card should not require opening anything. Rest the pointer on any
   tile (search result, printing row, deck row, an offer's thumbnail) and the
   full-size card appears beside it.

   Anything carrying data-preview="<image url>" takes part; data-preview2 adds
   the back face, so double-faced cards show both sides at once. One delegated
   listener, so tiles rendered later work without re-wiring.

   data-full and data-img count too: the plan's thumbnails, the favourites and
   the printings table already carry the big image for their click handlers, so
   they get the preview for free rather than each renderer repeating itself.

   Deliberate details:
     * a short delay, otherwise the panel flickers while the pointer crosses
       the grid on its way somewhere else;
     * it flips to the other side of the tile near the window edge and is
       clamped vertically, so it is never half off-screen;
     * scrolling, clicking and Esc dismiss it -- a preview must never sit on
       top of what you are trying to reach;
     * skipped entirely without a fine pointer (touch), where hover is a lie.
*/

const HOVER_DELAY = 120;
const PREVIEW_SEL = "[data-preview], [data-full], tr[data-img]";

/* The image to show for an element, whichever attribute it keeps it in. */
function previewSrc(el) {
  return el.dataset.preview || el.dataset.full || el.dataset.img || "";
}

/* The thumbnail this element already displays. Scryfall's full-size картинка
   can take several seconds on a cold cache, and waiting for it means pressing
   an arrow key and seeing nothing at all. The small one is on screen already,
   so it goes up instantly, upscaled into the right frame, and is swapped for
   the sharp version the moment it arrives. */
function previewThumb(el) {
  const img = el.tagName === "IMG" ? el : el.querySelector("img");
  return (img && (img.currentSrc || img.src)) || "";
}
const canHover = window.matchMedia
  && window.matchMedia("(hover: hover) and (pointer: fine)").matches;

let hoverTimer = null;
let hoverTarget = null;
// Whether the preview belongs to the pointer or to the keyboard cursor. It
// decides what scrolling means: the pointer has left the tile behind, so hide;
// the cursor moved WITH the page (scrollIntoView fires a scroll event), so the
// panel just needs re-placing. Without this, arrow keys never showed a preview
// at all -- their own scroll dismissed it.
let previewSource = "hover";

function hidePreview() {
  clearTimeout(hoverTimer);
  hoverTimer = null;
  hoverTarget = null;
  const box = $("#hoverpreview");
  if (box) box.hidden = true;
}

function placePreview(box, anchor) {
  const gap = 14;
  const margin = 8;
  const a = anchor.getBoundingClientRect();
  const w = box.offsetWidth;
  const h = box.offsetHeight;

  // To the right of the tile, unless it would not fit -- then to the left, and
  // if neither side fits, over the widest free side.
  let left = a.right + gap;
  if (left + w > window.innerWidth - margin) {
    const leftSide = a.left - gap - w;
    left = leftSide >= margin
      ? leftSide
      : Math.max(margin, Math.min(window.innerWidth - w - margin, a.left));
  }

  // Vertically centred on the tile, then pulled inside the window -- but never
  // over the sticky search row: covering the field you are typing into is
  // exactly the kind of "helpful" panel that gets in the way.
  const bar = document.querySelector(".panel.active .toolbar");
  const ceiling = bar ? Math.max(margin, bar.getBoundingClientRect().bottom + 4) : margin;
  let top = a.top + a.height / 2 - h / 2;
  top = Math.max(ceiling, Math.min(window.innerHeight - h - margin, top));

  box.style.left = Math.round(left) + "px";
  box.style.top = Math.round(top) + "px";
}

function showPreview(el, how) {
  const box = $("#hoverpreview");
  if (!box) return;
  previewSource = how || "hover";
  const front = previewSrc(el);
  if (!front) return;
  const back = el.dataset.preview2;

  const thumb = previewThumb(el);
  box.className = back ? "two" : "";
  box.innerHTML =
    '<img src="' + esc(thumb || front) + '" alt="">' +
    (back ? '<img src="' + esc(back) + '" alt="">' : "");

  // Up straight away: the frame keeps the card's proportions in CSS, so it is
  // the right size and shape from the first frame, never a sliver.
  box.hidden = false;
  placePreview(box, el);

  // Then quietly upgrade to the full-size picture.
  const shown = box.querySelector("img");
  if (thumb && front && front !== thumb) {
    const full = new Image();
    full.onload = () => {
      if (box.hidden || hoverTarget !== el) return;
      shown.src = front;
      placePreview(box, el);
    };
    full.src = front;
  }

  // The second face arrives later; re-place so the pair stays on screen.
  Array.prototype.forEach.call(box.querySelectorAll("img"), (img) => {
    img.addEventListener("load", () => {
      if (!box.hidden && hoverTarget === el) placePreview(box, el);
    });
  });
}

if (canHover) {
  document.addEventListener("mouseover", (ev) => {
    const el = ev.target.closest && ev.target.closest(PREVIEW_SEL);
    if (!el || el === hoverTarget || !previewSrc(el)) return;
    clearTimeout(hoverTimer);
    hoverTarget = el;
    hoverTimer = setTimeout(() => {
      if (hoverTarget === el && el.isConnected) showPreview(el);
    }, HOVER_DELAY);
  });

  document.addEventListener("mouseout", (ev) => {
    const el = ev.target.closest && ev.target.closest(PREVIEW_SEL);
    if (!el || el !== hoverTarget) return;
    // Leaving for a child of the same tile is not leaving.
    if (ev.relatedTarget && el.contains(ev.relatedTarget)) return;
    hidePreview();
  });

  window.addEventListener("scroll", () => {
    const box = $("#hoverpreview");
    if (!box || box.hidden) return;
    if (previewSource === "keys" && hoverTarget && hoverTarget.isConnected) {
      placePreview(box, hoverTarget);
      return;
    }
    hidePreview();
  }, { passive: true });
  document.addEventListener("click", hidePreview);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") hidePreview();
  });
}

function cardTile(c) {
  const price = c.prices && (c.prices.usd || c.prices.usd_foil);
  const img = c.image_small || (c.faces && c.faces[0] && c.faces[0].image_small);
  // display_name is the face that actually matched the query, so searching
  // "Petty Theft" is labelled "Petty Theft", not "Brazen Borrower // ...".
  const title = c.display_name || c.name;
  const isFace = c.matched_face != null;
  const big = c.image_normal || (c.faces && c.faces[0] && c.faces[0].image_normal) || img;
  const back = c.faces && c.faces[1] && c.faces[1].image_normal;
  return (
    '<div class="card" data-id="' + esc(c.id) + '"' +
      (big ? ' data-preview="' + esc(big) + '"' : "") +
      (back ? ' data-preview2="' + esc(back) + '"' : "") + ">" +
    (img
      ? '<img loading="lazy" src="' + esc(img) + '" alt="' + esc(title) + '">'
      : '<img alt="">') +
    '<div class="cardname">' + esc(title) + "</div>" +
    (isFace
      ? '<div class="cardru">сторона карты ' + esc(c.name) + "</div>"
      : c.flavor_name
        // On the card it is printed under this name -- the real name is the
        // small print. Show both so the card is recognisable either way.
        ? '<div class="cardru">напечатана как «' + esc(c.flavor_name) + "»</div>"
        : (c.ru_name ? '<div class="cardru">' + esc(c.ru_name) + "</div>" : "")) +
    '<div class="cardfoot"><span>' + esc((c.set_code || "").toUpperCase()) +
    " · " + esc(c.rarity || "") + "</span>" +
    (price ? "<span>$" + esc(price) + "</span>" : "") +
    "</div>" +
    // Adding a card should not require opening it. These appear on hover and
    // sit on the tile itself, so the preview (pointer-events: none) never
    // steals the click.
    '<div class="quick">' +
      '<button class="q-hunt" title="В охоту, 1 шт.">+ охота</button>' +
      '<button class="q-fav" title="В избранное, 1 шт.">★</button>' +
    "</div>" +
    "</div>"
  );
}

async function runSearch(reset) {
  const q = $("#search-q").value.trim();
  const sort = $("#search-sort").value;
  store.set("query", q);
  store.set("sort", sort);

  const ticket = ++searchTicket;

  if (reset) {
    searchOffset = 0;
    lastCards = [];
    $("#search-results").innerHTML = "";
    // A new query means a new result set: the keyboard cursor from the old one
    // would point at a card that is no longer there.
    gridCursor = -1;
    hidePreview();
  }
  $("#search-meta").innerHTML = '<span class="spinner">ищу…</span>';

  try {
    const r = await api("/api/search?limit=" + PAGE + "&offset=" + searchOffset +
      "&sort=" + encodeURIComponent(sort) + "&q=" + encodeURIComponent(q));

    // A newer search started while this one was in flight: drop the result.
    if (ticket !== searchTicket) return;

    // Later pages omit `total` (it costs a second full query server-side).
    if (r.total != null) searchTotal = r.total;
    lastCards = lastCards.concat(r.cards);
    $("#search-results").insertAdjacentHTML("beforeend", r.cards.map(cardTile).join(""));

    const shown = lastCards.length;
    $("#search-meta").textContent = shown
      ? "показано " + shown + " из " + searchTotal
      : "ничего не найдено";
    $("#search-more").hidden = shown >= searchTotal;
  } catch (e) {
    if (ticket !== searchTicket) return;
    $("#search-meta").textContent = "";
    toast("Поиск не удался: " + e.message, true);
  }
}

const runSearchDebounced = debounce(() => runSearch(true), 400);

$("#search-q").addEventListener("input", runSearchDebounced);
$("#search-q").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") { ev.preventDefault(); runSearch(true); }
});
$("#search-sort").addEventListener("change", () => runSearch(true));
$("#search-more").addEventListener("click", async (ev) => {
  // Guard against a double click: two requests would advance the offset twice
  // while only one page gets appended, silently skipping results.
  if (ev.target.disabled) return;
  ev.target.disabled = true;
  searchOffset = lastCards.length;
  try {
    await runSearch(false);
  } finally {
    ev.target.disabled = false;
  }
});

$("#filters-toggle").addEventListener("click", (ev) => {
  const panel = $("#filters-panel");
  panel.hidden = !panel.hidden;
  ev.target.setAttribute("aria-expanded", String(!panel.hidden));
  store.set("filtersOpen", !panel.hidden);
});
$("#filters-apply").addEventListener("click", applyFilterPanel);
$("#filters-reset").addEventListener("click", resetFilterPanel);
$("#f-colors").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".cbtn");
  if (btn) btn.classList.toggle("on");
});

$("#search-results").addEventListener("click", (ev) => {
  const tile = ev.target.closest(".card");
  if (!tile) return;
  const card = lastCards.find((c) => c.id === tile.dataset.id);
  if (!card) return;

  const at = gridTiles().indexOf(tile);
  if (at >= 0) {
    gridCursor = at;
    gridTiles().forEach((t, k) => t.classList.toggle("cursor", k === at));
  }

  // Quick actions first: they must not also open the card.
  if (ev.target.closest(".q-hunt")) {
    addToHunt(card.name, 1);
    return;
  }
  if (ev.target.closest(".q-fav")) {
    // No printing pinned from here: the tile is one printing of many, and the
    // печать that arrives is whatever the topdeck parser decides anyway.
    addToFavourites(card, 1, null);
    return;
  }
  openCard(card);
});

/* ============================================================= card modal */

let modalCard = null;
let modalFace = 0;
let modalPrinting = null;  // printing picked from the table, if any

function faceImage(card, faceIndex) {
  const faces = card.faces || [];
  const f = faces[faceIndex];
  // Adventure / split / flip cards are one physical card: Scryfall gives no
  // per-face image, so fall back to the card-level art.
  if (f && f.image_normal) return f.image_normal;
  return card.image_normal || card.image_small || "";
}

function legalityChips(legalities) {
  const order = ["standard", "pioneer", "modern", "legacy", "vintage", "commander", "pauper", "premodern"];
  return order
    .filter((f) => legalities && legalities[f])
    .map((f) => {
      const ok = legalities[f] === "legal";
      return '<span class="chip ' + (ok ? "ok" : "no") + '">' + esc(f) +
        (ok ? "" : ": " + esc(legalities[f])) + "</span>";
    })
    .join("");
}

function renderModal() {
  const c = modalCard;
  const faces = c.faces || [];
  const face = faces[modalFace] || {};
  const name = faces.length > 1 ? (face.name || c.name) : c.name;
  const typeLine = (faces.length > 1 ? face.type_line : c.type_line) || c.type_line || "";
  const rules = (faces.length > 1 ? face.oracle_text : c.oracle_text) || c.oracle_text || "";
  const mana = (faces.length > 1 ? face.mana_cost : c.mana_cost) || "";
  const pt = face.power || c.power
    ? ((face.power || c.power) + "/" + (face.toughness || c.toughness))
    : "";

  const canFlip = faces.length > 1;

  $("#modal-body").innerHTML =
    '<div class="cardview">' +
      '<div class="art">' +
        '<img id="modal-art" src="' + esc(faceImage(c, modalFace)) + '" alt="' + esc(name) + '">' +
        (canFlip
          ? '<div class="row tight"><button id="modal-flip" class="ghost">Перевернуть → ' +
            esc((faces[(modalFace + 1) % faces.length] || {}).name || "") + "</button></div>"
          : "") +
      "</div>" +
      "<div>" +
        "<h2>" + esc(name) + "</h2>" +
        (c.flavor_name
          ? '<div class="runame">напечатана как «' + esc(c.flavor_name) + "»</div>"
          : "") +
        (c.ru_name ? '<div class="runame">' + esc(c.ru_name) + "</div>" : "") +
        '<div class="typeline">' + esc(typeLine) +
          (mana ? " · " + esc(mana) : "") +
          (pt ? " · " + esc(pt) : "") +
        "</div>" +
        (rules ? '<div class="rules">' + esc(rules) + "</div>" : "") +
        '<div class="legal">' + legalityChips(c.legalities) + "</div>" +
        '<div class="qtyadd">' +
          "<span>В охоту:</span>" +
          [1, 2, 3, 4].map((n) => '<button class="add-hunt" data-n="' + n + '">' + n + " шт.</button>").join("") +
          '<button id="modal-prices" class="ghost">Цены на topdeck</button>' +
          '<button id="modal-combos-btn" class="ghost">Комбо с этой картой</button>' +
        "</div>" +
        '<div class="qtyadd">' +
          "<span>В избранное:</span>" +
          [1, 2, 3, 4].map((n) => '<button class="add-fav" data-n="' + n + '">' + n + " шт.</button>").join("") +
          '<span class="meta" id="modal-fav-hint">в текущую папку</span>' +
        "</div>" +
        '<div class="flabel">Все печати</div>' +
        '<div class="printings" id="modal-printings"><div class="meta">загружаю…</div></div>' +
        '<div class="offerlist" id="modal-offers"></div>' +
        '<div class="combolist" id="modal-combos"></div>' +
      "</div>" +
    "</div>";

  if (canFlip) {
    $("#modal-flip").addEventListener("click", () => {
      modalFace = (modalFace + 1) % faces.length;
      renderModal();
    });
  }
  $$(".add-hunt").forEach((b) => b.addEventListener("click", () => {
    addToHunt(c.name, parseInt(b.dataset.n, 10));
  }));
  $$(".add-fav").forEach((b) => b.addEventListener("click", () => {
    // If a printing was picked in the table, pin it: a Secret Lair foil is a
    // different want from the cheap reprint.
    addToFavourites(c, parseInt(b.dataset.n, 10), modalPrinting);
  }));
  $("#modal-prices").addEventListener("click", () => loadCardOffers(c));
  $("#modal-combos-btn").addEventListener("click", () => {
    if (typeof loadCardCombos === "function") loadCardCombos(c);
    else toast("Комбо пока не подключены", true);
  });
  loadPrintings(c);
}

async function loadPrintings(card) {
  if (!card.oracle_id) {
    $("#modal-printings").innerHTML = '<div class="meta">нет данных о печатях</div>';
    return;
  }
  try {
    const r = await api("/api/printings/" + encodeURIComponent(card.oracle_id));
    const rows = r.printings.map((p) => {
      const usd = (p.prices && p.prices.usd) || "";
      return '<tr data-img="' + esc(p.image_normal || "") + '" data-set="' +
        esc(p.set_code || "") + '" data-cn="' + esc(p.collector_number || "") + '">' +
        "<td>" + esc((p.set_code || "").toUpperCase()) + "</td>" +
        "<td>" + esc(p.set_name || "") + "</td>" +
        "<td>#" + esc(p.collector_number || "") + "</td>" +
        "<td>" + esc(p.rarity || "") + "</td>" +
        "<td>" + esc(p.flavor_name || (p.ru_name ? "рус" : "")) + "</td>" +
        "<td>" + (usd ? "$" + esc(usd) : "") + "</td>" +
        "</tr>";
    }).join("");
    $("#modal-printings").innerHTML = "<table>" + rows + "</table>";
    $("#modal-printings").addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr");
      if (!tr || !tr.dataset.img) return;
      $$("#modal-printings tr").forEach((r2) => r2.classList.remove("sel"));
      tr.classList.add("sel");
      $("#modal-art").src = tr.dataset.img;
      modalPrinting = { set_code: tr.dataset.set, collector_number: tr.dataset.cn };
      const hint = $("#modal-fav-hint");
      if (hint) {
        hint.textContent = "печать " + (tr.dataset.set || "").toUpperCase() +
          " #" + (tr.dataset.cn || "");
      }
    });
  } catch (e) {
    $("#modal-printings").innerHTML = '<div class="meta">не удалось загрузить печати</div>';
  }
}

async function loadCardOffers(card) {
  const box = $("#modal-offers");
  box.innerHTML = '<div class="meta spinner">спрашиваю topdeck…</div>';
  try {
    const r = await post("/api/offers", { names: [card.name] });
    if (!r.offers.length) {
      box.innerHTML = '<div class="meta">на topdeck сейчас нет предложений</div>';
      return;
    }

    // topdeck labels every result with the name we searched for, even when the
    // seller is selling a different card -- "Burgeoning" comes back with
    // "Urban Burgeoning" at a tenth of the price. Only verified lines are
    // priced here; the rest are counted, named and kept out of the way.
    const mine = r.offers.filter((o) => o.verdict === "match")
      .sort((a, b) => a.cost - b.cost);
    const others = r.other_cards || {};
    const otherCount = Object.keys(others)
      .reduce((n, k) => n + others[k], 0);
    const unclear = r.offers.filter((o) => o.verdict === "unclear");

    let html = "";
    if (mine.length) {
      html += '<div class="flabel">Предложения на topdeck — ' + mine.length +
        " шт., от " + rub(mine[0].cost) + "</div>" +
        mine.slice(0, 25).map(offerLine).join("");
    } else {
      html += '<div class="meta">Ни одно предложение не подтвердилось как «' +
        esc(card.name) + '» — topdeck отдал только похожие названия.</div>';
    }

    if (otherCount) {
      html += '<details class="help"><summary>Скрыто ' + otherCount +
        " " + offersWord(otherCount) + " других карт</summary><div class=\"meta\">" +
        Object.keys(others).sort((a, b) => others[b] - others[a])
          .map((name) => others[name] + " × " + esc(name)).join("<br>") +
        "</div></details>";
    }
    if (unclear.length) {
      html += '<details class="help"><summary>' + unclear.length +
        " " + offersWord(unclear.length) + " без узнаваемого имени в строке</summary>" +
        unclear.slice(0, 10).map(offerLine).join("") + "</details>";
    }
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<div class="meta" style="color:var(--bad)">' + esc(e.message) + "</div>";
  }
}

function offerLine(o) {
  const seller = o.seller && o.seller.name ? o.seller.name : "?";
  return '<div class="offer">' +
    "<div>" +
      '<div class="rawline">' + esc(plainLine(o.line)) + "</div>" +
      chipsFor(o.parsed || {}, "") +
      (o.verdict === "unclear"
        ? '<div class="printinfo">' + esc(o.verdict_reason || "") + "</div>"
        : "") +
    "</div>" +
    '<div class="price"><b>' + rub(o.cost) + "</b><small>" + esc(seller) +
      (o.qty ? " · " + o.qty + " шт." : "") + "</small>" +
      (o.url ? '<small><a href="' + esc(o.url) +
        '" target="_blank" rel="noopener">объявление</a></small>' : "") +
    "</div></div>";
}

function openCard(card) {
  modalCard = card;
  modalPrinting = null;
  modalFace = card.matched_face != null ? card.matched_face : 0;
  $("#overlay").hidden = false;
  renderModal();
}

function closeModal() {
  $("#overlay").hidden = true;
  $("#modal-body").innerHTML = "";
  modalCard = null;
}

$("#modal-close").addEventListener("click", closeModal);
$("#overlay").addEventListener("click", (ev) => {
  if (ev.target === $("#overlay")) closeModal();
});

/* ============================================================ hunt helpers */

function addToHunt(name, qty) {
  const box = $("#hunt-wants");
  const lines = box.value.split("\n").filter((l) => l.trim());
  const norm = (s) => s.trim().toLowerCase();
  let found = false;
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^\s*(\d{1,3})\s*[xX]?\s+(.+)$/);
    if (m && norm(m[2]) === norm(name)) {
      lines[i] = (parseInt(m[1], 10) + qty) + " " + m[2].trim();
      found = true;
      break;
    }
  }
  if (!found) lines.push(qty + " " + name);
  box.value = lines.join("\n") + "\n";
  store.set("hunt", box.value);
  toast('"' + name + '" ×' + qty + " — в списке охоты");
}

/* ==================================================================== deck */

let currentDeck = null;

const SECTION_TITLES = {
  main: "Основная колода",
  side: "Сайдборд",
  commander: "Командир",
  maybe: "Под вопросом",
};

const COLOR_HEX = { W: "#f8f2df", U: "#3f7fc1", B: "#4a4453", R: "#c2483f", G: "#4a9160", C: "#9aa0aa" };

function deckStats(deck) {
  const playable = deck.entries.filter((e) => e.section === "main" || e.section === "commander");
  const curve = {};
  const colors = {};
  let usd = 0;
  let known = 0;
  let mvTotal = 0;
  let mvCount = 0;
  const formats = {};

  playable.forEach((e) => {
    const c = e.card;
    if (!c) return;
    known += e.quantity;
    const isLand = (c.type_line || "").toLowerCase().indexOf("land") >= 0;
    if (!isLand) {
      const mv = Math.min(7, Math.floor(c.cmc || 0));
      curve[mv] = (curve[mv] || 0) + e.quantity;
      mvTotal += (c.cmc || 0) * e.quantity;
      mvCount += e.quantity;
    }
    const cols = (c.colors || "") || "C";
    cols.split("").forEach((ch) => { colors[ch] = (colors[ch] || 0) + e.quantity; });
    const price = c.prices && parseFloat(c.prices.usd);
    if (price) usd += price * e.quantity;
    Object.keys(c.legalities || {}).forEach((f) => {
      if (formats[f] === undefined) formats[f] = true;
      if (c.legalities[f] !== "legal") formats[f] = false;
    });
  });

  const maxCurve = Math.max(1, ...Object.values(curve));
  const curveHtml = [0, 1, 2, 3, 4, 5, 6, 7].map((mv) => {
    const n = curve[mv] || 0;
    const h = Math.round((n / maxCurve) * 100);
    return '<div class="bar" style="height:' + h + '%">' +
      (n ? "<span>" + n + "</span>" : "") +
      "<em>" + (mv === 7 ? "7+" : mv) + "</em></div>";
  }).join("");

  const colorTotal = Object.values(colors).reduce((a, b) => a + b, 0) || 1;
  const colorBar = Object.keys(COLOR_HEX)
    .filter((ch) => colors[ch])
    .map((ch) => '<div style="width:' + ((colors[ch] / colorTotal) * 100).toFixed(1) +
      "%;background:" + COLOR_HEX[ch] + '"></div>')
    .join("");
  const colorLegend = Object.keys(COLOR_HEX)
    .filter((ch) => colors[ch])
    .map((ch) => ch + " " + colors[ch])
    .join(" · ");

  const legalIn = Object.keys(formats).filter((f) => formats[f]);

  return '<div class="statgrid">' +
    '<div class="statbox"><h4>Карт</h4><div class="statbig">' + deck.total_cards + "</div>" +
      '<div class="meta">распознано ' + known + "</div></div>" +
    '<div class="statbox"><h4>Кривая маны (без земель)</h4><div class="curve">' + curveHtml + "</div></div>" +
    '<div class="statbox"><h4>Цвета</h4><div class="colorbar">' + colorBar + "</div>" +
      '<div class="colorlegend">' + esc(colorLegend || "—") + "</div></div>" +
    '<div class="statbox"><h4>Средняя МС</h4><div class="statbig">' +
      (mvCount ? (mvTotal / mvCount).toFixed(2) : "—") + "</div></div>" +
    '<div class="statbox"><h4>Оценка Scryfall</h4><div class="statbig">$' + usd.toFixed(2) + "</div>" +
      '<div class="meta">мировая цена, для сверки</div></div>' +
    '<div class="statbox"><h4>Нужно докупить</h4><div class="statbig">' +
      (deck.missing_copies || 0) + ' шт.</div>' +
      '<div class="meta">' + (deck.missing_names || 0) + ' назв. ≈ $' +
      (deck.missing_usd || 0).toFixed(2) + '</div></div>' +
    '<div class="statbox"><h4>Легальна в</h4><div class="legal">' +
      (legalIn.length
        ? legalIn.map((f) => '<span class="chip ok">' + esc(f) + "</span>").join("")
        : '<span class="meta">ни в одном из известных форматов</span>') +
      "</div></div>" +
  "</div>";
}

function renderDeck(deck) {
  currentDeck = deck;
  deckSel = new Set();
  deckLastClicked = null;

  // Collapse the paste box: it has done its job and otherwise eats the screen
  // the list needs.
  const paste = $("#panel-deck details.help");
  if (paste) paste.open = false;

  $("#deck-stats").innerHTML = deckStats(deck);
  $("#deck-workbench").hidden = false;
  $("#deck-actions").hidden = false;
  renderDeckFolderOptions();
  renderDeckList();

  const bits = [esc(deck.name), "источник: " + esc(deck.source), deck.total_cards + " карт"];
  if (deck.missing_names) {
    bits.push('<span style="color:var(--warn)">нет в коллекции: ' + deck.missing_names +
      " назв. / " + deck.missing_copies + " шт. ≈ $" + deck.missing_usd.toFixed(2) + "</span>");
  }
  if (deck.unknown_names && deck.unknown_names.length) {
    bits.push('<span style="color:var(--bad)">не распознано имён: ' + deck.unknown_names.length + "</span>");
  }
  if (deck.warnings && deck.warnings.length) {
    bits.push('<span style="color:var(--warn)">предупреждений: ' + deck.warnings.length + "</span>");
  }
  $("#deck-meta").innerHTML = bits.join(" · ");
}

function deckToHunt() {
  if (!currentDeck) return toast("Сначала загрузите колоду", true);
  const text = currentDeck.entries
    .filter((e) => e.section === "main" || e.section === "side" || e.section === "commander")
    .map((e) => e.quantity + " " + e.name)
    .join("\n");
  $("#hunt-wants").value = text;
  store.set("hunt", text);
  $("#hunt-source").textContent = 'Список из колоды "' + currentDeck.name + '". Можно править.';
  showTab("hunt");
  toast("Перенесено в охоту: " + currentDeck.entries.length + " позиций");
}

async function importDeck(body, btn) {
  btn.disabled = true;
  $("#deck-meta").innerHTML = '<span class="spinner">загружаю…</span>';
  try {
    const r = await post("/api/deck/import", body);
    renderDeck(r.deck);
    toast("Колода загружена: " + r.deck.total_cards + " карт");
  } catch (e) {
    $("#deck-meta").textContent = "";
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

$("#deck-url-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const url = $("#deck-url").value.trim();
  if (!url) return toast("Вставьте ссылку", true);
  importDeck({ url }, ev.target.querySelector("button"));
});
$("#deck-text-btn").addEventListener("click", (ev) => {
  const text = $("#deck-text").value.trim();
  if (!text) return toast("Вставьте список", true);
  importDeck({ text }, ev.target);
});
$("#deck-to-hunt").addEventListener("click", deckToHunt);
$("#deck-export").addEventListener("click", () => {
  if (!currentDeck) return;
  const secs = { commander: "Commander", main: "Deck", side: "Sideboard", maybe: "Maybeboard" };
  let out = [];
  Object.keys(secs).forEach((sec) => {
    const rows = currentDeck.entries.filter((e) => e.section === sec);
    if (!rows.length) return;
    out.push(secs[sec]);
    rows.forEach((e) => out.push(e.quantity + " " + e.name));
    out.push("");
  });
  copyText(out.join("\n"), "Колода скопирована");
});

/* ==================================================================== hunt */

function parseWants(text) {
  const wants = [];
  (text || "").split("\n").forEach((raw) => {
    const line = raw.trim();
    if (!line) return;
    const m = line.match(/^(\d{1,3})\s*[xX]?\s+(.+)$/);
    if (m) wants.push({ name: m[2].trim(), quantity: parseInt(m[1], 10) });
    else wants.push({ name: line, quantity: 1 });
  });
  return wants;
}

function readHuntFilters() {
  const cities = $("#f-cities").value.split(",").map((s) => s.trim()).filter(Boolean);
  const maxPrice = parseInt($("#f-maxprice").value, 10);
  const refs = parseInt($("#f-refs").value, 10);
  return {
    languages: $$(".lang:checked").map((c) => c.value),
    min_condition: $("#f-condition").value || null,
    max_price: Number.isFinite(maxPrice) ? maxPrice : null,
    min_seller_refs: Number.isFinite(refs) ? refs : null,
    include_shops: $("#f-shops").checked,
    include_users: $("#f-users").checked,
    require_stated_language: $("#f-needlang").checked,
    require_stated_condition: $("#f-needcond").checked,
    exclude_proxy: true,
    cities,
  };
}

const CERTAINTY_LABEL = {
  exact: "",
  partial: '<span class="chip warn">описано неполно</span>',
  ambiguous: '<span class="chip mixed">неоднозначно — проверьте у продавца</span>',
};

function chipsFor(parsed, certaintyChip) {
  const chips = [];
  if (certaintyChip) chips.push(certaintyChip);
  if (parsed.set_code) {
    chips.push('<span class="chip set">' + esc(parsed.set_code.toUpperCase()) +
      (parsed.collector_number ? " #" + esc(parsed.collector_number) : "") + "</span>");
  } else if (parsed.collector_number) {
    chips.push('<span class="chip warn">#' + esc(parsed.collector_number) + ", сет не указан</span>");
  } else {
    chips.push('<span class="chip warn">сет не указан</span>');
  }
  if (parsed.language) chips.push('<span class="chip">' + esc(parsed.language) + "</span>");
  if (parsed.condition) chips.push('<span class="chip">' + esc(parsed.condition) + "</span>");
  if (parsed.foil === true) chips.push('<span class="chip">foil</span>');
  (parsed.treatments || []).forEach((t) => chips.push('<span class="chip">' + esc(t) + "</span>"));
  if (parsed.promo_family) chips.push('<span class="chip warn">' + esc(parsed.promo_family) + "</span>");
  if (parsed.mixed) chips.push('<span class="chip mixed">смешанный лот</span>');
  // topdeck hosts no images of its own, so a photo only exists when the seller
  // pasted a link into the listing text.
  (parsed.links || []).forEach((link) => {
    chips.push('<span class="chip photo"><a href="' + esc(link) +
      '" target="_blank" rel="noopener">фото продавца</a></span>');
  });
  return '<div class="chips">' + chips.join("") + "</div>";
}

/* Who else sells this card, and a way to pick one.

   The plan used to present one supplier as if it were the only one -- and got
   it wrong: it bought a card from a shop at 500 while a seller already in the
   plan had it at 400. The algorithm no longer does that, but the choice still
   belongs to the person paying: maybe you want the shop anyway, or a seller in
   your city, or the printing whose line you like better.

   A dropdown of everything was the first attempt and it was worse than nothing:
   Sol Ring had 185 offers. So the row shows only what matters -- what is chosen
   now, and the one or two listings that beat it -- and the full list opens on
   request. */

function alternativesFor(want) {
  return (lastPlan && lastPlan.alternatives && lastPlan.alternatives[want]) || [];
}

function supplierLabel(r) {
  const bits = [r.seller_name];
  if (r.seller_kind === "shop") bits.push("магазин");
  if (r.in_plan) bits.push("уже в плане");
  const marks = [r.set_code, r.language, r.condition].filter(Boolean).join(" ");
  if (marks) bits.push(marks);
  if (r.qty > 1) bits.push(r.qty + " шт.");
  return bits.join(" · ");
}

function supplierChip(want, r, kind, note) {
  return (
    '<button class="altchip ' + kind + '" data-pick="' + esc(want) +
      '" data-key="' + esc(r.key) + '">' +
      "<b>" + rub(r.price) + "</b> " + esc(supplierLabel(r)) +
      (note ? ' <i>' + esc(note) + "</i>" : "") +
    "</button>"
  );
}

function supplierPicker(item) {
  const want = item.want;
  const rows = alternativesFor(want);
  if (rows.length < 2) return "";

  const currentKey = (item.offer && item.offer.key) || "";
  const current = rows.find((r) => r.key === currentKey);
  const pinned = pinnedOffers.has(want);
  const price = current ? current.price : item.unit_price;

  // The two suggestions worth a click: the cheapest anywhere, and the cheapest
  // from someone the plan already involves (no extra parcel).
  const cheapest = rows.find((r) => r.key !== currentKey && r.price < price);
  const cheapestHere = rows.find(
    (r) => r.key !== currentKey && r.in_plan && r.price < price);

  const chips = [];
  if (cheapestHere && (!cheapest || cheapestHere.key !== cheapest.key)) {
    chips.push(supplierChip(want, cheapestHere, "here", "без второй пересылки"));
  }
  if (cheapest) {
    chips.push(supplierChip(want, cheapest, "cheap",
      cheapest.in_plan ? "без второй пересылки" : "отдельная пересылка"));
  }

  return (
    '<div class="picker">' +
      '<span class="altnow' + (pinned ? " pinned" : "") + '">' +
        (pinned ? "выбрано вами: " : "берём у: ") +
        esc(current ? supplierLabel(current) : "—") +
      "</span>" +
      chips.join("") +
      (pinned
        ? '<button class="ghost tiny" data-unpin="' + esc(want) +
          '" title="Вернуть решение программе">сбросить</button>'
        : "") +
      '<button class="ghost tiny" data-alts="' + esc(want) + '">все ' +
        rows.length + " предложен" + plural(rows.length, "ие", "ия", "ий") +
      "</button>" +
      '<div class="alts" data-altlist="' + esc(want) + '" hidden></div>' +
    "</div>"
  );
}

function renderAlternatives(want, box) {
  const rows = alternativesFor(want);
  box.innerHTML =
    '<div class="altrows">' +
      rows.map((r) =>
        '<div class="altrow' + (r.chosen ? " on" : "") +
          '" data-pick="' + esc(want) + '" data-key="' + esc(r.key) + '">' +
          '<span class="p">' + rub(r.price) + "</span>" +
          '<span class="s">' + esc(r.seller_name) +
            (r.seller_kind === "shop" ? " · магазин" : "") +
            (r.in_plan ? ' · <span class="good">уже в плане</span>' : "") +
            (r.seller_city ? " · " + esc(r.seller_city) : "") +
          "</span>" +
          '<span class="l">' + esc(plainLine(r.line)) + "</span>" +
        "</div>").join("") +
    "</div>";
}

function offerRow(item) {
  const offer = item.offer;
  const parsed = offer.parsed || {};
  const printing = offer.printing;
  const thumb = printing && printing.image_small;
  const certainty = CERTAINTY_LABEL[offer.certainty] || "";
  const ordered = orderedCounts[(item.want || "").toLowerCase()] || 0;
  return (
    '<div class="offer">' +
    (thumb
      ? '<img class="thumb big" loading="lazy" src="' + esc(thumb) + '" alt="" data-full="' +
        esc((printing && printing.image_normal) || thumb) + '" title="открыть картинку печати">'
      : '<div class="thumb big"></div>') +
    "<div>" +
      '<div class="want">' + esc(item.want) + " — " + item.quantity + " шт." +
        (ordered ? ' <span class="chip ordered">заказано: ' + ordered + " шт.</span>" : "") +
      "</div>" +
      '<div class="rawline">' + esc(plainLine(offer.line) || "(продавец не указал строку)") + "</div>" +
      chipsFor(parsed, certainty) +
      supplierPicker(item) +
      // Which printing we think this is, spelled out under the parse.
      (printing
        ? '<div class="printinfo">на картинке: ' +
          esc((printing.set_code || "").toUpperCase()) + " · " +
          esc(printing.set_name || "") +
          (printing.collector_number ? " #" + esc(printing.collector_number) : "") +
          (parsed.set_code ? "" : " — сет продавцом не указан, версия предположительная") +
          "</div>"
        : '<div class="printinfo">печать определить не удалось</div>') +
    "</div>" +
    '<div class="price"><b>' + rub(item.subtotal) + "</b>" +
      "<small>" + item.quantity + " × " + rub(item.unit_price) + "</small>" +
      (offer.url ? '<small><a href="' + esc(offer.url) + '" target="_blank" rel="noopener">объявление</a></small>' : "") +
      // Changing your mind must be possible right where the offer is shown.
      // Both buttons rebuild the plan from offers already fetched, so no new
      // request goes to topdeck and the next best listing steps in at once.
      '<div class="rowacts">' +
        '<button class="ghost tiny" data-skip-offer="' + esc(offer.key || "") +
          '" title="Взять эту карту, но у кого-то другого">не это предложение</button>' +
        '<button class="ghost tiny" data-skip-want="' + esc(item.want) +
          '" title="Убрать карту из плана целиком">не брать карту</button>' +
      "</div>" +
    "</div></div>"
  );
}

/* A shop lot is not a conversation, it is an order on the shop's own site.
   So instead of a private-message draft it gets everything needed to place
   that order: the list to paste, a direct link to each card's page, and a
   search link where there is no direct one. The program stops there -- filling
   someone's cart under their account is the same line it does not cross when
   it refuses to send messages for them. */
function shopOrderBox(order, lot, index) {
  if (!order) return "";
  const shop = order.shop || {};
  const cards = order.cards || [];
  const withLinks = cards.filter((c) => c.url);

  return (
    '<div class="orderbox">' +
      '<div class="row tight wrap">' +
        "<b>Заказ в магазине " + esc(shop.name || "") + "</b>" +
        (shop.home
          ? '<a href="' + esc(shop.home) + '" target="_blank" rel="noopener">открыть магазин</a>'
          : "") +
        (shop.known
          ? ""
          : '<span class="chip warn" title="' + esc(shop.note || "") + '">магазин незнаком</span>') +
      "</div>" +
      '<textarea class="orderlist" readonly rows="' +
        Math.min(8, Math.max(2, cards.length)) + '">' + esc(order.list_text || "") +
      "</textarea>" +
      '<div class="row tight wrap">' +
        '<button class="copy-order">Скопировать список</button>' +
        (withLinks.length
          ? '<button class="copy-links ghost">Скопировать ссылки на карточки</button>'
          : "") +
        orderControls(lot, index) +
        '<span class="meta">Корзину собираете вы — программа ничего не заказывает от вашего имени.</span>' +
      "</div>" +
      '<div class="orderlinks">' +
        cards.map((c) =>
          '<span class="olink">' +
            "<b>" + c.quantity + "×</b> " + esc(c.name) +
            (c.url
              ? ' <a href="' + esc(c.url) + '" target="_blank" rel="noopener">карточка товара</a>'
              : c.search_url
                ? ' <a href="' + esc(c.search_url) + '" target="_blank" rel="noopener">найти в магазине</a>'
                : ' <span class="meta">ссылки нет</span>') +
          "</span>").join("") +
      "</div>" +
    "</div>"
  );
}

function lotBlock(lot, index) {
  const isShop = lot.seller_kind === "shop";
  const sellerLabel = lot.seller_url
    ? '<a href="' + esc(lot.seller_url) + '" target="_blank" rel="noopener">' + esc(lot.seller_name) + "</a>"
    : esc(lot.seller_name);
  return (
    '<div class="lot" data-lot="' + index + '">' +
      '<div class="lot-head">' +
        '<span class="lot-seller">' + sellerLabel + "</span>" +
        '<span class="badge ' + (isShop ? "shop" : "user") + '">' + (isShop ? "магазин" : "частный") + "</span>" +
        (lot.seller_city ? '<span class="badge">' + esc(lot.seller_city) + "</span>" : "") +
        (lot.seller_refs != null ? '<span class="badge">' + lot.seller_refs + " отзывов</span>" : "") +
        '<span class="badge">' + lot.distinct_cards + " назв. / " + lot.total_copies + " шт.</span>" +
        '<span class="lot-total">' + rub(lot.total) + "</span>" +
      "</div>" +
      lot.items.map(offerRow).join("") +
      (isShop ? shopOrderBox(lot.order, lot, index) : "") +
      '<div class="msgbox"' + (isShop ? " hidden" : "") + ">" +
        // Editable: it is your message. Edits survive a re-plan for as long as
        // this seller stays in it.
        '<textarea data-seller="' + esc(lot.seller_name) + '">' + esc(lot.message || "") + "</textarea>" +
        '<div class="row">' +
          '<button class="copy-msg">Скопировать сообщение</button>' +
          (lot.message_edited
            ? '<button class="ghost tiny reset-msg">вернуть черновик</button>'
            : "") +
          orderControls(lot, index) +
          '<span class="meta">' + (isShop
            ? "Это магазин — заказ оформляется у него на сайте, не через ЛС."
            : "Отправьте сообщение продавцу в личку на topdeck сами.") +
          "</span>" +
        "</div>" +
      "</div>" +
    "</div>"
  );
}

let lastPlan = null;
let lastHuntResult = null;
let savedOrders = [];
let orderedCounts = {};

function sameOrderAsLot(order, lot) {
  if (!order || !lot || order.seller_name.toLowerCase() !== lot.seller_name.toLowerCase()) {
    return false;
  }
  const shape = (items, nameKey) => {
    const counts = {};
    items.forEach((item) => {
      const name = String(item[nameKey] || "").toLowerCase();
      counts[name] = (counts[name] || 0) + Number(item.quantity || 0);
    });
    return Object.keys(counts).sort().map((name) => name + ":" + counts[name]).join("|");
  };
  return shape(order.items || [], "name") === shape(lot.items || [], "want");
}

function orderControls(lot, index) {
  const saved = savedOrders.find((order) => sameOrderAsLot(order, lot));
  return (
    '<span class="order-total">Сумма заказа: <b>' + rub(lot.total) + "</b></span>" +
    (saved
      ? '<span class="chip ordered">✓ заказ оформлен</span>' +
        '<button class="ghost tiny" data-receive-order="' + esc(saved.id) +
          '" title="Добавить карты в коллекцию">получено → в коллекцию</button>' +
        '<button class="ghost tiny" data-remove-order="' + esc(saved.id) +
          '">снять отметку</button>'
      : '<button class="ghost tiny mark-order" data-mark-order="' + index +
          '">Отметить заказанным</button>')
  );
}

function applyOrderState(state) {
  savedOrders = (state && state.orders) || [];
  orderedCounts = (state && state.ordered) || {};
  renderOrdersPanel();
}

async function loadOrders() {
  applyOrderState(await api("/api/orders"));
}

function renderOrdersPanel() {
  const box = $("#hunt-orders");
  if (!box) return;
  if (!savedOrders.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML =
    '<details class="pending-orders" open><summary>Заказано, ожидает получения — ' +
      savedOrders.length + "</summary>" +
      savedOrders.map((order) =>
        '<div class="pending-order">' +
          '<div><b>' + esc(order.seller_name) + "</b> · " + rub(order.total) +
            ' <span class="meta">' + esc(order.created) + "</span></div>" +
          '<div class="meta">' + (order.items || []).map((item) =>
            item.quantity + "× " + esc(item.name)).join(" · ") + "</div>" +
          '<div class="row tight">' +
            '<button class="tiny" data-receive-order="' + esc(order.id) +
              '">Получено → в коллекцию</button>' +
            '<button class="ghost tiny" data-remove-order="' + esc(order.id) +
              '">Снять отметку</button>' +
          "</div>" +
        "</div>"
      ).join("") +
    "</details>";
}

function huntPlanHtml(plan) {
  let html = "";
  if (plan.unfilled && plan.unfilled.length) {
    html += '<div class="unfilled"><h3>Не нашлось в продаже</h3>' +
      plan.unfilled.map((u) => esc(u.name) + " — не хватает " + u.still_missing + " шт.").join("<br>") +
      "</div>";
  }
  html += plan.lots.map(lotBlock).join("");
  return html || '<p class="meta">' + (huntStateEmpty()
    ? "Ничего не найдено под эти фильтры."
    : "В плане ничего не осталось — вы отказались от всего. Можно вернуть.") + "</p>";
}

function refreshOrderViews() {
  renderOrdersPanel();
  if (lastPlan) $("#hunt-plan").innerHTML = huntPlanHtml(lastPlan);
  if (currentDeck && typeof renderDeckList === "function") renderDeckList();
}

async function handleOrderClick(target) {
  const mark = target.dataset && target.dataset.markOrder;
  const remove = target.dataset && target.dataset.removeOrder;
  const receive = target.dataset && target.dataset.receiveOrder;
  if (mark == null && !remove && !receive) return false;
  target.disabled = true;
  try {
    let state;
    if (mark != null) {
      const lot = lastPlan && lastPlan.lots[Number(mark)];
      if (!lot) throw new Error("Заказ больше не найден в плане");
      state = await post("/api/orders", {
        seller_name: lot.seller_name,
        seller_kind: lot.seller_kind,
        items: lot.items.map((item) => ({
          name: item.want,
          quantity: item.quantity,
          unit_price: item.unit_price,
        })),
      });
      toast("Заказ отмечен — карты остались в охоте и колоде");
    } else if (remove) {
      state = await post("/api/orders/" + encodeURIComponent(remove) + "/remove", {});
      toast("Отметка заказа снята");
    } else {
      state = await post("/api/orders/" + encodeURIComponent(receive) + "/receive", {});
      toast("Карты добавлены в коллекцию");
      refreshStatus();
    }
    applyOrderState(state);
    refreshOrderViews();
  } catch (e) {
    toast(e.message, true);
    target.disabled = false;
  }
  return true;
}

/* ---------------------------------------------------------- changing your mind

   A hunt costs a polite 1.5s request per batch, so the offers it found stay on
   the server under `huntId`. Refusing an offer or a card therefore rebuilds the
   plan from what we already have -- instantly, and without asking topdeck
   anything again. Refusals are kept here as plain state and sent in full every
   time, which is what makes "вернуть" work: it just stops sending one. */

let huntId = null;
let huntWants = [];              // what the server says we still need
// How many copies were needed when the hunt ran. The quantity control has to
// keep THIS as its ceiling: after "take 1 of 4" the server reports a want of 1,
// and reading the ceiling from that would trap you at one copy for good.
let huntNeeded = new Map();      // card name (lowercased) -> copies needed
const skipOffers = new Map();    // offer key -> {want, line}
const skipWants = new Map();     // card name -> true
const huntQty = new Map();       // card name -> how many copies to take
const pinnedOffers = new Map();  // card name -> the offer key chosen by hand
let preferSeller = "";           // a seller to buy everything from
const editedMessages = new Map(); // seller name -> text the user rewrote
const huntNames = new Map();      // lowercased name -> as the card is written

function huntStateEmpty() {
  return !skipOffers.size && !skipWants.size && !huntQty.size
    && !pinnedOffers.size && !preferSeller;
}

function resetHuntChoices() {
  skipOffers.clear();
  skipWants.clear();
  huntQty.clear();
  pinnedOffers.clear();
  preferSeller = "";
}

/* Editing a plan means re-rendering it, and a re-render that loses your place
   is why editing felt unusable: you picked a supplier and the row you were
   working on jumped somewhere else. So the scroll position and the card whose
   offer list was open are put back afterwards. */
function huntViewState() {
  const open = document.querySelector("#hunt-plan .alts:not([hidden])");
  return {
    scroll: window.scrollY,
    openWant: open ? open.dataset.altlist : null,
  };
}

function restoreHuntView(state) {
  if (!state) return;
  if (state.openWant) {
    const box = document.querySelector(
      '#hunt-plan .alts[data-altlist="' + (window.CSS && CSS.escape
        ? CSS.escape(state.openWant) : state.openWant) + '"]');
    if (box) {
      renderAlternatives(state.openWant, box);
      box.hidden = false;
      const btn = box.parentElement.querySelector("[data-alts]");
      if (btn) btn.textContent = "свернуть";
    }
  }
  window.scrollTo({ top: state.scroll });
}

async function replanHunt() {
  if (!huntId) return;
  const view = huntViewState();
  const quantities = {};
  huntQty.forEach((v, k) => { quantities[k] = v; });
  const bar = $("#hunt-choices");
  bar.classList.add("busy");
  try {
    const pins = {};
    pinnedOffers.forEach((v, k) => { pins[k] = v; });
    const r = await post("/api/hunt/replan", {
      hunt_id: huntId,
      strategy: $("#f-strategy").value,
      skip_offers: Array.from(skipOffers.keys()),
      skip_wants: Array.from(skipWants.keys()),
      quantities,
      pins,
      prefer_seller: preferSeller,
    });
    await renderHuntResult(r, { replanned: true });
    restoreHuntView(view);
  } catch (e) {
    // The hunt fell out of the server's memory (restart, or four hunts later).
    toast(e.message, true);
  } finally {
    bar.classList.remove("busy");
  }
}

/* The card-level decisions live in one strip above the plan: how many copies of
   each card you actually want, and which cards you dropped. Offer-level
   refusals stay down in the rows next to the offer they concern. */
function renderHuntChoices() {
  const bar = $("#hunt-choices");
  if (!huntId || !huntNeeded.size) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;

  const chip = (name, needed, dropped) => {
    const qty = dropped ? 0 : (huntQty.has(name.toLowerCase())
      ? huntQty.get(name.toLowerCase()) : needed);
    return '<span class="wantchip' + (dropped ? " off" : "") + '">' +
      '<b>' + esc(name) + "</b>" +
      (dropped
        ? '<span class="meta">не берём</span>' +
          '<button class="ghost tiny" data-undrop="' + esc(name) + '">вернуть</button>'
        : '<input type="number" class="qty" min="1" max="' + needed +
            '" value="' + qty + '" data-qty="' + esc(name) + '" title="сколько штук брать">' +
          '<span class="meta">из ' + needed + "</span>" +
          '<button class="ghost tiny" data-skip-want="' + esc(name) + '">не брать</button>') +
      "</span>";
  };

  // Every card the hunt was for stays on the strip, whatever the current plan
  // says, so a card you dropped or trimmed can always be adjusted again.
  const live = [];
  const dropped = [];
  huntNeeded.forEach((needed, key) => {
    const name = huntNames.get(key) || key;
    if (skipWants.has(key)) dropped.push(chip(name, needed, true));
    else live.push(chip(name, needed, false));
  });

  // Who could supply the whole order, for "I would rather buy it all here".
  const cover = (lastPlan && lastPlan.coverage) || [];
  const coverRow = cover.length
    ? '<div class="row tight wrap"><span class="meta">Купить всё у одного:</span>' +
      '<select id="hunt-prefer">' +
        '<option value="">— как выгоднее —</option>' +
        cover.map((c) =>
          '<option value="' + esc(c.key) + '"' +
            (c.key === preferSeller ? " selected" : "") + ">" +
            esc(c.name) + (c.kind === "shop" ? " (магазин)" : "") +
            " — " + c.cards + " из " + huntNeeded.size +
          "</option>").join("") +
      "</select>" +
      (preferSeller
        ? '<span class="meta">остальное — где найдётся</span>'
        : "") +
      "</div>"
    : "";

  bar.innerHTML =
    '<div class="row tight wrap">' +
      '<span class="meta">Берём:</span>' + live.join("") + dropped.join("") +
    "</div>" +
    coverRow +
    (skipOffers.size
      ? '<div class="row tight wrap"><span class="meta">Отказались от предложений:</span>' +
        Array.from(skipOffers.entries()).map(([key, info]) =>
          '<span class="wantchip off"><b>' + esc(info.want) + "</b>" +
          '<span class="meta">' + esc(plainLine(info.line).slice(0, 46)) + "</span>" +
          '<button class="ghost tiny" data-unskip="' + esc(key) + '">вернуть</button></span>'
        ).join("") + "</div>"
      : "") +
    (huntStateEmpty()
      ? ""
      : '<div class="row tight"><button class="ghost tiny" id="hunt-reset-choices">' +
        "вернуть всё как было</button>" +
        '<span class="hint">пересчёт мгновенный — новые запросы к topdeck не идут</span></div>');
}

async function renderHuntResult(r, opts) {
  lastHuntResult = r;
  const plan = r.plan;
  huntWants = r.wants || [];
  if (!opts || !opts.replanned) {
    huntNeeded = new Map();
    huntNames.clear();
  }
  // Ceilings are remembered, never lowered: a card taken 1-of-4 comes back from
  // the server as a want of 1, and reading the ceiling from that would trap it.
  // New cards -- ones added to an order that already existed -- get their
  // ceiling here, which is how they reach the "Берём" strip at all.
  huntWants.forEach((w) => {
    const key = w.name.toLowerCase();
    huntNames.set(key, w.name);
    if (!huntNeeded.has(key)) huntNeeded.set(key, w.quantity);
  });

  const answer = await post("/api/messages", { plan });
  const drafts = answer.drafts;
  // Orders come back only for shop lots, in their own order, so they are
  // matched by seller rather than by index.
  const orders = {};
  (answer.orders || []).forEach((o) => { orders[o.seller_name] = o; });
  plan.lots.forEach((lot) => { lot.order = orders[lot.seller_name] || null; });
  plan.lots.forEach((lot, i) => {
    const fresh = drafts[i] ? drafts[i].message : "";
    // A message the user rewrote is theirs; a re-plan must not silently
    // overwrite it while that seller is still in the plan.
    if (editedMessages.has(lot.seller_name)) {
      lot.message = editedMessages.get(lot.seller_name);
      lot.message_edited = true;
    } else {
      lot.message = fresh;
    }
    lot.message_fresh = fresh;
  });
  lastPlan = plan;

  // The improvement pass is worth showing: it is the difference between the
  // plan the greedy pass produced and the one you are looking at.
  const moved = (plan.moves || []).length;
  const movedNote = moved
    ? " · <span class=\"good\">перенесено к тем, кто уже в плане: " + moved +
      (plan.saved ? ", дешевле на " + rub(plan.saved) : "") + "</span>"
    : "";

  $("#hunt-meta").innerHTML =
    "нужно докупить: " + (r.wants || []).length + " назв. · предложений: " +
    r.candidates.length + " · отфильтровано: " + r.rejected_count +
    (r.refused_count ? " · вы отказались: " + r.refused_count : "") +
    " · <b>итог: " + rub(plan.total) + " у " + plan.sellers + " прод.</b>" +
    movedNote;

  renderHuntChoices();

  $("#hunt-plan").innerHTML = huntPlanHtml(plan);
  $("#hunt-actions").hidden = !plan.lots.length;
  $("#hunt-addbox").hidden = !huntId;

  if (r.rejected_count) {
    const reasons = {};
    r.candidates.forEach((c) => {
      if (c.rejected) reasons[c.rejected] = (reasons[c.rejected] || 0) + 1;
    });
    $("#hunt-rejected").innerHTML =
      '<details class="help"><summary>Почему отброшено ' + r.rejected_count +
      " " + offersWord(r.rejected_count) + "</summary><div class=\"meta\">" +
      Object.keys(reasons).sort((a, b) => reasons[b] - reasons[a])
        .map((why) => reasons[why] + " × " + esc(why)).join("<br>") +
      "</div></details>";
  } else {
    $("#hunt-rejected").innerHTML = "";
  }

  if (opts && opts.replanned) toast("План пересчитан");
}

$("#hunt-btn").addEventListener("click", async (ev) => {
  const wants = parseWants($("#hunt-wants").value);
  if (!wants.length) return toast("Список пуст", true);

  store.set("hunt", $("#hunt-wants").value);
  store.set("huntFilters", readHuntFilters());

  ev.target.disabled = true;
  const started = Date.now();
  const tick = setInterval(() => {
    $("#hunt-meta").innerHTML = '<span class="spinner">ищу ' + wants.length +
      " назв. на topdeck… " + Math.round((Date.now() - started) / 1000) + " с</span>";
  }, 500);
  $("#hunt-plan").innerHTML = "";
  $("#hunt-rejected").innerHTML = "";
  $("#hunt-actions").hidden = true;

  try {
    const r = await post("/api/hunt", {
      wants,
      filters: readHuntFilters(),
      strategy: $("#f-strategy").value,
      use_collection: $("#f-collection").checked,
    });
    clearInterval(tick);

    if (r.note) { $("#hunt-meta").textContent = r.note; return; }

    huntId = r.hunt_id || null;
    resetHuntChoices();
    editedMessages.clear();
    await renderHuntResult(r);
  } catch (e) {
    clearInterval(tick);
    $("#hunt-meta").textContent = "";
    toast(e.message, true);
  } finally {
    clearInterval(tick);
    ev.target.disabled = false;
  }
});

$("#hunt-plan").addEventListener("click", async (ev) => {
  if (await handleOrderClick(ev.target)) return;
  if (ev.target.classList.contains("copy-order")) {
    const box = ev.target.closest(".orderbox").querySelector(".orderlist");
    copyText(box.value, "Список для магазина скопирован");
    return;
  }

  if (ev.target.classList.contains("copy-links")) {
    const links = $$(".orderlinks a", ev.target.closest(".orderbox"))
      .map((a) => a.href);
    copyText(links.join("\n"), "Ссылки скопированы: " + links.length);
    return;
  }

  if (ev.target.classList.contains("copy-msg")) {
    const box = ev.target.closest(".msgbox").querySelector("textarea");
    copyText(box.value, "Сообщение скопировано");
    return;
  }

  if (ev.target.classList.contains("reset-msg")) {
    const box = ev.target.closest(".msgbox").querySelector("textarea");
    const seller = box.dataset.seller;
    editedMessages.delete(seller);
    const lot = (lastPlan && lastPlan.lots || []).find((l) => l.seller_name === seller);
    if (lot) {
      lot.message = lot.message_fresh || "";
      lot.message_edited = false;
      box.value = lot.message;
    }
    ev.target.remove();
    return;
  }

  const dropOffer = ev.target.dataset.skipOffer;
  if (dropOffer) {
    const row = ev.target.closest(".offer");
    const want = ev.target.parentElement.querySelector("[data-skip-want]");
    skipOffers.set(dropOffer, {
      want: (want && want.dataset.skipWant) || "",
      line: (row && (row.querySelector(".rawline") || {}).textContent) || "",
    });
    replanHunt();
    return;
  }

  // Opening the full list of offers for one card.
  const alts = ev.target.closest("[data-alts]");
  if (alts) {
    const want = alts.dataset.alts;
    const box = ev.target.closest(".picker").querySelector("[data-altlist]");
    if (box.hidden) {
      renderAlternatives(want, box);
      box.hidden = false;
      alts.textContent = "свернуть";
    } else {
      box.hidden = true;
      box.innerHTML = "";
      alts.textContent = "все " + alternativesFor(want).length + " предложений";
    }
    return;
  }

  // Choosing a supplier: from a suggestion chip or from the full list.
  const pick = ev.target.closest("[data-pick]");
  if (pick) {
    const want = pick.dataset.pick;
    const key = pick.dataset.key;
    const rows = alternativesFor(want);
    const row = rows.find((r) => r.key === key);
    // Choosing what the plan already picked is not a choice worth pinning.
    if (row && row.chosen) pinnedOffers.delete(want);
    else pinnedOffers.set(want, key);
    replanHunt();
    return;
  }

  const unpin = ev.target.dataset.unpin;
  if (unpin) {
    pinnedOffers.delete(unpin);
    replanHunt();
    return;
  }

  const dropWant = ev.target.dataset.skipWant;
  if (dropWant) {
    skipWants.set(dropWant.toLowerCase(), { name: dropWant });
    huntQty.delete(dropWant.toLowerCase());
    replanHunt();
  }
});

$("#hunt-orders").addEventListener("click", async (ev) => {
  await handleOrderClick(ev.target);
});

/* The card-level strip: quantity, dropping a card, taking a refusal back. */
$("#hunt-choices").addEventListener("click", (ev) => {
  const t = ev.target;

  if (t.id === "hunt-reset-choices") {
    resetHuntChoices();
    replanHunt();
    return;
  }
  if (t.dataset.skipWant) {
    skipWants.set(t.dataset.skipWant.toLowerCase(), { name: t.dataset.skipWant });
    huntQty.delete(t.dataset.skipWant.toLowerCase());
    replanHunt();
    return;
  }
  if (t.dataset.undrop) {
    skipWants.delete(t.dataset.undrop.toLowerCase());
    replanHunt();
    return;
  }
  if (t.dataset.unskip) {
    skipOffers.delete(t.dataset.unskip);
    replanHunt();
  }
});

$("#hunt-choices").addEventListener("change", (ev) => {
  if (ev.target.id === "hunt-prefer") {
    preferSeller = ev.target.value;
    replanHunt();
    return;
  }
  const name = ev.target.dataset.qty;
  if (!name) return;
  const max = Number(ev.target.max) || 1;
  const want = Math.max(1, Math.min(max, Number(ev.target.value) || 1));
  ev.target.value = want;
  if (want === max) huntQty.delete(name.toLowerCase());
  else huntQty.set(name.toLowerCase(), want);
  replanHunt();
});

/* Your edits to a draft are remembered per seller, so a re-plan keeps them. */
$("#hunt-plan").addEventListener("input", (ev) => {
  const seller = ev.target.dataset && ev.target.dataset.seller;
  if (!seller) return;
  const lot = (lastPlan && lastPlan.lots || []).find((l) => l.seller_name === seller);
  if (lot && ev.target.value === (lot.message_fresh || "")) {
    editedMessages.delete(seller);
    return;
  }
  editedMessages.set(seller, ev.target.value);
  if (lot) { lot.message = ev.target.value; lot.message_edited = true; }
});

$("#hunt-copy-all").addEventListener("click", () => {
  if (!lastPlan) return;
  const text = lastPlan.lots.map((lot) =>
    "=== " + lot.seller_name + " (" + (lot.seller_kind === "shop" ? "магазин" : "частный") +
    ", " + lot.total + " руб.) ===\n" + lot.message).join("\n\n");
  copyText(text, "Все сообщения скопированы");
});

$("#hunt-export").addEventListener("click", () => {
  if (!lastPlan) return;
  const lines = ["План покупки — итого " + lastPlan.total + " руб. у " + lastPlan.sellers + " продавцов", ""];
  lastPlan.lots.forEach((lot) => {
    lines.push("--- " + lot.seller_name + " (" + (lot.seller_city || "город не указан") +
      ") — " + lot.total + " руб.");
    lot.items.forEach((it) => {
      lines.push("   " + it.quantity + " x " + it.want + " @ " + it.unit_price + " руб.");
      lines.push("      как записано у продавца: " + plainLine(it.offer.line));
    });
    lines.push("");
  });
  if (lastPlan.unfilled.length) {
    lines.push("Не нашлось:");
    lastPlan.unfilled.forEach((u) => lines.push("   " + u.name + " — " + u.still_missing + " шт."));
  }
  copyText(lines.join("\n"), "План скопирован");
});

/* ------------------------------------------------- adding one more card ----

   The useful part is the order of the answer: a card at 300 from someone
   already in the plan costs no extra postage and
   usually beats 250 from a stranger, so the sellers already in the order come
   first, then everyone else. Nothing joins the order until a listing is
   chosen: the lookup is one polite topdeck request and it changes nothing.
*/

let huntAddTicket = 0;

async function huntSuggest(text) {
  const ticket = ++huntAddTicket;
  if (!text) { $("#hunt-suggest").innerHTML = ""; return; }
  try {
    const r = await api("/api/search?limit=10&q=" + encodeURIComponent(text));
    if (ticket !== huntAddTicket) return;
    $("#hunt-suggest").innerHTML = (r.cards || []).map((c) =>
      '<div class="setrow" data-name="' + esc(c.name) + '">' +
        '<span class="code">' + esc((c.set_code || "").toUpperCase()) + "</span>" +
        '<span class="nm">' + esc(c.display_name || c.name) + "</span>" +
        '<span class="yr">' + esc(c.ru_name || "") + "</span>" +
      "</div>").join("");
  } catch (e) { /* keep the previous suggestions */ }
}

function huntOfferRow(row, name) {
  const marks = [row.set_code, row.language, row.condition].filter(Boolean).join(" ");
  return (
    '<div class="lookrow" data-add="' + esc(name) + '" data-key="' + esc(row.key) + '">' +
      '<span class="p">' + rub(row.price) + "</span>" +
      '<span class="s">' + esc(row.seller_name) +
        (row.seller_kind === "shop" ? " · магазин" : "") +
        (row.seller_city ? " · " + esc(row.seller_city) : "") +
        (row.qty > 1 ? " · " + row.qty + " шт." : "") +
      "</span>" +
      '<span class="l">' + esc(plainLine(row.line)) +
        (marks ? " · " + esc(marks) : "") + "</span>" +
      '<button class="ghost tiny">взять здесь</button>' +
    "</div>"
  );
}

async function huntLookup(name) {
  if (!huntId) return toast("Сначала запустите охоту", true);
  const qty = Math.max(1, parseInt($("#hunt-add-qty").value, 10) || 1);
  $("#hunt-suggest").innerHTML = "";
  $("#hunt-add").value = name;

  const box = $("#hunt-lookup");
  const started = Date.now();
  const tick = setInterval(() => {
    box.innerHTML = '<div class="meta spinner">спрашиваю topdeck про «' + esc(name) +
      "»… " + Math.round((Date.now() - started) / 1000) + " с</div>";
  }, 400);
  try {
    const r = await post("/api/hunt/lookup", { hunt_id: huntId, name: name,
                                               quantity: qty,
                                               filters: readHuntFilters() });
    clearInterval(tick);
    const here = r.with_sellers_in_plan || [];
    const there = r.elsewhere || [];

    if (!here.length && !there.length) {
      box.innerHTML = '<div class="lookbox"><div class="meta">«' + esc(r.name) +
        "» сейчас никто не продаёт — по крайней мере под ваши фильтры." +
        "</div></div>";
      return;
    }

    box.innerHTML =
      '<div class="lookbox">' +
        '<div class="row tight wrap"><b>' + esc(r.name) + "</b>" +
          '<span class="meta">' + qty + " шт. · предложений " + r.offers +
          (r.rejected ? " · отброшено " + r.rejected : "") + "</span>" +
          '<span style="flex:1"></span>' +
          '<button class="ghost tiny" id="hunt-look-cancel">не надо</button>' +
        "</div>" +
        (here.length
          ? '<div class="lookgroup"><h5>Есть у тех, у кого уже покупаем ' +
            '<span class="meta">— без второй пересылки</span></h5>' +
            here.map((x) => huntOfferRow(x, r.name)).join("") + "</div>"
          : '<div class="meta">Ни у кого из тех, кто уже в заказе, этой карты нет.</div>') +
        (there.length
          ? '<div class="lookgroup"><h5>У остальных ' +
            '<span class="meta">— это ещё одна посылка и ещё один разговор</span></h5>' +
            there.slice(0, 12).map((x) => huntOfferRow(x, r.name)).join("") +
            (there.length > 12
              ? '<div class="meta">…и ещё ' + (there.length - 12) + "</div>"
              : "") +
            "</div>"
          : "") +
      "</div>";
  } catch (e) {
    clearInterval(tick);
    box.innerHTML = '<div class="lookbox"><div class="meta">' + esc(e.message) +
      "</div></div>";
  } finally {
    clearInterval(tick);
  }
}

async function huntAddConfirmed(name, offerKey) {
  const qty = Math.max(1, parseInt($("#hunt-add-qty").value, 10) || 1);
  try {
    await post("/api/hunt/add", { hunt_id: huntId, name: name, quantity: qty,
                                  offer_key: offerKey });
  } catch (e) {
    toast(e.message, true);
    return;
  }
  // The card is now part of the order, and the pin the user chose is kept
  // server-side, so later re-plans do not quietly move it.
  pinnedOffers.set(name, offerKey);
  $("#hunt-lookup").innerHTML = "";
  $("#hunt-add").value = "";
  // Keep the wants box in step, so re-running the hunt includes the card.
  addToHunt(name, qty);
  await replanHunt();
  toast("«" + name + "» в заказе");
}

$("#hunt-add").addEventListener("input", debounce((ev) => {
  huntSuggest(ev.target.value.trim());
}, 250));

$("#hunt-add").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  ev.preventDefault();
  const first = $("#hunt-suggest .setrow");
  if (first) huntLookup(first.dataset.name);
  else if (ev.target.value.trim()) huntLookup(ev.target.value.trim());
});

$("#hunt-suggest").addEventListener("click", (ev) => {
  const row = ev.target.closest(".setrow");
  if (row) huntLookup(row.dataset.name);
});

$("#hunt-lookup").addEventListener("click", (ev) => {
  if (ev.target.id === "hunt-look-cancel") {
    $("#hunt-lookup").innerHTML = "";
    return;
  }
  const row = ev.target.closest(".lookrow");
  if (row) huntAddConfirmed(row.dataset.add, row.dataset.key);
});

/* ============================================================== collection */

$("#collection-save").addEventListener("click", async (ev) => {
  ev.target.disabled = true;
  try {
    const r = await post("/api/collection", { text: $("#collection-text").value });
    $("#collection-meta").textContent =
      "сохранено: " + r.stored + " названий, " + r.copies + " шт." +
      (r.warnings.length ? " · нераспознанных строк: " + r.warnings.length : "");
    // The previous collection is snapshotted, so overwriting is undoable.
    if (typeof renderCollectionBackups === "function") {
      renderCollectionBackups(r.backups);
    }
    toast("Коллекция сохранена");
    refreshStatus();
  } catch (e) {
    toast(e.message, true);
  } finally {
    ev.target.disabled = false;
  }
});

$("#collection-file").addEventListener("change", (ev) => {
  const file = ev.target.files && ev.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    $("#collection-text").value = String(reader.result || "");
    toast("Файл загружен — нажмите «Сохранить коллекцию»");
  };
  reader.onerror = () => toast("Не удалось прочитать файл", true);
  reader.readAsText(file, "utf-8");
});

/* ========================================================= keyboard, init */

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("#overlay").hidden) { closeModal(); return; }
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (ev.key === "/" && !typing) {
    ev.preventDefault();
    showTab("search");
    $("#search-q").focus();
    return;
  }
  gridKeys(ev, typing);
});

/* ------------------------------------------------- walking the grid by keys

   Typing a query and then reaching for the mouse to look through the results
   is the slow way. ArrowDown from the search field steps into the grid, the
   arrows walk it, and the card under the cursor shows the same big preview as
   hovering does -- so you read the results without clicking anything. Enter
   opens the card, Esc gives the keyboard back to the query. */

let gridCursor = -1;

function gridTiles() {
  return $$("#search-results .card");
}

function gridColumns() {
  const grid = $("#search-results");
  const cols = getComputedStyle(grid).gridTemplateColumns;
  const n = cols ? cols.split(" ").filter((x) => x.trim()).length : 1;
  return Math.max(1, n);
}

function markGridCursor(index, opts) {
  const tiles = gridTiles();
  if (!tiles.length) { gridCursor = -1; return; }
  const i = Math.max(0, Math.min(tiles.length - 1, index));
  gridCursor = i;
  tiles.forEach((t, k) => t.classList.toggle("cursor", k === i));
  const el = tiles[i];
  el.scrollIntoView({ block: "nearest", inline: "nearest" });
  if (!opts || opts.preview !== false) {
    // The keyboard gets the same big picture the pointer gets.
    hoverTarget = el;
    showPreview(el, "keys");
  }
}

function clearGridCursor() {
  gridTiles().forEach((t) => t.classList.remove("cursor"));
  gridCursor = -1;
  hidePreview();
}

function gridKeys(ev, typing) {
  if (!document.querySelector("#panel-search.active")) return;
  if (ev.altKey || ev.ctrlKey || ev.metaKey) return;

  // From the query field, ArrowDown steps into the results; everything else
  // typed there stays typing.
  if (typing) {
    if (document.activeElement.id === "search-q" && ev.key === "ArrowDown"
        && gridTiles().length) {
      ev.preventDefault();
      document.activeElement.blur();
      markGridCursor(gridCursor < 0 ? 0 : gridCursor);
    }
    return;
  }

  const cols = gridColumns();
  const step = {
    ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols,
  }[ev.key];

  if (step !== undefined) {
    if (!gridTiles().length) return;
    ev.preventDefault();
    if (gridCursor < 0) {
      markGridCursor(0);
      return;
    }
    // Stepping up from the first row goes back to the query field.
    if (ev.key === "ArrowUp" && gridCursor < cols) {
      clearGridCursor();
      $("#search-q").focus();
      return;
    }
    markGridCursor(gridCursor + step);
    return;
  }

  if (gridCursor < 0) return;

  if (ev.key === "Home" || ev.key === "End") {
    ev.preventDefault();
    markGridCursor(ev.key === "Home" ? 0 : gridTiles().length - 1);
    return;
  }
  if (ev.key === "Enter") {
    ev.preventDefault();
    const tile = gridTiles()[gridCursor];
    const card = tile && lastCards.find((c) => c.id === tile.dataset.id);
    if (card) { hidePreview(); openCard(card); }
    return;
  }
  if (ev.key === "Escape") {
    ev.preventDefault();
    clearGridCursor();
    $("#search-q").focus();
  }
}

$("#hunt-wants").addEventListener("input", debounce(() => {
  store.set("hunt", $("#hunt-wants").value);
}, 600));

(async function init() {
  await refreshStatus();
  await loadOrders();
  // Vocabularies first: restoring the panel renders tokens that depend on them.
  await Promise.all([loadSets(), loadFormats(), loadTypes()]);

  // Draw the static pickers unconditionally: restoreFilterPanel() returns
  // early when nothing was stored, which would leave them empty on a fresh
  // browser.
  renderFlags();

  restoreFilterPanel(store.get("filters", null));
  const openFilters = store.get("filtersOpen", false);
  $("#filters-panel").hidden = !openFilters;
  $("#filters-toggle").setAttribute("aria-expanded", String(openFilters));

  $("#search-q").value = store.get("query", "");
  $("#search-sort").value = store.get("sort", "relevance");
  $("#hunt-wants").value = store.get("hunt", "");

  const hf = store.get("huntFilters", null);
  if (hf) {
    $$(".lang").forEach((c) => (c.checked = (hf.languages || []).indexOf(c.value) >= 0));
    $("#f-condition").value = hf.min_condition || "";
    $("#f-maxprice").value = hf.max_price == null ? "" : hf.max_price;
    $("#f-refs").value = hf.min_seller_refs == null ? "" : hf.min_seller_refs;
    $("#f-cities").value = (hf.cities || []).join(", ");
    $("#f-shops").checked = hf.include_shops !== false;
    $("#f-users").checked = hf.include_users !== false;
    $("#f-needlang").checked = !!hf.require_stated_language;
    $("#f-needcond").checked = !!hf.require_stated_condition;
  }

  showTab(store.get("tab", "search"));

  try {
    const r = await api("/api/collection");
    const entries = Object.keys(r.collection || {});
    if (entries.length) {
      $("#collection-text").value = entries.map((n) => r.collection[n] + " " + n).join("\n");
    }
  } catch (e) { /* fine on first run */ }

  if ($("#search-q").value) runSearch(true);
})();

/* Clicking a printing thumbnail in the hunt plan opens the full artwork, so
   you can compare it against what the seller described. */
$("#hunt-plan").addEventListener("click", (ev) => {
  const img = ev.target.closest("img[data-full]");
  if (!img) return;
  window.open(img.dataset.full, "_blank", "noopener");
});
