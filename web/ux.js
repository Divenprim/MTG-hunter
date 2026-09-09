
/* ==========================================================================
   Удобство: тема, отмена, горячие клавиши, недавние запросы, профили фильтров.

   Всё пользовательское тут хранится в браузере (store), а не на сервере: это
   состояние интерфейса, а не данные. Единственное исключение — отмена: она
   опирается на снапшоты в базе, которые пишутся и так.
   ========================================================================== */

/* ------------------------------------------------------------------ тема ---

   Три состояния. По умолчанию тёмная, а не «как в системе»: программа всегда
   была тёмной, и обновление не должно молча её перекрашивать — тем более что
   переключатель стоит рядом. «Как в системе» читает prefers-color-scheme и
   подписывается на изменение: переключится система вечером — переключится и
   страница. */

const THEME_KEY = "theme";
let themeMedia = null;

function applyTheme() {
  const mode = store.get(THEME_KEY, "dark") || "dark";
  const root = document.documentElement;
  root.dataset.theme = mode;
  if (!themeMedia && window.matchMedia) {
    themeMedia = window.matchMedia("(prefers-color-scheme: light)");
    // Системная настройка может поменяться, пока страница открыта.
    const react = () => applyTheme();
    if (themeMedia.addEventListener) themeMedia.addEventListener("change", react);
    else if (themeMedia.addListener) themeMedia.addListener(react);
  }
  root.classList.toggle("sys-light", !!(themeMedia && themeMedia.matches));
  $$("#theme-switch button").forEach((b) => {
    b.classList.toggle("on", b.dataset.theme === mode);
  });
}

$("#theme-switch").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-theme]");
  if (!btn) return;
  store.set(THEME_KEY, btn.dataset.theme);
  applyTheme();
});

/* --------------------------------------------------------------- отмена ---

   Уведомление с кнопкой. Каждое хранилище и так снимает снапшот перед
   изменением — это было ради списка резервных копий, но того же снапшота
   хватает, чтобы вернуть всё назад. Поэтому «Отменить» не требует новой
   бухгалтерии, только кнопки.

   Предлагается не всегда, а там, где потеря заметна: удаление, замена,
   снятие отметки, получение заказа. */

function toastUndo(msg, kind, after) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("error");
  const btn = document.createElement("button");
  btn.className = "undo";
  btn.textContent = "Отменить";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const r = await post("/api/undo", { kind: kind });
      el.classList.remove("show");
      toast("Отменено: " + (r.label || kind));
      if (typeof after === "function") await after(r);
    } catch (e) {
      toast(e.message, true);
    }
  });
  el.appendChild(btn);
  el.classList.add("show");
  clearTimeout(toastTimer);
  // Дольше обычного: на «отменить» нужно время, чтобы понять, что произошло.
  toastTimer = setTimeout(() => el.classList.remove("show"), 9000);
}

/* Что перерисовать после отмены — зависит от того, что откатили. Ответ отмены
   уже несёт свежее состояние всех трёх хранилищ, так что второй раз спрашивать
   сервер не нужно. */
async function afterUndo(r) {
  if (r.orders && typeof applyOrderState === "function") {
    applyOrderState(r.orders);
    if (typeof refreshOrderViews === "function") refreshOrderViews();
  }

  if (r.favourites && typeof renderFavourites === "function") {
    const doc = r.favourites.favourites || r.favourites;
    if (doc && doc.folders) {
      favDoc = doc;
      if (!favDoc.folders.some((f) => f.id === favCurrent)) {
        favCurrent = favDoc.folders[0] ? favDoc.folders[0].id : null;
      }
      renderFavourites();
      if (typeof renderDeckFolderOptions === "function") renderDeckFolderOptions();
    }
  }

  // Коллекция живёт в текстовом поле: после отката его надо перечитать.
  try {
    const coll = await api("/api/collection");
    const entries = Object.keys(coll.collection || {});
    const box = $("#collection-text");
    if (box) {
      box.value = entries.map((n) => coll.collection[n] + " " + n).join("\n");
    }
  } catch (e) { /* поле не критично */ }

  if (typeof loadBackups === "function") loadBackups();
  refreshStatus();
}

