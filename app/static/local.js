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

const localBar = document.querySelector(".side__foot");

// Écran d'installation dans la fenêtre de l'appli (plus de fenêtre d'installeur Windows) :
// téléchargement avec pourcentage, puis installation ; MediaVior s'arrête pendant ce temps,
// et la page se recharge toute seule dès que la nouvelle version répond.
function showInstall(version) {
  document.querySelectorAll("dialog[open]").forEach((d) => d.close()); // ex. les Réglages
  const fill = h("div", { class: "progress__fill" });
  const pct = h("span", { class: "progress__text" }, "0 %");
  const bar = h("div", { class: "progress" }, h("div", { class: "progress__track" }, fill), pct);
  const status = h("p", { class: "hint" }, t("Téléchargement de la nouvelle version…"));
  const help = h("p", { class: "hint", hidden: true },
    t("C'est plus long que prévu. Si rien ne bouge, rouvre MediaVior depuis l'icône du bureau."));
  const box = h("div", { class: "install-box" },
    h("h2", {}, t("Mise à jour vers MediaVior {version}", { version })),
    bar, status, help);
  const screen = h("div", { class: "install-screen", role: "status", "aria-live": "polite" }, box);
  document.body.append(screen);
  const started = Date.now();
  let restarting = false;
  const tick = async () => {
    let r = null;
    try {
      r = await api("/api/local/maj");
    } catch (e) {
      /* MediaVior est arrêté pendant l'installation : on attend qu'il revienne */
    }
    const ins = r && r.install;
    if (r && (r.current === version || (restarting && !ins))) {
      status.textContent = t("C'est fait ! MediaVior redémarre…");
      fill.style.width = "100%";
      bar.classList.add("is-done");
      setTimeout(() => location.reload(), 800);
      return;
    }
    if (ins && ins.phase === "error") {
      status.textContent = t("Mise à jour impossible : {error}", { error: ins.error });
      const close = h("button", { type: "button", class: "btn btn--ghost btn--sm" }, t("Fermer"));
      close.addEventListener("click", () => location.reload());
      box.append(close);
      return;
    }
    if (ins && ins.phase === "download") {
      fill.style.width = ins.percent + "%";
      pct.textContent = ins.percent + " %";
    } else {
      restarting = true;
      bar.classList.add("is-busy");
      fill.style.width = "100%";
      pct.textContent = "";
      status.textContent = t("Installation… MediaVior se ferme puis se rouvre tout seul.");
    }
    help.hidden = Date.now() - started < 3 * 60 * 1000;
    setTimeout(tick, 700);
  };
  tick();
}

// Installe la nouvelle version (même chose depuis le panneau ou depuis les Réglages)
async function installUpdate(rel, btn) {
  const msg = rel.auto
    ? t("Installer la nouvelle version ? MediaVior se ferme et se rouvre tout seul (les téléchargements en cours sont arrêtés).")
    : t("Télécharger la nouvelle version ? Ouvre ensuite le fichier et glisse MediaVior dans Applications.");
  if (!confirm(msg)) return;
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = t("Mise à jour…");
  try {
    await api("/api/local/maj", { method: "POST" });
    if (rel.auto) return showInstall(rel.version);
  } catch (e) {
    showToast(e.message);
  }
  btn.disabled = false;
  btn.textContent = label;
}

// Bouton « Mettre à jour » en bas du panneau, et petit rond « ! » sur « Réglages »
let pendingRelease = null;
function showUpdateButton(rel) {
  if (!localBar || !rel.version) return;
  pendingRelease = rel;
  const gear = document.getElementById("settingsBtn");
  if (gear && !gear.querySelector(".side-tool__badge")) {
    gear.classList.add("side-tool--alert");
    gear.title = t("Nouvelle version disponible : {version}.", { version: rel.version });
    gear.append(h("span", { class: "side-tool__badge", "aria-hidden": "true" }, "!"));
  }
  let btn = document.getElementById("updateBtn");
  if (!btn) {
    btn = h("button", { type: "button", class: "btn btn--ghost btn--sm", id: "updateBtn" });
    btn.addEventListener("click", () => installUpdate(btn._rel, btn));
    localBar.prepend(btn);
  }
  btn._rel = rel;
  btn.textContent = t("Mettre à jour ({version})", { version: rel.version });
}

