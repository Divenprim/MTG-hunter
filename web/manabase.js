"use strict";

/* Манабаза: чего колоде не хватает по цветам и чем это добить.

   Вопрос «сколько каких земель» обычно решают на глаз, а он решается счётом.
   Сколько источников цвета нужно -- зависит от того, сколько цветных значков
   в самой требовательной карте и на каком ходу её играют; ориентир взят у
   Карстена, порог -- девяносто процентов партий.

   Подбор идёт по локальной базе и по долларовой цене: она есть почти у всех
   земель и не требует ни одного запроса наружу. Рублёвую цену узнают потом,
   охотой, и только для того, что выбрано.

   Тапнутые земли не запрещены -- одними развёрнутыми манабазу не собрать, --
   но в списке они стоят ниже равных им развёрнутых. Фетчи вынесены отдельно:
   они дают цвет не сразу и считаются иначе.

   Загружается после builder.js; пользуется его колодой и общими помощниками. */

let mbData = null;
let mbBudget = store.get("mb.budget", 5);
let mbOnlyOpen = store.get("mb.onlyopen", false);
let mbBusy = false;

function mbPanel() { return $("#bd-manabase"); }

const MB_ENTRY = {
  open: ["ok", "развёрнутой"],
  maybe: ["warn", "по условию"],
  tapped: ["", "тапнутой"],
};
const MB_COLORS = { W: "белый", U: "синий", B: "чёрный", R: "красный", G: "зелёный" };
/* Подтипы земель, которые кто-нибудь пересчитывает, в двух формах: после
   числа («нужно 10 Врат») и в заголовке («Врата, которых в колоде нет»).
   Одной формой тут не обойтись — получается либо «10 Врата», либо «Врат,
   которых нет». */
const MB_WHAT = {
  Gate: ["Врат", "Врата"], Desert: ["Пустынь", "Пустыни"],
  Locus: ["Локусов", "Локусы"], Sphere: ["Сфер", "Сферы"],
  Cave: ["Пещер", "Пещеры"], Town: ["Городов", "Города"],
  Lair: ["Логов", "Логова"], Mine: ["Шахт", "Шахты"],
  Tower: ["Башен", "Башни"], Planet: ["Планет", "Планеты"],
  Cloud: ["Облаков", "Облака"], Mountain: ["Гор", "Горы"],
  Island: ["Островов", "Острова"], Swamp: ["Болот", "Болота"],
  Plains: ["Равнин", "Равнины"], Forest: ["Лесов", "Леса"],
};

function mbWhat(kind, form) {
  const pair = MB_WHAT[kind];
  return pair ? pair[form === "many" ? 1 : 0] : kind;
}

async function mbOpen() {
  if (!bdDeck) return toast("Сначала откройте колоду", true);
  const panel = mbPanel();
  if (!panel.hidden && mbData && mbData.deckId === bdDeck.id) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  panel.innerHTML = '<p class="meta">считаю…</p>';
  await mbLoad();
}

async function mbLoad() {
  if (!bdDeck || mbBusy) return;
  mbBusy = true;
  try {
    const r = await api("/api/decks/" + bdDeck.id + "/manabase?budget=" +
      encodeURIComponent(mbBudget) + "&only_open=" + (mbOnlyOpen ? "true" : "false"));
    r.deckId = bdDeck.id;
    mbData = r;
  } catch (e) {
    mbPanel().innerHTML = '<p class="bad">' + esc(e.message) + "</p>";
    mbBusy = false;
    return;
  }
  mbBusy = false;
  mbRender();
}

/* Колода сменилась или изменился её состав -- манабаза пересчитывается: она
   вся про то, что в колоде лежит. */
function mbFollowDeck() {
  mbData = null;
  if (!mbPanel().hidden) {
    mbPanel().innerHTML = '<p class="meta">считаю…</p>';
    mbLoad();
  }
}

function mbRefresh() {
  if (!mbPanel().hidden) mbLoad();
}

