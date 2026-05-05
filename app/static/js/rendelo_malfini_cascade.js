// Malfini cascading dropdown — Póló kategória esetén minden line-row-on
// megjelenik egy modell→szín→méret választó, csak az aktívan elérhető
// kombinációkat mutatva. A választás után a sor `title` és `item_id`
// mezőjét automatikusan kitölti.
//
// Endpoint:    GET /items/malfini-tree?category_id=N
// Lépcső:      modell ▼ → szín ▼ (swatchcsel) → méret ▼ → fill-title
// Aktiválás:   ha a category select értéke == polo_category_id
(function () {
  const categorySelect = document.getElementById("category_id");
  if (!categorySelect) return; // nem új-igény / edit oldal

  let poloCategoryId = null;
  let treeCache = null; // {models: [...]} — fetched once amikor szükség van rá

  // ─── Init: polo_category_id lekérése egyszer ──────────────────────────
  fetch("/items/poll-poolo-category-id", { headers: { Accept: "application/json" } })
    .then((r) => r.json())
    .then((data) => {
      poloCategoryId = data.polo_category_id;
      updateCascadeVisibility();
    })
    .catch(() => {
      /* nem fatal — a cascade rejtve marad */
    });

  // ─── Cascade láthatóság a kategória-selecten alapulva ────────────────
  categorySelect.addEventListener("change", updateCascadeVisibility);

  function updateCascadeVisibility() {
    const isPolo =
      poloCategoryId !== null &&
      String(categorySelect.value) === String(poloCategoryId);
    document.querySelectorAll(".line-cascade").forEach((el) => {
      el.classList.toggle("hidden", !isPolo);
    });
    if (isPolo && treeCache === null) {
      loadTree();
    } else if (isPolo && treeCache !== null) {
      // Már be van töltve — populáljuk minden cascade modell-listáját
      populateAllModelDropdowns();
    }
  }

  function loadTree() {
    if (poloCategoryId === null) return;
    fetch(`/items/malfini-tree?category_id=${poloCategoryId}`, {
      headers: { Accept: "application/json" },
    })
      .then((r) => r.json())
      .then((data) => {
        treeCache = data;
        populateAllModelDropdowns();
      })
      .catch((e) => {
        console.error("[malfini-cascade] load failed", e);
      });
  }

  function populateAllModelDropdowns() {
    if (!treeCache) return;
    document.querySelectorAll(".cascade-model").forEach((sel) => {
      if (sel.dataset.populated === "1") return;
      sel.innerHTML = '<option value="">— modell —</option>';
      treeCache.models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m.code;
        opt.textContent = `${m.code} — ${m.label}`;
        sel.appendChild(opt);
      });
      sel.dataset.populated = "1";
    });
  }

  // ─── Event delegation: model/color/size onchange ──────────────────────
  document.addEventListener("change", function (e) {
    const target = e.target;
    if (!target.classList) return;
    const cascade = target.closest(".line-cascade");
    if (!cascade) return;

    const modelSel = cascade.querySelector(".cascade-model");
    const colorSel = cascade.querySelector(".cascade-color");
    const sizeSel = cascade.querySelector(".cascade-size");

    if (target.classList.contains("cascade-model")) {
      onModelChange(cascade, modelSel.value, colorSel, sizeSel);
    } else if (target.classList.contains("cascade-color")) {
      onColorChange(cascade, modelSel.value, colorSel.value, sizeSel);
    } else if (target.classList.contains("cascade-size")) {
      onSizeChange(cascade, modelSel.value, colorSel.value, sizeSel.value);
    }
  });

  function onModelChange(cascade, modelCode, colorSel, sizeSel) {
    // Színek populálása + size reset
    colorSel.innerHTML = '<option value="">— szín —</option>';
    sizeSel.innerHTML = '<option value="">— méret —</option>';
    sizeSel.disabled = true;
    if (!modelCode || !treeCache) {
      colorSel.disabled = true;
      return;
    }
    const model = treeCache.models.find((m) => m.code === modelCode);
    if (!model) {
      colorSel.disabled = true;
      return;
    }
    model.colors.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.code;
      opt.textContent = c.label;
      opt.dataset.hex = c.hex;
      colorSel.appendChild(opt);
    });
    colorSel.disabled = false;
    // Aktuális visual swatch frissítése
    updateColorSwatch(cascade, "");
  }

  function onColorChange(cascade, modelCode, colorCode, sizeSel) {
    sizeSel.innerHTML = '<option value="">— méret —</option>';
    if (!modelCode || !colorCode || !treeCache) {
      sizeSel.disabled = true;
      updateColorSwatch(cascade, "");
      return;
    }
    const model = treeCache.models.find((m) => m.code === modelCode);
    const color = model && model.colors.find((c) => c.code === colorCode);
    if (!color) {
      sizeSel.disabled = true;
      return;
    }
    updateColorSwatch(cascade, color.hex);
    color.sizes.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = JSON.stringify({
        id: s.item_id,
        code: s.item_code,
        name: s.item_name,
      });
      // Stock-jelzés a label mellett:
      //   null     → nem volt szinkron, label marad "XS"
      //   0        → "XS — nincs raktáron"
      //   1..      → "XS — 12 db"
      let label = s.size;
      if (s.stock_qty === 0) {
        label += " — nincs raktáron";
      } else if (typeof s.stock_qty === "number" && s.stock_qty > 0) {
        label += ` — ${s.stock_qty} db`;
      }
      opt.textContent = label;
      if (s.stock_qty === 0) {
        opt.style.color = "#999";
      }
      sizeSel.appendChild(opt);
    });
    sizeSel.disabled = false;
  }

  function onSizeChange(cascade, modelCode, colorCode, sizeRaw) {
    if (!sizeRaw) return;
    let payload;
    try {
      payload = JSON.parse(sizeRaw);
    } catch {
      return;
    }
    // A line-row-t megkeressük, és kitöltjük a title + item_id-t
    const row = cascade.closest(".line-row");
    if (!row) return;
    const titleInput = row.querySelector(".line-title");
    const itemIdInput = row.querySelector(".line-item-id");
    if (titleInput) titleInput.value = payload.name;
    if (itemIdInput) itemIdInput.value = payload.id;
    // Suggestions box ürítése (ne villanjon még az autocomplete is)
    const suggBox = row.querySelector(".line-suggestions");
    if (suggBox) suggBox.innerHTML = "";
  }

  // ─── Visualizáció: a kiválasztott szín hex pöttye a cascade-tetején ───
  function updateColorSwatch(cascade, hex) {
    let dot = cascade.querySelector(".cascade-color-swatch");
    if (!dot) return;
    if (hex) {
      dot.style.background = hex;
      dot.classList.remove("hidden");
    } else {
      dot.classList.add("hidden");
    }
  }
})();
