// MediaVior sur le téléphone : envoie des liens au PC jumelé et récupère les fichiers.
//
// Jumelage : le QR code du PC ouvre cette page avec « #j=paire.invitation.clé ». La clé reste
// sur le téléphone (elle n'est jamais envoyée au relais) et chiffre tous les messages
// (AES-GCM) : le relais ne voit passer que des données illisibles.
// Fichiers : envoyés directement par le PC (WebRTC), sans passer par le relais.
"use strict";

translatePage(); // voir i18n.js

const STORE = "mediavior-jumelage";
const DISMISS = "mediavior-installer-plus-tard";
const $ = (id) => document.getElementById(id);
const enc = new TextEncoder();
const dec = new TextDecoder();

// ---------------------------------------------------------------------------
// Outils
// ---------------------------------------------------------------------------

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

function toast(text, ms = 3200) {
  const el = $("toast");
  el.textContent = t(text);
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), ms);
}

function b64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function unb64(s) {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

function randomId() {
  return b64(crypto.getRandomValues(new Uint8Array(9)));
}

function load(key) {
  try {
    return JSON.parse(localStorage.getItem(key));
  } catch (e) {
    return null;
  }
}

function store(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    /* navigation privée : le jumelage ne sera pas retenu */
  }
}

function formatSize(n) {
  if (!n) return "";
  const units = LANG === "fr" ? ["o", "Ko", "Mo", "Go"] : ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  const value = n.toFixed(i > 1 ? 1 : 0);
  return `${LANG === "fr" ? value.replace(".", ",") : value} ${units[i]}`;
}

const IS_IOS = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const STANDALONE = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

// ---------------------------------------------------------------------------
// Chiffrement de bout en bout
// ---------------------------------------------------------------------------

let aesKey = null;

async function useKey(b64key) {
  aesKey = await crypto.subtle.importKey("raw", unb64(b64key), "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function seal(obj) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: enc.encode("tel>pc") }, aesKey, enc.encode(JSON.stringify(obj))));
  const out = new Uint8Array(12 + ct.length);
  out.set(iv);
  out.set(ct, 12);
  return b64(out);
}

async function unseal(d) {
  const raw = unb64(d);
  const pt = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: raw.subarray(0, 12), additionalData: enc.encode("pc>tel") }, aesKey, raw.subarray(12));
  return JSON.parse(dec.decode(pt));
}

// ---------------------------------------------------------------------------
// Jumelage et connexion au relais
// ---------------------------------------------------------------------------

let pairing = load(STORE); // { p: paire, c: clé, k: code d'accès, id }
let pending = null; // jumelage en cours (QR code scanné)
let ws = null;
let opened = false;
let retry = 0;
let pcOnline = false;
let state = { taches: [], fichiers: [] };

