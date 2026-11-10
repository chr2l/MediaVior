// Page vitrine (site public). Les boutons de téléchargement (système de la personne mis en
// avant) et la fenêtre « installer avec une IA » sont gérés par local.js, partagé avec l'appli.

document.querySelectorAll("[data-icon]").forEach((el) => el.append(icon(el.dataset.icon)));

// local.js affiche ses erreurs avec showToast (défini dans shell.js, absent ici)
if (typeof window.showToast !== "function") window.showToast = (text) => alert(text);
