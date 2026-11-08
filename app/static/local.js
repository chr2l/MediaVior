// Version PC (ouvrir le dossier, quitter) et prompt pour installer MediaVior chez soi.

const openFolderBtn = document.getElementById("openFolderBtn");
if (openFolderBtn) {
  openFolderBtn.addEventListener("click", () => {
    api("/api/local/open-folder", { method: "POST" }).catch((e) => showToast(e.message));
  });
}

const quitBtn = document.getElementById("quitBtn");
if (quitBtn) {
  quitBtn.addEventListener("click", async () => {
    const busy = document.querySelector("#queueList li");
    if (busy && !confirm("Des téléchargements sont en cours. Quitter quand même ?")) return;
    try {
      await api("/api/local/quit", { method: "POST" });
    } catch (e) {
      /* le serveur s'arrête : rien à afficher */
    }
    document.body.replaceChildren(
      h("div", { class: "quit-screen" },
        h("p", {}, "MediaVior est fermé. Tu peux fermer cette fenêtre."),
        h("p", { class: "hint" }, "Pour le rouvrir : double-clic sur l'icône MediaVior du bureau.")),
    );
    setTimeout(() => window.close(), 400);
  });
}

const promptDialog = document.getElementById("promptDialog");
const promptOpen = document.getElementById("promptOpen");
const promptText = document.getElementById("promptText");
const promptCopy = document.getElementById("promptCopy");
document.getElementById("promptClose").append(icon("close"));
document.getElementById("promptClose").addEventListener("click", () => promptDialog.close());
promptDialog.addEventListener("click", (e) => {
  if (e.target === promptDialog) promptDialog.close(); // clic sur le fond
});

async function loadPrompt() {
  if (promptText.value) return promptText.value;
  const res = await fetch("/api/prompt");
  if (!res.ok) throw new Error("Prompt introuvable.");
  promptText.value = await res.text();
  return promptText.value;
}

if (promptOpen) {
  promptOpen.addEventListener("click", async () => {
    promptDialog.showModal();
    try {
      await loadPrompt();
    } catch (e) {
      promptText.value = e.message;
    }
  });
}

promptCopy.addEventListener("click", async () => {
  try {
    const text = await loadPrompt();
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      // http:// sur le réseau local : pas d'accès au presse-papiers moderne
      promptText.select();
      document.execCommand("copy");
    }
    promptCopy.textContent = "Copié ✓";
    setTimeout(() => (promptCopy.textContent = "Copier le prompt"), 2000);
  } catch (e) {
    showToast(e.message);
  }
});
