// Theme toggle — a mockup-szerű segmented Light/Dark gombokat kezeli.
// `setHubTheme(theme)` átállítja a `data-theme`-et, menti localStorage-be,
// és frissíti az `.active` osztályt a gombokon.

(function () {
  var KEY = "hub-theme";

  function syncButtons(theme) {
    var lightBtn = document.querySelector(".theme-toggle .theme-light");
    var darkBtn  = document.querySelector(".theme-toggle .theme-dark");
    if (!lightBtn || !darkBtn) return;
    lightBtn.classList.toggle("active", theme === "light");
    darkBtn.classList.toggle("active",  theme === "dark");
  }

  window.setHubTheme = function (theme) {
    if (theme !== "light" && theme !== "dark") return;
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(KEY, theme); } catch (e) { /* ignore */ }
    syncButtons(theme);
  };

  // Page load: szinkronizálja az `active` állapotot a HTML-en lévő
  // `data-theme`-mel (amit a base.html FOUC-script már beállított).
  document.addEventListener("DOMContentLoaded", function () {
    var current = document.documentElement.getAttribute("data-theme") || "dark";
    syncButtons(current);
  });
})();
