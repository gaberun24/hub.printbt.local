// Másolás vágólapra — `navigator.clipboard.writeText` csak HTTPS-en /
// localhost-on érhető el. Belső HTTP-n (`hub.printbt.hu`) a böngésző
// blokkolja, ezért fallback `document.execCommand('copy')` kell.
function copyToClipboard(text, button) {
  const done = () => {
    const original = button.textContent;
    button.textContent = "✓ Másolva";
    button.disabled = true;
    setTimeout(() => {
      button.textContent = original;
      button.disabled = false;
    }, 1500);
  };
  const fail = () => {
    const original = button.textContent;
    button.textContent = "× Hiba — jelöld ki és Ctrl+C";
    setTimeout(() => {
      button.textContent = original;
    }, 2500);
  };

  // 1) Modern API (HTTPS / localhost)
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done, fail));
    return;
  }
  // 2) Fallback execCommand (HTTP)
  fallbackCopy(text, done, fail);
}

function fallbackCopy(text, onDone, onFail) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "-9999px";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {
    const ok = document.execCommand("copy");
    if (ok) onDone();
    else onFail();
  } catch {
    onFail();
  }
  document.body.removeChild(ta);
}
