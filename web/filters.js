"use strict";

/* Панель фильтров: сборка запроса, типы, сеты, исполнения.

   Уехало из app.js. Панель одна на программу и переезжает между вкладками
   (`moveFilterPanel`), поэтому и код у неё свой.

   Загружается после app.js и до boot.js, который её вызывает при запуске.
*/

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

/* Куда сейчас смотрит панель фильтров: "search" или "collection".

   Панель одна на программу и физически переезжает в ту вкладку, где её
   позвали. Второй набор кнопок был бы второй правдой: в поиске есть теги
   назначения, подбор сетов, ключевые слова и исполнения, и любой новый фильтр
   пришлось бы заводить дважды -- а значит однажды он завёлся бы в одном
   месте. */
let filtersTarget = "search";

function filtersInput() {
  return filtersTarget === "collection" ? $("#coll-q") : $("#search-q");
}

function composeQuery() {
  const f = readFilterPanel();
  const parts = bareWords(filtersInput().value);

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
  const query = composeQuery();
  filtersInput().value = query;
  store.set("filters", readFilterPanel());
  if (filtersTarget === "collection") {
    if (typeof holdApplyQuery === "function") holdApplyQuery(query);
    return;
  }
  runSearch(true);
}

/* Панель переезжает целиком -- со своими обработчиками и с тем, что в ней
   уже набрано. */
function moveFilterPanel(where) {
  const panel = $("#filters-panel");
  const host = where === "collection" ? $("#coll-filters-host")
                                      : $("#panel-search");
  if (where === "collection") host.appendChild(panel);
  else host.insertBefore(panel, $("#search-results"));
  filtersTarget = where;
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

/* Кнопки самой панели. Жили в app.js рядом с поиском и остались там при
   переезде: строка `addEventListener("click", applyFilterPanel)` берёт
   функцию значением **в момент загрузки**, а та уехала в файл, который
   грузится позже. Страница падала на этой строке, и всё, что в app.js ниже,
   не выполнялось вовсе -- поиск переставал работать целиком. */
$("#filters-toggle").addEventListener("click", (ev) => {
  const panel = $("#filters-panel");
  // Панель могла остаться в коллекции -- зовём её обратно к поиску.
  const moving = filtersTarget !== "search";
  if (moving) moveFilterPanel("search");
  panel.hidden = moving ? false : !panel.hidden;
  ev.target.setAttribute("aria-expanded", String(!panel.hidden));
  store.set("filtersOpen", !panel.hidden);
});
$("#filters-apply").addEventListener("click", applyFilterPanel);
$("#filters-reset").addEventListener("click", resetFilterPanel);
$("#f-colors").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".cbtn");
  if (btn) btn.classList.toggle("on");
});
