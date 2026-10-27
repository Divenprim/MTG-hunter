/* С чего начать покупки, когда колод несколько.

   «Чего не хватает» отвечает про одну колоду: открыл колоду -- увидел её
   список. Но деньги одни, а колод десять, и в таком списке карта для трёх
   колод стоит вперемешку с картой для одной. Здесь счёт идёт по карте: в
   скольких колодах её ждут, сколько копий не хватает на все сразу и во что
   это обойдётся.

   Запросов к topdeck отсюда не уходит. Цены берутся те, что уже узнаны, и
   про неизвестные так и написано -- «цену не спрашивали», а не «0 ₽». */

let buyData = null;
let buyBusy = false;

function buyQuery() {
  const parts = ["limit=300"];
  if ($("#buy-assembled") && $("#buy-assembled").checked) {
    parts.push("include_assembled=true");
  }
  if ($("#buy-basics") && $("#buy-basics").checked) {
    parts.push("skip_basics=false");
  }
  if ($("#buy-noside") && $("#buy-noside").checked) {
    parts.push("skip_side=true");
  }
  return parts.join("&");
}

function buyRow(card) {
  /* Колоды, которым карта нужна. Показываем три и «ещё N»: пять колод в
     строке превращают таблицу в простыню, а первые три отвечают на вопрос
     «кому это», ради которого строка и читается. */
  const where = (card.needs || []).slice(0, 3).map((n) =>
    '<span class="buydeck" data-deck="' + esc(n.deck_id) + '" title="' +
    esc(n.deck + ": не хватает " + n.lack + " из " + n.need) + '">' +
    esc(n.deck) + " ×" + n.lack + "</span>").join("");
  const more = (card.needs || []).length > 3
    ? '<span class="meta"> ещё ' + ((card.needs || []).length - 3) + "</span>"
    : "";

  const finishes = (card.finishes || []).length
    ? '<span class="buyfinish" title="Кроме этой карты колоде не нужно ' +
      'ничего">достраивает: ' + esc(card.finishes.join(", ")) + "</span>"
    : "";

  /* Куда карта идёт. «Только в сайд» -- это покупка, без которой колода
     всё равно играет, и такие строки стоят ниже; но увидеть это надо в
     строке, а не вычислять по порядку. */
  const sideMark = card.side_only
    ? '<span class="buyside" title="без сайдборда колода всё равно ' +
      'играет">только в сайд</span>'
    : card.side
    ? '<span class="buyside">в сайд ' + card.side + " из " + card.lack +
      "</span>"
    : "";

  return (
    '<div class="buyrow' + (card.side_only ? " sideonly" : "") + '">' +
      '<span class="buyname">' +
        '<b class="linkish" data-card="' + esc(card.name) + '">' +
          esc(card.name) + "</b>" + finishes + sideMark +
      "</span>" +
      '<span class="buycount" title="не хватает копий на все колоды сразу">' +
        card.lack + " шт." +
        (card.free ? '<span class="meta"> · свободно ' + card.free +
                     "</span>" : "") +
      "</span>" +
      '<span class="buyprice">' +
        (card.price
          ? rub(card.price) + '<span class="meta"> · всего ' +
            rub(card.cost) + "</span>" +
            /* Нижняя цена не от обычной копии: по числу этого не видно, а
               «250 ₽» за убитую карту и за нормальную -- разные покупки. */
            (card.price_plain && card.price_plain > card.price
              ? '<span class="meta" title="самое дешёвое объявление — не ' +
                'обычная копия"> · обычная ' + rub(card.price_plain) +
                "</span>"
              : "")
          : card.asked
          ? '<span class="meta" title="спрашивали — у продавцов не нашлось">' +
            "не нашлось</span>"
          : '<span class="meta">цену не спрашивали</span>') +
      "</span>" +
      '<span class="buywhere">' + where + more + "</span>" +
      '<button class="ghost tiny" data-buy-hunt="' + esc(card.name) +
        '" data-buy-qty="' + card.lack + '">в охоту</button>' +
    "</div>"
  );
}

