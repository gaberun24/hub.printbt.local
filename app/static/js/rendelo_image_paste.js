// Új igény / szerkesztés űrlapon: vágólapról képet beilleszt (Ctrl+V),
// előnézet, és normál fájl-választás után is mutatja az előnézetet.
(function () {
  const fileInput = document.getElementById("rendelo-image");
  if (!fileInput) return;

  const previewWrap = document.getElementById("rendelo-image-preview");
  const previewImg = previewWrap ? previewWrap.querySelector("img") : null;
  const previewName = previewWrap ? previewWrap.querySelector(".preview-name") : null;

  function showPreview(file) {
    if (!previewWrap || !previewImg) return;
    const url = URL.createObjectURL(file);
    previewImg.src = url;
    if (previewName) {
      const sizeKb = Math.round(file.size / 1024);
      previewName.textContent = `${file.name} • ${sizeKb} KB`;
    }
    previewWrap.classList.remove("hidden");
  }

  function setFile(file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
    showPreview(file);
  }

  // Vágólapról beillesztés (Ctrl+V) — bárhol az oldalon
  document.addEventListener("paste", function (e) {
    const items = Array.from(e.clipboardData?.items || []);
    const imageItem = items.find((it) => it.type && it.type.startsWith("image/"));
    if (!imageItem) return;
    const file = imageItem.getAsFile();
    if (!file) return;
    e.preventDefault();
    const ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
    const named = new File([file], file.name || `vagolap-${Date.now()}.${ext}`, {
      type: file.type,
    });
    setFile(named);
  });

  fileInput.addEventListener("change", function () {
    if (fileInput.files.length === 0) {
      previewWrap?.classList.add("hidden");
      return;
    }
    showPreview(fileInput.files[0]);
  });
})();
