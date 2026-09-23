/* Семейство колод: разные исполнения одного замысла рядом.

   История колоды идёт вдоль -- версия за версией. Развитие колоды так не
   выглядит: два turbofog это не «было-стало», а два исполнения одного замысла,
   и главный вопрос к ним не «что поменялось», а что у них общего. Общее и есть
   колода; остальное -- сменные части.

   Поэтому здесь матрица: строки -- карты, столбцы -- исполнения. Строка,
   закрашенная целиком, и есть ядро, и это видно без чтения. Ячейку можно
   править прямо в матрице: плюс и минус меняют колоду, а не показывают её.

   Отмеченные строки собираются в модуль -- кусок колоды, который дальше
   кладётся в любое исполнение целиком. */

let famData = null;
let famName = null;
let famPicked = new Set();          // колоды для разового сравнения
let famRows = new Set();            // строки, отмеченные под модуль
let famModules = [];

const FAM_GROUPS = [
  ["core", "Ядро", "есть во всех исполнениях — это и есть колода"],
  ["often", "Почти везде", "выкидывали, но возвращали"],
  ["flex", "Сменные", "место, где колода ещё не решена"],
  ["side_only", "Уже в сайдборде", "вынесено из основной колоды"],
];

async function famLoad(name) {
  try {
    const list = await api("/api/families");
    famRenderFamilies(list.families || []);
    famModules = (await api("/api/modules")).modules || [];
    famRenderModules();
  } catch (e) {
    $("#fam-side").innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
    return;
  }
  if (name) await famOpen(name);
}

async function famOpen(name) {
  famName = name;
  famRows = new Set();
  try {
    famData = await api("/api/family?name=" + encodeURIComponent(name));
  } catch (e) {
    $("#fam-main").innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
    return;
  }
  famRender();
  famGroupReady();
}

/* Групповые вопросы (спеки, руки, покупки) имеют смысл только когда группа
   открыта -- и относятся ровно к ней. */
function famGroupReady() {
  const bar = $("#fam-groupbar");
  if (bar) bar.hidden = !(famData && (famData.variants || []).length);
  if (typeof fgReset === "function") fgReset();
}

async function famCompare() {
  if (famPicked.size < 2) return toast("Отметьте хотя бы две колоды", true);
  famName = null;
  famRows = new Set();
  try {
    famData = await post("/api/family/compare",
                         { deck_ids: Array.from(famPicked) });
  } catch (e) {
    return toast(e.message, true);
  }
  famRender();
  famGroupReady();
}

/* --------------------------------------------------------------- боковая */

function famRenderFamilies(families) {
  const rows = families.map((f) =>
    '<div class="famrow' + (f.name === famName ? " on" : "") +
      '" data-family="' + esc(f.name) + '">' +
      "<b>" + esc(f.name) + "</b>" +
      '<span class="meta">' + f.variants +
        (f.variants === 1 ? " исполнение" : " исполнения") +
        (f.explicit ? "" : " · само по себе") + "</span>" +
    "</div>").join("");

  const decks = (bdDecks || []).map((d) =>
    '<label class="famdeck"><input type="checkbox" data-pick="' + esc(d.id) + '"' +
      (famPicked.has(d.id) ? " checked" : "") + "> " + esc(d.name) +
      '<span class="meta">' + esc(d.format || "") + "</span></label>").join("");

  $("#fam-side").innerHTML =
    "<h4>Семейства</h4>" + (rows || '<p class="meta">Пока нечего сравнивать.</p>') +
    "<h4>Сравнить любые</h4>" +
    '<div class="famdecks">' + decks + "</div>" +
    '<div class="row tight"><button id="fam-compare" class="ghost">' +
      "Сравнить отмеченные</button></div>";
}

function famRenderModules() {
  const rows = famModules.map((m) =>
    '<div class="modrow" data-module="' + esc(m.id) + '">' +
      "<b>" + esc(m.name) + "</b>" +
      '<span class="meta">' + m.names + " назв. / " + m.copies + " шт.</span>" +
      '<span class="meta">' + esc(m.cards.map(
        (c) => c.quantity + "× " + c.name).join(", ")) + "</span>" +
      '<div class="row tight">' +
        '<select data-into="' + esc(m.id) + '">' +
          (bdDecks || []).map((d) =>
            '<option value="' + esc(d.id) + '">' + esc(d.name) + "</option>").join("") +
        "</select>" +
        '<button class="ghost tiny" data-apply="' + esc(m.id) + '">положить</button>' +
        '<button class="ghost tiny" data-delmod="' + esc(m.id) + '">убрать</button>' +
      "</div>" +
    "</div>").join("");
  $("#fam-modules").innerHTML =
    "<h4>Модули</h4>" +
    '<p class="meta">Кусок колоды, который имеет смысл только целиком: ' +
    "«скипетр с туманом», пакет гейтов, движок добора. Отметьте строки в " +
    "матрице и соберите — потом кладётся в любое исполнение одной кнопкой.</p>" +
    (rows || '<p class="meta">Пока ни одного.</p>');
}

