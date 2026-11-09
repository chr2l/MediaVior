// Langue de l'interface : français ou anglais.
//
// Le texte reste écrit en français dans le HTML et le JS. La traduction anglaise est dans
// i18n-en.js : la clé est la phrase française exacte, la valeur sa traduction.
// - Dans le HTML : rien à faire, translateDom() traduit les textes et les attributs
//   (placeholder, title, aria-label, alt, data-label) qu'il trouve dans le dictionnaire
//   (ou dans I18N_EN_PATTERNS, pour les phrases qui contiennent un nombre ou un nom).
// - Dans le JS : t("Phrase en français {n}", { n: 3 }) renvoie la bonne langue.
// Une phrase absente du dictionnaire reste en français : rien ne casse.
//
// Choix de la langue : le bouton « English / Français » (gardé dans ce navigateur), sinon la
// langue du navigateur ou du système : français si elle commence par « fr », anglais sinon.
// Ce fichier est chargé dans <head>, avant tous les autres scripts.
// Copie de app/static/i18n.js (même moteur) : garder les deux pareils. Dans l'extension, la
// langue suit celle du navigateur (le nom et le menu clic droit viennent de _locales/).

(function () {
  let saved = null;
  try {
    saved = localStorage.getItem("mediavior-lang");
  } catch (e) {
    /* stockage bloqué */
  }
  const nav = (navigator.languages && navigator.languages[0]) || navigator.language || "fr";
  const lang = saved === "fr" || saved === "en" ? saved : /^fr\b/i.test(nav) ? "fr" : "en";
  window.LANG = lang;
  window.LOCALE = lang === "fr" ? "fr-FR" : nav.toLowerCase().startsWith("en") ? nav : "en-GB";
  document.documentElement.lang = lang;
  // En anglais, la page reste cachée le temps de la traduire (pas d'éclair de français)
  if (lang === "en") {
    document.documentElement.classList.add("i18n-wait");
    const style = document.createElement("style");
    style.textContent = ".i18n-wait body{visibility:hidden}";
    document.head.append(style);
    // Filet de sécurité : la page s'affiche quoi qu'il arrive
    setTimeout(() => document.documentElement.classList.remove("i18n-wait"), 1500);
  }
})();

const I18N = window.LANG === "en" ? window.I18N_EN || {} : {};
const I18N_PATTERNS = window.LANG === "en" ? window.I18N_EN_PATTERNS || [] : [];

// Traduit une phrase française. vars remplace {nom} dans le résultat.
function t(fr, vars) {
  let s = fr == null ? "" : String(fr);
  if (window.LANG === "en" && s) {
    if (Object.prototype.hasOwnProperty.call(I18N, s)) {
      s = I18N[s];
    } else {
      for (const [re, rep] of I18N_PATTERNS) {
        if (re.test(s)) {
          s = s.replace(re, rep);
          break;
        }
      }
    }
  }
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  return s;
}

const I18N_ATTRS = ["placeholder", "title", "aria-label", "alt", "data-label"];
const I18N_SKIP = new Set(["SCRIPT", "STYLE", "PRE", "TEXTAREA", "CODE"]);

// Traduit les textes d'une partie de la page (ou de toute la page)
function translateDom(root) {
  if (window.LANG !== "en" || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const parent = node.parentElement;
    if (parent && (I18N_SKIP.has(parent.tagName) || parent.closest("[data-no-i18n]"))) return;
    const raw = node.nodeValue;
    const core = raw.replace(/\s+/g, " ").trim();
    if (!core) return;
    const en = t(core);
    if (en === core) return;
    const lead = /^\s/.test(raw) ? " " : "";
    const trail = /\s$/.test(raw) ? " " : "";
    node.nodeValue = lead + en + trail;
  });
  root.querySelectorAll("*").forEach((el) => {
    I18N_ATTRS.forEach((attr) => {
      const value = el.getAttribute(attr);
      if (!value) return;
      const core = value.replace(/\s+/g, " ").trim();
      if (Object.prototype.hasOwnProperty.call(I18N, core)) el.setAttribute(attr, I18N[core]);
    });
  });
  // Liens vers la documentation anglaise : <a href="…fr…" data-href-en="…en…">
  root.querySelectorAll("[data-href-en]").forEach((el) => el.setAttribute("href", el.dataset.hrefEn));
  root.querySelectorAll("template").forEach((tpl) => translateDom(tpl.content));
}

function setLang(lang) {
  try {
    localStorage.setItem("mediavior-lang", lang);
  } catch (e) {
    /* stockage bloqué */
  }
  location.reload();
}

// Traduit la page et branche les boutons [data-lang-switch]. Appelé par le premier script du
// bas de page (common.js), avant que les autres scripts lisent ou écrivent dans la page.
function translatePage() {
  translateDom(document.body);
  document.title = t(document.title);
  document.querySelectorAll("[data-lang-switch]").forEach((btn) => {
    const other = window.LANG === "fr" ? "en" : "fr";
    btn.textContent = other === "en" ? "English" : "Français";
    btn.setAttribute("lang", other);
    btn.addEventListener("click", () => setLang(other));
  });
  document.documentElement.classList.remove("i18n-wait");
}
