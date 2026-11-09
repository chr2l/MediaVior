const ACTIVE = new Set(["queued", "downloading", "converting", "processing"]);

const urlInput = document.getElementById("url");
const analyzeBtn = document.getElementById("analyzeBtn");
const errorEl = document.getElementById("error");
const resultEl = document.getElementById("result");
const downloadBtn = document.getElementById("downloadBtn");
const batchEl = document.getElementById("batch");
const batchInput = document.getElementById("batchInput");
const batchCount = document.getElementById("batchCount");
const batchError = document.getElementById("batchError");
const batchBtn = document.getElementById("batchBtn");
const queueList = document.getElementById("queueList");
const queueEmpty = document.getElementById("queueEmpty");
const libraryList = document.getElementById("libraryList");
const libraryFilter = document.getElementById("libraryFilter");
const libraryEmpty = document.getElementById("libraryEmpty");
const libraryStats = document.getElementById("libraryStats");

function showError(message) {
  errorEl.textContent = message;
  errorEl.classList.remove("hidden");
}

function clearError() {
  errorEl.classList.add("hidden");
}

// ---------------------------------------------------------------------------
// Trois façons de télécharger : un lien, plusieurs liens (zip), liste de titres
// ---------------------------------------------------------------------------

const WAYS = ["lien", "liens", "titres"];
let currentWay = "lien";

function setWay(name, { focus = false } = {}) {
  if (!WAYS.includes(name)) name = WAYS[0];
  currentWay = name;
  document.querySelectorAll(".ways__btn").forEach((btn) => {
    const active = btn.dataset.way === name;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".way").forEach((el) => el.classList.toggle("hidden", el.dataset.way !== name));
  try {
    localStorage.setItem("mediavior-way", name);
  } catch (e) {
    /* navigation privée : tant pis */
  }
  if (focus) {
    const field = { lien: urlInput, liens: batchInput, titres: document.getElementById("sonsInput") }[name];
    if (field) field.focus();
  }
}

document.querySelectorAll(".ways__btn").forEach((btn) =>
  btn.addEventListener("click", () => setWay(btn.dataset.way, { focus: true })));

try {
  setWay(localStorage.getItem("mediavior-way") || "lien");
} catch (e) {
  setWay("lien");
}

// ---------------------------------------------------------------------------
// Options Vidéo / Audio (même bloc pour un lien seul et pour plusieurs liens)
// ---------------------------------------------------------------------------

// Explications courtes affichées sous le choix du format
const VIDEO_HINTS = {
  original: t("Meilleure qualité possible : la vidéo est gardée telle que le site la fournit, sans conversion "
    + "(souvent WebM en VP9 ou AV1). Parfait sur ordinateur ou avec VLC, mais pas toujours lu par un iPhone ou Photos Windows."),
  mp4: t("Lisible partout : téléphones, TV, logiciels de montage (H.264 + AAC). Si le site ne fournit pas ce format "
    + "à la qualité choisie (souvent au-delà du 1080p), le serveur convertit la vidéo, ce qui peut être long."),
  mov: t("Comme le MP4, mais dans le format préféré des logiciels Apple (Final Cut, iMovie)."),
};
const AUDIO_HINTS = {
  original: t("Meilleure qualité possible : la piste est gardée telle que le site la fournit, sans réencodage "
    + "(souvent Opus ou M4A). Lue par la plupart des appareils récents."),
  mp3: t("Le format le plus compatible, partout. Réencodé depuis la source : à 320 kb/s, la différence est inaudible."),
  flac: t("Sans perte, mais pas meilleur que l'original : les sites diffusent déjà en audio compressé. "
    + "Utile pour l'archivage ou les logiciels qui demandent du FLAC."),
  wav: t("Non compressé, très lourd (≈ 10 Mo par minute). Pour les logiciels de montage audio."),
};

function setupOptions(root) {
  root.append(document.getElementById("optionsTpl").content.cloneNode(true));
  const $ = (selector) => root.querySelector(selector);
  const quality = $(".js-quality");
  const container = $(".js-container");
  const audioContainer = $(".js-audio-container");
  const audioQuality = $(".js-audio-quality");
  const videoHint = $(".js-video-hint");
  const audioHint = $(".js-audio-hint");
  let mode = "video";
  let duration = 0;
  let audioSize = 0;

  root.querySelectorAll(".mode-toggle__btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      mode = btn.dataset.mode;
      root.querySelectorAll(".mode-toggle__btn").forEach((b) => b.classList.toggle("is-active", b === btn));
      root.querySelectorAll(".js-video").forEach((el) => el.classList.toggle("hidden", mode !== "video"));
      root.querySelectorAll(".js-audio").forEach((el) => el.classList.toggle("hidden", mode !== "audio"));
    });
  });

  // Taille estimée de chaque format audio à partir de la durée (et de la vraie piste pour l'original)
  function refreshAudio() {
    audioContainer.querySelectorAll("option").forEach((opt) => {
      let size = 0;
      if (opt.value === "original") size = audioSize || (duration ? (160000 / 8) * duration : 0);
      else if (opt.value === "mp3") size = duration ? (Number(audioQuality.value) * 1000 / 8) * duration : 0;
      else size = duration ? (Number(opt.dataset.kbps) * 1000 / 8) * duration : 0;
      opt.textContent = size ? `${opt.dataset.label} · ≈ ${formatBytes(size)}` : opt.dataset.label;
    });
    // Le débit ne s'applique qu'au MP3
    audioQuality.disabled = audioContainer.value !== "mp3";
    audioHint.textContent = AUDIO_HINTS[audioContainer.value];
  }

  function refreshVideo() {
    videoHint.textContent = VIDEO_HINTS[container.value];
  }

  audioContainer.addEventListener("change", refreshAudio);
  audioQuality.addEventListener("change", refreshAudio);
  container.addEventListener("change", refreshVideo);
  refreshAudio();
  refreshVideo();

  return {
    quality,
    setMedia(newDuration, newAudioSize) {
      duration = newDuration || 0;
      audioSize = newAudioSize || 0;
      refreshAudio();
    },
    values() {
      if (mode === "video") {
        return { mode, quality: quality.value || null, container: container.value, audio_quality: null };
      }
      return {
        mode,
        quality: null,
        container: audioContainer.value,
        audio_quality: audioContainer.value === "mp3" ? audioQuality.value : null,
      };
    },
  };
}