/* ---------------------------------------------------------------- матрица */

function famCell(row, variant) {
  const n = row.counts[variant.id] || 0;
  const side = row.in_side[variant.id] || 0;
  return '<span class="famcell' + (n ? "" : " zero") + '" data-cell="' +
      esc(row.key) + "|" + esc(variant.id) + '">' +
      '<button class="famminus" data-less="' + esc(row.name) + "|" +
        esc(variant.id) + '" title="убрать одну">−</button>' +
      "<b>" + (n || (side ? "сб" : "·")) + "</b>" +
      '<button class="famplus" data-more="' + esc(row.name) + "|" +
        esc(variant.id) + '" title="добавить одну">+</button>' +
    "</span>";
}

function famRender() {
  const data = famData;
  const vars = data.variants || [];
  const t = data.totals || {};

  const head =
    '<div class="famhead">' +
      "<h3>" + esc(data.name || "Сравнение") + "</h3>" +
      '<span class="meta">' + t.variants + " исполнения · " + t.names +
        " назв. · ядро " + t.core_names + " назв. / " + t.core_copies +
        " шт. · сменных " + t.flex_names + "</span>" +
      (data.name
        ? ""
        : '<button class="ghost tiny" id="fam-join">объединить в семейство</button>') +
    "</div>" +
    '<div class="famvars">' + vars.map((v) =>
      '<div class="famvar">' +
        "<b>" + esc(v.name) + "</b>" +
        '<span class="meta">' + esc(v.format || "") + " · " + v.copies +
          " шт. / " + v.names + " назв." +
          (v.assembled ? " · собрана" : "") + "</span>" +
        '<div class="row tight">' +
          '<button class="ghost tiny" data-open="' + esc(v.id) + '">открыть</button>' +
          '<button class="ghost tiny" data-branch="' + esc(v.id) +
            '">ответвить</button>' +
        "</div>" +
      "</div>").join("") + "</div>";

  const wincons = (data.wincons || []).map((k) =>
    (data.rows.find((r) => r.key === k) || {}).name).filter(Boolean);
  const sides = new Set(data.sideboard_candidates || []);

  const groups = FAM_GROUPS.map(([key, title, why]) => {
    const keys = new Set(data[key] || []);
    const rows = (data.rows || []).filter((r) => keys.has(r.key));
    if (!rows.length) return "";
    return '<div class="famgroup"><h4>' + title +
      ' <span class="meta">— ' + why + " (" + rows.length + ")</span></h4>" +
      rows.map((r) =>
        '<div class="famline' + (sides.has(r.key) ? " side" : "") + '">' +
          '<label class="famname">' +
            '<input type="checkbox" data-row="' + esc(r.key) + '"' +
              (famRows.has(r.key) ? " checked" : "") + ">" +
            "<span><b>" + esc(r.name) + "</b>" +
            (r.wincon ? ' <span class="chip ok">выигрывает</span>' : "") +
            (sides.has(r.key) ? ' <span class="chip">в сайдборд</span>' : "") +
            '<span class="meta">' + esc((r.tags || []).slice(0, 3).join(" · ")) +
            "</span></span>" +
          "</label>" +
          '<span class="famprice">' + (r.price ? rub(r.price) : "") + "</span>" +
          vars.map((v) => famCell(r, v)).join("") +
        "</div>").join("") +
      "</div>";
  }).join("");

  $("#fam-main").innerHTML = head +
    (wincons.length
      ? '<p class="meta">Чем выигрывает: <b>' + esc(wincons.join(", ")) +
        "</b></p>"
      : '<p class="meta">Карты, которая выигрывает сама, среди них нет — ' +
        "значит, побеждают уроном или добиванием.</p>") +
    '<div class="fammatrix" style="--vars:' + vars.length + '">' + groups + "</div>" +
    '<div class="row tight fammake">' +
      '<input type="text" id="fam-modname" placeholder="название модуля" ' +
        'autocomplete="off">' +
      '<button id="fam-make" class="ghost">Собрать модуль из отмеченных</button>' +
      '<span class="meta" id="fam-picked"></span>' +
    "</div>";
  famUpdatePicked();
}

