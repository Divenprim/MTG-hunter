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
let scanSound = true;

function scanReady() { return !!scanStream; }

/* ------------------------------------------------------------- состояние */

async function scanRefreshStatus() {
  try {
    const s = await api("/api/scan/status");
    const box = $("#scan-dbstate");
    if (s.ready) {
      box.innerHTML = '<span class="good">база отпечатков: ' +
        s.hashed.toLocaleString("ru") + " карт" +
        (s.scope === "all" ? " (все печати)" : " (по одной печати на карту)") +
        "</span>";
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
}

/* Кадр -- это только то, что внутри рамки: карта, а не стол вокруг неё. */
function scanFrameData(video) {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return null;

  // Рамка вписана в кадр по высоте и занимает 78% её -- ровно как в разметке.
  let h = vh * 0.78;
  let w = h / SCAN_RATIO;
  if (w > vw * 0.9) { w = vw * 0.9; h = w * SCAN_RATIO; }
  const x = (vw - w) / 2;
  const y = (vh - h) / 2;

  const canvas = $("#scan-canvas");
  canvas.width = 420;
  canvas.height = Math.round(420 * SCAN_RATIO);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, x, y, w, h, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.75);
}

async function scanTick() {
  if (scanBusy || !scanStream) return;
  if (Date.now() - scanHeld < SCAN_COOLDOWN) return;
  const image = scanFrameData($("#scan-video"));
  if (!image) return;
  scanBusy = true;
  try {
    const r = await post("/api/scan", { image: image, limit: 3 });
    scanShow(r);
  } catch (e) {
    $("#scan-live").innerHTML = '<span class="bad">' + esc(e.message) + "</span>";
  } finally {
    scanBusy = false;
  }
}

function scanShow(r) {
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
    scanAccept(best);
    scanLast = null;
    scanCommitted = best.card_id;
    scanHeld = Date.now();
  }
}

/* Зачёт: карта попадает в список этого сеанса. Ничего никуда не пишется --
   в коллекцию список уходит по кнопке, целиком и один раз. */
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
  $("#scan-found").innerHTML = scanFound.map((c) =>
    '<div class="scanrow" data-card="' + esc(c.card_id || c.name) + '">' +
      (c.image_small
        ? '<img loading="lazy" src="' + esc(c.image_small) + '" alt="">' : "") +
      '<div class="nm"><b>' + esc(c.ru_name || c.name) + "</b>" +
        (c.ru_name ? '<span class="meta">' + esc(c.name) + "</span>" : "") +
        '<span class="meta">' + esc((c.set_code || "").toUpperCase()) +
          (c.collector_number ? " #" + esc(c.collector_number) : "") +
          " · совпадение " + c.distance + "</span>" +
      "</div>" +
      '<div class="qty">' +
        '<button class="ghost tiny" data-less="' + esc(c.card_id || c.name) + '">−</button>' +
        "<b>" + c.quantity + "</b>" +
        '<button class="ghost tiny" data-more="' + esc(c.card_id || c.name) + '">+</button>' +
      "</div>" +
      '<button class="ghost tiny" data-drop="' + esc(c.card_id || c.name) + '">убрать</button>' +
    "</div>").join("");
}

$("#scan-found").addEventListener("click", (ev) => {
  const t = ev.target;
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

$("#scan-tocollection").addEventListener("click", async () => {
  if (!scanFound.length) return;
  const cards = scanFound.map((c) => ({ name: c.name, quantity: c.quantity }));
  try {
    const r = await post("/api/collection/add", { cards: cards });
    toast("В коллекцию: " + r.added + " шт.");
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
          '<span class="was">прочитано: ' + esc(c.text) +
            (c.in_step ? "" : " · вне общего ряда") + "</span></span>" +
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
