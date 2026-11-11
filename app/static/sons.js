// Liste de sons : titres écrits ou lus sur des captures, cherchés puis rendus en zip.

const sonsInput = document.getElementById("sonsInput");
const sonsAddBtn = document.getElementById("sonsAddBtn");
const sonsFiles = document.getElementById("sonsFiles");
const sonsFilesBtn = document.getElementById("sonsFilesBtn");
const sonsDrop = document.getElementById("sonsDrop");
const sonsInfo = document.getElementById("sonsInfo");
const sonsList = document.getElementById("sonsList");
const sonsActions = document.getElementById("sonsActions");
const sonsFetchBtn = document.getElementById("sonsFetchBtn");
const sonsFormat = document.getElementById("sonsFormat");
const sonsHint = document.getElementById("sonsHint");
const sonsZip = document.getElementById("sonsZip");
const sonsClear = document.getElementById("sonsClear");
const sonsProgress = document.getElementById("sonsProgress");
const sonsProgressFill = document.getElementById("sonsProgressFill");
const sonsProgressText = document.getElementById("sonsProgressText");

let sons = [];
let sonsJobActive = false;
const sonsSeenFinished = new Set();

function sonsMessage(text) {
  sonsInfo.textContent = text || "";
  sonsInfo.classList.toggle("hidden", !text);
}

function renderSons() {
  const n = sons.length;
  setBadge("sons", n);
  sonsClear.classList.toggle("hidden", !n);
  sonsActions.classList.toggle("hidden", !n);
  sonsHint.classList.toggle("hidden", !n);
  sonsFetchBtn.disabled = sonsJobActive;
  sonsFetchBtn.textContent = sonsJobActive
    ? t("Recherche en cours…")
    : n > 1 ? t("Chercher et mettre au coffre les {n} sons", { n }) : t("Chercher et mettre au coffre le son");

  sonsList.replaceChildren(
    ...sons.map((son) => {
      const input = h("input", {
        type: "text",
        class: "sons-list__input",
        value: son.query,
        "aria-label": t("Titre à chercher"),
        spellcheck: "false",
      });
      input.addEventListener("change", () => updateSon(son, input.value));
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") input.blur();
      });
      return h("li", { class: `sons-list__item${son.note ? " is-missing" : ""}` },
        h("div", { class: "sons-list__body" },
          input,
          son.note
            ? h("div", { class: "sons-list__note" }, t("Introuvable : {why} · ", { why: t(son.note) }),
                h("button", { type: "button", class: "btn-link", onclick: () => openPicker([son]) }, t("chercher sur YouTube")))
            : null,
          son.pick
            ? h("div", { class: "sons-list__pick" }, t("Vidéo choisie : {title} · ", { title: son.pick.title }),
                h("button", { type: "button", class: "btn-link", onclick: () => openPicker([son]) }, t("changer")),
                " · ",
                h("button", { type: "button", class: "btn-link", onclick: () => unpickSon(son) }, t("retirer")))
            : null),
        h("button", {
          type: "button",
          class: "icon-btn icon-btn--sm",
          "aria-label": t("Choisir la vidéo sur YouTube"),
          title: t("Choisir la vidéo sur YouTube"),
          onclick: () => openPicker([son]),
        }, icon("search")),
        h("button", {
          type: "button",
          class: "icon-btn icon-btn--sm",
          "aria-label": t("Retirer ce son"),
          title: t("Retirer ce son"),
          onclick: () => removeSon(son),
        }, icon("close")));
    })
  );
}

async function loadSons() {
  try {
    sons = await api("/api/sons");
  } catch (e) {
    return;
  }
  renderSons();
}

async function addSonsFromText() {
  const queries = sonsInput.value.split("\n").map((l) => l.trim()).filter(Boolean);
  if (!queries.length) return;
  try {
    sons = await api("/api/sons", { method: "POST", body: { queries } });
    sonsInput.value = "";
    sonsInput.style.height = "auto";
    sonsMessage("");
    renderSons();
  } catch (e) {
    sonsMessage(e.message);
  }
}

