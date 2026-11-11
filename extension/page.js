// Bouton MediaVior sur les sites de vidéos et de musique.
// - YouTube : dans la barre du lecteur, à côté de la roue des réglages.
// - SoundCloud, Vimeo, Bandcamp, Dailymotion : petit bouton rond en bas à droite de la page.
// - Spotify, Deezer : leurs morceaux sont protégés (DRM). On lit le titre en cours
//   (« Artiste - Titre »), puis MediaVior le cherche sur YouTube, comme la liste de sons.
// Le menu permet de choisir Vidéo ou Audio, la qualité et le format ; les choix sont retenus
// (les mêmes que dans la fenêtre de l'extension). L'envoi passe par background.js, seul à
// pouvoir parler à l'appli sur ce PC.

(() => {
  const msg = (key, sub) => chrome.i18n.getMessage(key, sub) || key;
  const DEFAULTS = { mode: "video", quality: "", videoContainer: "original", audioContainer: "mp3", audioQuality: "320" };
  const QUALITIES = ["", "2160", "1440", "1080", "720", "480"];
  const VIDEO_FORMATS = [["original", "fmtOriginal"], ["mp4", "fmtMp4"], ["mov", "fmtMov"]];
  const AUDIO_FORMATS = [["original", "fmtOriginal"], ["mp3", "fmtMp3"], ["flac", "fmtFlac"], ["wav", "fmtWav"]];
  const BITRATES = ["320", "192", "128"];
  // Flèche de téléchargement, dessinée élément par élément (Firefox refuse le HTML brut)
  function arrow() {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    const attrs = { viewBox: "0 0 36 36", width: "100%", height: "100%", "aria-hidden": "true" };
    for (const [k, v] of Object.entries(attrs)) svg.setAttribute(k, v);
    const p = document.createElementNS(NS, "path");
    const pathAttrs = { fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round",
      "stroke-linejoin": "round", d: "M18 10v11m0 0l-4.5-4.5M18 21l4.5-4.5M11 25h14" };
    for (const [k, v] of Object.entries(pathAttrs)) p.setAttribute(k, v);
    svg.append(p);
    return svg;
  }

  const path = () => location.pathname;
  const meta = (prop) => {
    const el = document.querySelector(`meta[property="${prop}"], meta[name="${prop}"]`);
    return el ? el.content.trim() : "";
  };

  // Morceau en cours d'après le lecteur du site (titre, artiste), sinon la page du morceau
  function nowPlaying() {
    const m = navigator.mediaSession && navigator.mediaSession.metadata;
    if (m && m.title) return m.artist ? `${m.artist} - ${m.title}` : m.title;
    return "";
  }

  const SITES = [
    {
      id: "youtube",
      host: /(^|\.)youtube\.com$/,
      url() {
        const id = new URL(location.href).searchParams.get("v");
        return path() === "/watch" && id ? `https://www.youtube.com/watch?v=${id}` : null;
      },
      // Dans le lecteur même
      bar: () => document.querySelector("#movie_player .ytp-right-controls"),
      box: () => document.querySelector("#movie_player"),
      title: () => {
        const el = document.querySelector("#title h1, h1.ytd-watch-metadata");
        return el ? el.textContent.trim() : null;
      },
    },
    {
      id: "soundcloud",
      host: /(^|\.)soundcloud\.com$/,
      audioOnly: true,
      url() {
        const parts = path().split("/").filter(Boolean);
        const reserved = ["discover", "stream", "feed", "you", "search", "upload", "charts", "messages",
          "notifications", "settings", "pages", "terms-of-use", "people", "signin", "logout"];
        if (parts.length !== 2 || reserved.includes(parts[0])) return null;
        if (["sets", "likes", "tracks", "albums", "reposts", "followers", "following", "popular-tracks"].includes(parts[1])) return null;
        return `https://soundcloud.com/${parts[0]}/${parts[1]}`;
      },
    },
    {
      id: "vimeo",
      host: /(^|\.)vimeo\.com$/,
      url() {
        const m = path().match(/\/(\d{5,})(?:\/|$)/);
        return m ? `https://vimeo.com/${m[1]}` : null;
      },
    },
    {
      id: "bandcamp",
      host: /\.bandcamp\.com$/,
      audioOnly: true,
      url: () => (path().startsWith("/track/") ? location.origin + path() : null),
    },
    {
      id: "dailymotion",
      host: /(^|\.)dailymotion\.com$/,
      url() {
        const m = path().match(/\/video\/([a-z0-9]+)/i);
        return m ? `https://www.dailymotion.com/video/${m[1]}` : null;
      },
    },
    {
      id: "spotify",
      host: /^open\.spotify\.com$/,
      search: true,
      query() {
        const playing = nowPlaying();
        if (playing) return playing;
        if (!path().includes("/track/")) return "";
        // og:description : « Artiste · Album · Song · 2020 »
        const artist = meta("og:description").split(" · ")[0];
        const title = meta("og:title");
        return title ? (artist ? `${artist} - ${title}` : title) : "";
      },
    },
    {
      id: "deezer",
      host: /(^|\.)deezer\.com$/,
      search: true,
      query() {
        const playing = nowPlaying();
        if (playing) return playing;
        return path().includes("/track/") ? meta("og:title") : "";
      },
    },
  ];

  const site = SITES.find((s) => s.host.test(location.hostname));
  if (!site) return;

  let button = null;
  let menu = null;
  let toast = null;
  let toastTimer = null;
  let lastKey = "";

  // Ce que le bouton enverrait maintenant : un lien, ou un titre à chercher sur YouTube
  function target() {
    if (site.search) {
      const q = (site.query() || "").replace(/\s+/g, " ").trim();
      return q ? { query: q } : null;
    }
    const url = site.url();
    return url ? { url } : null;
  }

  function container() {
    return (site.box && site.box()) || document.body;
  }

  function showToast(text, kind = "") {
    if (!toast || !toast.isConnected) {
      toast = document.createElement("div");
      toast.className = "mediavior-toast" + (site.box ? "" : " mediavior-toast--page");
      container().append(toast);
    }
    toast.textContent = text;
    toast.dataset.kind = kind;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.hidden = true), kind === "error" ? 7000 : 3500);
  }

  function closeMenu() {
    if (menu) menu.remove();
    menu = null;
  }

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    node.append(...children);
    return node;
  }

  function select(options, value) {
    const s = el("select");
    for (const [v, label] of options) s.append(new Option(label, v));
    s.value = options.some(([v]) => v === value) ? value : options[0][0];
    return s;
  }

  function field(label, control) {
    return el("label", { class: "mediavior-field" }, el("span", { text: label }), control);
  }

  async function send(choice, tgt) {
    closeMenu();
    showToast(msg(tgt.query ? "ytSearching" : "ytSending"));
    let res;
    try {
      res = await chrome.runtime.sendMessage({
        type: "mediavior-send",
        ...choice,
        url: tgt.url || null,
        query: tgt.query || null,
        title: tgt.query || (site.title ? site.title() : null),
      });
    } catch (e) {
      res = { ok: false, detail: msg("ytReload") }; // extension mise à jour : rafraîchir la page
    }
    if (res && res.ok) showToast(res.found ? msg("ytSentFound", [res.found]) : msg("ytSent"), "ok");
    else if (res && res.offline) showToast(msg("ytOffline"), "error");
    else if (res && res.notFound) showToast(msg("ytNotFound"), "error");
    else showToast(msg("ytFailed", [(res && res.detail) || "?"]), "error");
  }

  async function openMenu() {
    if (menu) return closeMenu();
    const tgt = target();
    if (!tgt) return;
    const s = { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
    let mode = site.audioOnly || site.search ? "audio" : s.mode;

    menu = el("div", { class: "mediavior-menu" + (site.box ? "" : " mediavior-menu--page"), role: "dialog", "aria-label": msg("ytButton") });
    menu.append(el("div", { class: "mediavior-menu__title", text: msg("ytButton") }));

    // Spotify / Deezer : le titre cherché sur YouTube, modifiable
    let queryInput = null;
    if (tgt.query) {
      queryInput = el("input", { type: "text", spellcheck: "false" });
      queryInput.value = tgt.query;
      menu.append(field(msg("ytQuery"), queryInput), el("p", { class: "mediavior-menu__hint", text: msg("ytDrmHint") }));
    }

    // Vidéo / Audio
    const toggle = el("div", { class: "mediavior-toggle", role: "group" });
    const modeBtns = ["video", "audio"].map((m) => {
      const b = el("button", { type: "button", "data-mode": m, text: msg(m === "audio" ? "ytAudio" : "ytVideo") });
      b.addEventListener("click", () => { mode = m; refresh(); chrome.storage.sync.set({ mode: m }); });
      toggle.append(b);
      return b;
    });
    if (!site.audioOnly && !site.search) menu.append(toggle);

    const quality = select(QUALITIES.map((q) => [q, q ? `${q}p max` : msg("ytBest")]), s.quality);
    const videoFmt = select(VIDEO_FORMATS.map(([v, k]) => [v, msg(k)]), s.videoContainer);
    const audioFmt = select(AUDIO_FORMATS.map(([v, k]) => [v, msg(k)]), s.audioContainer);
    const bitrate = select(BITRATES.map((b) => [b, `${b} kb/s`]), s.audioQuality);
    const videoRows = el("div", { class: "mediavior-grid" }, field(msg("ytQuality"), quality), field(msg("ytFormat"), videoFmt));
    const bitrateField = field(msg("ytBitrate"), bitrate);
    const audioRows = el("div", { class: "mediavior-grid" }, field(msg("ytFormat"), audioFmt), bitrateField);
    menu.append(videoRows, audioRows);

    const go = el("button", { type: "button", class: "mediavior-go", text: msg("ytDownload") });
    menu.append(go);
    if (!tgt.query) {
      const more = el("button", { type: "button", class: "mediavior-more", text: msg("ytMore") });
      more.addEventListener("click", () => {
        closeMenu();
        chrome.runtime.sendMessage({ type: "mediavior-popup", url: tgt.url });
      });
      menu.append(more);
    }

    function refresh() {
      modeBtns.forEach((b) => b.classList.toggle("is-active", b.dataset.mode === mode));
      videoRows.hidden = mode !== "video";
      audioRows.hidden = mode !== "audio";
      bitrateField.hidden = audioFmt.value !== "mp3";
    }
    const save = () => chrome.storage.sync.set({
      quality: quality.value, videoContainer: videoFmt.value,
      audioContainer: audioFmt.value, audioQuality: bitrate.value,
    });
    [quality, videoFmt, audioFmt, bitrate].forEach((c) => c.addEventListener("change", () => { save(); refresh(); }));
    go.addEventListener("click", () => {
      save();
      const audio = mode === "audio";
      const choice = {
        mode,
        quality: audio ? null : quality.value || null,
        container: audio ? audioFmt.value : videoFmt.value,
        audio_quality: audio && audioFmt.value === "mp3" ? bitrate.value : null,
      };
      const t = queryInput ? { query: queryInput.value.trim() } : tgt;
      if (t.query === "") return queryInput.focus();
      send(choice, t);
    });
    refresh();

    // Les touches tapées dans le menu ne doivent pas piloter le lecteur (espace, flèches…)
    for (const type of ["keydown", "keyup", "keypress"]) {
      menu.addEventListener(type, (e) => {
        if (e.key === "Escape") closeMenu();
        e.stopPropagation();
      });
    }
    menu.addEventListener("click", (e) => e.stopPropagation());
    container().append(menu);
    if (queryInput) queryInput.focus();
  }

  function makeButton() {
    const inBar = Boolean(site.bar);
    const btn = el("button", {
      type: "button",
      class: inBar ? "ytp-button mediavior-btn" : "mediavior-fab",
      title: msg("ytButton"),
      "aria-label": msg("ytButton"),
    });
    btn.append(arrow());
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openMenu();
    });
    return btn;
  }

  // Ajoute, garde ou retire le bouton selon la page (ces sites changent de page sans recharger)
  function update() {
    const tgt = target();
    const key = tgt ? tgt.url || tgt.query : "";
    if (key !== lastKey) closeMenu();
    lastKey = key;
    if (!tgt) {
      if (button) button.remove();
      return;
    }
    if (site.bar) {
      const bar = site.bar();
      if (!bar) return;
      if (!button || !bar.contains(button)) {
        button = button || makeButton();
        bar.prepend(button);
      }
    } else if (!button || !button.isConnected) {
      button = button || makeButton();
      document.body.append(button);
    }
  }

  document.addEventListener("click", closeMenu);
  document.addEventListener("yt-navigate-finish", update);
  let pending = false;
  new MutationObserver(() => {
    if (pending) return;
    pending = true;
    setTimeout(() => { pending = false; update(); }, 300);
  }).observe(document.documentElement, { childList: true, subtree: true });
  setInterval(update, 1500); // titre en cours qui change (Spotify, Deezer)
  update();
})();
