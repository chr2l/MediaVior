const ACTIVE = new Set(["queued", "downloading", "converting", "processing"]);

const urlInput = document.getElementById("url");
const analyzeBtn = document.getElementById("analyzeBtn");
const errorEl = document.getElementById("error");
const resultEl = document.getElementById("result");
const downloadBtn = document.getElementById("downloadBtn");
const batchEl = document.getElementById("batch");
const batchList = document.getElementById("batchList");
const batchBtn = document.getElementById("batchBtn");
const queueEl = document.getElementById("queue");
const queueList = document.getElementById("queueList");
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
// Options Vidéo / Audio (même bloc pour un lien seul et pour plusieurs liens)
// ---------------------------------------------------------------------------

// Explications courtes affichées sous le choix du format
const VIDEO_HINTS = {
  original: "Meilleure qualité possible : la vidéo est gardée telle que le site la fournit, sans conversion "
    + "(souvent WebM en VP9 ou AV1). Parfait sur ordinateur ou avec VLC, mais pas toujours lu par un iPhone ou Photos Windows.",
  mp4: "Lisible partout : téléphones, TV, logiciels de montage (H.264 + AAC). Si le site ne fournit pas ce format "
    + "à la qualité choisie (souvent au-delà du 1080p), le serveur convertit la vidéo, ce qui peut être long.",
  mov: "Comme le MP4, mais dans le format préféré des logiciels Apple (Final Cut, iMovie).",
};
const AUDIO_HINTS = {
  original: "Meilleure qualité possible : la piste est gardée telle que le site la fournit, sans réencodage "
    + "(souvent Opus ou M4A). Lue par la plupart des appareils récents.",
  mp3: "Le format le plus compatible, partout. Réencodé depuis la source : à 320 kb/s, la différence est inaudible.",
  flac: "Sans perte, mais pas meilleur que l'original : les sites diffusent déjà en audio compressé. "
    + "Utile pour l'archivage ou les logiciels qui demandent du FLAC.",
  wav: "Non compressé, très lourd (≈ 10 Mo par minute). Pour les logiciels de montage audio.",
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

[
  ["", "Meilleure disponible"],
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
    showBatch(urls);
    return;
  }
  batchEl.classList.add("hidden");
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
  analyzeBtn.textContent = "Analyse…";
  analyzeBtn.classList.add("is-loading");
  analyzeBtn.disabled = true;
  resultEl.classList.add("hidden");

  try {
    renderResult(await api("/api/analyze", { method: "POST", body: { url } }));
  } catch (e) {
    showError(e.message);
  } finally {
    analyzing = false;
    analyzeBtn.textContent = "Analyser";
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
    select.append(h("option", { value: "" }, "Meilleure disponible"));
  }
  singleOptions.setMedia(data.duration, data.audio_size);

  downloadBtn.disabled = false;
  downloadBtn.textContent = "Télécharger";
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
    downloadBtn.textContent = "Ajouté à la file ✓";
    urlInput.value = "";
    autoGrow();
    startPolling();
    setTimeout(() => {
      downloadBtn.textContent = "Télécharger";
      downloadBtn.disabled = false;
    }, 1500);
  } catch (e) {
    showError(e.message);
    downloadBtn.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Plusieurs liens
// ---------------------------------------------------------------------------

let batchUrls = [];

const shortUrl = (u) => u.replace(/^https?:\/\/(www\.)?/i, "");

function showBatch(urls) {
  batchUrls = urls;
  resultEl.classList.add("hidden");
  renderBatch();
  batchEl.classList.remove("hidden");
}

function hideBatch() {
  batchUrls = [];
  batchEl.classList.add("hidden");
}

function renderBatch() {
  const n = batchUrls.length;
  document.getElementById("batchTitle").textContent = `${n} lien${n > 1 ? "s" : ""}`;
  batchBtn.textContent = `Ajouter ${n > 1 ? `les ${n} liens` : "le lien"} à la file`;
  batchList.replaceChildren(
    ...batchUrls.map((u, i) =>
      h("li", { class: "batch-list__item" },
        h("span", { class: "batch-list__url", title: u }, shortUrl(u)),
        h("button", {
          type: "button",
          class: "icon-btn icon-btn--sm",
          "aria-label": "Retirer ce lien",
          title: "Retirer ce lien",
          onclick: () => {
            batchUrls.splice(i, 1);
            if (batchUrls.length) renderBatch();
            else hideBatch();
          },
        }, icon("close"))
      )
    )
  );
}

document.getElementById("batchClear").addEventListener("click", () => {
  hideBatch();
  urlInput.value = "";
  autoGrow();
  urlInput.focus();
});

batchBtn.addEventListener("click", async () => {
  clearError();
  batchBtn.disabled = true;
  batchBtn.classList.add("is-loading");
  const options = batchOptions.values();
  const failures = [];

  for (const url of batchUrls) {
    try {
      await api("/api/download", { method: "POST", body: { url, ...options } });
      startPolling();
    } catch (e) {
      failures.push({ url, message: e.message });
    }
  }

  batchBtn.disabled = false;
  batchBtn.classList.remove("is-loading");
  if (failures.length) {
    showError(failures.map((f) => `${shortUrl(f.url)} : ${f.message}`).join("\n"));
    batchUrls = failures.map((f) => f.url);
    renderBatch();
    urlInput.value = batchUrls.join("\n");
  } else {
    hideBatch();
    urlInput.value = "";
  }
  autoGrow();
});

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
  } catch (e) {
    next = 3000; // serveur momentanément injoignable : on réessaie
  }
  pollInFlight = false;
  if (pollKick) next = 0;
  if (next !== null) pollTimer = setTimeout(pollJobs, next);
}