function readLink(text) {
  // « #j=… » : QR code du PC (première fois). « #k=… » : jumelage recopié depuis Safari (iPhone).
  const j = text.match(/[#&]j=([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]{43})/);
  if (j) return { pending: { p: j[1], invite: j[2], c: j[3] } };
  const k = text.match(/[#&]k=([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]+)/);
  if (k) return { pairing: { p: k[1], c: k[2], k: k[3], id: k[4] } };
  return null;
}

function pairingLink(p) {
  return `${location.origin}/#k=${p.p}.${p.c}.${p.k}.${p.id}`;
}

function applyLink(found) {
  if (!found) return false;
  if (found.pending) pending = found.pending;
  if (found.pairing) {
    pairing = found.pairing;
    store(STORE, pairing);
  }
  return true;
}

function cleanUrl() {
  // Sur iPhone, dans Safari, on garde le jumelage dans l'adresse : l'appli ajoutée à l'écran
  // d'accueil ne voit pas les données de Safari, mais elle reprend cette adresse.
  const keep = IS_IOS && !STANDALONE && pairing ? "#k=" + pairingLink(pairing).split("#k=")[1] : "";
  history.replaceState(null, "", location.pathname + keep);
}

function wsUrl(target, query) {
  return `${location.origin.replace(/^http/, "ws")}/ws/tel/${target.p}?${query}`;
}

async function connect() {
  const target = pending || pairing;
  if (!target) return render();
  if (ws && ws.readyState <= 1) return;
  await useKey(target.c);
  const query = pending ? "invite=" + pending.invite : "k=" + pairing.k;
  opened = false;
  ws = new WebSocket(wsUrl(target, query));
  ws.onopen = () => {
    opened = true;
    retry = 0;
  };
  ws.onmessage = (e) => onRelay(e.data).catch((err) => console.warn(err));
  ws.onclose = (e) => onClose(e, target);
}

async function onClose(e, target) {
  ws = null;
  setOnline(false, true);
  if (pending && !opened) {
    // Invitation refusée : QR code expiré ou déjà utilisé
    pending = null;
    showPairError("Ce QR code a expiré ou a déjà servi. Sur le PC, affiche un nouveau QR code et scanne-le.");
    return;
  }
  if (e.code === 4001) return forget("Le PC a oublié ce téléphone. Scanne à nouveau son QR code.");
  if (!opened && pairing && target === pairing) {
    // Le relais a-t-il refusé le code d'accès, ou est-ce seulement le réseau ?
    try {
      const res = await fetch(wsUrl(pairing, "k=" + pairing.k), { cache: "no-store" });
      if (res.status === 403) return forget("Ce téléphone n'est plus relié au PC. Scanne à nouveau son QR code.");
    } catch (err) {
      /* hors ligne : on réessaie plus tard */
    }
  }
  retry = Math.min(retry + 1, 6);
  setTimeout(() => document.visibilityState === "visible" && connect(), 1000 * 2 ** retry);
}

async function onRelay(raw) {
  const msg = JSON.parse(raw);
  if (msg.t === "bienvenue") {
    if (msg.k && pending) {
      pairing = { p: pending.p, c: pending.c, k: msg.k, id: msg.id };
      pending = null;
      store(STORE, pairing);
      cleanUrl();
      toast("Téléphone relié au PC ✓");
    }
    render();
  } else if (msg.t === "pc") {
    setOnline(msg.en_ligne);
    if (msg.en_ligne) send({ t: "bonjour" });
  } else if (msg.t === "m") {
    await onMessage(await unseal(msg.d));
  }
}

async function send(obj) {
  if (!ws || ws.readyState !== 1) throw new Error(t("Pas de connexion au PC."));
  ws.send(JSON.stringify({ t: "m", d: await seal(obj) }));
}

function forget(reason) {
  pairing = null;
  pending = null;
  store(STORE, null);
  if (ws) ws.close();
  history.replaceState(null, "", location.pathname);
  render();
  if (reason) showPairError(reason);
}

function showPairError(text) {
  render();
  const el = $("erreurJumelage");
  el.textContent = t(text);
  el.hidden = false;
}

// Garde la connexion en vie (réponse gratuite du relais) et se reconnecte au retour sur la page
setInterval(() => ws && ws.readyState === 1 && ws.send("ping"), 30000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && (pairing || pending)) {
    retry = 0;
    connect();
  }
});

// ---------------------------------------------------------------------------
// Messages du PC
// ---------------------------------------------------------------------------

async function onMessage(msg) {
  if (msg.t === "etat") {
    state = { taches: msg.taches || [], fichiers: msg.fichiers || [] };
    if (msg.prefs) applyFavorites(msg.prefs);
    const before = pcVersion;
    pcVersion = Number(msg.v) || 0;
    $("majPc").hidden = pcVersion >= 2;
    if (before < 2 && pcVersion >= 2) scheduleAnalyse();
    renderLists();
  } else if (msg.t === "analyse") {
    const done = waiting.get(msg.rid);
    waiting.delete(msg.rid);
    if (done) done(msg);
  } else if (msg.t === "recu") {
    toast(msg.n > 1 ? t("C'est parti : le PC télécharge {n} liens ✓", { n: msg.n }) : "C'est parti : le PC télécharge ✓");
  } else if (msg.t === "erreur") {
    toast(msg.texte || "Le PC a refusé la demande.", 5000);
    if (msg.tid) failTransfer(msg.tid, msg.texte);
  } else if (msg.t === "offre") {
    await acceptOffer(msg);
  }
}

// ---------------------------------------------------------------------------
// Affichage
// ---------------------------------------------------------------------------

function setOnline(on, unknown = false) {
  pcOnline = on;
  const pill = $("statut");
  pill.hidden = !pairing;
  pill.classList.toggle("is-on", on);
  pill.textContent = t(on ? "PC connecté" : unknown ? "Connexion…" : "PC éteint");
  $("envoyer").disabled = !on;
  if (on) scheduleAnalyse();
  $("envoiInfo").textContent = t(on
    ? "Le PC télécharge le fichier. Tu pourras ensuite le récupérer ici."
    : "Allume le PC et ouvre MediaVior : le bouton se réactive tout seul.");
}

function render() {
  const paired = Boolean(pairing) && !pending;
  $("vueJumeler").hidden = paired;
  $("vueAppli").hidden = !paired;
  $("statut").hidden = !paired;
  $("erreurJumelage").hidden = true;
  if (paired) renderLists();
}

const STATUS = {
  queued: "En attente",
  downloading: "Téléchargement",
  converting: "Conversion",
  processing: "Traitement",
  error: "Échec",
  cancelled: "Annulé",
};

function renderLists() {
  const jobs = state.taches.filter((j) => j.status !== "done");
  $("taches").replaceChildren(...jobs.map((j) => {
    const active = ACTIVE.includes(j.status);
    const failed = j.status === "error" || j.status === "cancelled";
    return h("li", { class: "item" },
      h("span", { class: `item__dot item__dot--${j.mode || "video"}` }),
      h("div", { class: "item__body" },
        h("div", { class: "item__title" }, t(j.title || "Lien")),
        h("div", { class: "item__meta" + (j.status === "error" ? " is-error" : "") },
          j.status === "error" ? t(j.error || STATUS.error)
            : [t(STATUS[j.status] || j.status), active ? `${Math.round(j.progress || 0)} %` : null, j.step].filter(Boolean).join(" · ")),
        failed ? null : h("div", { class: "bar" }, h("i", { style: `width:${j.progress || 0}%` }))),
      active && pcVersion >= 2 && !j.cancelling
        ? h("div", { class: "item__actions" }, h("button", {
          type: "button", class: "btn btn--ghost btn--sm", onclick: () => cancelJob(j),
        }, t("Annuler")))
        : null);
  }));
  $("fichiers").replaceChildren(...state.fichiers.map(fileRow));
  $("vide").hidden = jobs.length > 0 || state.fichiers.length > 0;
}

const ACTIVE = ["queued", "downloading", "converting", "processing"];

async function cancelJob(j) {
  if (!confirm(t("Annuler « {titre} » ?", { titre: t(j.title || "Lien") }))) return;
  try {
    j.cancelling = true;
    renderLists();
    await send({ t: "annuler", id: j.id });
  } catch (err) {
    j.cancelling = false;
    renderLists();
    toast(err.message);
  }
}

const rows = new Map(); // id du fichier -> éléments de sa ligne (pour le transfert)

function fileRow(f) {
  const meta = h("div", { class: "item__meta" }, [f.ext && f.ext.toUpperCase(), formatSize(f.size)].filter(Boolean).join(" · "));
  const actions = h("div", { class: "item__actions" });
  const row = h("li", { class: "item" },
    h("span", { class: `item__dot item__dot--${f.ext === "zip" ? "archive" : f.mode || "video"}` }),
    h("div", { class: "item__body" }, h("div", { class: "item__title" }, f.title || f.filename), meta),
    actions);
  const prev = rows.get(f.id);
  rows.set(f.id, { row, meta, actions, f });
  if (prev && prev.done) showSaved(f.id, prev.done);
  else if (transfer && transfer.id === f.id) actions.append(h("span", { class: "item__meta" }, "…"));
  else actions.append(h("button", { type: "button", class: "btn btn--ghost btn--sm", onclick: () => requestFile(f) }, t("Récupérer")));
  return row;
}

// ---------------------------------------------------------------------------
// Envoyer des liens ou des titres : mêmes réglages que l'appli PC
// ---------------------------------------------------------------------------

const OPTIONS = "mediavior-tel-options";
let favorites = null; // préférés reçus du PC { video, audio, quality } ("" = meilleure qualité disponible)
let pcVersion = 0; // 2 et plus : le PC comprend les réglages, plusieurs liens, les titres
let way = "liens";

// Explications courtes sous le choix du format (mêmes phrases que l'appli PC)
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
  aiff: "Non compressé comme le WAV, mais avec titre, artiste et pochette : lu par Rekordbox, Serato et les platines CDJ. Pas meilleur que l'original : les sites diffusent déjà du son compressé.",
};
const MAX_QUALITIES = [
  ["", "Meilleure disponible"],
  ["2160", "4K (2160p) max"],
  ["1440", "1440p max"],
  ["1080", "1080p max"],
  ["720", "720p max"],
  ["480", "480p max"],
];

function extractUrls(text) {
  const urls = (text || "").match(/https?:\/\/[^\s<>"']+/gi) || [];
  return [...new Set(urls.map((u) => u.replace(/[)\]>.,;!?]+$/, "")))];
}

function firstUrl(text) {
  return extractUrls(text)[0] || "";
}

function titleLines() {
  return [...new Set($("titres").value.split(/\n+/).map((s) => s.trim()).filter(Boolean))];
}

function mode() {
  return way === "titres" ? "audio" : document.querySelector('input[name="mode"]:checked').value;
}

function autoGrow(el, max = 160) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight + 2, max)}px`;
}

// --- Réglages retenus d'une fois sur l'autre ---

function saveOptions() {
  store(OPTIONS, {
    mode: document.querySelector('input[name="mode"]:checked').value,
    format: $("format").value,
    formatAudio: $("formatAudio").value,
    debit: $("debit").value,
    zip: $("zip").checked,
    way,
  });
}

function restoreOptions() {
  const o = load(OPTIONS) || {};
  const pick = (id, value) => {
    if (value && [...$(id).options].some((opt) => opt.value === value)) $(id).value = value;
  };
  if (o.mode === "audio") document.querySelector('input[name="mode"][value="audio"]').checked = true;
  pick("format", o.format);
  pick("formatAudio", o.formatAudio);
  pick("debit", o.debit);
  $("zip").checked = Boolean(o.zip);
  if (o.way === "titres") way = "titres";
}

// --- Qualité : vraies définitions du média (après analyse), sinon un plafond ---

let analysis = null; // { url, title, thumbnail, duration, video_formats, audio_size } ou { url, loading } ou { url, error }

function fillQualities() {
  const select = $("qualite");
  const before = select.value;
  const formats = analysis && analysis.video_formats && analysis.video_formats.length && linkCount() === 1
    ? analysis.video_formats : null;
  $("qualiteLabel").textContent = t(formats ? "Qualité" : "Qualité maximale");
  if (formats) {
    select.replaceChildren(...formats.map(({ height, size }) => {
      let label = `${height}p`;
      if (height >= 2160) label += " (4K)";
      else if (height >= 1440) label += " (2K)";
      if (size) label += ` · ≈ ${formatSize(size)}`;
      return h("option", { value: height }, label);
    }));
  } else {
    select.replaceChildren(...MAX_QUALITIES.map(([value, label]) => h("option", { value }, t(label))));
  }
  if ([...select.options].some((o) => o.value === before)) select.value = before;
  else applyQualityFavorite(); // nouvelle liste : la qualité préférée
}

// Taille estimée de chaque format audio (comme sur le PC)
function refreshAudioSizes() {
  const duration = (linkCount() === 1 && analysis && analysis.duration) || 0;
  const audioSize = (linkCount() === 1 && analysis && analysis.audio_size) || 0;
  $("formatAudio").querySelectorAll("option").forEach((opt) => {
    let size = 0;
    if (opt.value === "original") size = audioSize || (duration ? (160000 / 8) * duration : 0);
    else if (opt.value === "mp3") size = duration ? (Number($("debit").value) * 1000 / 8) * duration : 0;
    else size = duration ? (Number(opt.dataset.kbps) * 1000 / 8) * duration : 0;
    const label = t(opt.dataset.label);
    opt.textContent = size ? `${label} · ≈ ${formatSize(size)}` : label;
  });
}

function linkCount() {
  return extractUrls($("lien").value).length;
}

// --- Affichage du formulaire ---

function refreshForm() {
  const titres = way === "titres";
  document.querySelectorAll(".tab").forEach((b) => {
    const on = b.dataset.way === way;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-selected", String(on));
  });
  document.querySelectorAll("[data-panel]").forEach((el) => (el.hidden = el.dataset.panel !== way));

  // Liste de titres : du son seulement, en MP3, WAV ou AIFF (comme sur le PC)
  $("type").hidden = titres;
  $("formatAudio").querySelectorAll("option").forEach((opt) => {
    opt.disabled = titres && !["mp3", "wav", "aiff"].includes(opt.value);
    opt.hidden = opt.disabled;
  });
  if (titres && !["mp3", "wav", "aiff"].includes($("formatAudio").value)) $("formatAudio").value = "mp3";

  const audio = mode() === "audio";
  $("optionsVideo").hidden = audio;
  $("optionsAudio").hidden = !audio;
  $("debit").disabled = $("formatAudio").value !== "mp3";
  $("formatInfo").textContent = t(audio ? AUDIO_HINTS[$("formatAudio").value] : VIDEO_HINTS[$("format").value]);
  refreshAudioSizes();

  const n = linkCount();
  const btn = $("envoyer");
  if (titres) {
    const nt = titleLines().length;
    $("zipChoix").hidden = true;
    $("nbTitres").textContent = nt
      ? t(nt > 1 ? "{n} titres. Le PC cherche chaque son sur YouTube et range tout dans un zip." : "{n} titre. Le PC le cherche sur YouTube et le range dans un zip.", { n: nt })
      : t("Un titre par ligne. Le PC cherche chaque son sur YouTube et range tout dans un zip.");
    btn.textContent = nt > 1 ? t("Chercher les {n} titres", { n: nt }) : t("Chercher sur YouTube");
  } else {
    $("zipChoix").hidden = n < 2;
    $("nbLiens").textContent = n > 1
      ? t("{n} liens trouvés. Mêmes réglages pour tous.", { n })
      : t("Un lien, ou plusieurs (un par ligne).");
    btn.textContent = n > 1
      ? t($("zip").checked ? "Mettre les {n} liens au coffre (zip)" : "Mettre les {n} liens au coffre", { n })
      : t("Mettre au coffre");
  }
  btn.disabled = !pcOnline;
}

function renderPreview() {
  const box = $("apercu");
  const url = extractUrls($("lien").value);
  if (way !== "liens" || url.length !== 1 || !analysis || analysis.url !== url[0]) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const img = $("apercuImg");
  img.hidden = !analysis.thumbnail;
  if (analysis.thumbnail && img.getAttribute("src") !== analysis.thumbnail) img.src = analysis.thumbnail;
  if (analysis.loading) {
    $("apercuTitre").textContent = t("Analyse du lien…");
    $("apercuInfo").textContent = t("Le PC regarde les qualités disponibles.");
  } else if (analysis.error) {
    $("apercuTitre").textContent = t(analysis.error);
    $("apercuInfo").textContent = t("Tu peux quand même l'envoyer.");
  } else {
    $("apercuTitre").textContent = analysis.title || "";
    $("apercuInfo").textContent = [analysis.source, formatDuration(analysis.duration)].filter(Boolean).join(" · ");
  }
}

function formatDuration(s) {
  if (!s) return "";
  s = Math.round(s);
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return hh ? `${hh}:${String(mm).padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
}

