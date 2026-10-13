"use strict";

/* Запуск: собрать всё, что уже загрузилось, и показать первый экран.

   Отдельным файлом и последним в списке нарочно. Пока это сидело в конце
   app.js, оно звало вещи из файлов, которые грузятся **после** него: порядок
   загрузки превращался в скрытое требование, и любой переезд кода ломал
   запуск молча. Запуск, который зависит от всех, должен и грузиться после
   всех.
*/

(async function init() {
  await refreshStatus();
  // Заказы живут в hunt.js, который грузится после этого файла: зовём через
  // проверку, как и всё остальное между файлами.
  if (typeof loadOrders === "function") await loadOrders();
  // Vocabularies first: restoring the panel renders tokens that depend on them.
  await Promise.all([loadSets(), loadFormats(), loadTypes()]);

  // Draw the static pickers unconditionally: restoreFilterPanel() returns
  // early when nothing was stored, which would leave them empty on a fresh
  // browser.
  renderFlags();

  restoreFilterPanel(store.get("filters", null));
  const openFilters = store.get("filtersOpen", false);
  $("#filters-panel").hidden = !openFilters;
  $("#filters-toggle").setAttribute("aria-expanded", String(openFilters));

  $("#search-q").value = store.get("query", "");
  $("#search-sort").value = store.get("sort", "relevance");
  $("#hunt-wants").value = store.get("hunt", "");

  const hf = store.get("huntFilters", null);
  if (hf) {
    $$(".lang").forEach((c) => (c.checked = (hf.languages || []).indexOf(c.value) >= 0));
    $("#f-condition").value = hf.min_condition || "";
    $("#f-maxprice").value = hf.max_price == null ? "" : hf.max_price;
    $("#f-refs").value = hf.min_seller_refs == null ? "" : hf.min_seller_refs;
    $("#f-cities").value = (hf.cities || []).join(", ");
    $("#f-shops").checked = hf.include_shops !== false;
    $("#f-users").checked = hf.include_users !== false;
    $("#f-needlang").checked = !!hf.require_stated_language;
    $("#f-needcond").checked = !!hf.require_stated_condition;
  }

  showTab(store.get("tab", "search"));

  try {
    const r = await api("/api/collection");
    const entries = Object.keys(r.collection || {});
    if (entries.length) {
      $("#collection-text").value = entries.map((n) => r.collection[n] + " " + n).join("\n");
    }
  } catch (e) { /* fine on first run */ }

  if (typeof profilesRender === "function") profilesRender();
  if (typeof showWhatsNew === "function") showWhatsNew();

  // Первый экран программы -- поиск, и до сих пор он открывался пустой
  // сеткой без единого слова: человек видел серое поле и не знал, что тут
  // вообще происходит. Если искать нечего, здороваемся и показываем, с чего
  // начать.
  if ($("#search-q").value) runSearch(true);
  else if (!(typeof lsMode === "function" && lsMode())) {
    $("#search-results").innerHTML = searchWelcome();
  }
  // Режим поиска помнится между заходами: выбрал наборы -- открылись наборы.
  if (typeof lsLoad === "function" && $("#search-mode")) {
    $("#search-mode").value = store.get("searchMode", "cards");
    if ($("#search-mode").value === "landsets") lsLoad();
  }
})();
