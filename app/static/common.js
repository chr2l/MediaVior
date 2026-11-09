// Outils partagés entre la page principale et l'éditeur.

// Traduction de la page (voir i18n.js), avant que les autres scripts y touchent
translatePage();

async function api(path, options = {}) {
  const init = { ...options };
  if (init.body && typeof init.body !== "string") {
    init.body = JSON.stringify(init.body);
    init.headers = { "Content-Type": "application/json", ...(init.headers || {}) };
  }
  const res = await fetch(path, init);
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    /* réponse vide */
  }
  if (!res.ok) {
    // Page web en aperçu : on propose de télécharger l'appli au lieu d'agir sur le serveur
    if (data && data.apercu) {
      const dialog = document.getElementById("promptDialog");
      if (dialog && !dialog.open) document.getElementById("showcasePrompt")?.click();
    }
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? t(detail) : t("Le serveur a renvoyé une erreur."));
  }
  return data;
}

// Création d'éléments DOM sans innerHTML (les titres viennent de sites tiers)
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

// Icônes statiques (contenu de confiance, injecté en SVG)
const ICONS = {
  download: '<path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 19h14"/>',
  scissors: '<circle cx="6" cy="7" r="2.5"/><circle cx="6" cy="17" r="2.5"/><path d="M8.2 8.3L19 16M8.2 15.7L19 8"/>',
  trash: '<path d="M5 7h14M10 4h4M7 7l1 13h8l1-13M10 11v6M14 11v6"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M8 5h3v14H8zM13 5h3v14h-3z" fill="currentColor" stroke="none"/>',
  music: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  film: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M8 5v14M16 5v14M3.5 9.5H8M3.5 14.5H8M16 9.5h4.5M16 14.5h4.5"/>',
  back: '<path d="M14.5 6L8.5 12l6 6"/>',
  archive: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 4v2m0 2v2m0 2v2"/><rect x="10.5" y="14" width="3" height="3" rx="0.5"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
  library: '<path d="M4.5 4.5h4v15h-4zM10 4.5h4v15h-4z"/><path d="M15.6 5.6l3.9-1 3 14.6-3.9 1z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  box: '<path d="M3.5 8l8.5-4 8.5 4v8.5L12 20.5 3.5 16.5z"/><path d="M3.5 8L12 12l8.5-4M12 12v8.5"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h7"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
  // Logo de MediaVior (dessin ASCII du coffre d'elie.place, en lisse) : cadre, hublot, deux réglages
  safe: '<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><rect x="5.5" y="7.5" width="7.5" height="9" rx="1.5"/><circle cx="9.25" cy="11" r="1.6"/><path d="M16 10h2.5M16 14h2.5"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
  disk: '<ellipse cx="12" cy="6" rx="7.5" ry="2.5"/><path d="M4.5 6v12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5V6M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
  folder: '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2"/>',
  image: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M20.5 16l-5-5-8 8"/>',
};

function icon(name) {
  const span = document.createElement("span");
  span.className = "icon";
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
  return span;
}

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return "";
  const s = Math.max(0, Math.round(seconds));
  const hrs = Math.floor(s / 3600);
  const min = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return hrs ? `${hrs}:${String(min).padStart(2, "0")}:${sec}` : `${min}:${sec}`;
}

// Temps au dixième de seconde, pour l'éditeur : 1:23.4
function formatTime(seconds) {
  const t = Math.max(0, seconds);
  const hrs = Math.floor(t / 3600);
  const min = Math.floor((t % 3600) / 60);
  const sec = (t % 60).toFixed(1).padStart(4, "0");
  return hrs ? `${hrs}:${String(min).padStart(2, "0")}:${sec}` : `${min}:${sec}`;
}

// Accepte "83.5", "1:23.5" ou "1:01:23.5" ; renvoie null si illisible
function parseTime(text) {
  const parts = String(text).trim().replace(",", ".").split(":");
  if (!parts.length || parts.length > 3 || parts.some((p) => p === "" || isNaN(Number(p)))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

function formatBytes(bytes) {
  if (!bytes) return "";
  const units = LANG === "fr" ? ["o", "Ko", "Mo", "Go", "To"] : ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let i = 0;
  while (value >= 1000 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  const digits = value < 10 && i > 0 ? 1 : 0;
  return `${value.toLocaleString(LOCALE, { maximumFractionDigits: digits })} ${units[i]}`;
}

function formatDate(timestamp) {
  const date = new Date(timestamp * 1000);
  const now = new Date();
  const time = date.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return t("aujourd'hui, {time}", { time });
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return t("hier, {time}", { time });
  return date.toLocaleDateString(LOCALE, {
    day: "numeric",
    month: "short",
    year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}

// Installation comme appli (nécessite HTTPS, ou localhost)
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
