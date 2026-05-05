// Quick-date chip-ek az archív-szűrő-sávhoz + nyomtatás trigger.

(function () {
  const fromInput = document.getElementById("af-from");
  const toInput = document.getElementById("af-to");

  function fmt(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function range(kind) {
    const today = new Date();
    let from, to;
    switch (kind) {
      case "this-month":
        from = new Date(today.getFullYear(), today.getMonth(), 1);
        to = today;
        break;
      case "last-month": {
        const m = today.getMonth();
        const y = today.getFullYear();
        from = new Date(y, m - 1, 1);
        to = new Date(y, m, 0);
        break;
      }
      case "last-30":
        from = new Date(today);
        from.setDate(from.getDate() - 30);
        to = today;
        break;
      case "this-year":
        from = new Date(today.getFullYear(), 0, 1);
        to = today;
        break;
      case "last-year":
        from = new Date(today.getFullYear() - 1, 0, 1);
        to = new Date(today.getFullYear() - 1, 11, 31);
        break;
      default:
        return null;
    }
    return { from: fmt(from), to: fmt(to) };
  }

  if (fromInput && toInput) {
    document.querySelectorAll(".quick-date-chip").forEach((btn) => {
      btn.addEventListener("click", function () {
        const r = range(btn.dataset.quickDate);
        if (!r) return;
        fromInput.value = r.from;
        toInput.value = r.to;
        [fromInput, toInput].forEach((el) => {
          el.classList.add("flash-bg");
          setTimeout(() => el.classList.remove("flash-bg"), 600);
        });
      });
    });
  }

  // Hónap-csoport count-ok kitöltése
  document.querySelectorAll(".archive-month-count").forEach((el) => {
    const month = el.dataset.month;
    const list = document.querySelector(`.req-list[data-archive-month="${month}"]`);
    if (list) {
      el.textContent = ` (${list.children.length})`;
    }
  });

  // Nyomtatás-mód
  document.querySelectorAll(".archive-print-btn").forEach((btn) => {
    btn.addEventListener("click", function () {
      document.body.classList.add("print-archive");
      setTimeout(() => {
        window.print();
        setTimeout(() => document.body.classList.remove("print-archive"), 100);
      }, 50);
    });
  });
})();