// --- Analyse d'un lien seul par le PC (titre, image, qualités disponibles) ---

const waiting = new Map(); // numéro de demande -> fonction à appeler avec la réponse

function ask(obj, ms = 60000) {
  const rid = randomId();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      waiting.delete(rid);
      reject(new Error(t("Le PC ne répond pas.")));
    }, ms);
    waiting.set(rid, (msg) => {
      clearTimeout(timer);
      resolve(msg);
    });
    send({ ...obj, rid }).catch((err) => {
      clearTimeout(timer);
      waiting.delete(rid);
      reject(err);
    });
  });
}

let analyseTimer = null;

function scheduleAnalyse() {
  clearTimeout(analyseTimer);
  analyseTimer = setTimeout(analyseLink, 500);
}

async function analyseLink() {
  const urls = extractUrls($("lien").value);
  if (urls.length !== 1 || pcVersion < 2 || !pcOnline) return refreshAll();
  const url = urls[0];
  if (analysis && analysis.url === url && !analysis.error) return refreshAll();
  analysis = { url, loading: true };
  refreshAll();
  try {
    const res = await ask({ t: "analyse", url });
    if (!analysis || analysis.url !== url) return;
    analysis = res.texte ? { url, error: res.texte } : { url, ...res };
  } catch (err) {
    if (!analysis || analysis.url !== url) return;
    analysis = { url, error: err.message };
  }
  refreshAll();
}

