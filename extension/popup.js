import { getSettings, saveSettings, api, findServer } from "./settings.js";

translatePage(); // voir i18n.js

const $ = (sel) => document.querySelector(sel);
const urlInput = $(".js-url");
const qualitySel = $(".js-quality");
const videoContainerSel = $(".js-video-container");
const audioContainerSel = $(".js-audio-container");
const audioQualitySel = $(".js-audio-quality");
const sendBtn = $(".js-send");
const analyzeStatus = $(".js-analyze-status");
const sendStatus = $(".js-send-status");

const STANDARD_QUALITIES = [
  ["", "Meilleure disponible"],
  ["2160", "4K (2160p) max"],
  ["1440", "1440p max"],
  ["1080", "1080p max"],
  ["720", "720p max"],
  ["480", "480p max"],
];
const STATUS_LABELS = {
  queued: "En file d'attente",
  downloading: "Téléchargement",
  converting: "Conversion",
  processing: "Traitement",
  done: "Terminé : c'est dans MediaVior.",
  error: "Échec",
  cancelled: "Annulé",
};

let settings;
let mode = "video";
let analysis = null; // réponse de /api/analyze pour le lien affiché
let analyzeSeq = 0;

function setStatus(el, text, kind = "") {
  el.textContent = t(text);
  el.classList.remove("is-error", "is-ok");
  if (kind) el.classList.add("is-" + kind);
}