function famUpdatePicked() {
  const box = $("#fam-picked");
  if (box) {
    box.textContent = famRows.size
      ? "отмечено " + famRows.size
      : "отметьте строки слева";
  }
}

/* ------------------------------------------------------------- действия */

$("#panel-family").addEventListener("change", async (ev) => {
  const pick = ev.target.closest("[data-pick]");
  if (pick) {
    if (pick.checked) famPicked.add(pick.dataset.pick);
    else famPicked.delete(pick.dataset.pick);
    return;
  }
  const row = ev.target.closest("[data-row]");
  if (row) {
    if (row.checked) famRows.add(row.dataset.row);
    else famRows.delete(row.dataset.row);
    famUpdatePicked();
  }
});

$("#panel-family").addEventListener("click", async (ev) => {
  const t = ev.target;

  const fam = t.closest("[data-family]");
  if (fam) return famOpen(fam.dataset.family);

  if (t.id === "fam-compare") return famCompare();

  const open = t.closest("[data-open]");
  if (open) {
    showTab("builder");
    if (typeof bdOpen === "function") bdOpen(open.dataset.open);
    return;
  }

  const branch = t.closest("[data-branch]");
  if (branch) {
    const name = (window.prompt("Название нового исполнения") || "").trim();
    if (!name) return;
    try {
      await post("/api/decks/" + branch.dataset.branch + "/branch", { name: name });
      await bdLoadDecks();
      toast("Ответвлено: «" + name + "»");
      await famLoad(famName);
    } catch (e) { toast(e.message, true); }
    return;
  }

  if (t.id === "fam-join") {
    const name = (window.prompt("Название семейства",
      (famData.variants[0] || {}).name || "") || "").trim();
    if (!name) return;
    try {
      for (const v of famData.variants) {
        await api("/api/decks/" + v.id, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ family: name }),
        });
      }
      await bdLoadDecks();
      toast("Теперь это одно семейство: «" + name + "»");
      await famLoad(name);
    } catch (e) { toast(e.message, true); }
    return;
  }

  // Плюс и минус правят колоду прямо из матрицы: это и есть доработка
  // исполнения, ради которой на неё смотрят.
  const step = t.closest("[data-more], [data-less]");
  if (step) {
    const [name, deckId] = (step.dataset.more || step.dataset.less).split("|");
    const add = !!step.dataset.more;
    try {
      if (add) {
        await post("/api/decks/" + deckId + "/cards",
                   { cards: [{ name: name, quantity: 1, section: "main" }] });
      } else {
        const deck = (await api("/api/decks/" + deckId)).deck;
        const card = (deck.cards || []).find(
          (c) => c.name === name && c.section !== "maybe");
        if (!card) return;
        if (card.quantity > 1) {
          await api("/api/decks/" + deckId + "/cards/" + card.id, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ quantity: card.quantity - 1 }),
          });
        } else {
          await api("/api/decks/" + deckId + "/cards/" + card.id, { method: "DELETE" });
        }
      }
      famData = famName
        ? await api("/api/family?name=" + encodeURIComponent(famName))
        : await post("/api/family/compare",
                     { deck_ids: famData.variants.map((v) => v.id) });
      famRender();
    } catch (e) { toast(e.message, true); }
    return;
  }

  if (t.id === "fam-make") {
    const name = ($("#fam-modname").value || "").trim();
    if (!name) return toast("Дайте модулю название", true);
    if (!famRows.size) return toast("Отметьте строки в матрице", true);
    const cards = Array.from(famRows).map((key) => {
      const row = famData.rows.find((r) => r.key === key);
      return { name: row.name, quantity: Math.max(1, row.max), section: "main" };
    });
    try {
      famModules = (await post("/api/modules",
        { name: name, cards: cards })).modules;
      famRows = new Set();
      famRenderModules();
      famRender();
      toast("Модуль «" + name + "» собран");
    } catch (e) { toast(e.message, true); }
    return;
  }

  const apply = t.closest("[data-apply]");
  if (apply) {
    const into = $('#fam-modules [data-into="' + apply.dataset.apply + '"]');
    if (!into || !into.value) return;
    try {
      const r = await post("/api/decks/" + into.value + "/modules/" +
                           apply.dataset.apply, {});
      toast("Положено карт: " + r.added);
      await bdLoadDecks();
      if (famName) await famOpen(famName);
    } catch (e) { toast(e.message, true); }
    return;
  }

  const del = t.closest("[data-delmod]");
  if (del) {
    try {
      famModules = (await api("/api/modules/" + del.dataset.delmod,
                              { method: "DELETE" })).modules;
      famRenderModules();
    } catch (e) { toast(e.message, true); }
  }
});
