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

/* Насколько высока шапка -- вопрос к экрану, а не к стилям.

   Верхняя полоса прилипшая, и всё остальное прилипшее -- строка столбцов в
   учёте, счётчик, полоса отмеченных в билдере -- липло к `top: 0`, то есть
   ровно под неё. Измерено: шапка кончается на 56-й точке, строка столбцов
   встаёт на нулевой -- её не было видно никогда. Высота полосы при этом не
   постоянная: на узком экране вкладки переносятся, и она становится вдвое
   выше.

   Поэтому высота измеряется и кладётся в переменную, а прилипающие строки
   смотрят на неё. */
function measureTopbar() {
  const bar = $(".topbar");
  if (!bar) return;
  // Узкое окно: шапка намеренно перестаёт быть липкой и уезжает вверх вместе
  // со страницей. Отступ под неё при этом не нужен -- иначе липкие строки
  // висят в пустоте на 93 пикселя выше того, к чему они прилипли.
  const sticky = getComputedStyle(bar).position === "sticky";
  const h = sticky ? Math.round(bar.getBoundingClientRect().height) : 0;
  document.documentElement.style.setProperty("--topbar-h", h + "px");
}

window.addEventListener("resize", debounce(measureTopbar, 150));
window.addEventListener("load", measureTopbar);
measureTopbar();

/* Шапка растёт уже после загрузки: счётчик базы приходит ответом сервера,
   строка переносится, и 56 превращаются в 92. `load` этого не застаёт, а
   `resize` не случается -- окно никто не трогал. Выходило, что прилипшие
   строки отступают на 56 от шапки высотой 92, и счётчик коллекции сидел под
   ней, видимый на четыре пикселя из сорока. Чинилось только если потянуть
   окно мышью.

   ResizeObserver смотрит на саму шапку, а не на окно, поэтому ему всё равно,
   отчего она изменилась: ответ сервера, смена темы, длинный адрес в сети. */
if (typeof ResizeObserver === "function") {
  const bar = $(".topbar");
  if (bar) new ResizeObserver(debounce(measureTopbar, 50)).observe(bar);
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
  // Уведомление не только скрывается, но и очищается. Скрытое оно оставалось
  // в тексте страницы навсегда: «Заказ отмечен» читалось в разметке спустя
  // три смены экрана, попадало в чтение с экрана и выглядело -- в том числе
  // для проверок -- как застрявшее сообщение.
  toastTimer = setTimeout(() => {
    el.classList.remove("show");
    hideToastSoon(el);
  }, isError ? 7000 : 3000);
}

/* Текст убирается не сразу: у ленты есть переход, и обнулить её содержимое в
   ту же миллисекунду -- значит мигнуть пустой лентой. */
let toastClear = null;
function hideToastSoon(el) {
  clearTimeout(toastClear);
  toastClear = setTimeout(() => {
    if (!el.classList.contains("show")) el.textContent = "";
  }, 600);
}

/* Во что превратить ответ сервера, когда он отказал.

   Раньше всё, что не строка, уходило в `JSON.stringify` -- и человек видел на
   экране `[{"type":"model_attributes_type","loc":["body"],"msg":"Input should
   be a valid dictionary"}]`. Для игрока это набор английских слов и палочек:
   непонятно, сломалась программа, виноват ли он сам, и надо ли что-то
   устанавливать.

   Разборные ошибки сервера -- это всегда ошибка программы, а не человека: он
   не выбирает, что ей отправить. Поэтому они сводятся к одной внятной фразе, а
   подробности уходят в консоль, где им и место. */
function apiTrouble(detail, status) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    console.warn("сервер не принял запрос:", detail);
    return "Программа отправила запрос, который сервер не понял. "
         + "Это её ошибка, не ваша.";
  }
  if (status === 404) return "Не нашлось — возможно, уже удалено.";
  if (status === 409) return "Сейчас этого сделать нельзя.";
  if (status >= 500) return "Сервер не справился. Попробуйте ещё раз.";
  if (!status) return "Нет связи с программой.";
  return "Не получилось (код " + status + ").";
}