function refreshAll() {
  fillQualities();
  refreshForm();
  renderPreview();
}

// --- Événements ---

document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
  way = b.dataset.way;
  saveOptions();
  refreshAll();
  (way === "titres" ? $("titres") : $("lien")).focus();
}));

["format", "formatAudio", "debit", "zip"].forEach((id) => $(id).addEventListener("change", () => {
  saveOptions();
  refreshForm();
}));
document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", () => {
  saveOptions();
  refreshForm();
}));

$("lien").addEventListener("input", () => {
  autoGrow($("lien"));
  refreshAll();
  scheduleAnalyse();
});
$("lien").addEventListener("keydown", (e) => {
  // Entrée envoie (comme avant) ; Maj + Entrée passe à la ligne pour un autre lien
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("envoi").requestSubmit();
  }
});
$("titres").addEventListener("input", () => {
  autoGrow($("titres"), 260);
  refreshForm();
});

$("envoi").addEventListener("submit", async (e) => {
  e.preventDefault();
  const audio = mode() === "audio";
  const opts = audio
    ? { mode: "audio", quality: null, container: $("formatAudio").value,
        audio_quality: $("formatAudio").value === "mp3" ? $("debit").value : null }
    : { mode: "video", quality: $("qualite").value || null, container: $("format").value, audio_quality: null };
  try {
    if (way === "titres") {
      const titres = titleLines();
      if (!titres.length) return toast("Écris au moins un titre.");
      if (titres.length > 100) return toast("100 titres maximum à la fois.");
      if (pcVersion < 2) return toast("Mets à jour MediaVior sur le PC pour utiliser la liste de titres.", 5000);
      await send({ t: "titres", titres, container: opts.container, audio_quality: opts.audio_quality });
      $("titres").value = "";
      autoGrow($("titres"), 260);
    } else {
      const urls = extractUrls($("lien").value);
      if (!urls.length) return toast("Colle un lien qui commence par http.");
      if (urls.length > 100) return toast("100 liens maximum à la fois.");
      if (urls.length === 1) {
        const a = analysis && analysis.url === urls[0] && !analysis.loading && !analysis.error ? analysis : null;
        await send({ t: "dl", url: urls[0], ...opts, title: a ? a.title : null, thumbnail: a ? a.thumbnail : null });
      } else if (pcVersion >= 2) {
        await send({ t: "liens", urls, zip: $("zip").checked, ...opts });
      } else {
        for (const url of urls) await send({ t: "dl", url, ...opts });
      }
      $("lien").value = "";
      analysis = null;
      autoGrow($("lien"));
    }
    toast("Envoyé au PC…");
    refreshAll();
  } catch (err) {
    toast(err.message);
  }
});

