// MediaVior sur le téléphone : envoie des liens au PC jumelé et récupère les fichiers.
//
// Jumelage : le QR code du PC ouvre cette page avec « #j=paire.invitation.clé ». La clé reste
// sur le téléphone (elle n'est jamais envoyée au relais) et chiffre tous les messages
// (AES-GCM) : le relais ne voit passer que des données illisibles.
// Fichiers : envoyés directement par le PC (WebRTC), sans passer par le relais.
"use strict";

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
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), ms);
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
  const units = ["o", "Ko", "Mo", "Go"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i > 1 ? 1 : 0).replace(".", ",")} ${units[i]}`;
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
  if (!ws || ws.readyState !== 1) throw new Error("Pas de connexion au PC.");
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
  el.textContent = text;
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
    renderLists();
  } else if (msg.t === "recu") {
    toast("C'est parti : le PC télécharge ✓");
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
  pill.textContent = on ? "PC connecté" : unknown ? "Connexion…" : "PC éteint";
  $("envoyer").disabled = !on;
  $("envoiInfo").textContent = on
    ? "Le PC télécharge le fichier. Tu pourras ensuite le récupérer ici."
    : "Allume le PC et ouvre MediaVior : le bouton se réactive tout seul.";
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
  $("taches").replaceChildren(...jobs.map((j) => h("li", { class: "item" },
    h("span", { class: `item__dot item__dot--${j.mode || "video"}` }),
    h("div", { class: "item__body" },
      h("div", { class: "item__title" }, j.title || "Lien"),
      h("div", { class: "item__meta" + (j.status === "error" ? " is-error" : "") },
        j.status === "error" ? j.error || STATUS.error : `${STATUS[j.status] || j.status} · ${Math.round(j.progress || 0)} %`),
      j.status === "error" ? null : h("div", { class: "bar" }, h("i", { style: `width:${j.progress || 0}%` }))),
  )));
  $("fichiers").replaceChildren(...state.fichiers.map(fileRow));
  $("vide").hidden = jobs.length > 0 || state.fichiers.length > 0;
}

const rows = new Map(); // id du fichier -> éléments de sa ligne (pour le transfert)

function fileRow(f) {
  const meta = h("div", { class: "item__meta" }, [f.ext && f.ext.toUpperCase(), formatSize(f.size)].filter(Boolean).join(" · "));
  const actions = h("div", { class: "item__actions" });
  const row = h("li", { class: "item" },
    h("span", { class: `item__dot item__dot--${f.mode || "video"}` }),
    h("div", { class: "item__body" }, h("div", { class: "item__title" }, f.title || f.filename), meta),
    actions);
  const prev = rows.get(f.id);
  rows.set(f.id, { row, meta, actions, f });
  if (prev && prev.done) showSaved(f.id, prev.done);
  else if (transfer && transfer.id === f.id) actions.append(h("span", { class: "item__meta" }, "…"));
  else actions.append(h("button", { type: "button", class: "btn btn--ghost btn--sm", onclick: () => requestFile(f) }, "Récupérer"));
  return row;
}

// ---------------------------------------------------------------------------
// Envoyer un lien
// ---------------------------------------------------------------------------

function firstUrl(text) {
  const m = (text || "").match(/https?:\/\/[^\s<>"']+/i);
  return m ? m[0] : "";
}

$("envoi").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = firstUrl($("lien").value) || $("lien").value.trim();
  if (!/^https?:\/\//i.test(url)) return toast("Colle un lien qui commence par http.");
  const mode = document.querySelector('input[name="mode"]:checked').value;
  try {
    await send({ t: "dl", url, mode });
    $("lien").value = "";
    toast("Envoyé au PC…");
  } catch (err) {
    toast(err.message);
  }
});

$("coller").addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    const url = firstUrl(text);
    if (url) $("lien").value = url;
    else toast("Pas de lien dans le presse-papiers.");
  } catch (e) {
    $("lien").focus();
    toast("Appuie longuement dans le champ, puis « Coller ».");
  }
});

$("oublier").addEventListener("click", () => {
  if (confirm("Oublier ce PC ? Il faudra rescanner son QR code pour le retrouver.")) forget();
});

// ---------------------------------------------------------------------------
// Récupérer un fichier : connexion directe avec le PC (WebRTC)
// ---------------------------------------------------------------------------

let transfer = null;

function setMeta(id, text) {
  const r = rows.get(id);
  if (r) r.meta.textContent = text;
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
    r.actions.replaceChildren(h("button", { type: "button", class: "btn btn--ghost btn--sm", onclick: () => requestFile(r.f) }, "Réessayer"));
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
      setMeta(tr.id, `Réception · ${pct} % · ${formatSize(tr.received)}`);
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
  r.meta.textContent = `Reçu · ${formatSize(done.file.size)}`;
  const buttons = [h("a", { class: "btn btn--ghost btn--sm", href: done.url, download: done.file.name }, "Enregistrer")];
  if (navigator.canShare && navigator.canShare({ files: [done.file] })) {
    buttons.push(h("button", {
      type: "button",
      class: "btn btn--ghost btn--sm",
      onclick: () => navigator.share({ files: [done.file], title: done.file.name }).catch(() => {}),
    }, "Partager"));
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
  } }, "Coller le jumelage copié dans Safari");
  $("vueJumeler").append(h("p", { class: "hint" }, "Tu as déjà scanné le QR code dans Safari ? Là-bas, touche « Copier pour l'écran d'accueil », puis reviens ici :"), btn);
}
if (IS_IOS && !STANDALONE) {
  $("vueAppli").append(h("p", { class: "hint" },
    "Ajouté à l'écran d'accueil, MediaVior s'ouvre déjà relié. Sinon : ",
    h("button", { type: "button", class: "btn-link", onclick: async () => {
      try {
        await navigator.clipboard.writeText(pairingLink(pairing));
        toast("Copié. Ouvre MediaVior depuis l'écran d'accueil et colle-le.");
      } catch (e) {
        toast("Copie impossible.");
      }
    } }, "Copier pour l'écran d'accueil")));
}

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

applyLink(readLink(location.hash));
// Partager → MediaVior (Android) : le lien arrive dans l'adresse
const params = new URLSearchParams(location.search);
const shared = firstUrl([params.get("url"), params.get("text"), params.get("title")].join(" "));
if (shared) $("lien").value = shared;
if (location.search || location.hash) cleanUrl();
setOnline(false, true);
render();
connect();
