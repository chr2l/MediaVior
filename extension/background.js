import { getSettings, findServer, api } from "./settings.js";

// Clic droit sur une page ou un lien : « Envoyer à MediaVior… »
// Le lien est mis de côté, puis la fenêtre de l'extension s'ouvre dessus.
// L'appli MediaVior de ce PC est trouvée toute seule : rien à régler après l'ajout.

const MENU_ID = "lecoffre-send";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: chrome.i18n.getMessage("menuSend"),
    contexts: ["page", "link", "video", "audio"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  const url = info.linkUrl || info.srcUrl || info.pageUrl || (tab && tab.url);
  if (!url) return;
  // Une vidéo lue via un blob: n'a pas d'adresse utilisable : on prend celle de la page
  const usable = /^https?:/i.test(url) ? url : info.pageUrl;
  await openPopupOn(usable);
});

// Ouvre la fenêtre de l'extension, déjà remplie avec ce lien
async function openPopupOn(url) {
  await chrome.storage.session.set({ pendingUrl: url });
  try {
    await chrome.action.openPopup();
  } catch {
    // Navigateur trop ancien pour ouvrir la fenêtre tout seul : petite fenêtre à part
    chrome.windows.create({ url: "popup.html?window=1", type: "popup", width: 400, height: 620 });
  }
}

// ---------------------------------------------------------------------------
// Bouton MediaVior sur les sites (page.js) : la page ne peut pas parler à l'appli elle-même
// (127.0.0.1), alors elle passe par ici avec le lien (ou, pour Spotify et Deezer, le titre à
// chercher sur YouTube) et les choix faits dans le menu : Vidéo ou Audio, qualité, format.
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === "mediavior-popup") {
    openPopupOn(msg.url);
    return false;
  }
  if (!msg || msg.type !== "mediavior-send") return false;
  sendToApp(msg).then(reply, (err) => reply({ ok: false, detail: err.message }));
  return true; // réponse envoyée plus tard
});

const MAX_SEARCH_DURATION = 15 * 60; // écarte les mix et albums entiers trouvés sur YouTube

async function sendToApp({ url, query, mode, quality, container, audio_quality, title }) {
  const settings = await getSettings();
  const server = await findServer(settings.server);
  try {
    await fetch(server + "/api/ping", { signal: AbortSignal.timeout(2000) });
  } catch {
    return { ok: false, offline: true };
  }
  let found = null;
  if (query) {
    // Morceau protégé (Spotify, Deezer) : la même chanson, trouvée sur YouTube par l'appli
    const results = await api(server, "/api/sons/search?q=" + encodeURIComponent(query));
    const pick = (results || []).find((r) => !r.duration || r.duration <= MAX_SEARCH_DURATION);
    if (!pick) return { ok: false, notFound: true };
    url = `https://www.youtube.com/watch?v=${pick.id}`;
    found = pick.title;
  }
  const audio = mode === "audio";
  const body = {
    url,
    mode: audio ? "audio" : "video",
    quality: audio ? null : quality || null,
    container: container || (audio ? settings.audioContainer : settings.videoContainer),
    audio_quality: audio ? audio_quality || null : null,
    title: title || null,
    thumbnail: null,
  };
  const { job_id } = await api(server, "/api/download", { method: "POST", body });
  return { ok: true, job_id, found };
}