/* ------------------------------------------------------ горячие клавиши ---

   Один список: из него собирается и окно, и подсказки. Расходиться нечему. */

const HOTKEYS = [
  ["Везде", [
    ["?", "это окно"],
    ["Esc", "закрыть окно или вернуться к запросу"],
  ]],
  ["Поиск", [
    ["/", "в строку запроса"],
    ["↓", "из строки — в результаты"],
    ["← ↑ → ↓", "по картам"],
    ["Enter", "открыть карту"],
    ["1…4", "добавить столько штук в охоту"],
    ["f", "в избранное"],
  ]],
  ["Билдер", [
    ["↑ ↓", "по картам"],
    ["← →", "по колонкам или стопкам"],
    ["+ −", "количество карты"],
    ["Del", "убрать карту из колоды"],
    ["Enter", "открыть карту"],
    ["/", "в фильтр по колоде"],
  ]],
  ["Строка запроса", [
    ["↓", "недавние и сохранённые запросы"],
    ["Ctrl+S", "сохранить текущий запрос"],
  ]],
];

function keysHtml() {
  return HOTKEYS.map(([title, rows]) =>
    '<div class="keygroup"><h4>' + esc(title) + "</h4>" +
    rows.map(([key, what]) =>
      '<div class="keyrow"><kbd>' + esc(key) + "</kbd><span>" +
      esc(what) + "</span></div>").join("") +
    "</div>").join("");
}

function keysOpen() {
  $("#keys-body").innerHTML = keysHtml();
  $("#keys-overlay").hidden = false;
}

function keysClose() {
  $("#keys-overlay").hidden = true;
}

$("#keys-btn").addEventListener("click", keysOpen);
$("#keys-close").addEventListener("click", keysClose);
$("#keys-overlay").addEventListener("click", (ev) => {
  if (ev.target === $("#keys-overlay")) keysClose();
});

/* ------------------------------------------------- недавние запросы ---

   Поиск ничего не помнил, а запросы вроде `s:secretlair cn>=2081 cn<=2101`
   набираются заново каждый раз. Последние — сами, именованные — по Ctrl+S. */

const RECENT_KEY = "recentQueries";
const SAVED_KEY = "savedQueries";
const RECENT_KEEP = 12;

function recentList() {
  const v = store.get(RECENT_KEY, []);
  return Array.isArray(v) ? v : [];
}

function savedList() {
  const v = store.get(SAVED_KEY, []);
  return Array.isArray(v) ? v : [];
}

function rememberQuery(q) {
  const clean = (q || "").trim();
  if (clean.length < 2) return;
  const list = recentList().filter((x) => x !== clean);
  list.unshift(clean);
  store.set(RECENT_KEY, list.slice(0, RECENT_KEEP));
}

function saveQuery() {
  const q = $("#search-q").value.trim();
  if (!q) return toast("Строка запроса пуста", true);
  const name = prompt("Назвать запрос:", q.slice(0, 40));
  if (!name) return;
  const list = savedList().filter((x) => x.name !== name);
  list.unshift({ name: name, q: q });
  store.set(SAVED_KEY, list.slice(0, 40));
  toast("Запрос сохранён: " + name);
  queriesRender();
}

function queriesBox() {
  let box = $("#recent-queries");
  if (!box) {
    box = document.createElement("div");
    box.id = "recent-queries";
    box.hidden = true;
    document.body.appendChild(box);
  }
  return box;
}

