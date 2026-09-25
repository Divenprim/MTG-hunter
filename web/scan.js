/* Сканер: навёл камеру на карту -- карта узналась.

   Так это и должно работать: пачку в двести карт не фотографируют по одной.
   Камера смотрит непрерывно, кадр уходит на сервер несколько раз в секунду, и
   как только карта узнана уверенно и дважды подряд -- она попадает в список, и
   можно класть следующую.

   Что происходит с кадром: из видео вырезается прямоугольник рамки (пропорции
   карты), сжимается в JPEG и уходит на /api/scan. Там из него считается
   отпечаток арта и сравнивается с заранее собранной базой (build_art.py).
   Наружу не уходит ничего, кадры нигде не сохраняются.

   Почему «дважды подряд»: один случайный кадр ловит карту в движении, на
   блике или в момент, когда в рамке ещё предыдущая. Два одинаковых ответа
   подряд -- признак того, что карта лежит и узнана, а не промелькнула. */

const SCAN_RATIO = 88 / 63;          // карта: 63 x 88 мм
const SCAN_EVERY = 400;              // мс между кадрами
const SCAN_REPEAT = 2;               // сколько одинаковых ответов подряд ждём
const SCAN_COOLDOWN = 900;           // мс покоя после зачёта, чтобы сменить карту

let scanStream = null;
let scanTimer = null;
let scanBusy = false;
let scanLast = null;                 // {card_id, times}
let scanHeld = 0;                    // время последнего зачёта
// Карта, которую только что зачли. Пока она лежит в рамке, второй раз её не
// считаем: иначе одна карта, оставленная под камерой, набежала бы десятками.
let scanCommitted = null;
let scanFound = [];                  // [{card_id, name, ru_name, quantity, ...}]
// Куда складывать: пустая строка -- коллекция, иначе id колоды.
let scanTarget = store.get("scan.target", "");
let scanSection = store.get("scan.section", "main");
let scanDecks = [];
let scanSound = true;
// Умеет ли сервер сам находить карту в кадре. Без этого остаётся рамка.
let scanDetect = false;
// Что нашёл поиск по имени в разборе строки: в разметке остаётся только номер.
let scanFixResults = [];

function scanReady() { return !!scanStream; }

/* ------------------------------------------------------------- состояние */

async function scanRefreshStatus() {
  try {
    const s = await api("/api/scan/status");
    const box = $("#scan-dbstate");
    scanDetect = !!s.detect;
    if (s.ready) {
      box.innerHTML = '<span class="good">база отпечатков: ' +
        s.hashed.toLocaleString("ru") + " карт" +
        (s.scope === "all" ? " (все печати)" : " (по одной печати на карту)") +
        "</span>" +
        (s.detect
          ? '<span class="meta"> · карта ищется в кадре: класть можно как ' +
            "угодно, лишь бы фон отличался от карты</span>"
          : '<span class="meta"> · карта ищется по рамке: чтобы угол перестал ' +
            "иметь значение, поставьте opencv-python-headless</span>");
      box.hidden = false;
      $("#scan-start").disabled = false;
    } else {
      box.innerHTML = '<b class="bad">База отпечатков не собрана.</b> ' +
        "Сканер узнаёт карту по картинке, и для этого ему нужны отпечатки " +
        "всех карт — они считаются один раз, примерно час:<br>" +
        "<code>.venv\\Scripts\\python.exe build_art.py</code>" +
        " — по одной печати на карту (быстрее),<br>" +
        "<code>.venv\\Scripts\\python.exe build_art.py --all</code>" +
        " — все печати: тогда узнаётся и конкретная версия карты." +
        (s.hashed ? "<br>Уже собрано: " + s.hashed.toLocaleString("ru") : "");
      box.hidden = false;
      $("#scan-start").disabled = true;
    }
    return s;
  } catch (e) {
    $("#scan-dbstate").textContent = e.message;
    $("#scan-dbstate").hidden = false;
    return null;
  }
}

/* ----------------------------------------------------------------- камера */

