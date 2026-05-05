// Új-igény értesítés a klienseknek (orderer/admin oldal).
// A `_sidebar.html`-ben van egy `#rendelo-poll` div, ami htmx-szel 60 mp-enként
// hívja a /rendelo/notify/poll endpointot. A szerver HX-Trigger headerben küldi
// a `rendelo:poll` eseményt. Mi itt összehasonlítjuk az előző értékkel és
// szólunk, ha új igény jött (toast + hang).

(function () {
  let lastSeenId = 0;
  let pollCount = 0;

  document.body.addEventListener("rendelo:poll", function (e) {
    pollCount++;
    const detail = e.detail || {};
    const id = parseInt(detail.latest_id || 0, 10);

    // Első poll csak a baseline-t állítja be — sose tűzünk értesítést
    // azonnal page load után (különben minden meglévő nyitott igény
    // megpingelne).
    if (pollCount === 1) {
      lastSeenId = id;
      return;
    }

    if (id > lastSeenId) {
      playDing();
      showToast(detail.latest_title || "Új igény", id);
      lastSeenId = id;
    }
  });

  function playDing() {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      // Két-hangú ding: 660 Hz → 880 Hz (E-A oktáv)
      tone(ctx, 660, 0.0, 0.18);
      tone(ctx, 880, 0.13, 0.3);
      setTimeout(() => ctx.close && ctx.close(), 800);
    } catch {
      /* ignore — sound is nice-to-have */
    }
  }

  function tone(ctx, freq, start, dur) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain).connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.value = freq;
    const t = ctx.currentTime + start;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.18, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, t + dur);
    osc.start(t);
    osc.stop(t + dur);
  }

  function showToast(title, requestId) {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("a");
    toast.className = "toast";
    toast.href = "/rendelo/" + requestId;
    toast.setAttribute("role", "alert");

    const eyebrow = document.createElement("strong");
    eyebrow.textContent = "Új igény";
    toast.appendChild(eyebrow);

    const body = document.createElement("span");
    body.textContent = title;
    toast.appendChild(body);

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));

    setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 300);
    }, 8000);
  }
})();