function queriesRender() {
  const box = queriesBox();
  const saved = savedList();
  const recent = recentList();
  if (!saved.length && !recent.length) {
    box.innerHTML = '<div class="qhead">пока пусто — Ctrl+S сохранит текущий запрос</div>';
    return;
  }
  box.innerHTML =
    (saved.length
      ? '<div class="qhead">сохранённые</div>' + saved.map((row) =>
          '<div class="qrow" data-q="' + esc(row.q) + '">' +
            "<b>" + esc(row.name) + "</b>" +
            '<span class="q">' + esc(row.q) + "</span>" +
            '<span class="drop" data-drop-saved="' + esc(row.name) + '" title="убрать">×</span>' +
          "</div>").join("")
      : "") +
    (recent.length
      ? '<div class="qhead">недавние</div>' + recent.map((q) =>
          '<div class="qrow" data-q="' + esc(q) + '">' +
            '<span class="q">' + esc(q) + "</span>" +
            '<span class="drop" data-drop-recent="' + esc(q) + '" title="забыть">×</span>' +
          "</div>").join("")
      : "");
}

function queriesOpen() {
  const box = queriesBox();
  queriesRender();
  const field = $("#search-q");
  const r = field.getBoundingClientRect();
  box.style.left = Math.round(r.left) + "px";
  box.style.top = Math.round(r.bottom + window.scrollY + 4) + "px";
  box.style.width = Math.round(r.width) + "px";
  box.hidden = false;
}

function queriesClose() {
  queriesBox().hidden = true;
}

function queriesPick(q) {
  $("#search-q").value = q;
  queriesClose();
  if (typeof runSearch === "function") runSearch(true);
}

document.addEventListener("click", (ev) => {
  const box = $("#recent-queries");
  if (!box || box.hidden) return;
  if (ev.target === $("#search-q")) return;
  if (!box.contains(ev.target)) queriesClose();
});

queriesBox().addEventListener("click", (ev) => {
  const savedDrop = ev.target.dataset && ev.target.dataset.dropSaved;
  const recentDrop = ev.target.dataset && ev.target.dataset.dropRecent;
  if (savedDrop) {
    store.set(SAVED_KEY, savedList().filter((x) => x.name !== savedDrop));
    queriesRender();
    return;
  }
  if (recentDrop) {
    store.set(RECENT_KEY, recentList().filter((x) => x !== recentDrop));
    queriesRender();
    return;
  }
  const row = ev.target.closest(".qrow");
  if (row) queriesPick(row.dataset.q);
});

/* --------------------------------------------- профили фильтров охоты ---

   Фильтры настраивались заново каждый раз. Профиль — это снимок всех полей
   фильтра под именем; переключение одним нажатием. */

const PROFILE_KEY = "huntProfiles";
// Ровно те поля, что есть в панели охоты. Языки отдельно: у чекбоксов языка
// нет id, они выбираются по классу.
const FILTER_FIELDS = [
  "f-condition", "f-maxprice", "f-refs", "f-cities", "f-strategy", "f-shops",
  "f-users", "f-collection", "f-needlang", "f-needcond", "f-skip-ordered",
];

function profileList() {
  const v = store.get(PROFILE_KEY, []);
  return Array.isArray(v) ? v : [];
}

function fieldValues() {
  const out = { langs: $$(".lang:checked").map((c) => c.value) };
  FILTER_FIELDS.forEach((id) => {
    const el = $("#" + id);
    if (!el) return;
    out[id] = el.type === "checkbox" ? el.checked : el.value;
  });
  return out;
}