async function scanStart() {
  if (scanStream) return scanStop();
  // Камера требует защищённого соединения: по http её не даёт ни один
  // браузер, кроме как на самом этом компьютере. Поэтому для планшета есть
  // run-ssl.bat, и сказать об этом надо до того, как человек решит, что
  // программа сломалась.
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $("#scan-note").innerHTML =
      '<b class="bad">Браузер не даёт доступ к камере по этому адресу.</b> ' +
      "Камера работает только на защищённом соединении (или на самом " +
      "компьютере, где запущена программа). Для планшета запустите " +
      "<code>run-ssl.bat</code> — он напечатает адрес вида " +
      "<code>https://192.168.…:8765</code> и как один раз поставить " +
      "сертификат.";
    $("#scan-note").hidden = false;
    return;
  }
  try {
    scanStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    });
  } catch (e) {
    $("#scan-note").innerHTML = '<b class="bad">Камера не открылась:</b> ' +
      esc(e.message) + ". Проверьте, что доступ разрешён в настройках браузера.";
    $("#scan-note").hidden = false;
    return;
  }
  const video = $("#scan-video");
  video.srcObject = scanStream;
  video.setAttribute("playsinline", "");     // iOS иначе открывает во весь экран
  await video.play();
  $("#scan-stage").hidden = false;
  $("#scan-note").hidden = true;
  $("#scan-start").textContent = "Выключить камеру";
  // Пока камера смотрит, страница живёт по другим правилам: на телефоне
  // объяснения уходят, кадр поднимается наверх, а ответ ложится полосой
  // поверх него. Всё это решают стили, отсюда нужен только признак.
  document.body.classList.add("scanning");
  $("#scan-stage").scrollIntoView({ block: "start", behavior: "smooth" });
  scanTimer = setInterval(scanTick, SCAN_EVERY);
}

function scanStop() {
  if (scanTimer) clearInterval(scanTimer);
  scanTimer = null;
  if (scanStream) scanStream.getTracks().forEach((t) => t.stop());
  scanStream = null;
  $("#scan-stage").hidden = true;
  $("#scan-start").textContent = "Включить камеру";
  $("#scan-live").innerHTML = "";
  document.body.classList.remove("scanning");
}

/* Кадр уходит целиком: карту в нём находит сервер, и поэтому неважно, под
   каким углом и где она лежит. Рамка остаётся подсказкой на случай, когда
   найти не удалось -- пёстрый фон, карта наполовину за кадром. */
function scanFrameData(video) {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return null;

  const canvas = $("#scan-canvas");
  const wide = Math.min(960, vw);
  canvas.width = wide;
  canvas.height = Math.round(vh * wide / vw);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.78);
}

/* Обводка найденной карты поверх видео: человек должен видеть, что программа
   смотрит именно на карту, а не на край стола. */
function scanOutline(quad) {
  const box = $("#scan-outline");
  const video = $("#scan-video");
  if (!quad || !video.videoWidth) { box.innerHTML = ""; return; }
  const w = video.clientWidth;
  const h = video.clientHeight;
  const points = quad.map((p) => (p[0] * w).toFixed(1) + "," + (p[1] * h).toFixed(1));
  box.innerHTML =
    '<svg viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '">' +
      '<polygon points="' + points.join(" ") + '"></polygon>' +
    "</svg>";
}

async function scanTick() {
  if (scanBusy || !scanStream) return;
  if (Date.now() - scanHeld < SCAN_COOLDOWN) return;
  const image = scanFrameData($("#scan-video"));
  if (!image) return;
  scanBusy = true;
  try {
    const r = await post("/api/scan", { image: image, limit: 3, detect: scanDetect });
    scanShow(r);
  } catch (e) {
    $("#scan-live").innerHTML = '<span class="bad">' + esc(e.message) + "</span>";
  } finally {
    scanBusy = false;
  }
}

