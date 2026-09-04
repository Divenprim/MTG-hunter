"use strict";

/* Favourites: a wishlist, not a collection.

   The collection answers "what do I own" and gets subtracted from decks.
   Favourites answer "what do I intend to order", so they keep a wanted
   quantity and live in folders -- "for the Modern deck" apart from "cheap
   upgrades later" -- and a whole folder can be pushed into the hunt.

   Loaded after app.js and reuses its helpers ($, api, toast, showTab, store,
   openCard, refreshStatus). */

let favDoc = { folders: [] };
let favCurrent = null;

function favFolder() {
  return favDoc.folders.find((f) => f.id === favCurrent) || favDoc.folders[0] || null;
}

function renderFavFolders() {
  $("#fav-folders").innerHTML = favDoc.folders.map((f) =>
    '<div class="favfolder' + (f.id === favCurrent ? " on" : "") + '" data-id="' + esc(f.id) + '">' +
    '<span class="nm">' + esc(f.name) + "</span>" +
    '<span class="cnt">' + f.cards.length + "</span>" +
    "</div>").join("");
}

function favCardRow(card, folderId) {
  const r = card.resolved;
  const img = r && r.image_small;
  const usd = r && r.prices && r.prices.usd;
  const others = favDoc.folders.filter((f) => f.id !== folderId);
  const sub = r
    ? esc((r.set_code || "").toUpperCase()) + " · " + esc(r.set_name || "") +
      (r.collector_number ? " #" + esc(r.collector_number) : "") +
      (r.ru_name ? " · " + esc(r.ru_name) : "")
    : "";
  return (
    '<div class="favrow' + (r ? "" : " missing") + '" data-card="' + esc(card.id) + '">' +
    (img
      ? '<img loading="lazy" src="' + esc(img) + '" alt="" data-full="' +
        esc((r && r.image_normal) || img) + '">'
      : "<div></div>") +
    "<div>" +
      '<div class="nm">' + esc(card.name) + (r ? "" : " — не найдена в базе") + "</div>" +
      '<div class="sub">' + sub + "</div>" +
      (card.note ? '<div class="note">' + esc(card.note) + "</div>" : "") +
    "</div>" +
    '<div class="qty"><input type="number" min="1" value="' + (card.quantity || 1) +
      '" data-qty="' + esc(card.id) + '"></div>' +
    '<div class="acts">' +
      (usd ? '<span class="chip">$' + esc(usd) + "</span>" : "") +
      (others.length
        ? '<select data-move="' + esc(card.id) + '"><option value="">переместить…</option>' +
          others.map((f) => '<option value="' + esc(f.id) + '">' + esc(f.name) + "</option>").join("") +
          "</select>"
        : "") +
      '<button class="ghost" data-remove="' + esc(card.id) + '">убрать</button>' +
    "</div></div>"
  );
}

function renderFavourites() {
  renderFavFolders();
  const folder = favFolder();
  if (!folder) {
    $("#fav-title").textContent = "—";
    $("#fav-summary").textContent = "";
    $("#fav-cards").innerHTML = "";
    return;
  }
  favCurrent = folder.id;
  $("#fav-title").textContent = folder.name;
  $("#fav-summary").textContent =
    folder.cards.length + " назв. · " + (folder.copies || 0) + " шт." +
    (folder.total_usd ? " · ≈ $" + folder.total_usd.toFixed(2) : "");
  $("#fav-cards").innerHTML = folder.cards.length
    ? folder.cards.map((c) => favCardRow(c, folder.id)).join("")
    : '<p class="meta">Папка пуста. Откройте карту в поиске и нажмите «В избранное».</p>';
}

async function favLoad() {
  try {
    const r = await api("/api/favourites");
    favDoc = r.favourites;
    if (!favCurrent || !favDoc.folders.some((f) => f.id === favCurrent)) {
      favCurrent = favDoc.folders[0] ? favDoc.folders[0].id : null;
    }
    renderFavourites();
    if (typeof renderDeckFolderOptions === "function") renderDeckFolderOptions();
  } catch (e) {
    $("#fav-cards").innerHTML = '<p class="meta">Не удалось загрузить избранное</p>';
  }
}

