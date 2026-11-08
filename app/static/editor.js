const ITEM_ID = document.body.dataset.itemId;
const MIN_SELECTION = 0.1;

const $ = (id) => document.getElementById(id);
const errorEl = $("error");
const timeline = $("timeline");
const fadeIn = $("fadeIn");
const fadeOut = $("fadeOut");
const gain = $("gain");
const normalize = $("normalize");
const mute = $("mute");
const fast = $("fast");
const format = $("format");
const renderBtn = $("renderBtn");

let media = null;
let duration = 0;
let hasVideo = false;
const sel = { start: 0, end: 0 };
let stopAt = null;
let currentJob = null;

$("backLink").append(icon("back"), "Bibliothèque");
$("playBtn").append(icon("play"));

const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

function showError(message) {
  errorEl.textContent = message;
  errorEl.classList.remove("hidden");
}

function clearError() {
  errorEl.classList.add("hidden");
}

// ---------------------------------------------------------------------------
// Chargement
// ---------------------------------------------------------------------------

async function init() {
  let item;
  try {
    item = await api(`/api/library/${ITEM_ID}`);
  } catch (e) {
    $("edTitle").textContent = "Fichier introuvable";
    showError(e.message);
    return;
  }

  document.title = `${item.title} · Éditeur`;
  $("edTitle").textContent = item.title;
  $("edMeta").replaceChildren(
    h("span", { class: "tag" }, item.ext.toUpperCase()),
    h("span", { class: "tag tag--muted" }, formatBytes(item.size)),
    item.width ? h("span", { class: "tag tag--muted" }, `${item.width}×${item.height}`) : null,
  );

  hasVideo = item.has_video;
  media = h(hasVideo ? "video" : "audio", {
    src: `/api/file/${ITEM_ID}?inline=1`,
    preload: "auto",
    playsinline: true,
  });
  if (hasVideo) {
    $("stage").prepend(media);
    $("stage").classList.remove("hidden");
  } else {
    media.classList.add("hidden");
    document.body.append(media);
  }

  if (item.has_audio) {
    const wave = $("wave");
    timeline.classList.add("is-loading");
    wave.addEventListener("load", () => timeline.classList.remove("is-loading"));
    wave.addEventListener("error", () => {
      timeline.classList.remove("is-loading");
      wave.classList.add("hidden");
    });
    wave.src = `/api/library/${ITEM_ID}/waveform`;
  } else {
    $("wave").classList.add("hidden");
  }

  // Formats de sortie possibles
  const options = [];
  if (item.has_video) options.push(["mp4", "MP4 (vidéo)"], ["mov", "MOV (vidéo)"]);
  if (item.has_audio) {
    const suffix = item.has_video ? " · audio seul" : "";
    options.push(["mp3", `MP3${suffix}`], ["wav", `WAV${suffix}`]);
  }
  format.replaceChildren(
    h("option", { value: "", class: "js-original", hidden: true }, `Identique à l'original (${item.ext.toUpperCase()})`),
    ...options.map(([value, label]) => h("option", { value }, label)),
  );
  format.value = options.some(([v]) => v === item.ext) ? item.ext : options[0][0];

  $("muteRow").classList.toggle("hidden", !(item.has_video && item.has_audio));

  duration = item.duration || 0;
  if (!duration) {
    await new Promise((resolve) => media.addEventListener("loadedmetadata", resolve, { once: true }));
    duration = media.duration || 0;
  }
  $("totalTime").textContent = formatDuration(duration);
  sel.start = 0;
  sel.end = duration;

  bindEvents();
  syncControls();
  render();
  $("editor").classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// Sélection et frise
// ---------------------------------------------------------------------------

const pct = (t) => `${(t / duration) * 100}%`;

function setSelection(start, end, moved) {
  start = clamp(start, 0, duration);
  end = clamp(end, 0, duration);
  if (end - start < MIN_SELECTION) {
    if (moved === "start") start = Math.max(0, end - MIN_SELECTION);
    else end = Math.min(duration, start + MIN_SELECTION);
  }
  sel.start = start;
  sel.end = end;
  syncControls();
  render();
}

function selectionLength() {
  return sel.end - sel.start;
}

// Les fondus ne peuvent pas dépasser la sélection
function syncControls() {
  const len = selectionLength();
  const maxFade = Math.max(0, Math.min(10, Math.floor(len * 10) / 10));
  fadeIn.max = maxFade;
  fadeOut.max = maxFade;
  if (Number(fadeIn.value) + Number(fadeOut.value) > len) {
    const ratio = len / (Number(fadeIn.value) + Number(fadeOut.value));
    fadeIn.value = (Number(fadeIn.value) * ratio).toFixed(1);
    fadeOut.value = Math.max(0, len - Number(fadeIn.value)).toFixed(1);
  }

  const off = fast.checked;
  document.querySelectorAll(".js-effect").forEach((el) => el.classList.toggle("is-disabled", off));
  [fadeIn, fadeOut, gain, normalize].forEach((el) => (el.disabled = off));
  format.disabled = off;
  format.querySelector(".js-original").hidden = !off;
  if (off) {
    format.dataset.previous = format.value || format.dataset.previous || "";
    format.value = "";
  } else if (!format.value) {
    format.value = format.dataset.previous || format.options[1].value;
  }

  const audioOnly = ["mp3", "wav"].includes(format.value);
  mute.disabled = audioOnly;
  if (audioOnly) mute.checked = false;

  $("fadeInValue").textContent = `${Number(fadeIn.value).toLocaleString("fr-FR")} s`;
  $("fadeOutValue").textContent = `${Number(fadeOut.value).toLocaleString("fr-FR")} s`;
  const g = Number(gain.value);
  $("gainValue").textContent = `${g > 0 ? "+" : ""}${g.toLocaleString("fr-FR")} dB`;
}

function render() {
  if (!duration) return;
  $("shadeLeft").style.width = pct(sel.start);
  $("shadeRight").style.left = pct(sel.end);
  const selection = $("selection");
  selection.style.left = pct(sel.start);
  selection.style.width = pct(selectionLength());
  $("handleStart").style.left = pct(sel.start);
  $("handleEnd").style.left = pct(sel.end);

  const len = selectionLength();
  const effects = !fast.checked;
  $("fadeInZone").style.width = effects ? `${(Number(fadeIn.value) / len) * 100}%` : "0";
  $("fadeOutZone").style.width = effects ? `${(Number(fadeOut.value) / len) * 100}%` : "0";

  if (document.activeElement !== $("startInput")) $("startInput").value = formatTime(sel.start);
  if (document.activeElement !== $("endInput")) $("endInput").value = formatTime(sel.end);
  $("selDuration").textContent = formatTime(len);

  for (const [handle, value] of [[$("handleStart"), sel.start], [$("handleEnd"), sel.end]]) {
    handle.setAttribute("aria-valuemin", "0");
    handle.setAttribute("aria-valuemax", String(Math.round(duration)));
    handle.setAttribute("aria-valuenow", value.toFixed(1));
    handle.setAttribute("aria-valuetext", formatTime(value));
  }
  renderPlayhead();
}

function renderPlayhead() {
  if (!media || !duration) return;
  $("playhead").style.left = pct(clamp(media.currentTime, 0, duration));
  $("curTime").textContent = formatTime(media.currentTime);
}

function timeFromEvent(e) {
  const rect = timeline.getBoundingClientRect();
  return clamp((e.clientX - rect.left) / rect.width, 0, 1) * duration;
}

function seek(t) {
  media.currentTime = clamp(t, 0, duration);
  renderPlayhead();
  applyPreview();
}

// ---------------------------------------------------------------------------
// Aperçu : les fondus et la coupure du son sont simulés pendant la lecture
// ---------------------------------------------------------------------------

function applyPreview() {
  if (!media) return;
  const t = media.currentTime;
  let envelope = 1;
  if (!fast.checked && t >= sel.start && t <= sel.end) {
    const fi = Number(fadeIn.value);
    const fo = Number(fadeOut.value);
    if (fi > 0) envelope = Math.min(envelope, (t - sel.start) / fi);
    if (fo > 0) envelope = Math.min(envelope, (sel.end - t) / fo);
  }
  envelope = clamp(envelope, 0, 1);
  const linearGain = fast.checked ? 1 : Math.pow(10, Number(gain.value) / 20);
  media.volume = clamp(envelope * Math.min(1, linearGain), 0, 1);
  media.muted = mute.checked;
  const showsVideo = hasVideo && !["mp3", "wav"].includes(format.value);
  // À l'arrêt, on montre l'image telle quelle : un écran noir au début d'un fondu ferait croire à un bug
  $("fadeOverlay").style.opacity = showsVideo && !media.paused ? String(1 - envelope) : "0";
}

function tick() {
  renderPlayhead();
  applyPreview();
  if (stopAt !== null && media.currentTime >= stopAt) {
    media.pause();
    stopAt = null;
  }
  if (!media.paused) requestAnimationFrame(tick);
}

function updatePlayButton() {
  const playing = !media.paused;
  $("playBtn").replaceChildren(icon(playing ? "pause" : "play"));
  $("playBtn").setAttribute("aria-label", playing ? "Pause" : "Lecture");
}

// ---------------------------------------------------------------------------
// Évènements
// ---------------------------------------------------------------------------

function bindEvents() {
  media.addEventListener("play", () => {
    updatePlayButton();
    requestAnimationFrame(tick);
  });
  media.addEventListener("pause", () => {
    updatePlayButton();
    applyPreview();
  });
  media.addEventListener("seeked", renderPlayhead);
  if (hasVideo) media.addEventListener("click", () => (media.paused ? media.play() : media.pause()));

  $("playBtn").addEventListener("click", () => {
    stopAt = null;
    if (media.paused) media.play();
    else media.pause();
  });

  $("playSelBtn").addEventListener("click", () => {
    seek(sel.start);
    stopAt = sel.end;
    media.play();
  });

  $("markStart").addEventListener("click", () => setSelection(media.currentTime, sel.end, "start"));
  $("markEnd").addEventListener("click", () => setSelection(sel.start, media.currentTime, "end"));

  // Glisser les poignées, ou cliquer/glisser ailleurs pour se déplacer
  timeline.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const handle = e.target.closest(".timeline__handle");
    const edge = handle ? handle.dataset.edge : "seek";
    if (handle) handle.focus();
    timeline.setPointerCapture(e.pointerId);
    timeline.classList.add("is-dragging");

    const move = (ev) => {
      const t = timeFromEvent(ev);
      if (edge === "start") {
        setSelection(t, sel.end, "start");
        seek(sel.start);
      } else if (edge === "end") {
        setSelection(sel.start, t, "end");
        seek(sel.end);
      } else {
        seek(t);
      }
    };
    const up = () => {
      timeline.classList.remove("is-dragging");
      timeline.removeEventListener("pointermove", move);
      timeline.removeEventListener("pointerup", up);
      timeline.removeEventListener("pointercancel", up);
    };
    move(e);
    timeline.addEventListener("pointermove", move);
    timeline.addEventListener("pointerup", up);
    timeline.addEventListener("pointercancel", up);
  });

  for (const handle of [$("handleStart"), $("handleEnd")]) {
    handle.addEventListener("keydown", (e) => {
      const isStart = handle.dataset.edge === "start";
      const step = e.shiftKey ? 1 : 0.1;
      let value = isStart ? sel.start : sel.end;
      if (e.key === "ArrowLeft" || e.key === "ArrowDown") value -= step;
      else if (e.key === "ArrowRight" || e.key === "ArrowUp") value += step;
      else if (e.key === "Home") value = isStart ? 0 : sel.start + MIN_SELECTION;
      else if (e.key === "End") value = isStart ? sel.end - MIN_SELECTION : duration;
      else return;
      e.preventDefault();
      if (isStart) setSelection(value, sel.end, "start");
      else setSelection(sel.start, value, "end");
      seek(isStart ? sel.start : sel.end);
    });
  }

  for (const [input, edge] of [[$("startInput"), "start"], [$("endInput"), "end"]]) {
    const commit = () => {
      const t = parseTime(input.value);
      if (t === null) {
        input.value = formatTime(edge === "start" ? sel.start : sel.end);
        return;
      }
      if (edge === "start") setSelection(t, sel.end, "start");
      else setSelection(sel.start, t, "end");
      input.value = formatTime(edge === "start" ? sel.start : sel.end);
    };
    input.addEventListener("change", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") input.blur();
    });
  }

  for (const control of [fadeIn, fadeOut, gain, normalize, mute, fast, format]) {
    control.addEventListener("input", () => {
      syncControls();
      render();
      applyPreview();
    });
  }

  // Barre d'espace : lecture / pause (hors champs de saisie)
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || e.target.closest("input, select, textarea, button, [role=slider]")) return;
    e.preventDefault();
    $("playBtn").click();
  });

  renderBtn.addEventListener("click", startRender);
  $("cancelBtn").addEventListener("click", async () => {
    if (!currentJob) return;
    $("cancelBtn").disabled = true;
    try {
      await api(`/api/jobs/${currentJob}/cancel`, { method: "POST" });
    } catch (e) {
      showError(e.message);
    }
  });

  window.addEventListener("resize", render);
}

