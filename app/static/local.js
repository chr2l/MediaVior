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

// Met en avant le bouton de téléchargement du système de la personne
const userOs = (() => {
  const ua = navigator.userAgent;
  // Téléphone ou tablette (un iPad se présente comme un Mac, mais tactile) : rien à mettre en avant
  if (/Android|iPhone|iPad|Mobile/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "";
  return /Windows/.test(ua) ? "win" : /Macintosh|Mac OS X/.test(ua) ? "mac" : /Linux/.test(ua) ? "linux" : "";
})();
for (const box of document.querySelectorAll(".dl-buttons")) {
  const mine = userOs && box.querySelector(`[data-os="${userOs}"]`);
  if (!mine) continue;
  mine.classList.add("is-mine");
  mine.lastChild.textContent = "Télécharger pour " + mine.lastChild.textContent;
  box.prepend(mine);
}

for (const opener of [promptOpen, document.getElementById("showcasePrompt")]) {
  if (!opener) continue;
  opener.addEventListener("click", async () => {
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

// ---------------------------------------------------------------------------
// Téléphone relié (QR code) : voir app/jumelage.py
// ---------------------------------------------------------------------------

const phoneDialog = document.getElementById("phoneDialog");
if (phoneDialog) {
  const qrBox = document.getElementById("phoneQr");
  const status = document.getElementById("phoneStatus");
  const forgetBtn = document.getElementById("phoneForget");
  let poll = null;
  let shownAt = 0;

  const setStatus = (text, kind = "") => {
    status.textContent = text;
    status.className = "phone-dialog__status" + (kind ? " is-" + kind : "");
  };

  const showStatus = (s) => {
    forgetBtn.hidden = !s.jumeles;
    if (!s.dispo) return setStatus(s.raison || "Indisponible pour l'instant.", "error");
    if (s.nouveau > shownAt) return setStatus("Téléphone relié ✓ Tu peux fermer cette fenêtre.", "ok");
    if (s.erreur && !s.connecte) return setStatus(s.erreur, "error");
    if (!s.connecte) return setStatus("Connexion au relais…");
    const n = s.jumeles;
    setStatus(n ? `${n} téléphone${n > 1 ? "s" : ""} relié${n > 1 ? "s" : ""}${s.en_ligne ? `, ${s.en_ligne} connecté${s.en_ligne > 1 ? "s" : ""} en ce moment` : ""}.`
      : "En attente du téléphone…");
  };

  const newQr = async () => {
    qrBox.replaceChildren(h("span", { class: "hint" }, "Préparation du QR code…"));
    try {
      const s = await api("/api/local/telephone/qr", { method: "POST" });
      shownAt = Date.now() / 1000;
      qrBox.replaceChildren(h("img", { src: s.qr, alt: "QR code à scanner avec le téléphone" }));
      showStatus(s);
    } catch (e) {
      qrBox.replaceChildren(h("span", { class: "hint" }, e.message));
    }
  };

  const refresh = async () => {
    try {
      showStatus(await api("/api/local/telephone"));
    } catch (e) {
      /* fenêtre en cours de fermeture */
    }
  };

  document.getElementById("phoneClose").append(icon("close"));
  document.getElementById("phoneClose").addEventListener("click", () => phoneDialog.close());
  phoneDialog.addEventListener("click", (e) => e.target === phoneDialog && phoneDialog.close());
  phoneDialog.addEventListener("close", () => clearInterval(poll));
  document.getElementById("phoneNewQr").addEventListener("click", newQr);
  forgetBtn.addEventListener("click", async () => {
    if (!confirm("Oublier tous les téléphones reliés ? Il faudra rescanner un QR code.")) return;
    try {
      await api("/api/local/telephone/oublier", { method: "POST" });
      await newQr();
    } catch (e) {
      showToast(e.message);
    }
  });
  document.getElementById("phoneBtn").addEventListener("click", () => {
    phoneDialog.showModal();
    newQr();
    clearInterval(poll);
    poll = setInterval(refresh, 2000);
  });
}

// ---------------------------------------------------------------------------
// Nouvelle version de l'appli prête à installer (.exe, .dmg, AppImage)
// ---------------------------------------------------------------------------

const localBar = document.querySelector(".topbar__local");
if (localBar) {
  const checkUpdate = async () => {
    let rel;
    try {
      rel = await api("/api/local/maj");
    } catch (e) {
      return;
    }
    if (!rel.version || document.getElementById("updateBtn")) return;
    const btn = h("button", { type: "button", class: "btn btn--ghost btn--sm", id: "updateBtn" },
      `Mettre à jour (${rel.version})`);
    btn.addEventListener("click", async () => {
      const msg = rel.auto
        ? "Installer la nouvelle version ? MediaVior se ferme et se rouvre tout seul (les téléchargements en cours sont arrêtés)."
        : "Télécharger la nouvelle version ? Ouvre ensuite le fichier et glisse MediaVior dans Applications.";
      if (!confirm(msg)) return;
      btn.disabled = true;
      btn.textContent = "Mise à jour…";
      try {
        await api("/api/local/maj", { method: "POST" });
        if (rel.auto) showToast("Installation en cours : MediaVior va se rouvrir.");
      } catch (e) {
        showToast(e.message);
      }
      btn.disabled = false;
      btn.textContent = `Mettre à jour (${rel.version})`;
    });
    localBar.prepend(btn);
  };
  setTimeout(checkUpdate, 8000);
  setInterval(checkUpdate, 30 * 60 * 1000);
}