async function favCall(path, options, okMsg) {
  try {
    const r = await api(path, options);
    favDoc = r.favourites;
    if (!favDoc.folders.some((f) => f.id === favCurrent)) {
      favCurrent = favDoc.folders[0] ? favDoc.folders[0].id : null;
    }
    renderFavourites();
    // The deck workbench has its own folder dropdown; keep it in step.
    if (typeof renderDeckFolderOptions === "function") renderDeckFolderOptions();
    if (typeof loadBackups === "function") loadBackups();
    refreshStatus();
    if (okMsg) toast(okMsg);
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

function favBody(method, body) {
  return {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  };
}

$("#fav-folders").addEventListener("click", (ev) => {
  const row = ev.target.closest(".favfolder");
  if (!row) return;
  favCurrent = row.dataset.id;
  renderFavourites();
});

$("#fav-newfolder-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const name = $("#fav-newfolder").value.trim();
  if (!name) return;
  const ok = await favCall("/api/favourites/folders", favBody("POST", { name }), "Папка создана");
  if (ok) {
    $("#fav-newfolder").value = "";
    const created = favDoc.folders.find((f) => f.name === name);
    if (created) {
      favCurrent = created.id;
      renderFavourites();
    }
  }
});

$("#fav-rename").addEventListener("click", async () => {
  const folder = favFolder();
  if (!folder) return;
  const name = prompt("Новое название папки:", folder.name);
  if (!name || name === folder.name) return;
  await favCall("/api/favourites/folders/" + folder.id, favBody("PATCH", { name }), "Переименовано");
});

$("#fav-delete").addEventListener("click", async () => {
  const folder = favFolder();
  if (!folder) return;
  if (!confirm("Удалить папку «" + folder.name + "» и всё её содержимое?")) return;
  await favCall("/api/favourites/folders/" + folder.id, { method: "DELETE" }, "Папка удалена");
});

$("#fav-cards").addEventListener("click", async (ev) => {
  const folder = favFolder();
  if (!folder) return;

  const remove = ev.target.closest("[data-remove]");
  if (remove) {
    await favCall(
      "/api/favourites/folders/" + folder.id + "/cards/" + remove.dataset.remove,
      { method: "DELETE" }
    );
    return;
  }

  const img = ev.target.closest("img[data-full]");
  if (img) {
    const row = img.closest(".favrow");
    const card = folder.cards.find((c) => c.id === row.dataset.card);
    if (card && card.resolved && card.resolved.oracle_id) {
      openCard({
        id: "fav-" + card.id,
        name: card.name,
        oracle_id: card.resolved.oracle_id,
        image_normal: card.resolved.image_normal,
        image_small: card.resolved.image_small,
        ru_name: card.resolved.ru_name,
        type_line: card.resolved.type_line,
        prices: card.resolved.prices,
        legalities: {},
        faces: [],
      });
    }
  }
});

$("#fav-cards").addEventListener("change", async (ev) => {
  const folder = favFolder();
  if (!folder) return;

  const qty = ev.target.closest("[data-qty]");
  if (qty) {
    const n = parseInt(qty.value, 10);
    if (!Number.isFinite(n) || n < 1) return;
    await favCall(
      "/api/favourites/folders/" + folder.id + "/cards/" + qty.dataset.qty,
      favBody("PATCH", { quantity: n })
    );
    return;
  }

  const move = ev.target.closest("[data-move]");
  if (move && move.value) {
    await favCall(
      "/api/favourites/folders/" + folder.id + "/cards/" + move.dataset.move + "/move",
      favBody("POST", { target_folder_id: move.value }),
      "Перемещено"
    );
  }
});

$("#fav-to-hunt").addEventListener("click", async () => {
  const folder = favFolder();
  if (!folder || !folder.cards.length) return toast("Папка пуста", true);
  try {
    const r = await api("/api/favourites/folders/" + folder.id + "/wants");
    const text = r.wants.map((w) => w.quantity + " " + w.name).join("\n");
    $("#hunt-wants").value = text;
    store.set("hunt", text);
    $("#hunt-source").textContent = "Список из папки «" + folder.name + "».";
    showTab("hunt");
    toast("В охоту: " + r.wants.length + " позиций");
  } catch (e) {
    toast(e.message, true);
  }
});

/* Called from the card modal. `printing` pins a specific print when the user
   picked one from the printings table -- a foil Secret Lair is not the same
   want as the cheap reprint. */
async function addToFavourites(card, quantity, printing) {
  if (!favDoc.folders.length) await favLoad();
  const folder = favFolder();
  if (!folder) {
    toast("Нет папок для избранного", true);
    return;
  }
  await favCall(
    "/api/favourites/folders/" + folder.id + "/cards",
    favBody("POST", {
      name: card.name,
      quantity: quantity || 1,
      set_code: printing ? printing.set_code : null,
      collector_number: printing ? printing.collector_number : null,
    }),
    "«" + card.name + "» → " + folder.name
  );
}

favLoad();

/* ---------------------------------------------------------------- backups */

/* Every mutation writes a snapshot first, so an accidental deletion is an
   inconvenience rather than lost work. This panel is how you undo one. */

function renderBackups(list) {
  const box = $("#fav-backups");
  if (!box) return;
  box.innerHTML = (list || []).length
    ? list.slice(0, 20).map((b) =>
        '<div class="backup" data-snap="' + b.id + '">' +
          '<span class="when">' + esc((b.created || "").slice(5, 16)) + "</span>" +
          '<span class="why">' + esc(b.reason || "изменение") + "</span>" +
          '<button data-restore="' + b.id + '">откатить</button>' +
        "</div>").join("")
    : '<p class="meta">пока нечего откатывать</p>';
}

$("#fav-backups").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-restore]");
  if (!btn) return;
  if (!confirm("Вернуть избранное к этому состоянию? Текущее сохранится отдельным снимком.")) return;
  try {
    const r = await api("/api/backups/favourites/restore", favBody("POST", {
      snapshot_id: parseInt(btn.dataset.restore, 10),
    }));
    favDoc = r.favourites;
    if (!favDoc.folders.some((f) => f.id === favCurrent)) {
      favCurrent = favDoc.folders[0] ? favDoc.folders[0].id : null;
    }
    renderFavourites();
    renderBackups(r.backups);
    if (typeof renderDeckFolderOptions === "function") renderDeckFolderOptions();
    refreshStatus();
    toast("Избранное восстановлено");
  } catch (e) {
    toast(e.message, true);
  }
});

