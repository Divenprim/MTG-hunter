"use strict";

/* Search by what a card is FOR, not by how it is worded.

   "рампа", "кража существ", "смена контроля" are not phrases printed on cards,
   so no amount of oracle-text matching finds them. Scryfall Tagger has 4524
   community-curated functional tags with 231k taggings, and a hierarchy: asking
   for `control-changing-effects` must also return its children, because the
   parent tag itself holds no cards.

   Loaded after app.js; uses its helpers and the shared filter state. */

let selectedTags = [];
let tagPresets = [];

function renderTagChips() {
  const box = $("#f-tag-chips");
  if (!box) return;
  box.innerHTML = selectedTags
    .map((t) => '<span class="chip removable tag" data-tag="' + esc(t) + '">' +
      esc(tagLabel(t)) + " ×</span>")
    .join("");
  $$("#f-tag-presets button").forEach((b) => {
    b.classList.toggle("on", selectedTags.indexOf(b.dataset.tag) >= 0);
  });
  $$("#f-tag-list .tagrow, #f-typal-list .tagrow").forEach((row) => {
    row.classList.toggle("on", selectedTags.indexOf(row.dataset.tag) >= 0);
  });
}

function tagLabel(slug) {
  const preset = tagPresets.find((p) => p.slug === slug);
  return preset ? preset.label : slug;
}

function toggleTag(slug) {
  const at = selectedTags.indexOf(slug);
  if (at >= 0) selectedTags.splice(at, 1);
  else selectedTags.push(slug);
  renderTagChips();
  applyFilterPanel();
}

function renderTagPresets() {
  $("#f-tag-presets").innerHTML = tagPresets
    .map((p) => '<button type="button" data-tag="' + esc(p.slug) + '" title="' +
      esc(p.slug) + '">' + esc(p.label) + "</button>")
    .join("");
  renderTagChips();
}

function renderTagList(tags) {
  $("#f-tag-list").innerHTML = tags.map((t) =>
    '<div class="tagrow" data-tag="' + esc(t.slug) + '">' +
      '<span class="slug">' + esc(t.slug) + "</span>" +
      '<span class="desc">' + esc(t.description || "") + "</span>" +
      '<span class="n">' + t.card_count + "</span>" +
    "</div>").join("");
  renderTagChips();
}

async function searchTags(needle) {
  try {
    const r = await api("/api/tags?limit=60&q=" + encodeURIComponent(needle || ""));
    if (r.presets && r.presets.length && !tagPresets.length) {
      tagPresets = r.presets;
      renderTagPresets();
    }
    if (r.keywords && r.keywords.length && !$("#f-kw-presets").innerHTML) {
      renderKeywordPresets(r.keywords);
    }
    if (r.typal && r.typal.length && !typalTags.length) {
      typalTags = r.typal;
      renderTypalList("");
    }
    renderTagList(r.tags || []);
    if (needle && !(r.tags || []).length) {
      $("#f-tag-list").innerHTML =
        '<div class="tagrow"><span class="desc">Метки с «' + esc(needle) + "» не нашлось</span></div>";
    }
  } catch (e) {
    $("#f-tag-list").innerHTML =
      '<div class="tagrow"><span class="desc">не удалось загрузить метки</span></div>';
  }
}

$("#f-tag-presets").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (btn) toggleTag(btn.dataset.tag);
});

$("#f-tag-list").addEventListener("click", (ev) => {
  const row = ev.target.closest(".tagrow");
  if (row && row.dataset.tag) toggleTag(row.dataset.tag);
});

$("#f-tag-chips").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip.removable");
  if (chip) toggleTag(chip.dataset.tag);
});

$("#f-tag-input").addEventListener("input", debounce((ev) => {
  searchTags(ev.target.value.trim());
}, 300));

/* --------------------------------------------------------- keywords & typal */

/* "Направление" is not always a functional tag. Defender, Flash and the other
   223 printed keyword abilities have no Tagger tag at all (the only
   defender-related tag, `turns-off-defender-self`, means the opposite), and
   tribes live in 238 separate `typal-*` tags. Both belong here rather than
   buried in the generic tag list. */

let selectedKeywords = [];
let typalTags = [];

function renderKeywordChips() {
  $$("#f-kw-presets button").forEach((b) => {
    b.classList.toggle("on", selectedKeywords.indexOf(b.dataset.kw) >= 0);
  });
}

function renderKeywordPresets(list) {
  $("#f-kw-presets").innerHTML = list
    .map((k) => '<button type="button" data-kw="' + esc(k.keyword) + '" title="' +
      esc(k.keyword) + '">' + esc(k.label) + "</button>")
    .join("");
  renderKeywordChips();
}

$("#f-kw-presets").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  const at = selectedKeywords.indexOf(btn.dataset.kw);
  if (at >= 0) selectedKeywords.splice(at, 1);
  else selectedKeywords.push(btn.dataset.kw);
  renderKeywordChips();
  applyFilterPanel();
});

function renderTypalList(filter) {
  const needle = (filter || "").trim().toLowerCase();
  const rows = (needle
    ? typalTags.filter((t) => t.slug.indexOf(needle) >= 0)
    : typalTags).slice(0, 60);
  $("#f-typal-list").innerHTML = rows.map((t) =>
    '<div class="tagrow' + (selectedTags.indexOf(t.slug) >= 0 ? " on" : "") +
      '" data-tag="' + esc(t.slug) + '">' +
      '<span class="slug">' + esc(t.slug.replace("typal-", "")) + "</span>" +
      '<span class="desc">' + esc(t.description || "") + "</span>" +
      '<span class="n">' + t.card_count + "</span>" +
    "</div>").join("");
}

$("#f-typal-list").addEventListener("click", (ev) => {
  const row = ev.target.closest(".tagrow");
  if (!row) return;
  toggleTag(row.dataset.tag);
  renderTypalList($("#f-typal-input").value);
});

$("#f-typal-input").addEventListener("input", debounce((ev) => {
  renderTypalList(ev.target.value);
}, 200));

// Load everything last: the initial fetch fills the keyword and typal blocks,
// whose state is declared above.
searchTags("");
