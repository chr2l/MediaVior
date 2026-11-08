import { getSettings, saveSettings, normalizeServer, originPattern, api } from "./settings.js";

const input = document.querySelector(".js-server");
const status = document.querySelector(".js-status");
const saveBtn = document.querySelector(".js-save");

function setStatus(text, kind = "") {
  status.textContent = text;
  status.className = "status js-status" + (kind ? " is-" + kind : "");
}

getSettings().then((s) => { input.value = s.server; });

saveBtn.addEventListener("click", async () => {
  let server;
  try {
    server = normalizeServer(input.value);
    if (!server) throw new Error();
  } catch {
    setStatus("Adresse invalide.", "error");
    return;
  }
  input.value = server;
  // La demande doit partir directement du clic, avant tout await
  const granted = await chrome.permissions
    .request({ origins: [originPattern(server)] })
    .catch(() => false);
  await saveSettings({ server });
  if (!granted) {
    setStatus("Enregistré, mais sans l'autorisation d'accès : l'envoi risque d'échouer. Réessaie et accepte la demande.", "error");
    return;
  }
  setStatus("Test en cours…");
  try {
    await api(server, "/api/jobs");
    setStatus("C'est bon : MediaVior répond.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  }
});
