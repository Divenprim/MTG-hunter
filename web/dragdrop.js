/* Перетаскивание: один механизм для мыши, пера и пальца.

   Раньше здесь был HTML5 drag-and-drop (draggable + dragstart/drop). Он
   работает только там, где есть мышь: **iOS Safari его не поддерживает
   вовсе**, так что на айпаде колоду нельзя было ни разложить, ни перекинуть
   карту из сайда в мейн. Плюс он умеет бросать только туда, где заранее
   развешаны обработчики, а «бросить в сайдборд, которого в колоде ещё нет»
   ему объяснить нечем.

   Поэтому здесь pointer events и свой призрак под курсором:

   * мышь начинает тащить после 5 px движения — случайный клик не считается;
   * палец начинает после удержания (250 мс) без движения — иначе любое
     пролистывание списка превращалось бы в перетаскивание. Пока держат,
     страница не прокручивается: touchmove отменяется, и только после начала
     перетаскивания;
   * цель ищется через elementFromPoint, а не по всплытию события, — поэтому
     бросать можно куда угодно, в том числе на полосу секций, которая
     появляется только на время перетаскивания;
   * у края экрана список прокручивается сам, иначе на планшете дальнюю
     колонку не достать.

   Отмена — Escape или pointercancel (системный жест, звонок, что угодно).
*/

const DRAG_MOUSE_SLOP = 5;      // px, после которых мышь считается тащащей
const DRAG_HOLD_MS = 250;       // сколько держать пальцем
const DRAG_HOLD_SLOP = 10;      // px, дозволенные за время удержания
const DRAG_EDGE = 90;           // px от края, где начинается автопрокрутка
const DRAG_EDGE_STEP = 14;

let dragActive = null;          // {opts, el, ghost, target}

function dragStopScroll(ev) {
  if (dragActive) ev.preventDefault();
}
document.addEventListener("touchmove", dragStopScroll, { passive: false });

function dragCleanup() {
  if (!dragActive) return;
  const { el, ghost, opts } = dragActive;
  if (ghost && ghost.parentNode) ghost.parentNode.removeChild(ghost);
  if (el) el.classList.remove("dragging");
  document.querySelectorAll(".dropover").forEach(
    (e) => e.classList.remove("dropover"));
  document.body.classList.remove("dragging-now");
  dragActive = null;
  if (opts && opts.onEnd) opts.onEnd();
}

function dragGhostFor(el, opts) {
  const ghost = document.createElement("div");
  ghost.className = "dragghost";
  ghost.innerHTML = opts.ghost ? opts.ghost(el) : el.outerHTML;
  const box = el.getBoundingClientRect();
  ghost.style.width = Math.min(box.width, 220) + "px";
  document.body.appendChild(ghost);
  return ghost;
}

function dragMoveGhost(x, y) {
  const g = dragActive.ghost;
  g.style.transform = "translate(" + (x + 12) + "px," + (y + 12) + "px)";
}

function dragHighlight(x, y) {
  const opts = dragActive.opts;
  const under = document.elementFromPoint(x, y);
  const target = under ? under.closest(opts.targets) : null;
  const ok = target && (!opts.accepts || opts.accepts(target, dragActive.el));
  if (dragActive.target !== (ok ? target : null)) {
    document.querySelectorAll(".dropover").forEach(
      (e) => e.classList.remove("dropover"));
    if (ok) target.classList.add("dropover");
    dragActive.target = ok ? target : null;
  }
}

function dragEdgeScroll(y) {
  if (y < DRAG_EDGE) window.scrollBy(0, -DRAG_EDGE_STEP);
  else if (y > window.innerHeight - DRAG_EDGE) window.scrollBy(0, DRAG_EDGE_STEP);
}

/* Повесить перетаскивание на контейнер.

   opts = {
     root:    элемент-контейнер,
     handle:  селектор того, что можно тащить,
     targets: селектор того, куда можно бросать,
     accepts: (target, el) => bool      -- необязательно,
     ghost:   (el) => html              -- что показать под курсором,
     onStart: (el) => void,
     onDrop:  (target, el) => void,
     onEnd:   () => void,
   } */
function makeDraggable(opts) {
  const root = opts.root;
  if (!root) return;

  root.addEventListener("pointerdown", (ev) => {
    if (ev.button !== undefined && ev.button !== 0) return;
    // Кнопка внутри карточки -- это кнопка: нажатие на «+1» не должно
    // оказываться началом перетаскивания.
    if (ev.target.closest(opts.ignore || "button, input, select, textarea, a")) return;
    const el = ev.target.closest(opts.handle);
    if (!el || !root.contains(el)) return;

    const startX = ev.clientX;
    const startY = ev.clientY;
    const touch = ev.pointerType !== "mouse";
    let holdTimer = null;
    let started = false;

    const begin = () => {
      if (started || dragActive) return;
      started = true;
      dragActive = { opts: opts, el: el, ghost: null, target: null };
      dragActive.ghost = dragGhostFor(el, opts);
      el.classList.add("dragging");
      document.body.classList.add("dragging-now");
      if (opts.onStart) opts.onStart(el);
      dragMoveGhost(startX, startY);
    };

    const move = (e) => {
      const dx = Math.abs(e.clientX - startX);
      const dy = Math.abs(e.clientY - startY);
      if (!started) {
        // Палец, который поехал раньше срока, листает страницу, а не тащит.
        if (touch) {
          if (dx > DRAG_HOLD_SLOP || dy > DRAG_HOLD_SLOP) return done(false);
          return;
        }
        if (dx + dy < DRAG_MOUSE_SLOP) return;
        begin();
      }
      dragMoveGhost(e.clientX, e.clientY);
      dragHighlight(e.clientX, e.clientY);
      dragEdgeScroll(e.clientY);
    };

    const done = (drop, e) => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", cancel, true);
      window.removeEventListener("keydown", esc, true);
      if (holdTimer) clearTimeout(holdTimer);
      if (!started) { dragCleanup(); return; }
      const target = dragActive && dragActive.target;
      const dragged = dragActive && dragActive.el;
      dragCleanup();
      if (drop && target && opts.onDrop) opts.onDrop(target, dragged, e);
    };

    const up = (e) => done(true, e);
    const cancel = () => done(false);
    const esc = (e) => { if (e.key === "Escape") done(false); };

    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", cancel, true);
    window.addEventListener("keydown", esc, true);

    if (touch) holdTimer = setTimeout(begin, DRAG_HOLD_MS);
  });
}

/* Идёт ли перетаскивание прямо сейчас: по этому интерфейс показывает
   полосу секций и прячет подсказки. */
function dragging() {
  return !!dragActive;
}