function scanShow(r) {
  scanOutline(r.detected ? r.quad : null);
  $("#scan-stage").classList.toggle("nodetect", !r.detected);
  const best = (r.matches || [])[0];
  if (!best) {
    $("#scan-live").innerHTML = '<span class="meta">ничего не узнаю</span>';
    scanLast = null;
    scanCommitted = null;
    return;
  }

  // Та же карта всё ещё под камерой -- ждём, пока её уберут. Это и есть ритм
  // сканирования пачки: положил, услышал сигнал, убрал, положил следующую.
  if (scanCommitted && r.sure && best.card_id === scanCommitted) {
    $("#scan-live").innerHTML =
      '<span class="good">✓ ' + esc(best.ru_name || best.name) + "</span>" +
      ' <span class="meta">— уберите карту и кладите следующую</span>';
    return;
  }
  scanCommitted = null;

  const label = esc(best.ru_name || best.name) +
    ' <span class="meta">' + esc(best.set_code || "").toUpperCase() +
    (best.collector_number ? " #" + esc(best.collector_number) : "") + "</span>";
  $("#scan-live").innerHTML =
    (r.sure ? '<span class="good">' : '<span class="meta">похоже на </span><span>') +
    label + "</span>" +
    ' <span class="meta">(' + best.distance + ")</span>";

  if (!r.sure) { scanLast = null; return; }
  if (scanLast && scanLast.card_id === best.card_id) scanLast.times += 1;
  else scanLast = { card_id: best.card_id, times: 1 };

  if (scanLast.times >= SCAN_REPEAT) {
    // Остальные догадки кладём рядом: если карта узналась неверно, править
    // проще всего из них.
    best.alts = (r.matches || []).slice(1, 4);
    scanAccept(best);
    scanLast = null;
    scanCommitted = best.card_id;
    scanHeld = Date.now();
  }
}

/* Зачёт: карта попадает в список этого сеанса. Ничего никуда не пишется --
   в коллекцию список уходит по кнопке, целиком и один раз. */
/* Что делать, если узналось неправильно. Список из одних имён -- это список
   для машины: человеку надо увидеть карту крупно и, если ошиблись, поправить
   на месте, а не удалять и переснимать. Поэтому у каждой строки есть и
   увеличение, и разбор: другие догадки самого сканера и обычный поиск по
   имени. */

function scanAccept(card) {
  // Ключ -- печать, если она известна (камера), иначе имя (снимок пачки: там
  // прочитано имя, а какая это печать, снимок не говорит).
  const key = card.card_id || card.name;
  const seen = scanFound.find((c) => (c.card_id || c.name) === key);
  if (seen) seen.quantity += 1;
  else scanFound.unshift(Object.assign({ quantity: 1 }, card));
  scanRenderFound();
  scanBeep();
  toast("+ " + (card.ru_name || card.name));
}

function scanBeep() {
  if (!scanSound) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.value = 0.05;
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start();
    setTimeout(() => { osc.stop(); ctx.close(); }, 90);
  } catch (e) { /* звук -- приятность, а не обязанность */ }
}

/* ------------------------------------------------------------- что нашли */

function scanRenderFound() {
  const total = scanFound.reduce((n, c) => n + c.quantity, 0);
  $("#scan-count").textContent = scanFound.length
    ? scanFound.length + " назв. / " + total + " шт."
    : "";
  $("#scan-actions").hidden = !scanFound.length;
  $("#scan-found").innerHTML = scanFound.map((c, i) => {
    const key = esc(c.card_id || c.name);
    const big = c.image_normal || c.image_small;
    return '<div class="scanrow" data-card="' + key + '">' +
      (c.image_small
        ? '<img loading="lazy" src="' + esc(c.image_small) + '" alt="" ' +
          'class="zoom" data-zoom="' + i + '" title="Показать крупно"' +
          (big ? ' data-preview="' + esc(big) + '"' : "") + ">"
        : '<span class="noart"></span>') +
      '<div class="nm"><b>' + esc(c.ru_name || c.name) + "</b>" +
        (c.ru_name ? '<span class="meta">' + esc(c.name) + "</span>" : "") +
        '<span class="meta">' + esc((c.set_code || "").toUpperCase()) +
          (c.collector_number ? " #" + esc(c.collector_number) : "") +
          (c.distance != null ? " · совпадение " + c.distance : "") + "</span>" +
      "</div>" +
      '<div class="qty">' +
        '<button class="ghost" data-less="' + key + '">−</button>' +
        "<b>" + c.quantity + "</b>" +
        '<button class="ghost" data-more="' + key + '">+</button>' +
      "</div>" +
      '<button class="ghost" data-fix="' + i + '">не та карта</button>' +
      '<button class="ghost" data-drop="' + key + '">убрать</button>' +
      '<div class="scanfix" data-fixbox="' + i + '" hidden></div>' +
    "</div>";
  }).join("");
}

