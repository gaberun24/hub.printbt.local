// Theme toggle: kapcsolja a `data-theme` attribútumot a <html>-en, és menti
// a választást localStorage-ba. A FOUC-prevention inline script (base.html
// <head>) gondoskodik arról, hogy oldal-betöltéskor már a helyes téma
// legyen aktív, mire ide jutunk.

(function () {
  var KEY = "hub-theme";
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;

  btn.addEventListener("click", function () {
    var current = document.documentElement.getAttribute("data-theme");
    var next = current === "dark" ? "light" : "dark";
    if (next === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    try { localStorage.setItem(KEY, next); } catch (e) { /* ignore */ }
  });
})();
