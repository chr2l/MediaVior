// Navigation de l'appli : trois onglets (Télécharger / Liste de sons / Bibliothèque),
// pastilles de compteur sur les onglets et petite notification en bas d'écran.

const VIEWS = ["telecharger", "sons", "bibliotheque"];
const toastEl = document.getElementById("toast");
const toastText = document.getElementById("toastText");
const toastAction = document.getElementById("toastAction");
let currentView = null;
let libraryUnseen = 0; // fichiers arrivés pendant qu'on regardait ailleurs
let toastTimer = null;
let toastHandler = null;

document.querySelectorAll("[data-icon]").forEach((el) => el.append(icon(el.dataset.icon)));

function viewFromHash() {
  const name = location.hash.slice(1);
  return VIEWS.includes(name) ? name : VIEWS[0];
}

function showView(name) {
  if (!VIEWS.includes(name)) name = VIEWS[0];
  if (location.hash.slice(1) !== name) history.replaceState(null, "", `#${name}`);
  if (name === currentView) return;
  currentView = name;
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("hidden", el.dataset.view !== name));
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.view === name;
    tab.classList.toggle("is-active", active);
    if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
  if (name === "bibliotheque") {
    libraryUnseen = 0;
    setBadge("bibliotheque", 0);
    hideToast();
  }
}

// Date de la dernière mise à jour, en bas à droite
const updatedEl = document.getElementById("updated");
const updatedAt = new Date(Number(updatedEl.dataset.ts) * 1000);
if (!isNaN(updatedAt)) {
  const day = updatedAt.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  const time = updatedAt.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  updatedEl.textContent = `Mis à jour le ${day} à ${time}`;
}

window.addEventListener("hashchange", () => showView(viewFromHash()));
showView(viewFromHash());

function setBadge(view, count) {
  const badge = document.querySelector(`.tab[data-view="${view}"] .tab__badge`);
  if (!badge) return;
  badge.textContent = count > 99 ? "99+" : String(count);
  badge.classList.toggle("hidden", !count);
}

function announceNewFiles(jobs) {
  if (!jobs.length || currentView === "bibliotheque") return;
  libraryUnseen += jobs.length;
  setBadge("bibliotheque", libraryUnseen);
  const text = jobs.length === 1 && jobs[0].title
    ? `« ${jobs[0].title} » est dans la bibliothèque.`
    : `${jobs.length} nouveaux fichiers dans la bibliothèque.`;
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