async function api(path, options) {
  const resp = await fetch(path, options);
  let payload = null;
  try { payload = await resp.json(); } catch (e) { /* error page, not JSON */ }
  if (!resp.ok) {
    const detail = (payload && (payload.detail || payload.message));
    throw new Error(apiTrouble(detail, resp.status));
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

/* Две валюты, и каждая пишется одним способом.

   Рубли -- это настоящая цена у продавца, доллары -- мировая оценка Scryfall,
   по которой сверяются. Смешивать их нельзя, а писать по-разному -- тем более:
   на соседних экранах стояли «$81.08» и «$131,89», потому что в одном месте
   доллары печатались через toFixed, а в другом через русскую локаль, которая
   ставит запятую. Доллар -- всегда с точкой, рубль -- всегда с пробелом по
   тысячам: так эти числа пишут там, откуда они взяты. */
const rub = (n) => Number(n || 0).toLocaleString("ru") + " ₽";
/* Имя не `usd`: в шести местах так названо само число, и короткое имя
   функции молча перекрывалось бы локальной переменной. */
const dollars = (n) => "$" + Number(n || 0).toFixed(2);

/* Russian counts need the right ending: 1 предложение, 2 предложения,
   5 предложений. "отброшено 1 предложений" is the kind of small wrongness that
   makes a whole interface feel unfinished. */
/* Цена и то, чем она была. Приписка появляется только если цена менялась:
   «стало дешевле» имеет смысл, «было столько же» — нет. */
function wasPrice(price) {
  if (!price || price.was == null || price.min == null) return "";
  if (price.was === price.min) return "";
  const down = price.min < price.was;
  return '<span class="wasprice ' + (down ? "down" : "up") + '" title="' +
    (price.was_at ? "прошлая проверка: " + esc(price.was_at) : "прошлая цена") +
    '">(было ' + Number(price.was).toLocaleString("ru") + " ₽)</span>";
}

function plural(n, one, few, many) {
  const abs = Math.abs(Number(n) || 0) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return many;
  if (last > 1 && last < 5) return few;
  if (last === 1) return one;
  return many;
}

const offersWord = (n) => plural(n, "предложение", "предложения", "предложений");

/* Сколько печатей в базе. Живое число из ответа сервера: приветствие и шапка
   отвечают на один вопрос и должны отвечать одинаково. */
let dbPrintings = 0;
/* «отказались от 1 предложения», а не «от 1 предложение»: после предлога
   нужен родительный, и форма для единицы здесь другая. */
const offersWordOf = (n) => plural(n, "предложения", "предложений", "предложений");

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

/* Полоса вкладок на телефоне длиннее экрана вдвое и прокручивается пальцем.
   Две вещи делают это читаемым: текущая вкладка всегда видна целиком (иначе
   слева оставалось «лдер» от «Билдера»), и край полосы растворяется там, где
   за ним ещё что-то есть. */
function tabsEdges() {
  const strip = $(".tabs");
  if (!strip) return;
  const room = strip.scrollWidth - strip.clientWidth;
  strip.classList.toggle("more-left", room > 1 && strip.scrollLeft > 4);
  strip.classList.toggle("more-right", room > 1 && strip.scrollLeft < room - 4);
}

function tabsShowActive() {
  const strip = $(".tabs");
  const now = strip && strip.querySelector(".tab.active");
  if (!now) return;
  if (strip.scrollWidth > strip.clientWidth + 1) {
    now.scrollIntoView({block: "nearest", inline: "nearest"});
  }
  tabsEdges();
}

function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  tabsShowActive();
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + name));
  store.set("tab", name);
  // Камера не должна оставаться включённой на вкладке, которую закрыли: это
  // и горящий индикатор рядом с объективом, и зря греющийся планшет.
  // Список колод мог устареть: колоду создают и на других вкладках --
  // ответвлением в «Версиях», например.
  // Открытую колоду перечитываем целиком, а не только список: её карты могли
  // поправить в «Версиях» -- плюсом и минусом прямо в матрице.
  if (name === "builder" && typeof bdLoadDecks === "function") {
    bdLoadDecks();
    if (typeof bdDeck !== "undefined" && bdDeck && typeof bdOpen === "function") {
      bdOpen(bdDeck.id);
    }
  }
  if (name === "collection" && typeof holdLoad === "function") holdLoad();
  // Зашли в охоту и ничего не ищем -- предложим прошлый результат вместо
  // пустого экрана. Заново магазин не спрашиваем.
  if (name === "hunt" && typeof offerLastHunt === "function") offerLastHunt();
  if (name === "family" && typeof famLoad === "function") famLoad(famName);
  if (name === "scan") {
    if (typeof scanRefreshStatus === "function") scanRefreshStatus();
    // Колоду могли завести только что -- список для «складывать в колоду»
    // перечитывается при каждом заходе на вкладку.
    if (typeof scanLoadDecks === "function") scanLoadDecks();
  } else if (typeof scanStop === "function" && typeof scanReady === "function"
             && scanReady()) {
    scanStop();
  }
}
$$(".tab").forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));
(function () {
  const strip = $(".tabs");
  if (!strip) return;
  strip.addEventListener("scroll", tabsEdges, {passive: true});
  window.addEventListener("resize", debounce(tabsShowActive, 150));
  window.addEventListener("load", tabsShowActive);
  tabsEdges();
})();