function buyRender() {
  const box = $("#buy-body");
  const head = $("#buy-summary");
  if (!buyData) {
    box.innerHTML = '<p class="meta">Считаю…</p>';
    return;
  }
  const t = buyData.totals || {};
  if (!buyData.cards.length) {
    head.textContent = "";
    box.innerHTML =
      '<p class="meta">Всё, что нужно вашим колодам, у вас есть. ' +
      "Колод в счёте: " + (t.decks || 0) + ".</p>";
    return;
  }

  head.innerHTML =
    "Колод в счёте: <b>" + (t.decks || 0) + "</b>, чего-то не хватает " +
    (t.decks_short || 0) + ". Разных карт купить: <b>" + (t.cards || 0) +
    "</b> (" + (t.copies || 0) + " шт.) на <b>" + rub(t.rub || 0) + "</b>" +
    (t.no_price
      ? ' <span class="meta">+ ' + t.no_price + " назв. без цены" +
        (t.never_asked
          ? " (" + t.never_asked + " ещё не спрашивали)"
          : " — спрашивали, не нашлось") + "</span>"
      : "") +
    ". Нужны больше чем одной колоде: <b>" + (t.multi_deck || 0) + "</b>" +
    (t.finishing ? ", достраивают колоду целиком: <b>" + t.finishing +
                   "</b>" : "") +
    (t.basics
      ? ' <span class="meta">· базовых земель не хватает ' + t.basics +
        " — их обычно не покупают</span>"
      : "") +
    (t.side_copies
      ? ' <span class="meta">· в сайдборды из этого ' + t.side_copies +
        " шт." + (t.side_only ? ", и " + t.side_only +
          " назв. нужны только им" : "") + "</span>"
      : "");

  box.innerHTML =
    '<div class="buyhead">' +
      "<span>карта</span><span>сколько</span><span>цена</span>" +
      "<span>кому нужна</span><span></span>" +
    "</div>" +
    buyData.cards.map(buyRow).join("");

  buyPricesButton();
}

/* Сколько карт в списке без цены -- и предложение спросить про них.

   Без цены карта не всплывает как дешёвая (это правильно), но и решить по
   ней ничего нельзя. Спрашивается только по кнопке и только про те, цену
   которых мы не знаем: каждая -- это вежливые 1.5 с к чужому серверу. */
const BUY_PRICE_BATCH = 40;

function buyNoPrice() {
  /* Только те, которых ещё не спрашивали. Карта, про которую спросили и не
     нашли, лежит в кеше без цены -- спрашивать её снова той же кнопкой
     значит каждый раз тратить полторы секунды на один и тот же ответ. */
  return (buyData && buyData.cards ? buyData.cards : [])
    .filter((c) => !c.price && !c.asked).map((c) => c.name);
}

function buyPricesButton() {
  const btn = $("#buy-prices");
  if (!btn) return;
  const left = buyNoPrice();
  btn.hidden = !left.length || buyBusy;
  if (!left.length) return;
  const take = Math.min(left.length, BUY_PRICE_BATCH);
  btn.textContent = "Узнать цены: " + take +
    (left.length > take ? " из " + left.length : "");
  btn.title = "Спросить topdeck про карты без цены — по 1.5 с на карту, " +
    "это около " + Math.ceil(take * 1.5 / 60) + " мин";
}

async function buyLoad() {
  if (buyBusy) return;
  buyBusy = true;
  $("#buy-body").innerHTML = '<span class="spinner">считаю по всем колодам…</span>';
  try {
    buyData = await api("/api/shopping?" + buyQuery());
    buyRender();
  } catch (e) {
    $("#buy-body").innerHTML = '<p class="meta">' + esc(e.message) + "</p>";
  } finally {
    // Кнопка «узнать цены» прячется, пока список считается, -- а считается
    // он ровно до этой строки. Нарисовать её раньше значит нарисовать
    // спрятанной: это уже было поймано проверкой.
    buyBusy = false;
    buyPricesButton();
  }
}

function buyText() {
  return (buyData && buyData.cards ? buyData.cards : [])
    .map((c) => c.lack + " " + c.name).join("\n");
}

$("#buy-body").addEventListener("click", (ev) => {
  const hunt = ev.target.closest("[data-buy-hunt]");
  if (hunt) {
    addToHunt(hunt.dataset.buyHunt, Number(hunt.dataset.buyQty) || 1);
    toast("В охоту: " + hunt.dataset.buyHunt + " ×" + hunt.dataset.buyQty);
    return;
  }
  const deck = ev.target.closest("[data-deck]");
  if (deck && typeof bdOpen === "function") {
    bdOpen(deck.dataset.deck);
    return;
  }
  const card = ev.target.closest("[data-card]");
  if (card && typeof openCardByName === "function") {
    openCardByName(card.dataset.card);
  }
});

$("#buy-assembled").addEventListener("change", buyLoad);
$("#buy-basics").addEventListener("change", buyLoad);
$("#buy-noside").addEventListener("change", buyLoad);

