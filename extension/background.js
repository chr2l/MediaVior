// Clic droit sur une page ou un lien : « Envoyer à MediaVior… »
// Le lien est mis de côté, puis la fenêtre de l'extension s'ouvre dessus.

const MENU_ID = "lecoffre-send";

chrome.runtime.onInstalled.addListener((details) => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: chrome.i18n.getMessage("menuSend"),
    contexts: ["page", "link", "video", "audio"],
  });
  if (details.reason === "install") chrome.runtime.openOptionsPage();
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  const url = info.linkUrl || info.srcUrl || info.pageUrl || (tab && tab.url);
  if (!url) return;
  // Une vidéo lue via un blob: n'a pas d'adresse utilisable : on prend celle de la page
  const usable = /^https?:/i.test(url) ? url : info.pageUrl;
  await chrome.storage.session.set({ pendingUrl: usable });
  try {
    await chrome.action.openPopup();
  } catch {
    // Navigateur trop ancien pour ouvrir la fenêtre tout seul : petite fenêtre à part
    chrome.windows.create({ url: "popup.html?window=1", type: "popup", width: 400, height: 620 });
  }
});