/* Окно карты -- то же самое, что в поиске: обе стороны, все печати, цены.
   Отдельного «просмотра для сканера» не нужно, и заводить его было бы враньём:
   это та же карта. */
async function scanZoom(card) {
  if (typeof openCard !== "function") return;
  if (card.card_id) {
    try {
      const r = await api("/api/card/" + encodeURIComponent(card.card_id));
      if (r && r.card) return openCard(r.card);
    } catch (e) { /* ниже покажем то, что знаем сами */ }
  }
  openCard({
    name: card.name, ru_name: card.ru_name, oracle_id: card.oracle_id,
    image_normal: card.image_normal || card.image_small,
    image_small: card.image_small, set_code: card.set_code,
    collector_number: card.collector_number,
  });
}

/* Разбор строки: чем ещё это может быть. Сначала догадки самого сканера (они
   уже посчитаны и ничего не стоят), потом обычный поиск по имени -- на случай,
   когда карты нет и среди догадок. */
function scanFixHtml(card) {
  // Показываем только те догадки, которые правда могли быть этой картой.
  // Когда найденная карта в четырёх битах, а следующая в тридцати шести,
  // предлагать тридцать шесть -- это не помощь, а шум.
  const near = (card.alts || []).filter(
    (a) => a.distance == null || card.distance == null
      || a.distance <= Math.max(card.distance + 16, 30));
  const alts = near.map((a, k) =>
    '<button class="altpick" data-alt="' + k + '">' +
      (a.image_small ? '<img src="' + esc(a.image_small) + '" alt="">' : "") +
      "<span><b>" + esc(a.ru_name || a.name) + "</b>" +
      '<span class="meta">' + esc((a.set_code || "").toUpperCase()) +
      (a.distance != null ? " · " + a.distance : "") + "</span></span>" +
    "</button>").join("");
  return (
    (alts
      ? '<div class="meta">Может быть, это:</div><div class="altrow">' +
        alts + "</div>"
      : '<div class="meta">Других похожих карт сканер не нашёл — ' +
        "найдите нужную по имени.</div>") +
    '<div class="row tight">' +
      '<input type="text" class="fixsearch" placeholder="или найдите карту по имени" ' +
      'autocomplete="off">' +
    "</div>" +
    '<div class="fixresults"></div>'
  );
}

/* Заменить узнанную карту на выбранную: количество и место в списке
   сохраняются -- человек исправляет имя, а не пересчитывает карты заново. */
function scanReplace(index, card) {
  const old = scanFound[index];
  if (!old) return;
  scanFound[index] = Object.assign({}, old, {
    card_id: card.card_id || card.id || null,
    oracle_id: card.oracle_id || null,
    name: card.name,
    ru_name: card.ru_name || null,
    image_small: card.image_small || null,
    image_normal: card.image_normal || null,
    set_code: card.set_code || null,
    collector_number: card.collector_number || null,
    distance: card.distance != null ? card.distance : null,
    alts: old.alts,
    how: "поправлено",
  });
  scanRenderFound();
  toast("Теперь это «" + (card.ru_name || card.name) + "»");
}

