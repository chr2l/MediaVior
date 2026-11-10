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
// Bouton MediaVior dans le lecteur YouTube (youtube.js) : la page ne peut pas parler à
// l'appli elle-même (127.0.0.1), alors elle passe par ici avec le lien et Vidéo ou Audio.
// Les formats sont ceux choisis la dernière fois dans la fenêtre de l'extension.
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

async function sendToApp({ url, mode, title }) {
  const settings = await getSettings();
  const server = await findServer(settings.server);
  const audio = mode === "audio";
  const body = {
    url,
    mode: audio ? "audio" : "video",
    quality: audio ? null : settings.quality || null,
    container: audio ? settings.audioContainer : settings.videoContainer,
    audio_quality: audio && settings.audioContainer === "mp3" ? settings.audioQuality : null,
    title: title || null,
    thumbnail: null,
  };
  try {
    await fetch(server + "/api/ping", { signal: AbortSignal.timeout(2000) });
  } catch {
    return { ok: false, offline: true };
  }
  const { job_id } = await api(server, "/api/download", { method: "POST", body });
  return { ok: true, job_id };
}
