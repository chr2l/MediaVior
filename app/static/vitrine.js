// Page vitrine (site public) : icônes, sommaire du haut. Les boutons de téléchargement
// (système de la personne mis en avant) et la fenêtre « autres façons d'installer » sont dans
// local.js, partagé avec l'appli.

document.querySelectorAll("[data-icon]").forEach((el) => el.append(icon(el.dataset.icon)));

// local.js affiche ses erreurs avec showToast (défini dans shell.js, absent ici)
if (typeof window.showToast !== "function") window.showToast = (text) => alert(text);

// Sommaire du haut : met en avant la partie en cours de lecture
const navLinks = [...document.querySelectorAll(".v-top__nav a")];
const parts = navLinks.map((a) => document.querySelector(a.getAttribute("href")));
function markCurrent() {
  let current = null;
  for (const [i, part] of parts.entries()) {
    if (part && part.getBoundingClientRect().top - 120 <= 0) current = navLinks[i];
  }
  navLinks.forEach((a) => a.classList.toggle("is-active", a === current));
}
window.addEventListener("scroll", markCurrent, { passive: true });
markCurrent();