$("coller").addEventListener("click", async () => {
  try {
    const urls = extractUrls(await navigator.clipboard.readText());
    if (!urls.length) return toast("Pas de lien dans le presse-papiers.");
    // Un lien déjà là : on ajoute les nouveaux en dessous (plusieurs liens)
    const current = extractUrls($("lien").value);
    $("lien").value = [...new Set([...current, ...urls])].join("\n");
    autoGrow($("lien"));
    refreshAll();
    scheduleAnalyse();
  } catch (e) {
    $("lien").focus();
    toast("Appuie longuement dans le champ, puis « Coller ».");
  }
});

$("oublier").addEventListener("click", () => {
  if (confirm("Oublier ce PC ? Il faudra rescanner son QR code pour le retrouver.")) forget();
});

// --- Préférés (signet dans les listes) : format vidéo, format audio, qualité vidéo ---
// Gardés par le PC : les mêmes que dans l'appli et l'extension. Un PC trop ancien n'en envoie pas :
// la liste reste alors sans signet.
const FAV_TEXTS = {
  favorite: t("Préféré"),
  mark: t("Choisir comme format préféré"),
  unmark: t("Ne plus en faire le format préféré"),
};
const QUALITY_FAV_TEXTS = {
  favorite: t("Préférée"),
  mark: t("Choisir comme qualité préférée"),
  unmark: t("Ne plus en faire la qualité préférée"),
};
const pickers = {
  quality: MediaViorFormats.enhance($("qualite"), {
    texts: QUALITY_FAV_TEXTS, canFavorite: false, onFavorite: (v) => sendFavorite("quality", v),
  }),
  video: MediaViorFormats.enhance($("format"), {
    texts: FAV_TEXTS, canFavorite: false, alignRight: true, onFavorite: (v) => sendFavorite("video", v),
  }),
  audio: MediaViorFormats.enhance($("formatAudio"), {
    texts: FAV_TEXTS, canFavorite: false, onFavorite: (v) => sendFavorite("audio", v),
  }),
};