function mbLandRow(c) {
  const [cls, word] = MB_ENTRY[c.entry] || ["", c.entry];
  return (
    '<div class="mbland" data-open="' + esc(c.name) + '"' +
        (c.image_normal ? ' data-preview="' + esc(c.image_normal) + '"' : "") + ">" +
      (c.image_small
        ? '<img loading="lazy" src="' + esc(c.image_small) + '" alt="">'
        : '<span class="mbnoart"></span>') +
      '<div class="mbbody">' +
        "<b>" + esc(c.ru_name || c.name) + "</b>" +
        '<span class="meta">' + esc(c.name) + "</span>" +
        '<span class="mbtags">' +
          '<span class="chip">' + esc(c.covers || c.produces) + "</span>" +
          '<span class="chip ' + cls + '">' + word + "</span>" +
          (c.usd != null
            ? '<span class="chip">$' + c.usd.toFixed(2) + "</span>"
            : '<span class="chip">цена неизвестна</span>') +
          (c.have ? '<span class="chip ok">уже в колоде</span>' : "") +
        "</span>" +
        '<div class="row tight">' +
          '<button type="button" class="ghost tiny" data-mbadd="' + esc(c.name) +
            '">+ в колоду</button>' +
          '<button type="button" class="dots" data-suggest="' + esc(c.name) +
            '" title="Что сделать с картой">…</button>' +
        "</div>" +
      "</div>" +
    "</div>"
  );
}

function mbPlanOf(rep) {
  return ((rep || {}).plan || [])[0] || null;
}

/* Бывают колоды, где земли -- это и есть победа: турбофог выигрывает десятью
   Вратами, трон Урзы -- тремя землями. Считать такую манабазу по цветам и
   советовать «поменяйте тапленды на удобные двойные» значит предлагать
   разобрать то, ради чего колода собрана. Поэтому план выносится наверх, до
   всякой арифметики, и написано, сколько слотов он занял. */
function mbPlanBlock(rep) {
  const plan = mbPlanOf(rep);
  if (!plan) return "";
  const what = plan.what === "land"
    ? "земель" + (plan.distinct ? " с разными именами" : "")
    : esc(mbWhat(plan.what)) + (plan.distinct ? " с разными именами" : "");
  return (
    '<div class="mbplan' + (plan.ok ? " ok" : " short") + '">' +
      "<b>" + (plan.wins ? "Земли — это победа" : "Земли — часть плана") +
        "</b>" +
      "<span>" + esc(plan.card) + (plan.kind === "pair"
        ? " работает только вместе с остальными"
        : ": нужно " + plan.need + " " + what) + "</span>" +
      '<span class="chip ' + (plan.ok ? "ok" : "warn") + '">сейчас ' +
        plan.have + (plan.ok ? " — собран" : " — не собран") + "</span>" +
      '<span class="meta">Планом занято ' + (rep.plan_lands || 0) + " земель " +
        "из " + (rep.lands || 0) + "; на цвета остаётся " +
        (rep.free_lands || 0) + ". Эти земли не меняются на удобные: цифры " +
        "ниже — про свободные слоты, а не про весь список.</span>" +
    "</div>"
  );
}

