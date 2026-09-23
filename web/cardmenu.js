/* Меню по правой кнопке.

   В списке карта правится кнопками в строке, а в стопках и плитках -- ничем:
   там нет ни количества, ни «убрать». А стопки -- вид по умолчанию, то есть
   чаще всего колода открыта именно в нём. Убрать один Fog из четырёх было
   попросту нечем.

   Поэтому меню: правой кнопкой по карте в любом виде. Наверху счётчик, который
   меняет количество не закрывая меню, -- убрать три копии из четырёх это три
   нажатия подряд, а не три открытия меню. Под ним всё остальное.

   На планшете правой кнопки нет, а долгое нажатие занято перетаскиванием,
   поэтому у карточек есть кнопка «…»: то же самое меню, только по нажатию. */

let menuBox = null;
let menuOff = null;             // как отписаться от «закрыть по клику мимо»

function closeCardMenu() {
  if (menuOff) { menuOff(); menuOff = null; }
  if (menuBox && menuBox.parentNode) menuBox.parentNode.removeChild(menuBox);
  menuBox = null;
}

/* Закрытие по клику мимо вешается не навсегда, а на время жизни меню -- и со
   следующего витка событий. Иначе тот же самый клик, которым меню открыли,
   доходит до документа и тут же его закрывает: по правой кнопке меню работало,
   а по кнопке «…» появлялось и сразу исчезало. */
function menuWatchOutside() {
  const away = (ev) => {
    if (!ev.target.closest(".cardmenu")) closeCardMenu();
  };
  const esc = (ev) => {
    if (ev.key === "Escape") closeCardMenu();
  };
  const timer = setTimeout(() => {
    document.addEventListener("click", away, true);
    document.addEventListener("contextmenu", away, true);
  }, 0);
  document.addEventListener("keydown", esc, true);
  window.addEventListener("scroll", closeCardMenu, true);
  return () => {
    clearTimeout(timer);
    document.removeEventListener("click", away, true);
    document.removeEventListener("contextmenu", away, true);
    document.removeEventListener("keydown", esc, true);
    window.removeEventListener("scroll", closeCardMenu, true);
  };
}

/* items: [{label, hint, on, danger, disabled, checked}] либо {counter: {...}}
   либо "-" для разделителя. */
function showCardMenu(x, y, title, items) {
  closeCardMenu();
  const box = document.createElement("div");
  box.className = "cardmenu";
  box.innerHTML =
    (title ? '<div class="cmtitle">' + title + "</div>" : "") +
    items.map((item, i) => {
      if (item === "-") return '<div class="cmsep"></div>';
      if (item.counter) {
        return '<div class="cmcount" data-i="' + i + '">' +
          '<button data-step="-1" title="на одну меньше">−</button>' +
          "<b>" + item.counter.value + "</b>" +
          '<button data-step="1" title="на одну больше">+</button>' +
          '<span class="meta">' + esc(item.counter.label || "") + "</span>" +
        "</div>";
      }
      return '<button class="cmitem' + (item.danger ? " danger" : "") +
        (item.checked ? " on" : "") + '" data-i="' + i + '"' +
        (item.disabled ? " disabled" : "") + ">" +
        esc(item.label) +
        (item.hint ? '<span class="meta">' + esc(item.hint) + "</span>" : "") +
      "</button>";
    }).join("");

  document.body.appendChild(box);
  menuBox = box;
  menuOff = menuWatchOutside();

  // Меню не должно уезжать за край экрана: у нижних карт оно иначе
  // открывается там, куда не докрутить.
  const rect = box.getBoundingClientRect();
  const left = Math.min(x, window.innerWidth - rect.width - 8);
  const top = Math.min(y, window.innerHeight - rect.height - 8);
  box.style.left = Math.max(8, left) + "px";
  box.style.top = Math.max(8, top) + "px";

  box.addEventListener("click", async (ev) => {
    const step = ev.target.closest("[data-step]");
    if (step) {
      const row = step.closest(".cmcount");
      const item = items[parseInt(row.dataset.i, 10)];
      const next = await item.counter.on(parseInt(step.dataset.step, 10));
      if (next == null) return closeCardMenu();
      row.querySelector("b").textContent = next;
      return;
    }
    const btn = ev.target.closest(".cmitem");
    if (!btn || btn.disabled) return;
    const item = items[parseInt(btn.dataset.i, 10)];
    closeCardMenu();
    if (item && item.on) item.on();
  });
  return box;
}