function renderQueue(jobs) {
  const visible = jobs.filter((j) => j.status !== "done");
  queueEl.classList.toggle("hidden", !visible.length);
  setBadge("telecharger", visible.filter((j) => ACTIVE.has(j.status)).length);

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
      return job.position === 1 ? "En attente · prochain" : `En attente · ${job.position}ᵉ dans la file`;
    case "downloading": {
      const parts = [pct];
      if (job.step) parts.push(job.step);
      if (job.speed) parts.push(`${formatBytes(job.speed)}/s`);
      if (job.eta) parts.push(`${formatDuration(job.eta)} restantes`);
      return parts.join(" · ");
    }
    case "converting":
      if (job.kind === "sons") return "Création du zip…";
      return job.encoding ? `Conversion… ${pct}` : "Conversion…";
    case "processing":
      return `Montage… ${pct}`;
    case "cancelled":
      return "Annulé";
    case "error":
      return job.error || "Erreur";
    default:
      return "";
  }
}

function updateJobNode(node, job) {
  node.job = job;
  node.title.textContent = job.title;
  node.title.title = job.title;

  if (node.thumbSrc !== (job.thumbnail || null)) {
    node.thumbSrc = job.thumbnail || null;
    node.thumb.replaceChildren(
      job.thumbnail
        ? h("img", { src: job.thumbnail, alt: "", referrerpolicy: "no-referrer" })
        : icon(job.kind === "edit" ? "scissors" : job.kind === "sons" ? "archive" : "download")
    );
  }

  const active = ACTIVE.has(job.status);
  const busy = job.status === "queued" || (job.status === "converting" && !job.encoding);
  node.progress.classList.toggle("hidden", !active);
  node.progress.classList.toggle("is-busy", busy);
  node.fill.style.width = busy ? "100%" : `${job.progress || 0}%`;

  node.meta.textContent = node.cancelling && active ? "Annulation…" : jobStatusText(job);
  node.meta.classList.toggle("is-error", job.status === "error");
  node.root.classList.toggle("is-muted", job.status === "cancelled");

  node.action.textContent = active ? "Annuler" : "Retirer";
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
      queueEl.classList.toggle("hidden", !queueNodes.size);
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
  libraryStats.textContent = n ? `${n} fichier${n > 1 ? "s" : ""} · ${formatBytes(total)}` : "";
  libraryFilter.classList.toggle("hidden", n < 6 && !filter);

  libraryEmpty.classList.toggle("hidden", items.length > 0);
  libraryEmpty.textContent = n
    ? "Aucun titre ne correspond à ce filtre."
    : "Rien dans la bibliothèque pour l'instant. Les fichiers téléchargés apparaîtront ici.";

  libraryList.replaceChildren(...items.map((item) => libraryRow(item, highlightIds.includes(item.id))));
  renderSelection();
}

