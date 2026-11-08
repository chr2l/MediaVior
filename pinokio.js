// Pinokio (https://pinokio.co) : installe et lance MediaVior en un clic.
module.exports = {
  version: "3.7",
  title: "MediaVior",
  description: "Sauvegarde des vidéos et des musiques depuis un lien (YouTube, SoundCloud, Bandcamp…), sur ton PC.",
  icon: "app/static/icons/icon-512.png",
  menu: async (kernel, info) => {
    const installed = info.exists("env");
    const running = {
      install: info.running("install.js"),
      start: info.running("start.js"),
      update: info.running("update.js"),
    };
    if (running.install) {
      return [{ default: true, icon: "fa-solid fa-plug", text: "Installation…", href: "install.js" }];
    }
    if (!installed) {
      return [{ default: true, icon: "fa-solid fa-plug", text: "Installer", href: "install.js" }];
    }
    if (running.start) {
      const local = info.local("start.js");
      if (local && local.url) {
        return [
          { default: true, icon: "fa-solid fa-rocket", text: "Ouvrir MediaVior", href: local.url },
          { icon: "fa-solid fa-terminal", text: "Terminal", href: "start.js" },
        ];
      }
      return [{ default: true, icon: "fa-solid fa-terminal", text: "Démarrage…", href: "start.js" }];
    }
    if (running.update) {
      return [{ default: true, icon: "fa-solid fa-rotate", text: "Mise à jour…", href: "update.js" }];
    }
    return [
      { default: true, icon: "fa-solid fa-power-off", text: "Lancer", href: "start.js" },
      { icon: "fa-solid fa-rotate", text: "Mettre à jour", href: "update.js" },
      { icon: "fa-solid fa-plug", text: "Réinstaller", href: "install.js" },
    ];
  },
};