function mbRender() {
  if (!mbData) return;
  const rep = mbData.report || {};
  const entry = rep.entry || {};

  const colors = (rep.colors || []).map((c) => {
    const worst = c.worst || {};
    return (
      '<div class="mbcolor' + (c.short ? " short" : "") + '">' +
        "<b>" + esc(MB_COLORS[c.color] || c.color) + "</b>" +
        '<span class="mbnums">' + c.have + " из " + c.need + "</span>" +
        (c.short
          ? '<span class="chip warn">не хватает ' + c.short + "</span>"
          : '<span class="chip ok">хватает</span>') +
        (worst.name
          ? '<span class="meta">по самой требовательной: ' + esc(worst.name) +
            " " + esc(worst.cost || "") + " к ходу " + worst.turn + "</span>"
          : '<span class="meta">цветных карт нет — источники лишние</span>') +
      "</div>"
    );
  }).join("");

  mbPanel().innerHTML =
    '<div class="fmthead">' +
      "<b>Манабаза</b>" +
      '<span class="meta">земель ' + rep.lands + " · развёрнутыми " +
        (entry.open || 0) + " · по условию " + (entry.maybe || 0) +
        " · тапнутыми " + (entry.tapped || 0) +
        (entry.fetch ? " · фетчей " + entry.fetch : "") + "</span>" +
      '<button type="button" class="ghost" data-mbclose="1">Закрыть</button>' +
    "</div>" +

    '<p class="meta">Сколько источников цвета нужно — считается по самой ' +
      "требовательной карте этого цвета: столько, чтобы разыграть её вовремя " +
      "примерно в девяти партиях из десяти. Источник — всё, что добавляет ману " +
      "этого цвета, включая камни и существ.</p>" +

    mbPlanBlock(rep) +

    '<div class="mbcolors">' + colors + "</div>" +

    (rep.ok
      ? '<p class="good">Цветов хватает: по каждому источников не меньше, чем ' +
        "нужно самой требовательной карте.</p>"
      : "") +

    '<div class="row tight wrap mbtools">' +
      '<label class="inline">не дороже, $' +
        '<input type="number" id="mb-budget" min="0" step="0.5" value="' +
          mbBudget + '" style="width:80px"></label>' +
      '<label class="inline"><input type="checkbox" id="mb-open"' +
        (mbOnlyOpen ? " checked" : "") + "> только те, что входят развёрнутыми</label>" +
      '<span class="meta">цена — долларовая, за самую дешёвую печать; ' +
        "рублёвую узнает охота</span>" +
    "</div>" +

    ((mbData.plan || []).length
      ? "<h4>" + esc(mbData.plan_what ? mbWhat(mbData.plan_what, "many")
                          : "Земли плана") +
        ", которых в колоде нет <span class=\"meta\">— они и цвет дают, и " +
        "план двигают</span></h4>" +
        '<div class="mblands">' + mbData.plan.map(mbLandRow).join("") + "</div>"
      : "") +

    ((mbData.duals || []).length
      ? "<h4>Чем добить цвета" +
        (mbPlanOf(rep)
          ? " <span class=\"meta\">— плана эти земли не двигают: берите их " +
            "только в свободные слоты</span>"
          : "") +
        '</h4><div class="mblands">' +
        mbData.duals.map(mbLandRow).join("") + "</div>"
      : '<p class="meta">Под эти цвета и этот бюджет ничего не нашлось — ' +
        "попробуйте поднять порог цены.</p>") +

    ((mbData.fetch || []).length
      ? "<h4>Фетчи <span class=\"meta\">— цвет дают не сразу: сначала " +
        "достают землю, поэтому считаются отдельно</span></h4>" +
        '<div class="mblands">' + mbData.fetch.map(mbLandRow).join("") + "</div>"
      : "") +

    ((mbData.costly || []).length
      ? "<h4>С оговорками <span class=\"meta\">— цвет за доплату или с " +
        "оглядкой на чужие земли; источником не считаются</span></h4>" +
        '<div class="mblands">' + mbData.costly.slice(0, 6).map(mbLandRow).join("") +
        "</div>"
      : "");
}

mbPanel().addEventListener("click", async (ev) => {
  const t = ev.target;
  if (t.dataset.mbclose) { mbPanel().hidden = true; return; }

  const add = t.closest("[data-mbadd]");
  if (add) {
    await bdAddByName(add.dataset.mbadd, 1, "main");
    return;
  }

  const more = t.closest("[data-suggest]");
  if (more) {
    const box = more.getBoundingClientRect();
    bdSuggestMenu(more.dataset.suggest, box.left, box.bottom + 4);
    return;
  }

  const open = t.closest("[data-open]");
  if (open && !t.closest("button")) openCardByName(open.dataset.open);
});

mbPanel().addEventListener("contextmenu", (ev) => {
  const land = ev.target.closest("[data-open]");
  if (!land) return;
  ev.preventDefault();
  bdSuggestMenu(land.dataset.open, ev.clientX, ev.clientY);
});

mbPanel().addEventListener("change", async (ev) => {
  if (ev.target.id === "mb-budget") {
    mbBudget = Math.max(0, parseFloat(ev.target.value) || 0);
    store.set("mb.budget", mbBudget);
    await mbLoad();
  }
  if (ev.target.id === "mb-open") {
    mbOnlyOpen = ev.target.checked;
    store.set("mb.onlyopen", mbOnlyOpen);
    await mbLoad();
  }
});
