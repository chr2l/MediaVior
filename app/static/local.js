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
    if (busy && !confirm(t("Des téléchargements sont en cours. Quitter quand même ?"))) return;
    try {
      await api("/api/local/quit", { method: "POST" });
    } catch (e) {
      /* le serveur s'arrête : rien à afficher */
    }
    document.body.replaceChildren(
      h("div", { class: "quit-screen" },
        h("p", {}, t("MediaVior est fermé. Tu peux fermer cette fenêtre.")),
        h("p", { class: "hint" }, t("Pour le rouvrir : double-clic sur l'icône MediaVior du bureau."))),
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
  const res = await fetch(`/api/prompt?lang=${LANG}`);
  if (!res.ok) throw new Error(t("Prompt introuvable."));
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
  mine.lastChild.textContent = t("Télécharger pour {os}", { os: mine.lastChild.textContent });
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
    promptCopy.textContent = t("Copié ✓");
    setTimeout(() => (promptCopy.textContent = t("Copier le prompt")), 2000);
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
    if (!s.dispo) return setStatus(t(s.raison || "Indisponible pour l'instant."), "error");
    if (s.nouveau > shownAt) return setStatus(t("Téléphone relié ✓ Tu peux fermer cette fenêtre."), "ok");
    if (s.erreur && !s.connecte) return setStatus(t(s.erreur), "error");
    if (!s.connecte) return setStatus(t("Connexion au relais…"));
    const n = s.jumeles;
    if (!n) return setStatus(t("En attente du téléphone…"));
    const linked = t(n > 1 ? "{n} téléphones reliés" : "{n} téléphone relié", { n });
    const online = s.en_ligne
      ? t(s.en_ligne > 1 ? ", {n} connectés en ce moment" : ", {n} connecté en ce moment", { n: s.en_ligne })
      : "";
    setStatus(`${linked}${online}.`);
  };

  const newQr = async () => {
    qrBox.replaceChildren(h("span", { class: "hint" }, t("Préparation du QR code…")));
    try {
      const s = await api("/api/local/telephone/qr", { method: "POST" });
      shownAt = Date.now() / 1000;
      qrBox.replaceChildren(h("img", { src: s.qr, alt: t("QR code à scanner avec le téléphone") }));
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
    if (!confirm(t("Oublier tous les téléphones reliés ? Il faudra rescanner un QR code."))) return;
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
// Extension de navigateur, sans le Chrome Web Store : voir /api/local/extension
// ---------------------------------------------------------------------------

const extDialog = document.getElementById("extDialog");
if (extDialog) {
  const pathEl = document.getElementById("extPath");
  const prepareBtn = document.getElementById("extPrepare");
  const copyBtn = document.getElementById("extCopy");
  const showPath = (text, kind = "") => {
    pathEl.textContent = text;
    pathEl.className = "ext-steps__path" + (kind ? " is-" + kind : "");
  };

  document.getElementById("extClose").append(icon("close"));
  document.getElementById("extClose").addEventListener("click", () => extDialog.close());
  extDialog.addEventListener("click", (e) => e.target === extDialog && extDialog.close());
  document.getElementById("extBtn").addEventListener("click", async () => {
    extDialog.showModal();
    try {
      const info = await api("/api/local/extension");
      if (info.ready) showPath(t("Dossier prêt : {folder}", { folder: info.folder }), "ok");
    } catch (e) {
      /* pas grave : le bouton « Préparer » refera la demande */
    }
  });
  prepareBtn.addEventListener("click", async () => {
    prepareBtn.disabled = true;
    try {
      const { folder } = await api("/api/local/extension", { method: "POST" });
      showPath(t("Dossier prêt : {folder}", { folder }), "ok");
    } catch (e) {
      showPath(e.message, "error");
    }
    prepareBtn.disabled = false;
  });
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText("chrome://extensions");
      copyBtn.textContent = t("Copié ✓");
      setTimeout(() => (copyBtn.textContent = t("Copier")), 2000);
    } catch (e) {
      showToast(t("Copie impossible : sélectionne l'adresse et copie-la à la main."));
    }
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
      t("Mettre à jour ({version})", { version: rel.version }));
    btn.addEventListener("click", async () => {
      const msg = rel.auto
        ? t("Installer la nouvelle version ? MediaVior se ferme et se rouvre tout seul (les téléchargements en cours sont arrêtés).")
        : t("Télécharger la nouvelle version ? Ouvre ensuite le fichier et glisse MediaVior dans Applications.");
      if (!confirm(msg)) return;
      btn.disabled = true;
      btn.textContent = t("Mise à jour…");
      try {
        await api("/api/local/maj", { method: "POST" });
        if (rel.auto) showToast(t("Installation en cours : MediaVior va se rouvrir."));
      } catch (e) {
        showToast(e.message);
      }
      btn.disabled = false;
      btn.textContent = t("Mettre à jour ({version})", { version: rel.version });
    });
    localBar.prepend(btn);
  };
  setTimeout(checkUpdate, 8000);
  setInterval(checkUpdate, 30 * 60 * 1000);
}

// ---------------------------------------------------------------------------
// Réglages : dossier des médias, lancement au démarrage de l'ordinateur
// ---------------------------------------------------------------------------

const settingsDialog = document.getElementById("settingsDialog");
if (settingsDialog) {
  const folderEl = document.getElementById("settingsFolder");
  const pickBtn = document.getElementById("settingsPick");
  const moveBox = document.getElementById("settingsMove");
  const autoBox = document.getElementById("settingsAutostart");
  const autoRow = document.getElementById("settingsAutostartRow");
  const versionEl = document.getElementById("settingsVersion");

  const show = (s) => {
    folderEl.textContent = s.folder;
    if (openFolderBtn) openFolderBtn.title = s.folder;
    moveBox.parentElement.hidden = !s.count;
    autoRow.hidden = s.autostart === null;
    autoBox.checked = !!s.autostart;
    versionEl.textContent = s.version ? t("MediaVior version {v}", { v: s.version }) : "";
  };
  const save = async (body) => show(await api("/api/local/settings", { method: "POST", body }));

  document.getElementById("settingsClose").append(icon("close"));
  document.getElementById("settingsClose").addEventListener("click", () => settingsDialog.close());
  settingsDialog.addEventListener("click", (e) => e.target === settingsDialog && settingsDialog.close());
  document.getElementById("settingsBtn").addEventListener("click", async () => {
    settingsDialog.showModal();
    try {
      show(await api("/api/local/settings"));
    } catch (e) {
      showToast(e.message);
    }
  });

  pickBtn.addEventListener("click", async () => {
    pickBtn.disabled = true;
    try {
      let { path, manual } = await api("/api/local/pick-folder", { method: "POST" });
      if (manual) path = prompt(t("Chemin complet du dossier où ranger les médias :"), folderEl.textContent);
      if (path) {
        await save({ folder: path.trim(), move: moveBox.checked });
        showToast(t("Les prochains médias arriveront dans ce dossier."));
        if (moveBox.checked && typeof loadLibrary === "function") loadLibrary();
      }
    } catch (e) {
      showToast(e.message);
    }
    pickBtn.disabled = false;
  });

  autoBox.addEventListener("change", async () => {
    try {
      await save({ autostart: autoBox.checked });
    } catch (e) {
      autoBox.checked = !autoBox.checked;
      showToast(e.message);
    }
  });
}