$("#buy-copy").addEventListener("click", () => {
  copyText(buyText(), "Список покупок скопирован");
});

$("#buy-prices").addEventListener("click", async () => {
  const names = buyNoPrice().slice(0, BUY_PRICE_BATCH);
  if (!names.length) return;
  const btn = $("#buy-prices");
  btn.disabled = true;
  btn.textContent = "спрашиваю " + names.length + " карт…";
  try {
    const r = await post("/api/prices", { names: names, only_missing: true });
    const got = (r.report || {}).updated || 0;
    toast(got ? "Цены узнаны: " + got : "Ни одной цены не нашлось");
    buyData = null;
    await buyLoad();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    buyPricesButton();
  }
});

/* Двадцать первых -- а не весь список: охота спрашивает topdeck по 1.5 с на
   карту, и отправить туда двести названий значит занять программу на пять
   минут. Двадцать -- это полминуты и верхушка списка, ради которой он и
   считался. */
$("#buy-to-hunt").addEventListener("click", () => {
  const take = (buyData && buyData.cards ? buyData.cards : []).slice(0, 20);
  if (!take.length) return toast("Список пуст", true);
  take.forEach((c) => addToHunt(c.name, c.lack));
  toast("В охоту: " + take.length + " назв.");
});


/* ------------------------------------------------------- а что лишнее

   Обратная сторона того же вопроса. Карта считается лишней, если её больше,
   чем просят все колоды вместе, -- и собранные тоже: то, что лежит в
   собранной колоде, не лишнее, оно занято. Базовых земель тут нет: их не
   продают поштучно. */

let spareData = null;

function spareRow(card) {
  return (
    '<div class="buyrow">' +
      '<span class="buyname"><b class="linkish" data-card="' +
        esc(card.name) + '">' + esc(card.name) + "</b>" +
        (card.in_decks
          ? '<span class="meta"> нужна колодам: ' + card.needed + "</span>"
          : '<span class="meta"> не нужна ни одной колоде</span>') +
      "</span>" +
      '<span class="buycount">лишних ' + card.spare +
        '<span class="meta"> из ' + card.owned + "</span></span>" +
      '<span class="buyprice">' +
        (card.price
          ? rub(card.price) + '<span class="meta"> · всего ' +
            rub(card.worth) + "</span>"
          : '<span class="meta">цену не спрашивали</span>') +
      "</span>" +
      '<span class="buywhere"></span><span></span>' +
    "</div>"
  );
}

function spareRender() {
  const box = $("#spare-body");
  if (!spareData) return;
  const t = spareData.totals || {};
  if (!spareData.cards.length) {
    $("#spare-summary").textContent = "";
    box.innerHTML = '<p class="meta">Лишнего нет: всё, что лежит, ' +
      "расписано по колодам.</p>";
    return;
  }
  $("#spare-summary").innerHTML =
    "Лишних названий: <b>" + (t.cards || 0) + "</b> (" + (t.copies || 0) +
    " шт.), за них дадут примерно <b>" + rub(t.rub || 0) + "</b>" +
    (t.no_price
      ? ' <span class="meta">+ ' + t.no_price + " назв. без цены</span>"
      : "") +
    (t.unused
      ? ". Не нужны ни одной колоде: <b>" + t.unused + "</b>"
      : "") + ".";
  box.innerHTML = spareData.cards.map(spareRow).join("");
}

async function spareLoad() {
  const keep = $("#spare-keep") ? Number($("#spare-keep").value) || 0 : 0;
  $("#spare-body").innerHTML = '<span class="spinner">считаю…</span>';
  try {
    spareData = await api("/api/shopping/spare?limit=200&keep=" + keep);
    spareRender();
  } catch (e) {
    $("#spare-body").innerHTML = '<p class="meta">' + esc(e.message) + "</p>";
  }
}

$("#buy-spare").addEventListener("toggle", () => {
  if ($("#buy-spare").open && !spareData) spareLoad();
});
$("#spare-keep").addEventListener("change", spareLoad);
$("#spare-copy").addEventListener("click", () => {
  copyText((spareData && spareData.cards ? spareData.cards : [])
    .map((c) => c.spare + " " + c.name).join("\n"),
    "Список лишнего скопирован");
});
$("#spare-body").addEventListener("click", (ev) => {
  const card = ev.target.closest("[data-card]");
  if (card && typeof openCardByName === "function") {
    openCardByName(card.dataset.card);
  }
});
