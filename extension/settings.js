// Réglages partagés par la fenêtre, les options et le service worker.

export const DEFAULTS = {
  server: "http://127.0.0.1:8010",
  mode: "video",            // "video" | "audio"
  quality: "",              // hauteur max ("" = meilleure disponible)
  videoContainer: "original",
  audioContainer: "mp3",
  audioQuality: "320",
};

export async function getSettings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

export function saveSettings(values) {
  return chrome.storage.sync.set(values);
}

// "127.0.0.1:8010/" → "http://127.0.0.1:8010"
export function normalizeServer(raw) {
  let url = (raw || "").trim();
  if (!url) return "";
  if (!/^https?:\/\//i.test(url)) url = "http://" + url;
  const parsed = new URL(url);
  return parsed.origin + parsed.pathname.replace(/\/+$/, "");
}

// Motif de permission pour l'adresse de MediaVior (ex: "http://127.0.0.1/*").
// Avec cette permission, le navigateur laisse l'extension parler au serveur sans CORS.
export function originPattern(server) {
  const { protocol, hostname } = new URL(server);
  return `${protocol}//${hostname}/*`;
}

export async function api(server, path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } };
  if (init.body && typeof init.body !== "string") {
    init.body = JSON.stringify(init.body);
    init.headers["Content-Type"] = "application/json";
  }
  let resp;
  try {
    resp = await fetch(server + path, init);
  } catch {
    throw new Error("MediaVior ne répond pas. Vérifie l'adresse dans les options et que MediaVior est bien lancé.");
  }
  let data = null;
  try {
    data = await resp.json();
  } catch {
    /* réponse vide */
  }
  if (!resp.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail : `Erreur ${resp.status}`);
  }
  return data;
}
