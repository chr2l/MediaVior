// Bouton MediaVior dans la barre du lecteur YouTube, à côté de la roue des réglages.
// Un clic ouvre un petit menu : Vidéo ou Audio (avec les formats choisis la dernière fois
// dans la fenêtre de l'extension), ou « Plus de choix… » pour ouvrir cette fenêtre.
// L'envoi passe par background.js, qui seul peut parler à l'appli sur ce PC.

(() => {
  const msg = (key, sub) => chrome.i18n.getMessage(key, sub) || key;
  const DEFAULTS = { mode: "video", quality: "", videoContainer: "original", audioContainer: "mp3", audioQuality: "320" };
  const ICON =
    '<svg viewBox="0 0 36 36" width="100%" height="100%" aria-hidden="true">' +
    '<path fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
    'd="M18 10v11m0 0l-4.5-4.5M18 21l4.5-4.5M11 25h14"/></svg>';

  let menu = null;
  let toast = null;
  let toastTimer = null;

  // Lien propre de la vidéo en cours, sans la playlist ni le minutage
  function videoUrl() {
    const id = new URL(location.href).searchParams.get("v");
    return id ? `https://www.youtube.com/watch?v=${id}` : null;
  }

  function videoTitle() {
    const el = document.querySelector("#title h1, h1.ytd-watch-metadata");
    return el ? el.textContent.trim() : null;
  }

  function player() {
    return document.querySelector("#movie_player");
  }

  function showToast(text, kind = "") {
    const box = player();
    if (!box) return;
    if (!toast || !toast.isConnected) {
      toast = document.createElement("div");
      toast.className = "mediavior-toast";
      box.append(toast);
    }
    toast.textContent = text;
    toast.dataset.kind = kind;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.hidden = true), kind === "error" ? 6000 : 3000);
  }

  function closeMenu() {
    if (menu) menu.remove();
    menu = null;
  }

  function describe(s, mode) {
    if (mode === "audio") {
      const c = s.audioContainer;
      if (c === "original") return msg("ytBest");
      return c === "mp3" ? `MP3 ${s.audioQuality} kb/s` : c.toUpperCase();
    }
    const parts = [];
    if (s.videoContainer !== "original") parts.push(s.videoContainer.toUpperCase());
    parts.push(s.quality ? `${s.quality}p max` : msg("ytBest"));
    return parts.join(" · ");
  }

  async function send(mode) {
    closeMenu();
    const url = videoUrl();
    if (!url) return;
    showToast(msg("ytSending"));
    let res;
    try {
      res = await chrome.runtime.sendMessage({ type: "mediavior-send", url, mode, title: videoTitle() });
    } catch (e) {
      res = { ok: false, detail: e.message }; // extension rechargée : la page doit être rafraîchie
    }
    if (res && res.ok) showToast(msg("ytSent"), "ok");
    else if (res && res.offline) showToast(msg("ytOffline"), "error");
    else showToast(msg("ytFailed", [(res && res.detail) || "?"]), "error");
  }

  async function openMenu(button) {
    if (menu) return closeMenu();
    const s = { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
    menu = document.createElement("div");
    menu.className = "mediavior-menu";
    menu.setAttribute("role", "menu");
    const item = (label, sub, onClick) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "menuitem");
      b.innerHTML = "<strong></strong><small></small>";
      b.querySelector("strong").textContent = label;
      b.querySelector("small").textContent = sub;
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        onClick();
      });
      menu.append(b);
    };
    const title = document.createElement("div");
    title.className = "mediavior-menu__title";
    title.textContent = msg("ytButton");
    menu.append(title);
    // Le choix utilisé la dernière fois en premier
    const modes = s.mode === "audio" ? ["audio", "video"] : ["video", "audio"];
    for (const m of modes) item(msg(m === "audio" ? "ytAudio" : "ytVideo"), describe(s, m), () => send(m));
    item(msg("ytMore"), "", () => {
      closeMenu();
      chrome.runtime.sendMessage({ type: "mediavior-popup", url: videoUrl() });
    });
    menu.addEventListener("click", (e) => e.stopPropagation());
    player().append(menu);
  }

  function addButton() {
    if (!videoUrl()) return;
    const bar = document.querySelector("#movie_player .ytp-right-controls");
    if (!bar || bar.querySelector(".mediavior-btn")) return;
    const btn = document.createElement("button");
    btn.className = "ytp-button mediavior-btn";
    btn.title = msg("ytButton");
    btn.setAttribute("aria-label", msg("ytButton"));
    btn.innerHTML = ICON;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openMenu(btn);
    });
    bar.prepend(btn);
  }

  // YouTube change de vidéo sans recharger la page : on revérifie à chaque navigation,
  // et quand le lecteur apparaît ou se reconstruit.
  document.addEventListener("yt-navigate-finish", () => { closeMenu(); addButton(); });
  document.addEventListener("click", closeMenu);
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeMenu());
  let pending = false;
  const later = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; addButton(); });
  };
  new MutationObserver(later).observe(document.documentElement, { childList: true, subtree: true });
  addButton();
})();
