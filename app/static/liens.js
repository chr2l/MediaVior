// Version PC : la fenêtre de l'appli tourne dans Edge/Chrome. Sans ce fichier, les liens
// vers d'autres sites (GitHub, aide…) s'ouvriraient dans ce navigateur-là.
// Ici, on demande à l'appli de les ouvrir dans le navigateur par défaut de l'ordinateur.
function ouvrirAilleurs(e) {
  if (e.defaultPrevented || (e.type === "auxclick" && e.button !== 1)) return;
  const a = e.target.closest && e.target.closest("a[href]");
  if (!a || a.hasAttribute("download")) return;
  let url;
  try {
    url = new URL(a.getAttribute("href"), location.href);
  } catch (err) {
    return;
  }
  if (!/^https?:$/.test(url.protocol) || url.origin === location.origin) return;
  e.preventDefault();
  fetch("/api/local/open-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url.href }),
  }).then((r) => {
    if (!r.ok) throw new Error();
  }).catch(() => window.open(url.href, "_blank", "noopener")); // secours : comme avant
}
document.addEventListener("click", ouvrirAilleurs);
document.addEventListener("auxclick", ouvrirAilleurs);