$("#scan-found").addEventListener("input", debounce(async (ev) => {
  const field = ev.target.closest(".fixsearch");
  if (!field) return;
  // Поиск отложенный, а список за эти четверть секунды мог перерисоваться --
  // например, потому что карту как раз заменили. Тогда писать уже некуда.
  const panel = field.closest(".scanfix");
  const box = panel && panel.querySelector(".fixresults");
  if (!box || !panel.isConnected) return;
  const text = field.value.trim();
  if (text.length < 2) { box.innerHTML = ""; return; }
  try {
    const r = await api("/api/search?limit=6&q=" + encodeURIComponent(text));
    // Найденное держим в переменной, а в разметке -- только номер: карта в
    // атрибуте была бы JSON внутри HTML внутри строки, то есть три уровня
    // экранирования на ровном месте.
    scanFixResults = r.cards || [];
    box.innerHTML = scanFixResults.map((c, k) =>
      '<button class="altpick" data-found="' + k + '">' +
        (c.image_small ? '<img src="' + esc(c.image_small) + '" alt="">' : "") +
        "<span><b>" + esc(c.ru_name || c.name) + "</b>" +
        '<span class="meta">' + esc(c.name) + " · " +
        esc((c.set_code || "").toUpperCase()) + "</span></span>" +
      "</button>").join("") ||
      '<span class="meta">ничего не нашлось</span>';
  } catch (e) {
    box.innerHTML = '<span class="bad">' + esc(e.message) + "</span>";
  }
}, 250));

$("#scan-found").addEventListener("click", async (ev) => {
  const t = ev.target;

  const zoom = t.closest("[data-zoom]");
  if (zoom) {
    scanZoom(scanFound[parseInt(zoom.dataset.zoom, 10)]);
    return;
  }

  const fix = t.closest("[data-fix]");
  if (fix) {
    const i = parseInt(fix.dataset.fix, 10);
    const box = $("#scan-found [data-fixbox=\"" + i + "\"]");
    if (!box || !scanFound[i]) return;
    if (box.hidden) {
      box.innerHTML = scanFixHtml(scanFound[i]);
      box.hidden = false;
      const field = box.querySelector(".fixsearch");
      if (field) field.focus();
    } else {
      box.hidden = true;
    }
    return;
  }

  const alt = t.closest("[data-alt]");
  if (alt) {
    const row = alt.closest(".scanfix");
    const i = parseInt(row.dataset.fixbox, 10);
    const card = scanFound[i];
    const near = (card.alts || []).filter(
      (a) => a.distance == null || card.distance == null
        || a.distance <= Math.max(card.distance + 16, 30));
    const pick = near[parseInt(alt.dataset.alt, 10)];
    if (pick) scanReplace(i, pick);
    return;
  }

  const found = t.closest("[data-found]");
  if (found) {
    const row = found.closest(".scanfix");
    const i = parseInt(row.dataset.fixbox, 10);
    const card = scanFixResults[parseInt(found.dataset.found, 10)];
    if (card) {
      scanReplace(i, {
        card_id: card.id, oracle_id: card.oracle_id, name: card.name,
        ru_name: card.ru_name, image_small: card.image_small,
        image_normal: card.image_normal, set_code: card.set_code,
        collector_number: card.collector_number,
      });
    }
    return;
  }

  const id = t.dataset.more || t.dataset.less || t.dataset.drop;
  if (!id) return;
  const card = scanFound.find((c) => (c.card_id || c.name) === id);
  if (!card) return;
  if (t.dataset.more) card.quantity += 1;
  if (t.dataset.less) card.quantity -= 1;
  if (t.dataset.drop || card.quantity <= 0) {
    scanFound = scanFound.filter((c) => (c.card_id || c.name) !== id);
  }
  scanRenderFound();
});

$("#scan-start").addEventListener("click", scanStart);

$("#scan-sound").addEventListener("change", (ev) => {
  scanSound = ev.target.checked;
});

$("#scan-clear").addEventListener("click", () => {
  if (!scanFound.length) return;
  scanFound = [];
  scanRenderFound();
});

