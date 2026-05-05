// Rendelő — Item-katalógus autocomplete + multi-line request űrlap kezelése.
//
// Minden `.line-row`-on belül van:
//   - input.line-title         — a felhasználó ide gépel
//   - input.line-item-id       — hidden, autocomplete választáskor itt tárolódik
//   - input.line-qty           — mennyiség
//   - input.line-unit          — egység
//   - .line-suggestions div    — ide rajzolódik az autocomplete dropdown
//
// A + gomb klónozza az ELSŐ sort, frissíti az indexet (lines[N][...]),
// és új sorként a containerbe rakja.

(function () {
  const linesContainer = document.getElementById("lines-container");
  if (!linesContainer) return; // nem az új-igény oldalon vagyunk

  // ===== Autocomplete: fetch-csel keres, eredmény a SAJÁT sora .line-suggestions-jébe =====

  let activeTitleInput = null; // a fókuszált .line-title
  let suggestTimer = null;

  linesContainer.addEventListener("input", function (e) {
    if (!e.target.classList.contains("line-title")) return;
    activeTitleInput = e.target;

    // Az item_id tisztul ha a user szerkeszti a címet (a katalógus-tétel
    // már nem érvényes, ha a cím nem egyezik vele)
    const row = e.target.closest(".line-row");
    const itemIdInput = row.querySelector(".line-item-id");
    if (itemIdInput) itemIdInput.value = "";

    clearTimeout(suggestTimer);
    suggestTimer = setTimeout(() => fetchSuggestions(e.target), 200);
  });

  linesContainer.addEventListener("focusin", function (e) {
    if (!e.target.classList.contains("line-title")) return;
    activeTitleInput = e.target;
    if (e.target.value.trim().length >= 2) {
      clearTimeout(suggestTimer);
      suggestTimer = setTimeout(() => fetchSuggestions(e.target), 200);
    }
  });

  function fetchSuggestions(input) {
    const row = input.closest(".line-row");
    const target = row.querySelector(".line-suggestions");
    if (!target) return;
    const q = input.value.trim();
    if (q.length < 2) {
      target.innerHTML = "";
      return;
    }
    fetch(`/items/search?q=${encodeURIComponent(q)}`, { credentials: "same-origin" })
      .then((r) => r.text())
      .then((html) => {
        target.innerHTML = html;
      })
      .catch(() => {
        // hálózati hiba — csendben lenyeljük, autocomplete csak nice-to-have
      });
  }

  // ===== Suggestion clicked: form mezők kitöltése =====
  linesContainer.addEventListener("click", function (e) {
    const btn = e.target.closest(".item-suggestion");
    if (!btn) return;
    e.preventDefault();
    const row = btn.closest(".line-row");
    if (!row) return;

    const brand = btn.dataset.itemBrand || "";
    const name = btn.dataset.itemName || "";
    const code = btn.dataset.itemCode || "";
    const defaultUnit = btn.dataset.itemDefaultUnit || "db";

    const titleParts = [];
    if (brand) titleParts.push(brand);
    if (name) titleParts.push(name);
    if (code) titleParts.push(code);

    const titleInput = row.querySelector(".line-title");
    if (titleInput) titleInput.value = titleParts.join(" ");

    const itemIdInput = row.querySelector(".line-item-id");
    if (itemIdInput) itemIdInput.value = btn.dataset.itemId || "";

    const unitInput = row.querySelector(".line-unit");
    if (unitInput) unitInput.value = defaultUnit;

    // Suggestions eltüntetése
    const suggBox = row.querySelector(".line-suggestions");
    if (suggBox) suggBox.innerHTML = "";

    // Fókusz a qty-re
    const qtyInput = row.querySelector(".line-qty");
    if (qtyInput) {
      qtyInput.focus();
      qtyInput.select();
    }
  });

  // ===== Bezárás kívülre kattintásra =====
  document.addEventListener("click", function (e) {
    if (e.target.closest(".line-title") || e.target.closest(".item-suggestions")) {
      return;
    }
    linesContainer.querySelectorAll(".line-suggestions").forEach((box) => {
      box.innerHTML = "";
    });
  });

  // ===== Escape — bezárja az aktív sor suggestions-jét =====
  linesContainer.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (!e.target.classList.contains("line-title")) return;
    const row = e.target.closest(".line-row");
    const suggBox = row.querySelector(".line-suggestions");
    if (suggBox) suggBox.innerHTML = "";
  });

  // ===== Új sor hozzáadása (+) =====
  window.addRequestLine = function () {
    const existingRows = linesContainer.querySelectorAll(".line-row");
    const newIndex = existingRows.length;

    // Klónozzuk az ELSŐ sort és újraírjuk az indexeket
    const template = existingRows[0];
    const clone = template.cloneNode(true);
    clone.dataset.lineIndex = newIndex;

    // A row-header sorszámot frissítjük
    const noLabel = clone.querySelector(".line-row-no");
    if (noLabel) noLabel.textContent = `${newIndex + 1}.`;

    // Az inputok name attribútumait átírjuk: lines[0][...] → lines[N][...]
    clone.querySelectorAll("input, textarea, select").forEach((el) => {
      if (el.name) {
        el.name = el.name.replace(/^lines\[\d+\]/, `lines[${newIndex}]`);
      }
      // Kiürítjük az értékeket — a default-okat hagyjuk (qty=1, unit=db)
      if (
        el.classList.contains("line-title") ||
        el.classList.contains("line-item-id") ||
        el.classList.contains("line-row-id")
      ) {
        // Edit-formon az új sornak NINCS line.id-ja, így a hidden lines[N][id]
        // mező value-ját mindig üresre kell hozni a clone-on. Különben a backend
        // azt hinné hogy létező sort akarunk update-elni a régi ID-val.
        el.value = "";
      } else if (el.classList.contains("line-qty")) {
        el.value = "1";
      } else if (el.classList.contains("line-unit")) {
        el.value = "db";
      }
      // autofocus csak az első sornál
      el.removeAttribute("autofocus");
    });

    // Suggestions div ürítése
    const suggBox = clone.querySelector(".line-suggestions");
    if (suggBox) suggBox.innerHTML = "";

    linesContainer.appendChild(clone);
    refreshLineNumbers();

    // Fókusz az új sor title-jére
    const newTitle = clone.querySelector(".line-title");
    if (newTitle) newTitle.focus();
  };

  // ===== Sor törlése (×) =====
  window.removeRequestLine = function (btn) {
    const rows = linesContainer.querySelectorAll(".line-row");
    if (rows.length <= 1) {
      // Az utolsó sor nem törölhető
      return;
    }
    const row = btn.closest(".line-row");
    if (row) row.remove();
    refreshLineNumbers();
  };

  // Sorszámok és input name-ek újraszámozása töröléskor
  function refreshLineNumbers() {
    const rows = linesContainer.querySelectorAll(".line-row");
    rows.forEach((row, idx) => {
      row.dataset.lineIndex = idx;
      const noLabel = row.querySelector(".line-row-no");
      if (noLabel) noLabel.textContent = `${idx + 1}.`;
      row.querySelectorAll("input, textarea, select").forEach((el) => {
        if (el.name) el.name = el.name.replace(/^lines\[\d+\]/, `lines[${idx}]`);
      });
      // Az első sor remove-gombja inaktív (egy sornak mindig kell maradnia)
      const removeBtn = row.querySelector(".line-row-remove");
      if (removeBtn) {
        removeBtn.style.display = rows.length > 1 ? "" : "none";
      }
    });
  }

  // Inicializálás: az 1 sor remove-gombját elrejtjük amíg nincs több sor
  refreshLineNumbers();
})();