function formatBytes(n) {
  if (!n) return "";
  const units = LANG === "fr" ? ["o", "Ko", "Mo", "Go"] : ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function formatDuration(s) {
  if (!s) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : m;
  return (h ? h + ":" : "") + mm + ":" + String(sec).padStart(2, "0");
}

function fillQualities(options, preferred) {
  qualitySel.replaceChildren(...options.map(([value, label]) => new Option(t(label), value)));
  // La qualité retenue la dernière fois, ou la plus proche en dessous
  const values = options.map(([v]) => v);
  if (values.includes(preferred)) {
    qualitySel.value = preferred;
  } else if (preferred) {
    const below = values.filter((v) => v && Number(v) <= Number(preferred));
    qualitySel.value = below.length ? below[0] : values[values.length - 1];
  }
}

function setMode(next) {
  mode = next;
  document.querySelectorAll(".mode-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.mode === mode));
  document.querySelectorAll(".js-video").forEach((el) => el.classList.toggle("hidden", mode !== "video"));
  document.querySelectorAll(".js-audio").forEach((el) => el.classList.toggle("hidden", mode !== "audio"));
  refreshMp3();
}

function refreshMp3() {
  $(".js-mp3-field").classList.toggle("hidden", audioContainerSel.value !== "mp3");
}

function validUrl(raw) {
  try {
    const u = new URL(raw.trim());
    return /^https?:$/.test(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}

async function analyze() {
  const url = validUrl(urlInput.value);
  const seq = ++analyzeSeq;
  analysis = null;
  $(".js-media").classList.add("hidden");
  fillQualities(STANDARD_QUALITIES, settings.quality);
  sendBtn.disabled = !url;
  if (!url) {
    setStatus(analyzeStatus, urlInput.value.trim() ? "Ce n'est pas un lien http(s)." : "Colle un lien à envoyer.");
    return;
  }
  setStatus(analyzeStatus, "Analyse du lien…");
  try {
    const data = await api(settings.server, "/api/analyze", { method: "POST", body: { url } });
    if (seq !== analyzeSeq) return;
    analysis = data;
    $(".js-title").textContent = data.title;
    $(".js-sub").textContent = [data.source, formatDuration(data.duration)].filter(Boolean).join(" · ");
    const thumb = $(".js-thumb");
    thumb.classList.toggle("hidden", !data.thumbnail);
    if (data.thumbnail) thumb.src = data.thumbnail;
    $(".js-media").classList.remove("hidden");
    if (data.video_formats && data.video_formats.length) {
      fillQualities(data.video_formats.map(({ height, size }) => {
        let label = `${height}p`;
        if (height >= 2160) label += " (4K)";
        else if (height >= 1440) label += " (2K)";
        if (size) label += ` · ≈ ${formatBytes(size)}`;
        return [String(height), label];
      }), settings.quality);
    }
    setStatus(analyzeStatus, "");
  } catch (err) {
    if (seq !== analyzeSeq) return;
    // On laisse quand même envoyer : MediaVior réessaiera de son côté
    setStatus(analyzeStatus, err.message, "error");
  }
}

function choice() {
  if (mode === "video") {
    return { mode, quality: qualitySel.value || null, container: videoContainerSel.value, audio_quality: null };
  }
  const container = audioContainerSel.value;
  return { mode, quality: null, container, audio_quality: container === "mp3" ? audioQualitySel.value : null };
}

async function follow(jobId) {
  const bar = $(".js-progress-bar");
  $(".js-progress").classList.remove("hidden");
  for (;;) {
    let job;
    try {
      job = await api(settings.server, `/api/jobs/${jobId}`);
    } catch {
      return; // la fenêtre suit seulement à titre indicatif
    }
    bar.style.width = `${job.status === "done" ? 100 : job.progress || 0}%`;
    let text = t(STATUS_LABELS[job.status] || job.status);
    if (job.status === "queued" && job.position > 1) text += ` (position ${job.position})`;
    if (job.status === "downloading") text += ` · ${Math.round(job.progress || 0)} %`;
    if (job.status === "error" && job.error) text += `${LANG === "fr" ? " : " : ": "}${t(job.error)}`;
    const kind = job.status === "done" ? "ok" : job.status === "error" ? "error" : "";
    setStatus(sendStatus, text, kind);
    if (!["queued", "downloading", "converting", "processing"].includes(job.status)) return;
    await new Promise((r) => setTimeout(r, 1000));
  }
}

async function send() {
  const url = validUrl(urlInput.value);
  if (!url) return;
  sendBtn.disabled = true;
  setStatus(sendStatus, "Envoi…");
  const picked = choice();
  saveSettings({
    mode,
    quality: mode === "video" ? qualitySel.value : settings.quality,
    videoContainer: videoContainerSel.value,
    audioContainer: audioContainerSel.value,
    audioQuality: audioQualitySel.value,
  });
  const usable = analysis && analysis.url ? analysis : null;
  try {
    const { job_id } = await api(settings.server, "/api/download", {
      method: "POST",
      body: {
        url: usable ? usable.url : url,
        ...picked,
        title: usable ? usable.title : null,
        thumbnail: usable ? usable.thumbnail : null,
      },
    });
    sendBtn.textContent = t("Envoyé ✓");
    setStatus(sendStatus, STATUS_LABELS.queued);
    follow(job_id);
  } catch (err) {
    setStatus(sendStatus, err.message, "error");
    sendBtn.disabled = false;
  }
}

async function currentUrl() {
  const { pendingUrl } = await chrome.storage.session.get("pendingUrl");
  if (pendingUrl) {
    await chrome.storage.session.remove("pendingUrl");
    return pendingUrl;
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab && tab.url && /^https?:/i.test(tab.url) ? tab.url : "";
}

async function init() {
  settings = await getSettings();
  settings.server = await findServer(settings.server);
  videoContainerSel.value = settings.videoContainer;
  audioContainerSel.value = settings.audioContainer;
  audioQualitySel.value = settings.audioQuality;
  setMode(settings.mode);

  document.querySelectorAll(".mode-btn").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  audioContainerSel.addEventListener("change", refreshMp3);
  urlInput.addEventListener("change", analyze);
  urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") urlInput.blur(); });
  sendBtn.addEventListener("click", send);
  $(".js-options").addEventListener("click", (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); });
  $(".js-open-coffre").addEventListener("click", (e) => { e.preventDefault(); chrome.tabs.create({ url: settings.server + "/" }); });

  urlInput.value = await currentUrl();
  if (!urlInput.value) urlInput.focus();
  analyze();
}

init();