async function sendFavorite(kind, container) {
  favorites = { ...favorites, [kind]: container };
  try {
    await send({ t: "pref", kind, container });
  } catch (err) {
    toast(err.message);
  }
}

// Qualité préférée absente de la liste : la plus haute en dessous (sinon la plus basse)
function applyQualityFavorite() {
  const fav = favorites && favorites.quality;
  if (fav == null) return;
  const select = $("qualite");
  const values = [...select.options].map((o) => o.value);
  let v = fav;
  if (!values.includes(fav)) {
    const heights = values.filter((x) => x !== "").map(Number).sort((a, b) => b - a);
    if (!heights.length) return;
    v = String(fav === "" ? heights[0] : heights.find((h) => h <= Number(fav)) ?? heights[heights.length - 1]);
  }
  if (select.value !== v) select.value = v;
}

// Préférés reçus du PC : un préféré nouveau ou changé devient le choix affiché
function applyFavorites(prefs) {
  const before = favorites || { video: null, audio: null, quality: null };
  let changed = favorites === null;
  const next = {};
  ["video", "audio", "quality"].forEach((kind) => {
    const value = prefs[kind] ?? null;
    next[kind] = value;
    const differs = value !== before[kind];
    if (differs) changed = true;
    pickers[kind].setCanFavorite(kind in prefs); // PC sans la qualité préférée : pas de signet
    pickers[kind].setFavorite(value, differs && kind !== "quality");
  });
  favorites = next;
  if (next.quality !== before.quality) applyQualityFavorite();
  if (changed) {
    saveOptions();
    refreshForm();
  }
}