/* Колоды подгружаются, когда открывают сканер: список у них свой, и держать
   его копию всё время незачем. */
async function scanLoadDecks() {
  try {
    const r = await api("/api/decks");
    scanDecks = r.decks || [];
  } catch (e) {
    scanDecks = [];
  }
  const box = $("#scan-target");
  const known = scanDecks.some((d) => d.id === scanTarget);
  if (!known) scanTarget = "";
  box.innerHTML = '<option value="">в коллекцию</option>' +
    scanDecks.map((d) =>
      '<option value="' + esc(d.id) + '"' +
      (d.id === scanTarget ? " selected" : "") + ">в колоду «" +
      esc(d.name) + "»</option>").join("");
  box.value = scanTarget;
  scanRenderWhere();
}

function scanDeckName() {
  const deck = scanDecks.find((d) => d.id === scanTarget);
  return deck ? deck.name : "";
}

const SCAN_SECTION_WORD = {
  main: "основная", side: "сайдборд", maybe: "под вопросом",
  commander: "командир",
};

function scanRenderWhere() {
  const name = scanDeckName();
  $("#scan-section-box").hidden = !scanTarget;
  $("#scan-tocollection").textContent = scanTarget
    ? "Добавить всё в колоду «" + name + "»"
    : "Добавить всё в коллекцию";
  $("#scan-where-note").textContent = scanTarget
    ? "узнанное пойдёт в колоду «" + name + "», секция «" +
      (SCAN_SECTION_WORD[scanSection] || scanSection) + "» — а не в коллекцию"
    : "";
}

$("#scan-target").addEventListener("change", (ev) => {
  scanTarget = ev.target.value;
  store.set("scan.target", scanTarget);
  scanRenderWhere();
});

$("#scan-section").addEventListener("change", (ev) => {
  scanSection = ev.target.value;
  store.set("scan.section", scanSection);
  scanRenderWhere();
});

$("#scan-tocollection").addEventListener("click", async () => {
  if (!scanFound.length) return;
  // Печать идёт вместе с именем: сканер её узнал, и в коллекции она должна
  // остаться -- Ashaya из DSC и из CMM стоят по-разному.
  const cards = scanFound.map((c) => ({
    name: c.name, quantity: c.quantity,
    set_code: c.set_code || null, collector_number: c.collector_number || null,
  }));
  try {
    if (scanTarget) {
      await post("/api/decks/" + scanTarget + "/cards", {
        cards: cards.map((c) => Object.assign({ section: scanSection }, c)),
      });
      toast("В колоду «" + scanDeckName() + "»: " +
            cards.reduce((n, c) => n + c.quantity, 0) + " шт.");
      if (typeof bdLoadDecks === "function") bdLoadDecks();
    } else {
      const r = await post("/api/collection/add", { cards: cards });
      toast("В коллекцию: " + r.added + " шт.");
    }
    scanFound = [];
    scanRenderFound();
    refreshStatus();
  } catch (e) {
    toast(e.message, true);
  }
});

$("#scan-tohunt").addEventListener("click", () => {
  if (!scanFound.length) return;
  const text = scanFound.map((c) => c.quantity + " " + c.name).join("\n");
  $("#hunt-wants").value = text;
  store.set("hunt", text);
  $("#hunt-source").textContent = "Отсканировано: " + scanFound.length + " назв.";
  showTab("hunt");
  toast("В охоту: " + scanFound.length + " назв.");
});

$("#scan-copy").addEventListener("click", () => {
  if (!scanFound.length) return;
  copyText(scanFound.map((c) => c.quantity + " " + c.name).join("\n"),
           "Список скопирован");
});

/* Снимок из файла -- запасной путь: когда камеру открыть нельзя (планшет по
   http) или когда карта уже сфотографирована. */