/* ================================================================== status */

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const db = s.db || {};
    if (!db.built) {
      $("#status").innerHTML = '<span style="color:var(--bad)">база карт не собрана — запустите build_db.py</span>';
      return;
    }
    // Адрес, по которому эта же страница открывается с планшета. Показан
    // только в сетевом режиме (run.bat lan) -- и сразу с оговоркой: пароля
    // нет, а коллекция и колоды видны всем, кто в этой сети.
    const lan = s.lan || {};
    const net = (lan.open && (lan.urls || []).length)
      ? ' · <span class="lanchip" title="Сервер открыт для всей локальной сети: ' +
        "пароля нет, кто в сети — тот и видит вашу коллекцию и колоды. " +
        'Только этот компьютер — запуск обычным run.bat.">с планшета: ' +
        esc((lan.urls || []).map((u) => u.replace("http://", "")).join(" · ")) +
        "</span>"
      : "";
    // То же число понадобится приветствию: там оно было вписано руками --
    // «108 тысяч» против живых 109 461 в шапке, два ответа на один вопрос.
    dbPrintings = db.printings || 0;
    $("#status").innerHTML =
      esc(db.printings.toLocaleString("ru")) + " печатей · " +
      esc(db.russian.toLocaleString("ru")) + " рус · коллекция: " +
      esc((s.collection_cards || 0).toLocaleString("ru")) + " шт." + net;
  } catch (e) {
    $("#status").textContent = "нет связи с сервером";
  }
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

/* ------------------------------------------------- что у меня уже есть

   Поиск отвечал на вопрос «что это за карта», но не на «нужна ли она мне»:
   в выдаче не было ни слова о том, что карта уже лежит в коллекции, хотя
   программа знает ответ -- он написан в шапке, «коллекция: 105 шт.». Чтобы
   проверить себя, человек уходил на вкладку «Коллекция», искал там и
   возвращался. Три действия ради того, чтобы не купить второй раз.

   Коллекция небольшая и целиком приходит одним ответом, поэтому держим её
   здесь и спрашиваем заново только после того, как она изменилась. */

let ownedCounts = {};