restoreOptions();
refreshAll();

// ---------------------------------------------------------------------------
// Récupérer un fichier : connexion directe avec le PC (WebRTC)
// ---------------------------------------------------------------------------

let transfer = null;

function setMeta(id, text) {
  const r = rows.get(id);
  if (r) r.meta.textContent = t(text);
}

async function requestFile(f) {
  if (transfer) return toast("Un fichier arrive déjà, patiente un instant.");
  transfer = { tid: randomId(), id: f.id, parts: [], received: 0, size: f.size || 0 };
  const r = rows.get(f.id);
  if (r) r.actions.replaceChildren(h("span", { class: "item__meta" }, "…"));
  setMeta(f.id, "Connexion au PC…");
  transfer.timer = setTimeout(() => failTransfer(transfer && transfer.tid), 30000);
  try {
    await send({ t: "get", id: f.id, tid: transfer.tid });
  } catch (err) {
    failTransfer(transfer.tid, err.message);
  }
}

function failTransfer(tid, text) {
  if (!transfer || transfer.tid !== tid) return;
  const { id, pc, opened: wasOpen } = transfer;
  clearTimeout(transfer.timer);
  if (pc) pc.close();
  transfer = null;
  const reason = text || (wasOpen
    ? "Le transfert s'est coupé. Réessaie."
    : "Connexion directe impossible sur ce réseau : le fichier reste sur ton PC.");
  toast(reason, 6000);
  const r = rows.get(id);
  if (r) {
    r.meta.textContent = reason;
    r.actions.replaceChildren(h("button", { type: "button", class: "btn btn--ghost btn--sm", onclick: () => requestFile(r.f) }, t("Réessayer")));
  }
}

function iceGathered(pc, ms) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => pc.iceGatheringState === "complete" && resolve();
    pc.addEventListener("icegatheringstatechange", done);
    setTimeout(resolve, ms);
  });
}

async function acceptOffer(msg) {
  if (!transfer || transfer.tid !== msg.tid) return;
  const pc = new RTCPeerConnection({ iceServers: msg.ice || [] });
  transfer.pc = pc;
  pc.ondatachannel = (e) => receive(e.channel, transfer);
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === "failed" && transfer && transfer.pc === pc) failTransfer(transfer.tid);
  };
  await pc.setRemoteDescription({ type: "offer", sdp: msg.sdp });
  await pc.setLocalDescription(await pc.createAnswer());
  await iceGathered(pc, 4000);
  await send({ t: "reponse", tid: msg.tid, sdp: pc.localDescription.sdp });
}

function receive(channel, tr) {
  channel.binaryType = "arraybuffer";
  let last = 0;
  channel.onopen = () => {
    tr.opened = true;
    clearTimeout(tr.timer);
    setMeta(tr.id, "Réception…");
  };
  channel.onmessage = (e) => {
    if (transfer !== tr) return;
    if (typeof e.data === "string") {
      const m = JSON.parse(e.data);
      if (m.t === "debut") {
        Object.assign(tr, { name: m.nom, type: m.type || "application/octet-stream", size: m.taille });
        clearTimeout(tr.timer);
      } else if (m.t === "fin") {
        finishTransfer(tr);
      } else if (m.t === "erreur") {
        failTransfer(tr.tid, m.texte);
      }
      return;
    }
    tr.parts.push(e.data);
    tr.received += e.data.byteLength;
    const now = Date.now();
    if (now - last > 250) {
      last = now;
      const pct = tr.size ? Math.floor((tr.received / tr.size) * 100) : 0;
      setMeta(tr.id, `${t("Réception")} · ${pct} % · ${formatSize(tr.received)}`);
    }
  };
  channel.onclose = () => transfer === tr && !tr.finished && failTransfer(tr.tid);
}