const singleOptions = setupOptions(resultEl.querySelector(".js-options"));
const batchOptions = setupOptions(batchEl.querySelector(".js-options"));
// Plusieurs liens : la qualité choisie est un plafond (chaque média prend le meilleur en dessous)
batchOptions.quality.closest(".field").querySelector(".field-label").textContent = t("Qualité maximale");

[
  ["", t("Meilleure disponible")],
  ["2160", "4K (2160p) max"],
  ["1440", "1440p max"],
  ["1080", "1080p max"],
  ["720", "720p max"],
  ["480", "480p max"],
].forEach(([value, label]) => batchOptions.quality.append(h("option", { value }, label)));

// ---------------------------------------------------------------------------
// Saisie : un lien → analyse, plusieurs liens → file d'attente
// ---------------------------------------------------------------------------

function extractUrls(text) {
  const tokens = text
    .split(/\s+/)
    .map((t) => t.replace(/^[(<["']+/, "").replace(/[)\]>.,;!?"']+$/, ""));
  const urls = tokens.filter(
    (t) => /^https?:\/\/\S+$/i.test(t) || /^([\w-]+\.)+[a-z]{2,}(\/\S*)?$/i.test(t)
  );
  return [...new Set(urls)];
}

function autoGrow() {
  urlInput.style.height = "auto";
  urlInput.style.height = `${Math.min(urlInput.scrollHeight + 2, 180)}px`; // + bordures
}

function handleInput() {
  const text = urlInput.value.trim();
  if (!text) return;
  clearError();
  const urls = extractUrls(text);
  if (urls.length > 1) {
    // Plusieurs liens collés dans la case « Un lien » : on passe tout seul à « Plusieurs liens »
    batchInput.value = urls.join("\n");
    urlInput.value = "";
    autoGrow();
    resultEl.classList.add("hidden");
    setWay("liens");
    renderBatch();
    return;
  }
  analyze(urls[0] || text);
}

urlInput.addEventListener("input", autoGrow);
urlInput.addEventListener("paste", () => setTimeout(() => { autoGrow(); handleInput(); }, 0));
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleInput();
  }
});
analyzeBtn.addEventListener("click", handleInput);

// ---------------------------------------------------------------------------
// Un seul lien
// ---------------------------------------------------------------------------

let analyzing = false;
let currentAnalysis = null;

async function analyze(url) {
  if (analyzing) return;
  analyzing = true;
  analyzeBtn.textContent = t("Analyse…");
  analyzeBtn.classList.add("is-loading");
  analyzeBtn.disabled = true;
  resultEl.classList.add("hidden");

  try {
    renderResult(await api("/api/analyze", { method: "POST", body: { url } }));
  } catch (e) {
    showError(e.message);
  } finally {
    analyzing = false;
    analyzeBtn.textContent = t("Analyser");
    analyzeBtn.classList.remove("is-loading");
    analyzeBtn.disabled = false;
  }
}

function renderResult(data) {
  currentAnalysis = data;
  resultEl.classList.remove("hidden");
  document.getElementById("title").textContent = data.title;
  document.getElementById("source").textContent = data.source || "";
  document.getElementById("duration").textContent = formatDuration(data.duration);

  const thumb = document.getElementById("thumb");
  thumb.classList.toggle("hidden", !data.thumbnail);
  if (data.thumbnail) thumb.src = data.thumbnail;

  const select = singleOptions.quality;
  select.replaceChildren();
  if (data.video_formats && data.video_formats.length) {
    data.video_formats.forEach(({ height, size }) => {
      let label = `${height}p`;
      if (height >= 2160) label += " (4K)";
      else if (height >= 1440) label += " (2K)";
      if (size) label += ` · ≈ ${formatBytes(size)}`;
      select.append(h("option", { value: height }, label));
    });
  } else {
    select.append(h("option", { value: "" }, t("Meilleure disponible")));
  }
  singleOptions.setMedia(data.duration, data.audio_size);

  downloadBtn.disabled = false;
  downloadBtn.textContent = t("Mettre au coffre");
  resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

downloadBtn.addEventListener("click", async () => {
  if (!currentAnalysis) return;
  clearError();
  downloadBtn.disabled = true;
  try {
    await api("/api/download", {
      method: "POST",
      body: {
        url: currentAnalysis.url,
        title: currentAnalysis.title,
        thumbnail: currentAnalysis.thumbnail,
        ...singleOptions.values(),
      },
    });
    downloadBtn.textContent = t("En route vers le coffre ✓");
    urlInput.value = "";
    autoGrow();
    startPolling();
    revealQueue();
    setTimeout(() => {
      downloadBtn.textContent = t("Mettre au coffre");
      downloadBtn.disabled = false;
    }, 1500);
  } catch (e) {
    showError(e.message);
    downloadBtn.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Plusieurs liens : un même format, tout dans un seul zip
// ---------------------------------------------------------------------------

const shortUrl = (u) => u.replace(/^https?:\/\/(www\.)?/i, "");

function batchUrls() {
  return extractUrls(batchInput.value);
}

function renderBatch() {
  const n = batchUrls().length;
  batchCount.textContent = n
    ? t(n > 1 ? "{n} liens trouvés." : "{n} lien trouvé.", { n })
    : t("Jusqu'à 100 liens.");
  batchBtn.disabled = n < 1 || n > 100;
  batchBtn.textContent = n > 1 ? t("Mettre les {n} liens au coffre (zip)", { n }) : t("Mettre au coffre en zip");
}

batchInput.addEventListener("input", renderBatch);

batchBtn.addEventListener("click", async () => {
  const urls = batchUrls();
  if (!urls.length) return;
  batchError.classList.add("hidden");
  batchBtn.disabled = true;
  batchBtn.classList.add("is-loading");
  try {
    await api("/api/links", { method: "POST", body: { urls, ...batchOptions.values() } });
    batchInput.value = "";
    startPolling();
    revealQueue();
    showToast(t(urls.length > 1 ? "{n} liens en route : le zip arrivera dans le coffre." : "{n} lien en route : le zip arrivera dans le coffre.", { n: urls.length }));
  } catch (e) {
    batchError.textContent = e.message;
    batchError.classList.remove("hidden");
  } finally {
    batchBtn.classList.remove("is-loading");
    renderBatch();
  }
});

renderBatch();

// ---------------------------------------------------------------------------
// File d'attente
// ---------------------------------------------------------------------------

const queueNodes = new Map();
const seenDone = new Set();
let pollTimer = null;
let pollInFlight = false;
let pollKick = false;

function startPolling() {
  if (pollInFlight) {
    pollKick = true; // une requête part déjà : on relancera juste après
    return;
  }
  clearTimeout(pollTimer);
  pollJobs();
}

async function pollJobs() {
  pollInFlight = true;
  pollKick = false;
  let next = null;
  try {
    const jobs = await api("/api/jobs");
    renderQueue(jobs);
    sonsOnJobs(jobs);
    const newlyDone = jobs.filter((j) => j.status === "done" && !seenDone.has(j.id));
    newlyDone.forEach((j) => seenDone.add(j.id));
    if (newlyDone.length) {
      loadLibrary(newlyDone.map((j) => j.id));
      announceNewFiles(newlyDone);
    }
    if (jobs.some((j) => ACTIVE.has(j.status))) next = 1000;
    // Rien en cours : on regarde quand même de temps en temps, pour voir les
    // téléchargements lancés ailleurs (téléphone, autre onglet)
    else if (document.visibilityState === "visible") next = 4000;
  } catch (e) {
    next = 3000; // serveur momentanément injoignable : on réessaie
  }
  pollInFlight = false;
  if (pollKick) next = 0;
  if (next !== null) pollTimer = setTimeout(pollJobs, next);
}

function renderQueue(jobs) {
  const visible = jobs.filter((j) => j.status !== "done");
  queueEmpty.classList.toggle("hidden", visible.length > 0);
  setBadge("encours", visible.filter((j) => ACTIVE.has(j.status)).length);

  const ids = new Set(visible.map((j) => j.id));
  for (const [id, node] of queueNodes) {
    if (!ids.has(id)) {
      node.root.remove();
      queueNodes.delete(id);
    }
  }

  visible.forEach((job, index) => {
    let node = queueNodes.get(job.id);
    if (!node) {
      node = createJobNode();
      queueNodes.set(job.id, node);
    }
    updateJobNode(node, job);
    if (queueList.children[index] !== node.root) {
      queueList.insertBefore(node.root, queueList.children[index] || null);
    }
  });
}

function createJobNode() {
  const node = {
    thumb: h("div", { class: "job__thumb" }),
    title: h("div", { class: "job__title" }),
    fill: h("div", { class: "progress__fill" }),
    meta: h("div", { class: "job__meta" }),
    action: h("button", { type: "button", class: "btn-link" }),
    thumbSrc: undefined,
  };
  node.progress = h("div", { class: "progress progress--slim" },
    h("div", { class: "progress__track" }, node.fill));
  node.root = h("li", { class: "job" },
    node.thumb,
    h("div", { class: "job__body" }, node.title, node.progress, node.meta),
    node.action);
  node.action.addEventListener("click", () => onJobAction(node));
  return node;
}

function jobStatusText(job) {
  const pct = `${Math.round(job.progress || 0)} %`;
  switch (job.status) {
    case "queued":
      return job.position === 1 ? t("En attente · prochain") : t("En attente · {n}ᵉ dans la file", { n: job.position });
    case "downloading": {
      const parts = [pct];
      if (job.step) parts.push(t(job.step));
      if (job.speed) parts.push(`${formatBytes(job.speed)}/s`);
      if (job.eta) parts.push(t("{time} restantes", { time: formatDuration(job.eta) }));
      return parts.join(" · ");
    }
    case "converting":
      if (job.kind === "sons" || job.kind === "links") return t("Création du zip…");
      return job.encoding ? t("Conversion… {pct}", { pct }) : t("Conversion…");
    case "processing":
      return t("Montage… {pct}", { pct });
    case "cancelled":
      return t("Annulé");
    case "error":
      return t(job.error || "Erreur");
    default:
      return "";
  }
}

function updateJobNode(node, job) {
  node.job = job;
  node.title.textContent = t(job.title);
  node.title.title = t(job.title);

  if (node.thumbSrc !== (job.thumbnail || null)) {
    node.thumbSrc = job.thumbnail || null;
    node.thumb.replaceChildren(
      job.thumbnail
        ? h("img", { src: job.thumbnail, alt: "", referrerpolicy: "no-referrer" })
        : icon({ edit: "scissors", sons: "archive", links: "archive" }[job.kind] || "download")
    );
  }

  const active = ACTIVE.has(job.status);
  const busy = job.status === "queued" || (job.status === "converting" && !job.encoding);
  node.progress.classList.toggle("hidden", !active);
  node.progress.classList.toggle("is-busy", busy);
  node.fill.style.width = busy ? "100%" : `${job.progress || 0}%`;

  node.meta.textContent = node.cancelling && active ? t("Annulation…") : jobStatusText(job);
  node.meta.classList.toggle("is-error", job.status === "error");
  node.root.classList.toggle("is-muted", job.status === "cancelled");

  node.action.textContent = active ? t("Annuler") : t("Retirer");
  node.action.disabled = Boolean(node.cancelling && active);
}

async function onJobAction(node) {
  const job = node.job;
  try {
    if (ACTIVE.has(job.status)) {
      node.cancelling = true;
      updateJobNode(node, job);
      await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      startPolling();
    } else {
      await api(`/api/jobs/${job.id}`, { method: "DELETE" });
      node.root.remove();
      queueNodes.delete(job.id);
      queueEmpty.classList.toggle("hidden", queueNodes.size > 0);
    }
  } catch (e) {
    showError(e.message);
  }
}

// ---------------------------------------------------------------------------
// Bibliothèque
// ---------------------------------------------------------------------------

let libraryItems = [];

async function loadLibrary(highlightIds = []) {
  try {
    libraryItems = await api("/api/library");
  } catch (e) {
    return;
  }
  renderLibrary(highlightIds);
}

function renderLibrary(highlightIds = []) {
  const filter = libraryFilter.value.trim().toLowerCase();
  const items = filter
    ? libraryItems.filter((i) => i.title.toLowerCase().includes(filter))
    : libraryItems;

  const total = libraryItems.reduce((sum, i) => sum + i.size, 0);
  const n = libraryItems.length;
  libraryStats.textContent = n ? t(n > 1 ? "{n} médias · {size}" : "{n} média · {size}", { n, size: formatBytes(total) }) : "";
  renderStats();
  libraryFilter.classList.toggle("hidden", n < 6 && !filter);

  libraryEmpty.classList.toggle("hidden", items.length > 0);
  libraryEmpty.textContent = n
    ? t("Aucun titre ne correspond à ce filtre.")
    : t("Ton coffre est vide pour l’instant. Ce que tu mets au coffre apparaîtra ici.");

  // Rangés par jour, du plus récent au plus ancien
  const rows = [];
  let lastDay = null;
  items.forEach((item) => {
    const day = dayLabel(item.created);
    if (day !== lastDay) {
      rows.push(h("li", { class: "item-day", "aria-hidden": "true" }, day));
      lastDay = day;
    }
    rows.push(libraryRow(item, highlightIds.includes(item.id)));
  });
  libraryList.replaceChildren(...rows);
  renderSelection();
}

// ---------------------------------------------------------------------------
// En-tête « MediaVior » : petit mot et pastilles de stats
// ---------------------------------------------------------------------------

const statsEl = document.getElementById("stats");
const heroHello = document.getElementById("heroHello");

function sinceText(timestamp) {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - timestamp) / 60));
  if (minutes < 1) return t("à l'instant");
  if (minutes < 60) return t(minutes > 1 ? "il y a {n} minutes" : "il y a {n} minute", { n: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t(hours > 1 ? "il y a {n} heures" : "il y a {n} heure", { n: hours });
  const days = Math.round(hours / 24);
  return t(days > 1 ? "il y a {n} jours" : "il y a {n} jour", { n: days });
}

function listenText(seconds) {
  const hours = Math.floor(seconds / 3600);
  if (hours >= 1) return t("{n} h à écouter", { n: hours });
  return t("{n} min à écouter", { n: Math.max(1, Math.round(seconds / 60)) });
}

function renderStats() {
  const items = libraryItems;
  if (!items.length) {
    heroHello.textContent = t("Colle un lien pour mettre ton premier média à l'abri.");
    statsEl.replaceChildren();
    return;
  }
  heroHello.textContent = t("Dernier média rangé {since}.", { since: sinceText(items[0].created) });
  const count = (mode) => items.filter((i) => i.mode === mode).length;
  const size = items.reduce((sum, i) => sum + i.size, 0);
  const seconds = items.reduce((sum, i) => sum + (i.duration || 0), 0);
  const n = items.length;
  const chip = (kind, iconName, strong, text) =>
    h("div", { class: `stat tint tint--${kind}` }, icon(iconName), h("b", {}, strong), h("span", { class: "stat__label" }, text));
  const chips = [chip("neutral", "lock", n, t(n > 1 ? "médias à l'abri" : "média à l'abri"))];
  const sons = count("audio");
  const videos = count("video");
  const zips = count("archive");
  if (sons) chips.push(chip("son", "music", sons, t(sons > 1 ? "sons" : "son")));
  if (videos) chips.push(chip("video", "film", videos, t(videos > 1 ? "vidéos" : "vidéo")));
  if (zips) chips.push(chip("zip", "box", zips, `zip${zips > 1 ? "s" : ""}`));
  chips.push(chip("neutral", "disk", formatBytes(size), seconds ? listenText(seconds) : t("sur le disque")));
  statsEl.replaceChildren(...chips);
}

function dayLabel(timestamp) {
  const date = new Date(timestamp * 1000);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return t("Aujourd'hui");
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return t("Hier");
  const label = date.toLocaleDateString(LOCALE, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function libraryRow(item, isNew) {
  const fallback = () => icon({ audio: "music", archive: "box" }[item.mode] || "film");
  const kind = { audio: "son", archive: "zip" }[item.mode] || "video";
  const thumb = item.thumbnail
    ? h("img", {
        src: item.thumbnail,
        alt: "",
        loading: "lazy",
        referrerpolicy: "no-referrer",
        onerror: (e) => e.target.replaceWith(fallback()),
      })
    : fallback();

  // Titre d'un zip (« Plusieurs liens · 3 fichiers ») : écrit par le serveur, traduit ici
  const shownTitle = item.mode === "archive" ? t(item.title) : item.title;

  // Sous le titre : le format choisi et la durée (ou le nombre de fichiers d'un zip)
  const meta = [
    item.ext.toUpperCase(),
    item.duration ? formatDuration(item.duration) : null,
    item.mode === "archive" && item.count ? t(item.count > 1 ? "{n} fichiers" : "{n} fichier", { n: item.count }) : null,
    formatBytes(item.size),
  ].filter(Boolean).join(" · ");

  if (selecting) {
    const checked = selected.has(item.id);
    return h("li", {
      class: `item item--selectable${checked ? " is-selected" : ""}`,
      "data-id": item.id,
      role: "checkbox",
      "aria-checked": String(checked),
      tabindex: "0",
      onclick: () => toggleSelected(item.id),
      onkeydown: (e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          toggleSelected(item.id);
        }
      },
    },
      h("span", { class: "item__check", "aria-hidden": "true" }, icon("check")),
      h("div", { class: `item__thumb tint tint--${kind}` }, thumb),
      h("div", { class: "item__body" },
        h("div", { class: "item__title", title: shownTitle }, shownTitle),
        h("div", { class: "item__meta" }, meta)));
  }

  return h("li", { class: `item${isNew ? " is-new" : ""}` },
    h("div", { class: `item__thumb tint tint--${kind}` }, thumb),
    h("div", { class: "item__body" },
      h("div", { class: "item__title", title: shownTitle }, shownTitle),
      h("div", { class: "item__meta" },
        item.edited ? h("span", { class: "tag tag--small" }, t("édité")) : null,
        meta,
        isNew ? h("span", { class: "item__stored" }, icon("lock"), t("rangé")) : null)),
    h("div", { class: "item__actions" },
      h("a", {
        class: "icon-btn",
        href: `/api/file/${item.id}`,
        download: true,
        title: t("Retélécharger le fichier"),
        "aria-label": t("Retélécharger le fichier"),
      }, icon("download")),
      item.mode === "archive" ? null : h("a", {
        class: "icon-btn",
        href: `/edit/${item.id}`,
        title: t("Couper, fondus, volume…"),
        "aria-label": t("Ouvrir dans l'éditeur"),
      }, icon("scissors")),
      h("button", {
        type: "button",
        class: "icon-btn icon-btn--danger",
        title: t("Enlever du coffre"),
        "aria-label": t("Enlever du coffre"),
        onclick: () => deleteItem(item),
      }, icon("trash"))));
}

async function deleteItem(item) {
  if (!confirm(t("Enlever « {title} » du coffre ?\nLe fichier sera définitivement effacé.", { title: item.title }))) return;
  try {
    await api(`/api/library/${item.id}`, { method: "DELETE" });
    libraryItems = libraryItems.filter((i) => i.id !== item.id);
    renderLibrary();
  } catch (e) {
    showError(e.message);
  }
}

libraryFilter.addEventListener("input", () => renderLibrary());

// ---------------------------------------------------------------------------
// Sélection multiple : télécharger ou supprimer plusieurs fichiers d'un coup
// ---------------------------------------------------------------------------

const selectBtn = document.getElementById("selectBtn");
const selbar = document.getElementById("selbar");
const selAll = document.getElementById("selAll");
const selCount = document.getElementById("selCount");
const selDownload = document.getElementById("selDownload");
const selDelete = document.getElementById("selDelete");
selDownload.append(icon("download"), t("Télécharger"));
selDelete.append(icon("trash"), t("Enlever"));

let selecting = false;
const selected = new Set();

function visibleItems() {
  const filter = libraryFilter.value.trim().toLowerCase();
  return filter ? libraryItems.filter((i) => i.title.toLowerCase().includes(filter)) : libraryItems;
}

function setSelecting(on) {
  selecting = on;
  selected.clear();
  renderLibrary();
}

function toggleSelected(id) {
  if (selected.has(id)) selected.delete(id);
  else selected.add(id);
  // Mise à jour sur place : garde le défilement et le focus clavier
  const row = libraryList.querySelector(`[data-id="${id}"]`);
  if (row) {
    row.classList.toggle("is-selected", selected.has(id));
    row.setAttribute("aria-checked", String(selected.has(id)));
  }
  renderSelection();
}

function renderSelection() {
  // Un fichier supprimé entre-temps ne reste pas sélectionné
  const known = new Set(libraryItems.map((i) => i.id));
  for (const id of selected) if (!known.has(id)) selected.delete(id);
  if (!libraryItems.length) selecting = false;

  selectBtn.classList.toggle("hidden", !libraryItems.length);
  selectBtn.textContent = selecting ? t("Terminé") : t("Sélectionner");
  selectBtn.setAttribute("aria-pressed", String(selecting));
  document.getElementById("library").classList.toggle("is-selecting", selecting);
  selbar.classList.toggle("hidden", !selecting);
  if (!selecting) return;

  const n = selected.size;
  const visible = visibleItems();
  const allVisible = visible.length > 0 && visible.every((i) => selected.has(i.id));
  selAll.textContent = allVisible ? t("Tout désélectionner") : t("Tout sélectionner");
  selCount.textContent = n ? t(n > 1 ? "{n} sélectionnés" : "{n} sélectionné", { n }) : t("Choisis des fichiers");
  selDownload.disabled = !n;
  selDelete.disabled = !n;
}

selectBtn.addEventListener("click", () => setSelecting(!selecting));

selAll.addEventListener("click", () => {
  const visible = visibleItems();
  const allVisible = visible.every((i) => selected.has(i.id));
  visible.forEach((i) => (allVisible ? selected.delete(i.id) : selected.add(i.id)));
  renderLibrary();
});

selDownload.addEventListener("click", () => {
  const ids = [...selected];
  if (!ids.length) return;
  // Un seul fichier : tel quel. Plusieurs : un zip (un seul téléchargement, aussi sur téléphone)
  const href = ids.length === 1 ? `/api/file/${ids[0]}` : `/api/files.zip?ids=${ids.join(",")}`;
  h("a", { href, download: true }).click();
  if (ids.length > 1) showToast(t("Préparation du zip ({n} fichiers)… le téléchargement va démarrer.", { n: ids.length }));
  setSelecting(false);
});

selDelete.addEventListener("click", async () => {
  const items = libraryItems.filter((i) => selected.has(i.id));
  if (!items.length) return;
  const n = items.length;
  const question = n === 1
    ? t("Enlever « {title} » du coffre ?\nCette action est définitive.", { title: items[0].title })
    : t("Enlever ces {n} fichiers du coffre ?\nCette action est définitive.", { n });
  if (!confirm(question)) return;
  selDelete.disabled = true;
  selDelete.classList.add("is-loading");
  const failures = [];
  for (const item of items) {
    try {
      await api(`/api/library/${item.id}`, { method: "DELETE" });
    } catch (e) {
      failures.push(`${item.title} : ${e.message}`);
    }
  }
  selDelete.classList.remove("is-loading");
  await loadLibrary();
  setSelecting(false);
  const done = n - failures.length;
  if (done) showToast(t(done > 1 ? "{n} fichiers enlevés." : "{n} fichier enlevé.", { n: done }));
  if (failures.length) alert(`${t("Impossible d'enlever :")}\n${failures.join("\n")}`);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && selecting && !document.querySelector("dialog[open]")) setSelecting(false);
});

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------

// Lien reçu via le partage Android (appli installée) ou via /?url=...
function consumeSharedLink() {
  const params = new URLSearchParams(location.search);
  const shared = ["url", "text", "title"].map((k) => params.get(k)).filter(Boolean).join(" ");
  if (!shared) return;
  history.replaceState(null, "", "/");
  showView("telecharger");
  setWay("lien");
  const urls = extractUrls(shared);
  if (!urls.length) {
    showError(t("Aucun lien trouvé dans le contenu partagé."));
    return;
  }
  urlInput.value = urls.join("\n");
  autoGrow();
  handleInput();
}

async function init() {
  loadLibrary();
  try {
    const jobs = await api("/api/jobs");
    jobs.filter((j) => j.status === "done").forEach((j) => seenDone.add(j.id));
    renderQueue(jobs);
  } catch (e) {
    /* le suivi ci-dessous réessaiera */
  }
  startPolling();
  consumeSharedLink();
}

// Retour sur l'onglet / l'appli : on rafraîchit ce qui a pu changer entre-temps
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    startPolling();
    loadLibrary();
  }
});

init();