async function updateSon(son, query) {
  if (!query.trim()) {
    renderSons();
    return;
  }
  try {
    sons = await api(`/api/sons/${son.id}`, { method: "PATCH", body: { query } });
    renderSons();
  } catch (e) {
    sonsMessage(e.message);
  }
}

async function unpickSon(son) {
  try {
    sons = await api(`/api/sons/${son.id}/pick`, { method: "DELETE" });
    renderSons();
  } catch (e) {
    sonsMessage(e.message);
  }
}

async function removeSon(son) {
  try {
    sons = await api(`/api/sons/${son.id}`, { method: "DELETE" });
    renderSons();
  } catch (e) {
    sonsMessage(e.message);
  }
}

sonsClear.addEventListener("click", async () => {
  if (!confirm(t("Vider toute la liste de sons ?"))) return;
  try {
    sons = await api("/api/sons", { method: "DELETE" });
    renderSons();
  } catch (e) {
    sonsMessage(e.message);
  }
});

sonsAddBtn.addEventListener("click", addSonsFromText);
sonsInput.addEventListener("input", () => {
  sonsInput.style.height = "auto";
  sonsInput.style.height = `${Math.min(sonsInput.scrollHeight + 2, 180)}px`;
});
sonsInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    addSonsFromText();
  }
});

// ---------------------------------------------------------------------------
// Captures d'écran : envoyées une par une, le serveur y lit les titres
// ---------------------------------------------------------------------------