function libraryRow(item, isNew) {
  const fallback = () => icon({ audio: "music", archive: "archive" }[item.mode] || "film");
  const thumb = item.thumbnail
    ? h("img", {
        src: item.thumbnail,
        alt: "",
        loading: "lazy",
        referrerpolicy: "no-referrer",
        onerror: (e) => e.target.replaceWith(fallback()),
      })
    : fallback();

  const meta = [
    item.ext.toUpperCase(),
    formatBytes(item.size),
    item.duration ? formatDuration(item.duration) : null,
    formatDate(item.created),
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
      h("div", { class: "item__thumb" }, thumb),
      h("div", { class: "item__body" },
        h("div", { class: "item__title", title: item.title }, item.title),
        h("div", { class: "item__meta" }, meta)));
  }

  return h("li", { class: `item${isNew ? " is-new" : ""}` },
    h("div", { class: "item__thumb" }, thumb),
    h("div", { class: "item__body" },
      h("div", { class: "item__title", title: item.title }, item.title),
      h("div", { class: "item__meta" },
        item.edited ? h("span", { class: "tag tag--small" }, "édité") : null,
        meta)),
    h("div", { class: "item__actions" },
      h("a", {
        class: "icon-btn",
        href: `/api/file/${item.id}`,
        download: true,
        title: "Récupérer le fichier",
        "aria-label": "Récupérer le fichier",
      }, icon("download")),
      item.mode === "archive" ? null : h("a", {
        class: "icon-btn",
        href: `/edit/${item.id}`,
        title: "Couper, fondus, volume…",
        "aria-label": "Ouvrir dans l'éditeur",
      }, icon("scissors")),
      h("button", {
        type: "button",
        class: "icon-btn icon-btn--danger",
        title: "Supprimer du serveur",
        "aria-label": "Supprimer du serveur",
        onclick: () => deleteItem(item),
      }, icon("trash"))));
}

async function deleteItem(item) {
  if (!confirm(`Supprimer « ${item.title} » du serveur ?\nLe fichier sera définitivement effacé.`)) return;
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
selDownload.append(icon("download"), "Télécharger");
selDelete.append(icon("trash"), "Supprimer");

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
  selectBtn.textContent = selecting ? "Terminé" : "Sélectionner";
  selectBtn.setAttribute("aria-pressed", String(selecting));
  document.getElementById("library").classList.toggle("is-selecting", selecting);
  selbar.classList.toggle("hidden", !selecting);
  if (!selecting) return;

  const n = selected.size;
  const visible = visibleItems();
  const allVisible = visible.length > 0 && visible.every((i) => selected.has(i.id));
  selAll.textContent = allVisible ? "Tout désélectionner" : "Tout sélectionner";
  selCount.textContent = n ? `${n} sélectionné${n > 1 ? "s" : ""}` : "Choisis des fichiers";
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
  if (ids.length > 1) showToast(`Préparation du zip (${ids.length} fichiers)… le téléchargement va démarrer.`);
  setSelecting(false);
});

selDelete.addEventListener("click", async () => {
  const items = libraryItems.filter((i) => selected.has(i.id));
  if (!items.length) return;
  const n = items.length;
  const what = n === 1 ? `« ${items[0].title} »` : `ces ${n} fichiers`;
  if (!confirm(`Supprimer ${what} du serveur ?\nCette action est définitive.`)) return;
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
  if (done) showToast(`${done} fichier${done > 1 ? "s" : ""} supprimé${done > 1 ? "s" : ""}.`);
  if (failures.length) alert(`Impossible de supprimer :\n${failures.join("\n")}`);
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
  const urls = extractUrls(shared);
  if (!urls.length) {
    showError("Aucun lien trouvé dans le contenu partagé.");
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
    if (jobs.some((j) => ACTIVE.has(j.status))) startPolling();
  } catch (e) {
    /* le prochain ajout relancera le suivi */
  }
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