// ---------------------------------------------------------------------------
// Rendu côté serveur
// ---------------------------------------------------------------------------

async function startRender() {
  clearError();
  const round = (v) => Math.round(v * 1000) / 1000;
  const payload = {
    start: round(sel.start),
    end: round(sel.end),
    fade_in: fast.checked ? 0 : Number(fadeIn.value),
    fade_out: fast.checked ? 0 : Number(fadeOut.value),
    gain: fast.checked ? 0 : Number(gain.value),
    normalize: !fast.checked && normalize.checked,
    mute: mute.checked,
    format: fast.checked ? null : format.value,
    fast: fast.checked,
  };

  renderBtn.disabled = true;
  renderBtn.classList.add("is-loading");
  $("renderActions").classList.add("hidden");
  try {
    const { job_id } = await api(`/api/library/${ITEM_ID}/edit`, { method: "POST", body: payload });
    currentJob = job_id;
    $("cancelBtn").disabled = false;
    $("cancelBtn").classList.remove("hidden");
    $("renderProgress").classList.remove("hidden", "is-done");
    trackRender(job_id);
  } catch (e) {
    showError(e.message);
    renderBtn.disabled = false;
    renderBtn.classList.remove("is-loading");
  }
}

async function trackRender(jobId) {
  const progress = $("renderProgress");
  const fill = $("renderFill");
  const text = $("renderText");
  let job;
  try {
    job = await api(`/api/jobs/${jobId}`);
  } catch (e) {
    setTimeout(() => trackRender(jobId), 2000);
    return;
  }

  const queued = job.status === "queued";
  progress.classList.toggle("is-busy", queued);
  fill.style.width = queued ? "100%" : `${job.progress || 0}%`;
  text.textContent = queued
    ? (job.position === 1 ? "En attente…" : `En attente (${job.position}ᵉ)`)
    : `${Math.round(job.progress || 0)} %`;

  if (job.status === "queued" || job.status === "processing") {
    setTimeout(() => trackRender(jobId), 700);
    return;
  }

  currentJob = null;
  renderBtn.disabled = false;
  renderBtn.classList.remove("is-loading");

  if (job.status === "done") {
    progress.classList.add("is-done");
    fill.style.width = "100%";
    text.textContent = "Terminé";
    $("cancelBtn").classList.add("hidden");
    $("resultLink").href = `/api/file/${jobId}`;
    $("resultLink").textContent = `Récupérer : ${job.filename}`;
    $("resultEdit").href = `/edit/${jobId}`;
    $("renderActions").classList.remove("hidden");
    renderBtn.textContent = "Créer une autre version";
    return;
  }

  progress.classList.add("hidden");
  $("cancelBtn").classList.remove("hidden");
  if (job.status === "error") showError(job.error || "Le montage a échoué.");
}

init();