async function readScreens(files) {
  const images = [...files].filter((f) => f.type.startsWith("image/"));
  if (!images.length) return;
  sonsFilesBtn.classList.add("is-loading");
  let added = 0;
  const failures = [];
  for (const [i, file] of images.entries()) {
    sonsMessage(t("Lecture de la capture {i}/{n}…", { i: i + 1, n: images.length }));
    try {
      const res = await fetch("/api/sons/ocr", {
        method: "POST",
        body: file,
        headers: { "Content-Type": file.type || "application/octet-stream" },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(t((data && data.detail) || "Le serveur a renvoyé une erreur."));
      sons = data.sons;
      added += data.added;
      renderSons();
    } catch (e) {
      failures.push(`${file.name || "capture"} : ${e.message}`);
    }
  }
  sonsFilesBtn.classList.remove("is-loading");
  const summary = added
    ? t(added > 1 ? "{n} titres ajoutés. Vérifie-les : la lecture d'image peut se tromper." : "{n} titre ajouté. Vérifie-le : la lecture d'image peut se tromper.", { n: added })
    : t("Aucun nouveau titre trouvé sur ces captures.");
  sonsMessage([summary, ...failures].join("\n"));
}

sonsFiles.addEventListener("change", () => {
  readScreens(sonsFiles.files);
  sonsFiles.value = "";
});

["dragenter", "dragover"].forEach((type) =>
  sonsDrop.addEventListener(type, (e) => {
    e.preventDefault();
    sonsDrop.classList.add("is-over");
  })
);
["dragleave", "drop"].forEach((type) =>
  sonsDrop.addEventListener(type, () => sonsDrop.classList.remove("is-over"))
);
sonsDrop.addEventListener("drop", (e) => {
  e.preventDefault();
  readScreens(e.dataTransfer.files);
});

// Une image collée n'importe où sur la page (Ctrl+V après une capture) part dans la liste
document.addEventListener("paste", (e) => {
  const files = [...(e.clipboardData ? e.clipboardData.files : [])].filter((f) => f.type.startsWith("image/"));
  if (!files.length) return;
  e.preventDefault();
  showView("telecharger");
  setWay("titres");
  readScreens(files);
});

// ---------------------------------------------------------------------------
// Recherche + téléchargement
// ---------------------------------------------------------------------------

sonsFetchBtn.addEventListener("click", async () => {
  const [container, quality] = sonsFormat.value.split(":");
  sonsFetchBtn.disabled = true;
  sonsZip.classList.add("hidden");
  try {
    await api("/api/sons/fetch", {
      method: "POST",
      body: { container, audio_quality: quality || null },
    });
    sonsJobActive = true;
    sonsMessage("");
    renderSons();
    startPolling();
  } catch (e) {
    sonsMessage(e.message);
    sonsFetchBtn.disabled = false;
  }
});

// Appelé à chaque rafraîchissement de la file (app.js)
function sonsOnJobs(jobs) {
  const sonsJobs = jobs.filter((j) => j.kind === "sons");
  const wasActive = sonsJobActive;
  const running = sonsJobs.find((j) => ACTIVE.has(j.status));
  sonsJobActive = Boolean(running);
  if (wasActive !== sonsJobActive) renderSons();
  showSonsProgress(running);

  for (const job of sonsJobs) {
    if (ACTIVE.has(job.status) || sonsSeenFinished.has(job.id)) continue;
    sonsSeenFinished.add(job.id);
    if (!wasActive) continue; // terminé avant l'ouverture de la page
    // Les sons introuvables s'ouvrent dans la fenêtre YouTube, pour les choisir à la main
    loadSons().then(() => {
      const missing = sons.filter((s) => s.note);
      if (missing.length && !ytDialog.open) openPicker(missing);
    });
    if (job.status === "done") showZip(job);
  }
}

// Suivi de la recherche en cours, sous le bouton
function showSonsProgress(job) {
  sonsProgress.classList.toggle("hidden", !job);
  if (!job) return;
  const busy = job.status === "queued" || job.status === "converting";
  sonsProgress.querySelector(".progress").classList.toggle("is-busy", busy);
  sonsProgressFill.style.width = busy ? "100%" : `${job.progress || 0}%`;

  let text;
  if (job.status === "queued") text = t("En attente dans la file…");
  else if (job.status === "converting") text = t("Création du zip…");
  else {
    const parts = [`${Math.round(job.progress || 0)} %`];
    if (job.step) parts.push(job.step);
    text = parts.join(" · ");
  }
  const counts = [];
  if (job.found) counts.push(t(job.found > 1 ? "{n} trouvés" : "{n} trouvé", { n: job.found }));
  if (job.missing) counts.push(t(job.missing > 1 ? "{n} introuvables" : "{n} introuvable", { n: job.missing }));
  sonsProgressText.textContent = counts.length ? `${text} (${counts.join(", ")})` : text;
}

function showZip(job) {
  const missing = job.missing
    ? " " + t(job.missing > 1 ? "{n} sons introuvables, signalés dans la liste." : "{n} son introuvable, signalé dans la liste.", { n: job.missing })
    : "";
  sonsZip.replaceChildren(
    h("button", { type: "button", class: "btn btn--success btn--sm", onclick: () => downloadFile(`/api/file/${job.id}`) },
      icon("download"), t("Télécharger le zip")),
    h("span", { class: "hint" }, t(job.found > 1 ? "{n} sons dans le zip." : "{n} son dans le zip.", { n: job.found }) + missing)
  );
  sonsZip.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// Fenêtre YouTube : retrouver à la main un son que la recherche n'a pas trouvé
// ---------------------------------------------------------------------------

const ytDialog = document.getElementById("ytDialog");
const ytFor = document.getElementById("ytFor");
const ytForm = document.getElementById("ytForm");
const ytQuery = document.getElementById("ytQuery");
const ytPlayer = document.getElementById("ytPlayer");
const ytInfo = document.getElementById("ytInfo");
const ytResults = document.getElementById("ytResults");
const ytRemaining = document.getElementById("ytRemaining");
const ytSkip = document.getElementById("ytSkip");
document.getElementById("ytClose").append(icon("close"));

let ytQueue = [];
let ytSearchId = 0;

function openPicker(list) {
  ytQueue = [...list];
  if (!ytDialog.open) ytDialog.showModal();
  showPickerSon();
}

function showPickerSon() {
  const son = ytQueue[0];
  if (!son) {
    closePicker();
    return;
  }
  ytFor.textContent = t("Pour : {q}", { q: son.query });
  const left = ytQueue.length - 1;
  ytRemaining.textContent = left ? t(left > 1 ? "Encore {n} sons à retrouver après celui-ci" : "Encore {n} son à retrouver après celui-ci", { n: left }) : "";
  ytSkip.textContent = left ? t("Passer") : t("Fermer");
  ytQuery.value = son.query;
  searchYoutube();
}

function closePicker() {
  ytQueue = [];
  ytPlayer.replaceChildren();
  ytPlayer.classList.add("hidden");
  if (ytDialog.open) ytDialog.close();
}

function nextPickerSon() {
  ytQueue.shift();
  showPickerSon();
}

function ytMessage(text) {
  ytInfo.textContent = text || "";
  ytInfo.classList.toggle("hidden", !text);
}

async function searchYoutube() {
  const q = ytQuery.value.trim();
  if (!q) return;
  const searchId = ++ytSearchId;
  ytPlayer.replaceChildren();
  ytPlayer.classList.add("hidden");
  ytResults.replaceChildren();
  ytMessage(t("Recherche sur YouTube…"));
  let results;
  try {
    results = await api(`/api/sons/search?q=${encodeURIComponent(q)}`);
  } catch (e) {
    if (searchId === ytSearchId) ytMessage(e.message);
    return;
  }
  if (searchId !== ytSearchId) return; // une autre recherche est partie entre-temps
  ytMessage(results.length ? "" : t("Aucun résultat. Essaie d'autres mots."));
  ytResults.replaceChildren(...results.map(ytResultNode));
}

function ytResultNode(video) {
  const meta = [video.channel, video.duration ? formatDuration(video.duration) : null].filter(Boolean).join(" · ");
  const li = h("li", { class: "yt-results__item" },
    h("button", {
      type: "button",
      class: "yt-results__preview",
      title: t("Écouter"),
      onclick: () => previewVideo(video, li),
    },
      h("img", { src: video.thumbnail, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }),
      icon("play")),
    h("div", { class: "yt-results__body" },
      h("div", { class: "yt-results__title", title: video.title }, video.title),
      meta ? h("div", { class: "yt-results__meta" }, meta) : null),
    h("button", { type: "button", class: "btn btn--solid btn--sm", onclick: () => pickVideo(video) }, t("Choisir")));
  return li;
}

function previewVideo(video, li) {
  ytResults.querySelectorAll(".is-playing").forEach((el) => el.classList.remove("is-playing"));
  li.classList.add("is-playing");
  ytPlayer.replaceChildren(h("iframe", {
    src: `https://www.youtube-nocookie.com/embed/${video.id}?autoplay=1`,
    title: video.title,
    allow: "autoplay; encrypted-media; picture-in-picture",
    allowfullscreen: true,
  }));
  ytPlayer.classList.remove("hidden");
}

async function pickVideo(video) {
  const son = ytQueue[0];
  if (!son) return;
  try {
    sons = await api(`/api/sons/${son.id}/pick`, { method: "PUT", body: { video_id: video.id, title: video.title } });
    renderSons();
    nextPickerSon();
  } catch (e) {
    ytMessage(e.message);
  }
}

ytForm.addEventListener("submit", (e) => {
  e.preventDefault();
  searchYoutube();
});
ytSkip.addEventListener("click", nextPickerSon);
document.getElementById("ytClose").addEventListener("click", closePicker);
ytDialog.addEventListener("close", () => {
  ytQueue = [];
  ytPlayer.replaceChildren(); // coupe le son de l'aperçu
  ytPlayer.classList.add("hidden");
});

async function initSons() {
  await loadSons();
  try {
    sonsOnJobs(await api("/api/jobs"));
  } catch (e) {
    /* rien */
  }
}

initSons();