function normName(name) {
  return (name || "").trim().toLowerCase()
    .replace(/[’`]/g, "'").replace(/\s+/g, " ");
}

function setOwned(collection) {
  const map = {};
  const src = collection || {};
  for (const key of Object.keys(src)) map[normName(key)] = src[key];
  ownedCounts = map;
  refreshOwnedChips();
}

async function loadOwned() {
  try {
    const r = await api("/api/collection");
    setOwned(r.collection);
  } catch (e) {
    ownedCounts = {};
  }
}

/* Коллекция меняется, пока выдача на экране: карту положили в неё из этого
   же окна. Перерисовывать всю выдачу ради одной надписи незачем -- метки
   знают своё имя и обновляются на месте. */
function refreshOwnedChips() {
  for (const tile of $$("#search-results .card")) {
    const name = tile.dataset.name;
    if (!name) continue;
    const n = ownedCounts[normName(name)] || 0;
    let chip = tile.querySelector(".have");
    if (!n) {
      if (chip) chip.remove();
      continue;
    }
    if (!chip) {
      chip = document.createElement("span");
      chip.className = "have ok";
      tile.appendChild(chip);
    }
    chip.textContent = "у вас " + n + " шт.";
  }
}

/* Сколько копий этой карты у меня. Двусторонние карты коллекция хранит под
   полным именем, а выдача показывает ту сторону, что подошла под запрос, --
   поэтому спрашиваем обоими именами. */
function ownedOf(card) {
  if (!card) return 0;
  const tries = [card.name, card.display_name];
  for (const t of tries) {
    const n = ownedCounts[normName(t)];
    if (n) return n;
  }
  const full = (card.name || "").split("//")[0];
  return ownedCounts[normName(full)] || 0;
}

function ownedChip(card) {
  const n = ownedOf(card);
  return n ? '<span class="have ok">у вас ' + n + " шт.</span>" : "";
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
    '<div class="card" data-id="' + esc(c.id) + '" data-name="' + esc(c.name) + '"' +
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
    // Две валюты значат разное, и до сих пор об этом не было сказано нигде:
    // доллар -- мировая оценка Scryfall, рубль -- то, за что карту вправду
    // продают здесь. Рубль ближе к делу, поэтому он виден и стоит первым;
    // доллар остаётся для сверки и подписан.
    (c.rub && c.rub.min != null
      ? '<span class="rub" title="Самое дешёвое предложение на topdeck' +
        (c.rub.checked_at ? ", проверено " + esc(c.rub.checked_at) : "") +
        '">от ' + Number(c.rub.min).toLocaleString("ru") + " ₽</span>"
      : "") +
    (price
      ? '<span class="usd" title="Мировая оценка Scryfall — для сверки, не' +
        ' цена здесь">' + dollars(price) + "</span>"
      : "") +
    "</div>" +
    ownedChip(c) +
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
  // Наборы земель живут в том же контейнере: пока выбран их режим, обычный
  // поиск в него не пишет -- иначе список наборов затирается на каждом
  // нажатии в строке запроса.
  if (typeof lsMode === "function" && lsMode()) return;
  const q = $("#search-q").value.trim();
  const sort = $("#search-sort").value;
  store.set("query", q);
  store.set("sort", sort);
  // Запросы вроде `s:secretlair cn>=2081` набирать заново незачем.
  if (reset && typeof rememberQuery === "function") rememberQuery(q);
  if (typeof queriesClose === "function") queriesClose();

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
    // Пустая выдача -- это первый экран, на котором человек застревает. Одной
    // строчки «ничего не найдено» мало: непонятно, ошибся ли он в имени,
    // перемудрил ли с фильтрами или такой карты правда нет. Поэтому здесь
    // сказано, что именно искалось, и что можно сделать дальше.
    if (!shown) $("#search-results").innerHTML = searchNothing(q, r.instead);
    // Подсказка про мимо -- только на первой странице: на второй человек уже
    // понял, что ищет, и листает нарочно.
    const weakBox = $("#search-weak");
    if (weakBox) weakBox.remove();
    if (shown && reset && weakMatch(q, lastCards)) {
      $("#search-results").insertAdjacentHTML("afterbegin", searchWeakNote(q));
    }
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

/* Первый экран: что это за программа и с чего начать.

   Примеры -- нажимаемые: язык запросов проще показать, чем описать. Всё
   остальное -- три коротких указания на главные пути, потому что вкладок
   девять и по названиям не всегда понятно, какая из них нужна. */
const WELCOME_TRIES = [
  ["Fog", "по имени — и по русскому тоже"],
  ["otag:fog f:modern", "по назначению карты и формату"],
  ["t:creature c:g mv<=3 r:rare", "тип, цвет, мана, редкость"],
  ["s:dmu cn>=200", "сет и номер в нём"],
];

function searchWelcome() {
  return (
    '<div class="nothing welcome">' +
      "<b>MTG Hunter</b>" +
      '<p class="meta">Поиск идёт по локальной базе Scryfall — ' +
        (dbPrintings
          ? esc(dbPrintings.toLocaleString("ru")) + " бумажных печатей"
          : "бумажные печати") +
        ", включая русские. Наружу ничего не спрашивается, " +
        "пока вы сами не нажмёте «искать на topdeck».</p>" +
      '<p class="meta">Попробуйте:</p>' +
      '<div class="welcometries">' +
        WELCOME_TRIES.map(([q, why]) =>
          '<button type="button" class="ghost" data-try="' + esc(q) + '">' +
            "<code>" + esc(q) + "</code>" +
            '<span class="meta">' + esc(why) + "</span>" +
          "</button>").join("") +
      "</div>" +
      '<p class="meta">Дальше по вкладкам: <b>Билдер</b> — собрать колоду и ' +
        "увидеть, чего не хватает; <b>Охота</b> — найти недостающее у " +
        "продавцов и разложить по посылкам; <b>Сканер</b> — узнать карту " +
        "камерой и сложить коллекцию.</p>" +
    "</div>"
  );
}

/* Пустая выдача -- с объяснением и выходом.

   Запрос показывается целиком: чаще всего в нём и ошибка -- лишний фильтр или
   опечатка в имени. Если фильтры собирали панелью, предлагается искать только
   по имени: это ровно то, что человек делает руками, стирая половину строки. */
/* Русскую фразу -- в запрос.

   «Зелёная рампа» не находится и не может найтись: так не называется ни одна
   карта. По русским именам поиск ищет -- «Лес» даёт шестьдесят карт, -- а вот
   описание того, что человек хочет, он понять не может. Перевод приходит с
   сервера: словарь там тот же, по которому нарисована панель фильтров.

   Что не перевелось -- сказано вслух. Показать выдачу не по тому, что
   спрашивали, и промолчать было бы хуже, чем не показать ничего. */
function searchInstead(instead) {
  if (!instead || !instead.query) return "";
  const read = (instead.parts || [])
    .map((p) => esc(p.what) + " → <code>" + esc(p.term) + "</code>").join(", ");
  return (
    '<div class="instead">' +
      "<b>Похоже, это описание, а не имя карты</b>" +
      '<p class="meta">Так и ищется: ' + read + ".</p>" +
      ((instead.unknown || []).length
        ? '<p class="meta">Не понял: ' +
          instead.unknown.map((w) => "«" + esc(w) + "»").join(", ") +
          " — этих слов в словаре назначений нет, и в запрос они не вошли.</p>"
        : "") +
      '<button type="button" class="ghost" data-try="' + esc(instead.query) +
        '">Искать <code>' + esc(instead.query) + "</code></button>" +
    "</div>"
  );
}

/* Выдача не пустая, но мимо.

   «Молния» даёт двенадцать карт -- Ball Lightning, Branching Bolt и прочие,
   у которых есть слово «lightning» или «bolt», -- и ни одна из них не
   «Удар Молнии». Все подсказки шестого этапа висят на пустой выдаче, и
   здесь не срабатывает ни одна: человек видит дюжину чужих карт и решает,
   что его карты в базе нет.

   «Слабая» -- это когда ни одно имя не содержит того, что набрали. Проверка
   нарочно грубая: задача не угадать карту, а не молчать. */
function weakMatch(q, cards) {
  const words = String(q || "").trim().toLowerCase().split(/\s+/)
    .filter((w) => w && w.indexOf(":") < 0 && !/[<>=]/.test(w));
  if (!words.length || !cards.length) return false;
  const hit = (c) => {
    const names = [c.name, c.ru_name, c.display_name, c.flavor_name]
      .concat((c.faces || []).map((f) => f.name))
      .filter(Boolean).join(" | ").toLowerCase();
    return words.every((w) => names.indexOf(w) >= 0);
  };
  return !cards.some(hit);
}

function searchWeakNote(q) {
  const words = String(q || "").trim();
  return (
    '<div class="nothing weak" id="search-weak">' +
      "<b>Нашли не то?</b>" +
      '<p class="meta">Ни у одной найденной карты нет в имени «' +
        esc(words) + "» — это карты, подошедшие по другим словам. " +
        "У карт русские имена официальные: «Молния» — это " +
        "<b>Удар Молнии</b>, «Остров» — <b>Island</b>. " +
        "Попробуйте полное имя или его кусок.</p>" +
      '<p class="meta">Можно искать и по описанию того, что карта делает: ' +
        "<code>зелёная рампа</code>, <code>контрмагия</code>.</p>" +
    "</div>"
  );
}

function searchNothing(q, instead) {
  const parts = String(q || "").trim().split(/\s+/).filter(Boolean);
  const words = parts.filter((p) => p.indexOf(":") < 0 && !/[<>=]/.test(p));
  const filters = parts.filter((p) => words.indexOf(p) < 0);
  return (
    '<div class="nothing">' +
      "<b>Ничего не нашлось</b>" +
      '<p class="meta">Искали: <code>' + esc(q || "(пустой запрос)") + "</code></p>" +
      searchInstead(instead) +
      (filters.length
        ? '<p class="meta">Условий в запросе: ' + filters.length +
          ". Чем их больше, тем легче попасть в пустоту — уберите лишние " +
          "или поищите только по имени.</p>" +
          (words.length
            ? '<button type="button" class="ghost" data-onlyname="' +
              esc(words.join(" ")) + '">Искать только «' +
              esc(words.join(" ")) + "»</button>"
            : '<button type="button" class="ghost" id="nothing-reset">' +
              "Сбросить фильтры</button>")
        : '<p class="meta">Проверьте написание — ищется и по русским именам, ' +
          "и по обеим сторонам двусторонних карт. Или попробуйте часть имени: " +
          "поиск понимает кусок слова.</p>") +
      /* Панель фильтров не слева: она во всю ширину над выдачей и открывается
         кнопкой «Фильтры» над ней. Человек, которому сказали «слева»,
         смотрит налево, не находит ничего и решает, что назначений в
         программе нет -- хотя их там 35 готовых и 60 в полном списке.
         Поэтому называем не сторону, а кнопку, и сразу открываем панель. */
      '<p class="meta">Язык запросов понимает <code>t:creature</code>, ' +
        "<code>c:g</code>, <code>mv&lt;=3</code>, <code>otag:ramp</code>, " +
        "<code>s:dmu</code>, <code>r:rare</code> — и всё это можно собрать " +
        'кнопкой <button type="button" class="linkish" id="nothing-filters">' +
        "Фильтры</button> над выдачей: назначения карты там отдельной " +
        "группой.</p>" +
    "</div>"
  );
}

$("#search-results").addEventListener("click", (ev) => {
  const tryIt = ev.target.closest("[data-try]");
  if (tryIt) {
    $("#search-q").value = tryIt.dataset.try;
    runSearch(true);
    return;
  }

  const only = ev.target.closest("[data-onlyname]");
  if (only) {
    $("#search-q").value = only.dataset.onlyname;
    runSearch(true);
    return;
  }
  if (ev.target.id === "nothing-reset") {
    if (typeof resetFilterPanel === "function") resetFilterPanel();
    $("#search-q").value = "";
    runSearch(true);
    return;
  }
  // Подсказка не только называет панель, но и открывает её: иначе человек
  // прочитал «кнопкой Фильтры» и ищет её глазами по экрану.
  if (ev.target.id === "nothing-filters") {
    const panel = $("#filters-panel");
    if (filtersTarget !== "search") moveFilterPanel("search");
    panel.hidden = false;
    $("#filters-toggle").setAttribute("aria-expanded", "true");
    store.set("filtersOpen", true);
    const tags = $("#f-tag-input");
    if (tags) { tags.scrollIntoView({block: "center"}); tags.focus(); }
  }
});


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
    '<div class="statbox"><h4>Оценка Scryfall</h4><div class="statbig">' + dollars(usd) + "</div>" +
      '<div class="meta">мировая цена, для сверки</div></div>' +
    '<div class="statbox"><h4>Нужно докупить</h4><div class="statbig">' +
      (deck.missing_copies || 0) + ' шт.</div>' +
      '<div class="meta">' + (deck.missing_names || 0) + ' назв. ≈ ' +
      dollars(deck.missing_usd) + '</div></div>' +
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
      " назв. / " + deck.missing_copies + " шт. ≈ " + dollars(deck.missing_usd) + "</span>");
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
  huntTake(
    currentDeck.entries.filter((e) => e.section === "main"
                                   || e.section === "side"
                                   || e.section === "commander"),
    'Добавлено из колоды "' + currentDeck.name + '". Можно править.');
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
    // Прошлая коллекция сохранена снимком, поэтому замену можно отменить
    // сразу, не идя в список резервных копий.
    if (typeof toastUndo === "function") {
      toastUndo("Коллекция сохранена", "collection", afterUndo);
    } else {
      toast("Коллекция сохранена");
    }
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

/* Курсор по карточкам -- общий для поиска и для билдера.

   Был написан дважды: `markGridCursor` здесь и `bdMarkCursor` в builder.js.
   Код одинаковый до строчки, расходились только три вещи -- где искать
   карточки, каким классом помечать и показывать ли большую картинку. Их и
   оставляем на виду у вызывающего, а одинаковое -- здесь.

   Возвращает новый номер курсора: -1, если помечать нечего. */
function cursorMark(els, index, cls, preview) {
  if (!els.length) return -1;
  const i = Math.max(0, Math.min(els.length - 1, index));
  els.forEach((el, k) => el.classList.toggle(cls, k === i));
  const el = els[i];
  el.scrollIntoView({ block: "nearest", inline: "nearest" });
  // С клавиатуры показывается та же большая картинка, что и при наведении.
  if (preview && typeof showPreview === "function") showPreview(el, "keys");
  return i;
}

function cursorClear(els, cls) {
  els.forEach((el) => el.classList.remove(cls));
}

function markGridCursor(index) {
  gridCursor = cursorMark(gridTiles(), index, "cursor", false);
  if (gridCursor < 0) return;
  // Поиск, в отличие от билдера, помнит, над чем «висит» указатель: большая
  // картинка там живёт по наведению, и клавиатура должна её перехватывать.
  hoverTarget = gridTiles()[gridCursor];
  showPreview(hoverTarget, "keys");
}

function clearGridCursor() {
  cursorClear(gridTiles(), "cursor");
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
  /* Окно справки обещало «1…4 — добавить столько штук в охоту» и «f — в
     избранное», а обработчиков не было ни одного: рядом в разметке стоит
     комментарий «описание не может разойтись с поведением», и оно разошлось.
     Делаем обещанное.

     Буква берётся по ev.code, а не по ev.key: в русской раскладке на той же
     клавише «а», и обещание работало бы только при переключении раскладки. */
  if (/^[1-4]$/.test(ev.key) || ev.code === "KeyF") {
    const tile = gridTiles()[gridCursor];
    const card = tile && lastCards.find((c) => c.id === tile.dataset.id);
    if (!card) return;
    ev.preventDefault();
    if (ev.code === "KeyF") {
      addToFavourites(card, 1, null);
    } else {
      addToHunt(card.name, parseInt(ev.key, 10));
    }
    return;
  }
  if (ev.key === "Escape") {
    ev.preventDefault();
    clearGridCursor();
    $("#search-q").focus();
  }
}



/* Clicking a printing thumbnail in the hunt plan opens the full artwork, so
   you can compare it against what the seller described. */
$("#hunt-plan").addEventListener("click", (ev) => {
  const img = ev.target.closest("img[data-full]");
  if (!img) return;
  window.open(img.dataset.full, "_blank", "noopener");
});