async function loadBackups() {
  try {
    const r = await api("/api/backups");
    renderBackups(r.favourites);
    renderCollectionBackups(r.collection);
  } catch (e) { /* panel stays empty */ }
}

function renderCollectionBackups(list) {
  const box = $("#coll-backups");
  if (!box) return;
  box.innerHTML = (list || []).length
    ? list.slice(0, 20).map((b) =>
        '<div class="backup">' +
          '<span class="when">' + esc((b.created || "").slice(5, 16)) + "</span>" +
          '<span class="why">' + esc(b.reason || "изменение") + "</span>" +
          '<button data-crestore="' + b.id + '">откатить</button>' +
        "</div>").join("")
    : '<p class="meta">пока нечего откатывать</p>';
}

$("#coll-backups").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-crestore]");
  if (!btn) return;
  if (!confirm("Вернуть коллекцию к этому состоянию?")) return;
  try {
    const r = await api("/api/backups/collection/restore", favBody("POST", {
      snapshot_id: parseInt(btn.dataset.crestore, 10),
    }));
    const entries = Object.keys(r.collection || {});
    $("#collection-text").value = entries.map((n) => r.collection[n] + " " + n).join("\n");
    renderCollectionBackups(r.backups);
    refreshStatus();
    toast("Коллекция восстановлена");
  } catch (e) {
    toast(e.message, true);
  }
});

loadBackups();