if (localBar) {
  const checkUpdate = async () => {
    try {
      showUpdateButton(await api("/api/local/maj"));
    } catch (e) {
      /* pas de réponse : on réessaiera plus tard */
    }
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
  const splitBox = document.getElementById("settingsSplit");
  const kindsBox = document.getElementById("settingsKinds");
  const audioEl = document.getElementById("settingsAudio");
  const videoEl = document.getElementById("settingsVideo");

  const show = (s) => {
    folderEl.textContent = s.folder;
    if (openFolderBtn) openFolderBtn.title = s.folder;
    moveBox.parentElement.hidden = !s.count;
    autoRow.hidden = s.autostart === null;
    autoBox.checked = !!s.autostart;
    versionEl.textContent = s.version ? t("MediaVior version {v}", { v: s.version }) : "";
    updateRow.hidden = !s.version; // seulement l'appli installée (.exe, .dmg, AppImage)
    if (pendingRelease && !foundRel) showFound(pendingRelease); // déjà détectée en arrière-plan
    const split = Boolean(s.audio_folder || s.video_folder);
    if (split || !kindsBox.hidden) {
      splitBox.checked = true;
      kindsBox.hidden = false;
    }
    audioEl.textContent = s.audio_folder || s.folder;
    videoEl.textContent = s.video_folder || s.folder;
  };
  const save = async (body) => show(await api("/api/local/settings", { method: "POST", body }));

  // « Rechercher une mise à jour » : redemande tout de suite à GitHub
  const updateRow = document.getElementById("settingsUpdateRow");
  const checkBtn = document.getElementById("settingsCheck");
  const installBtn = document.getElementById("settingsInstall");
  const updateMsg = document.getElementById("settingsUpdateMsg");
  let foundRel = null;
  const showFound = (rel) => {
    foundRel = rel;
    updateMsg.textContent = t("Nouvelle version disponible : {version}.", { version: rel.version });
    updateMsg.hidden = false;
    installBtn.textContent = t("Mettre à jour ({version})", { version: rel.version });
    installBtn.hidden = false;
  };
  checkBtn.addEventListener("click", async () => {
    checkBtn.disabled = true;
    checkBtn.textContent = t("Recherche…");
    updateMsg.hidden = true;
    installBtn.hidden = true;
    try {
      const res = await api("/api/local/maj/verifier", { method: "POST" });
      foundRel = null;
      if (res.release && res.release.version) {
        showFound(res.release);
        showUpdateButton(res.release);
      } else {
        updateMsg.textContent = t("MediaVior est à jour.");
      }
    } catch (e) {
      updateMsg.textContent = e.message;
    }
    updateMsg.hidden = false;
    checkBtn.disabled = false;
    checkBtn.textContent = t("Rechercher une mise à jour");
  });
  installBtn.addEventListener("click", () => foundRel && installUpdate(foundRel, installBtn));

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

  // Un dossier pour les sons, un pour les vidéos (ou le même pour les deux)
  splitBox.addEventListener("change", async () => {
    kindsBox.hidden = !splitBox.checked;
    if (splitBox.checked) return; // la personne choisit ensuite chaque dossier
    try {
      await save({ audio_folder: "", video_folder: "" });
      showToast(t("Sons et vidéos arriveront de nouveau dans le dossier principal."));
    } catch (e) {
      showToast(e.message);
    }
  });
  settingsDialog.querySelectorAll("[data-pick-kind]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const kind = btn.dataset.pickKind;
      const current = (kind === "audio" ? audioEl : videoEl).textContent;
      btn.disabled = true;
      try {
        let { path, manual } = await api("/api/local/pick-folder", { method: "POST" });
        if (manual) path = prompt(t("Chemin complet du dossier :"), current);
        if (path) {
          await save({ [`${kind}_folder`]: path.trim() });
          showToast(t(kind === "audio" ? "Les prochains sons arriveront dans ce dossier." : "Les prochaines vidéos arriveront dans ce dossier."));
        }
      } catch (e) {
        showToast(e.message);
      }
      btn.disabled = false;
    });
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
