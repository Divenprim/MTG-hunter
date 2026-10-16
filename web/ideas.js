"use strict";

/* «Что добавить в колоду» — по тому, чем колода занята.

   Предложка умела один вопрос: что играют с этим командиром. Человек,
   собирающий модерн, получал поле «имя командира» и пустоту: командира в
   его колоде нет и не будет.

   Здесь другой вопрос и другой ответ. Сервер читает, про что колода —
   туманы, милл, реанимация, манадорки, — и по каждой теме предлагает карты
   в её цветах и её формате. Наружу не уходит ничего: темы берутся из тегов
   локальной базы, цены — из тех, что уже спрошены.

   Загружается после recommend.js: живёт в том же окне и пользуется его
   переключателем вкладок. */

let ideasData = null;
let ideasDeckId = null;

function ideasDeck() {
  return (typeof bdDeck !== "undefined" && bdDeck) ? bdDeck : null;
}

function ideasMoney(pick) {
  const bits = [];
  if (pick.rub != null) {
    bits.push('<b class="rub">от ' + Number(pick.rub).toLocaleString("ru") + " ₽</b>");
  }
  if (pick.usd != null) {
    bits.push('<span class="usd">' + dollars(pick.usd) + "</span>");
  }
  if (!bits.length) bits.push('<span class="meta">цену не спрашивали</span>');
  return bits.join(" · ");
}

function ideasCard(pick) {
  // data-preview -- общий для всей программы признак «на это можно навести и
  // увидеть карту крупно»: его читает предпросмотр из app.js. Без него
  // миниатюра здесь была единственной во всей программе, которая не
  // раскрывается.
  const big = pick.image_normal || pick.image_small;
  return (
    '<div class="ideacard" data-card="' + esc(pick.name) + '"' +
      (big ? ' data-preview="' + esc(big) + '"' : "") + ">" +
      (pick.image_small
        ? '<img loading="lazy" src="' + esc(pick.image_small) + '" alt="">'
        : '<div class="noart">' + esc(pick.name) + "</div>") +
      '<div class="ideabody">' +
        '<div class="nm">' + esc(pick.name) + "</div>" +
        (pick.ru_name ? '<div class="meta">' + esc(pick.ru_name) + "</div>" : "") +
        '<div class="meta">' + esc(pick.type_line || "") + "</div>" +
        '<div class="money">' + ideasMoney(pick) + "</div>" +
        '<div class="row tight">' +
          '<button class="ghost tiny" data-idea-deck="' + esc(pick.name) +
            '">+ в колоду</button>' +
          '<button class="ghost tiny" data-idea-hunt="' + esc(pick.name) +
            '">+ в охоту</button>' +
        "</div>" +
      "</div>" +
    "</div>"
  );
}

function ideasSection(section) {
  return (
    '<div class="ideabox">' +
      "<h3>" + esc(section.label) + "</h3>" +
      '<p class="meta">' + esc(section.why) +
        (section.examples.length
          ? " · у вас: " + esc(section.examples.join(", "))
          : "") +
      "</p>" +
      (section.description
        ? '<p class="meta dim">' + esc(section.description) + "</p>"
        : "") +
      '<div class="ideagrid">' + section.picks.map(ideasCard).join("") + "</div>" +
    "</div>"
  );
}

function ideasRender() {
  const box = $("#ideas-body");
  const meta = $("#ideas-meta");
  if (!ideasData) {
    box.innerHTML = "";
    meta.textContent = "";
    return;
  }
  const d = ideasData;
  if (!d.sections.length) {
    meta.textContent = "";
    box.innerHTML =
      '<p class="meta">Пока не видно, про что колода. Так бывает у совсем ' +
      "маленьких колод и у наборов «всего понемногу»: тема — это когда " +
      "несколько карт делают одно и то же. Доберите десяток карт в одну " +
      "сторону, и предложка увидит замысел.</p>";
    return;
  }

  const colours = d.colors
    ? d.colors.split("").map((c) => '<span class="mi mi-' + esc(c.toLowerCase()) +
        '">' + esc(c) + "</span>").join("")
    : '<span class="meta">бесцветная</span>';
  meta.innerHTML =
    "Колода «" + esc(d.deck_name || "") + "» · " +
    (d.format ? esc(d.format) + " · " : "") +
    "цвета: " + colours + " · " +
    "разобрано карт: " + d.read + " из " + d.of +
    ' · <span class="meta">предлагается то, чего в колоде нет, ' +
    "в её цветах и её формате</span>";

  box.innerHTML = d.sections.map(ideasSection).join("");
}

async function ideasLoad() {
  const deck = ideasDeck();
  const box = $("#ideas-body");
  if (!deck) {
    $("#ideas-meta").textContent = "";
    box.innerHTML =
      '<p class="meta">Откройте колоду в билдере — предложка читает именно ' +
      "её.</p>";
    return;
  }
  ideasDeckId = deck.id;
  box.innerHTML = '<p class="meta spinner">читаю, про что колода…</p>';
  try {
    const order = $("#ideas-order").value;
    ideasData = await api("/api/decks/" + deck.id + "/ideas?order=" +
                          encodeURIComponent(order));
    ideasRender();
  } catch (e) {
    box.innerHTML = '<p class="meta">не вышло: ' + esc(e.message) + "</p>";
  }
}

function ideasOpen() {
  const deck = ideasDeck();
  // Колода сменилась, пока окно было закрыто -- читаем заново: старые
  // предложения относятся к другой колоде и молча врут.
  if (!ideasData || !deck || deck.id !== ideasDeckId) {
    ideasLoad();
    return;
  }
  ideasRender();
}

$("#ideas-order").addEventListener("change", ideasLoad);
$("#ideas-run").addEventListener("click", ideasLoad);

$("#ideas-body").addEventListener("click", async (ev) => {
  const toDeck = ev.target.closest("[data-idea-deck]");
  if (toDeck) {
    const deck = ideasDeck();
    if (!deck) return;
    toDeck.disabled = true;
    try {
      await post("/api/decks/" + deck.id + "/cards",
                 { cards: [{ name: toDeck.dataset.ideaDeck, quantity: 1,
                             section: "main" }] });
      toast(toDeck.dataset.ideaDeck + " в колоде");
      if (typeof bdOpen === "function") await bdOpen(deck.id);
    } catch (e) {
      toast(e.message, true);
    } finally {
      toDeck.disabled = false;
    }
    return;
  }

  const toHunt = ev.target.closest("[data-idea-hunt]");
  if (toHunt && typeof addToHunt === "function") {
    addToHunt(toHunt.dataset.ideaHunt, 1);
    toast("В охоту: " + toHunt.dataset.ideaHunt);
    return;
  }

  // Нажатие по самой карточке открывает карту -- как везде в программе.
  const card = ev.target.closest(".ideacard");
  if (card && typeof openCardByName === "function") {
    openCardByName(card.dataset.card);
  }
});