$("#scan-file").addEventListener("change", async (ev) => {
  const file = (ev.target.files || [])[0];
  if (!file) return;
  const data = await new Promise((done) => {
    const fr = new FileReader();
    fr.onload = () => done(fr.result);
    fr.readAsDataURL(file);
  });
  try {
    const r = await post("/api/scan", { image: data, limit: 3 });
    const best = (r.matches || [])[0];
    if (!best) return toast("Не узнал карту на снимке", true);
    scanShow(r);
    if (!r.sure) toast("Не уверен: " + (best.ru_name || best.name), true);
    else scanAccept(best);
  } catch (e) {
    toast(e.message, true);
  } finally {
    ev.target.value = "";
  }
});

/* ------------------------------------------------------- снимок пачки --- */

/* Двести карт внахлёст -- одна фотография. Арта там не видно, поэтому карта
   узнаётся не отпечатком, а прочитанным именем; и раз это чтение, а не
   сравнение картинок, результат показывается на проверку: уверенное отмечено,
   сомнительное видно и не отмечено. Ничего не попадает в список молча. */

let pileFound = [];

$("#scan-pilefile").addEventListener("change", async (ev) => {
  const file = (ev.target.files || [])[0];
  if (!file) return;
  const box = $("#scan-pile");
  box.hidden = false;
  box.innerHTML = '<p class="meta">читаю снимок…</p>';
  const data = await new Promise((done) => {
    const fr = new FileReader();
    fr.onload = () => done(fr.result);
    fr.readAsDataURL(file);
  });
  try {
    const r = await post("/api/scan/pile", { image: data });
    pileFound = r.cards || [];
    pileRender(r);
  } catch (e) {
    box.innerHTML = '<span class="bad">' + esc(e.message) + "</span>";
  } finally {
    ev.target.value = "";
  }
});

function pileRender(r) {
  const box = $("#scan-pile");
  if (!r.ok) {
    box.innerHTML = '<b class="bad">Не могу разобрать снимок.</b> ' +
      esc(r.detail || "");
    return;
  }
  if (!pileFound.length) {
    box.innerHTML = '<b>Имён на снимке не нашлось.</b> ' +
      '<span class="meta">Разложите карты так, чтобы у каждой было видно имя ' +
      "целиком — при слишком плотном нахлёсте его закрывает соседняя карта. " +
      "И снимайте сверху, а не сбоку.</span>";
    return;
  }
  const sure = pileFound.filter((c) => c.sure).length;
  box.innerHTML =
    "<p><b>На снимке: " + pileFound.length + "</b> " +
    '<span class="meta">(уверенно — ' + sure + ")</span></p>" +
    pileFound.map((c, i) =>
      '<label class="pilerow' + (c.sure ? "" : " doubt") + '">' +
        '<input type="checkbox" data-pile="' + i + '"' + (c.sure ? " checked" : "") + ">" +
        (c.image_small
          ? '<img loading="lazy" src="' + esc(c.image_small) + '" alt="">'
          : "<span></span>") +
        '<span class="nm"><b>' + esc(c.ru_name || c.name) + "</b>" +
          '<span class="was">' +
          (c.how === "арт" ? "узнана по картинке"
                           : "прочитано: " + esc(c.text)) +
          (c.how === "оба" ? " · и по картинке" : "") +
          (c.in_step || c.how === "арт" ? "" : " · вне общего ряда") +
        "</span></span>" +
        '<span class="meta">' + Math.round(c.score * 100) + "%</span>" +
      "</label>").join("") +
    '<div class="row tight" style="margin-top:8px">' +
      '<button id="pile-take">Добавить отмеченные в список</button>' +
      '<button id="pile-close" class="ghost">Закрыть</button>' +
    "</div>";

  $("#pile-take").addEventListener("click", () => {
    const picked = $$("#scan-pile input[data-pile]:checked")
      .map((el) => pileFound[parseInt(el.dataset.pile, 10)]);
    if (!picked.length) return toast("Ничего не отмечено", true);
    picked.forEach((c) => scanAccept(c));
    $("#scan-pile").hidden = true;
    pileFound = [];
  });
  $("#pile-close").addEventListener("click", () => {
    $("#scan-pile").hidden = true;
    pileFound = [];
  });
}
