// Navigation de l'appli. Sur ordinateur : la page Télécharger au centre et un panneau fixe à droite
// (onglets En cours / Bibliothèque). Sur téléphone : trois onglets en bas qui affichent l'un ou l'autre.
// Aussi : pastilles de compteur sur les onglets et petite notification en bas d'écran.

const VIEWS = ["telecharger", "encours", "bibliotheque"];
const PANES = ["encours", "bibliotheque"];
const wideQuery = window.matchMedia("(min-width: 961px)");
const toastEl = document.getElementById("toast");
const toastText = document.getElementById("toastText");
const toastAction = document.getElementById("toastAction");
let currentView = null;
let currentPane = "bibliotheque";
let libraryUnseen = 0; // fichiers arrivés pendant que la bibliothèque était cachée
let toastTimer = null;
let toastHandler = null;

document.querySelectorAll("[data-icon]").forEach((el) => el.append(icon(el.dataset.icon)));

function viewFromHash() {
  const name = location.hash.slice(1);
  return VIEWS.includes(name) ? name : VIEWS[0];
}

function libraryVisible() {
  return currentPane === "bibliotheque" && (wideQuery.matches || currentView === "bibliotheque");
}

function showView(name) {
  if (!VIEWS.includes(name)) name = VIEWS[0];
  if (location.hash.slice(1) !== name) history.replaceState(null, "", `#${name}`);
  const changed = name !== currentView;
  currentView = name;
  if (PANES.includes(name)) currentPane = name;
  document.body.dataset.view = name;
  document.querySelectorAll(".pane").forEach((el) => el.classList.toggle("hidden", el.dataset.pane !== currentPane));
  document.querySelectorAll(".tab").forEach((tab) => {
    // Onglets du panneau : celui affiché à droite. Onglets du bas : la vue en cours.
    const inSide = Boolean(tab.closest(".side"));
    const active = tab.dataset.view === (inSide ? currentPane : name);
    tab.classList.toggle("is-active", active);
    if (inSide) tab.setAttribute("aria-selected", String(active));
    else if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  if (changed && !wideQuery.matches) window.scrollTo(0, 0);
  if (libraryVisible()) {
    libraryUnseen = 0;
    setBadge("bibliotheque", 0);
    hideToast();
  }
}

// Après un ajout : sur ordinateur, on montre l'onglet En cours (sur téléphone, on reste sur place)
function revealQueue() {
  if (wideQuery.matches && currentPane !== "encours") showView("encours");
}

wideQuery.addEventListener("change", () => showView(currentView));

// Date de la dernière mise à jour, dans le pied de page
const updatedEl = document.getElementById("updated");
const updatedAt = updatedEl ? new Date(Number(updatedEl.dataset.ts) * 1000) : NaN;
if (!isNaN(updatedAt)) {
  const day = updatedAt.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  const time = updatedAt.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  updatedEl.textContent = `Mis à jour le ${day} à ${time}`;
}

window.addEventListener("hashchange", () => showView(viewFromHash()));
showView(viewFromHash());

function setBadge(view, count) {
  document.querySelectorAll(`.tab[data-view="${view}"] .tab__badge, [data-badge="${view}"]`).forEach((badge) => {
    badge.textContent = count > 99 ? "99+" : String(count);
    badge.classList.toggle("hidden", !count);
  });
}

function announceNewFiles(jobs) {
  if (!jobs.length || libraryVisible()) return;
  libraryUnseen += jobs.length;
  setBadge("bibliotheque", libraryUnseen);
  const text = jobs.length === 1 && jobs[0].title
    ? `« ${jobs[0].title} » est dans le coffre.`
    : `${jobs.length} nouveaux fichiers dans le coffre.`;
  showToast(text, "Voir", () => showView("bibliotheque"));
}

function showToast(text, actionLabel, onAction) {
  toastText.textContent = text;
  toastAction.textContent = actionLabel || "";
  toastAction.classList.toggle("hidden", !actionLabel);
  toastHandler = onAction || null;
  toastEl.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, 6000);
}

function hideToast() {
  clearTimeout(toastTimer);
  toastEl.classList.add("hidden");
}

toastAction.addEventListener("click", () => {
  const handler = toastHandler;
  hideToast();
  if (handler) handler();
});