function finishTransfer(tr) {
  tr.finished = true;
  const blob = new Blob(tr.parts, { type: tr.type });
  tr.parts = [];
  if (tr.pc) tr.pc.close();
  transfer = null;
  const file = new File([blob], tr.name || "fichier", { type: tr.type });
  const done = { file, url: URL.createObjectURL(blob) };
  const r = rows.get(tr.id);
  if (r) r.done = done;
  showSaved(tr.id, done);
  toast("Fichier reçu ✓ Touche « Enregistrer ».");
}

function showSaved(id, done) {
  const r = rows.get(id);
  if (!r) return;
  r.done = done;
  r.meta.textContent = `${t("Reçu")} · ${formatSize(done.file.size)}`;
  const buttons = [h("a", { class: "btn btn--ghost btn--sm", href: done.url, download: done.file.name }, t("Enregistrer"))];
  if (navigator.canShare && navigator.canShare({ files: [done.file] })) {
    buttons.push(h("button", {
      type: "button",
      class: "btn btn--ghost btn--sm",
      onclick: () => navigator.share({ files: [done.file], title: done.file.name }).catch(() => {}),
    }, t("Partager")));
  }
  r.actions.replaceChildren(...buttons);
}

// ---------------------------------------------------------------------------
// Écran d'accueil
// ---------------------------------------------------------------------------

let installEvent = null;

function showInstall(kind) {
  const until = load(DISMISS);
  if (STANDALONE || (until && until > Date.now()) || !matchMedia("(pointer: coarse)").matches) return;
  $("installer").hidden = false;
  $("installerBtn").hidden = kind !== "android";
  $("installerIos").hidden = kind !== "ios";
  $("installerAutre").hidden = kind !== "autre";
}

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installEvent = e;
  showInstall("android");
});

$("installerBtn").addEventListener("click", async () => {
  if (!installEvent) return;
  installEvent.prompt();
  const { outcome } = await installEvent.userChoice;
  installEvent = null;
  if (outcome === "accepted") $("installer").hidden = true;
});

$("installerPlusTard").addEventListener("click", () => {
  store(DISMISS, Date.now() + 7 * 24 * 3600 * 1000);
  $("installer").hidden = true;
});

window.addEventListener("appinstalled", () => ($("installer").hidden = true));

if (IS_IOS) showInstall("ios");
else setTimeout(() => !installEvent && showInstall("autre"), 3000);

// iPhone : l'appli de l'écran d'accueil ne voit pas le jumelage fait dans Safari.
// On propose de le coller (copié depuis Safari) si l'adresse ne l'a pas apporté.
if (IS_IOS && STANDALONE) {
  const btn = h("button", { type: "button", class: "btn btn--ghost", onclick: async () => {
    try {
      if (applyLink(readLink(await navigator.clipboard.readText()))) {
        render();
        connect();
      } else toast("Copie d'abord le jumelage depuis Safari.");
    } catch (e) {
      toast("Impossible de lire le presse-papiers.");
    }
  } }, t("Coller le jumelage copié dans Safari"));
  $("vueJumeler").append(h("p", { class: "hint" }, t("Tu as déjà scanné le QR code dans Safari ? Là-bas, touche « Copier pour l'écran d'accueil », puis reviens ici :")), btn);
}
if (IS_IOS && !STANDALONE) {
  $("vueAppli").append(h("p", { class: "hint" },
    t("Ajouté à l'écran d'accueil, MediaVior s'ouvre déjà relié. Sinon : "),
    h("button", { type: "button", class: "btn-link", onclick: async () => {
      try {
        await navigator.clipboard.writeText(pairingLink(pairing));
        toast("Copié. Ouvre MediaVior depuis l'écran d'accueil et colle-le.");
      } catch (e) {
        toast("Copie impossible.");
      }
    } }, t("Copier pour l'écran d'accueil"))));
}

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

applyLink(readLink(location.hash));
// Partager → MediaVior (Android) : le lien arrive dans l'adresse
const params = new URLSearchParams(location.search);
const shared = firstUrl([params.get("url"), params.get("text"), params.get("title")].join(" "));
if (shared) {
  $("lien").value = extractUrls([params.get("url"), params.get("text"), params.get("title")].join(" ")).join("\n");
  way = "liens";
  autoGrow($("lien"));
  refreshAll();
}
if (location.search || location.hash) cleanUrl();
setOnline(false, true);
render();
connect();