function applyFieldValues(values) {
  const langs = (values && values.langs) || [];
  $$(".lang").forEach((c) => { c.checked = langs.indexOf(c.value) >= 0; });
  Object.keys(values || {}).forEach((id) => {
    if (id === "langs") return;
    const el = $("#" + id);
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!values[id];
    else el.value = values[id];
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function profilesRender() {
  const box = $("#hunt-profiles");
  if (!box) return;
  const list = profileList();
  box.innerHTML =
    '<div class="row tight wrap">' +
      '<span class="meta">Профили фильтров:</span>' +
      (list.length
        ? list.map((p) =>
            '<span class="chip" data-profile="' + esc(p.name) + '">' + esc(p.name) +
            '<span class="drop" data-drop-profile="' + esc(p.name) + '" title="убрать">×</span>' +
            "</span>").join("")
        : '<span class="meta">пока нет</span>') +
      '<button type="button" class="ghost tiny" id="hunt-profile-save">Сохранить текущие</button>' +
    "</div>";
}

$("#hunt-profiles").addEventListener("click", (ev) => {
  if (ev.target.id === "hunt-profile-save") {
    const name = prompt("Название профиля:", "рус, NM, до 500");
    if (!name) return;
    const list = profileList().filter((p) => p.name !== name);
    list.push({ name: name, values: fieldValues() });
    store.set(PROFILE_KEY, list.slice(0, 20));
    profilesRender();
    toast("Профиль сохранён: " + name);
    return;
  }
  const drop = ev.target.dataset && ev.target.dataset.dropProfile;
  if (drop) {
    store.set(PROFILE_KEY, profileList().filter((p) => p.name !== drop));
    profilesRender();
    return;
  }
  const chip = ev.target.closest("[data-profile]");
  if (chip) {
    const found = profileList().find((p) => p.name === chip.dataset.profile);
    if (found) {
      applyFieldValues(found.values);
      toast("Фильтры: " + found.name);
    }
  }
});

/* ------------------------------------------------------------ что нового ---

   Обновление — это распаковка архива поверх папки, и о новых кнопках узнать
   негде. Показывается один раз на браузер и закрывается насовсем. */

const SEEN_KEY = "seenVersion";

async function showWhatsNew() {
  const box = $("#whatsnew");
  if (!box) return;
  try {
    const seen = store.get(SEEN_KEY, "") || "";
    const r = await api("/api/whatsnew?seen=" + encodeURIComponent(seen));
    if (!r.fresh || !r.entries.length) return;
    box.innerHTML =
      '<div class="row tight wrap">' +
        "<h3>Версия " + esc(r.version) + " — что нового</h3>" +
        '<span style="flex:1"></span>' +
        '<button type="button" class="ghost tiny" id="whatsnew-close">Понятно</button>' +
      "</div>" +
      r.entries.map((e) =>
        (r.entries.length > 1 ? "<b>" + esc(e.version) + " · " + esc(e.title) + "</b>" : "") +
        "<ul>" + e.lines.map((l) => "<li>" + esc(l) + "</li>").join("") + "</ul>"
      ).join("");
    box.hidden = false;
    $("#whatsnew-close").addEventListener("click", () => {
      store.set(SEEN_KEY, r.version);
      box.hidden = true;
    });
  } catch (e) {
    // Новости — не повод ломать загрузку страницы.
  }
}

/* --------------------------------------------------------- клавиши общие --- */

document.addEventListener("keydown", (ev) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);

  if (ev.key === "Escape") {
    if (!$("#keys-overlay").hidden) { keysClose(); return; }
    const box = $("#recent-queries");
    if (box && !box.hidden) { queriesClose(); return; }
  }

  // Ctrl+S в строке запроса сохраняет запрос, а не страницу.
  if (ev.key.toLowerCase() === "s" && (ev.ctrlKey || ev.metaKey)
      && document.activeElement.id === "search-q") {
    ev.preventDefault();
    saveQuery();
    return;
  }

  if (ev.key === "?" && !typing) {
    ev.preventDefault();
    keysOpen();
  }
});

$("#search-q").addEventListener("keydown", (ev) => {
  const box = $("#recent-queries");
  if (ev.key === "ArrowDown" && !$("#search-q").value.trim() && (!box || box.hidden)) {
    // Пустая строка и ↓ — показать историю, а не прыгать в результаты.
    ev.preventDefault();
    ev.stopPropagation();
    queriesOpen();
  }
});

function queriesMaybeOpen() {
  // И по фокусу, и по клику: в уже сфокусированное поле фокус второй раз не
  // приходит, а показать историю всё равно надо.
  if (!$("#search-q").value.trim()) queriesOpen();
}

$("#search-q").addEventListener("focus", queriesMaybeOpen);
$("#search-q").addEventListener("click", queriesMaybeOpen);
$("#search-q").addEventListener("input", () => {
  if ($("#search-q").value.trim()) queriesClose();
});

/* Кнопки в шапке и состояние темы — сразу, как только этот файл загружен:
   init() в app.js стартует раньше, чем существует applyTheme. */
applyTheme();
