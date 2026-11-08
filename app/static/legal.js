// Sommaire : met en avant la partie en cours de lecture (et la garde visible sur téléphone).
const links = [...document.querySelectorAll("#toc a")];
const sections = links.map((a) => document.querySelector(a.getAttribute("href")));

function setActive(id) {
  links.forEach((a) => {
    const on = a.getAttribute("href") === `#${id}`;
    a.classList.toggle("is-active", on);
    if (on) {
      a.setAttribute("aria-current", "true");
      a.scrollIntoView({ block: "nearest", inline: "nearest" });
    } else a.removeAttribute("aria-current");
  });
}

function update() {
  // La dernière partie dont le titre est passé sous le haut de l'écran
  const offset = window.innerWidth <= 820 ? 80 : 40;
  let current = sections[0];
  for (const s of sections) if (s.getBoundingClientRect().top - offset <= 0) current = s;
  // Tout en bas de la page : la dernière partie, même courte
  if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) current = sections.at(-1);
  setActive(current.id);
}

links.forEach((a) => a.addEventListener("click", () => setTimeout(() => setActive(a.getAttribute("href").slice(1)), 0)));
window.addEventListener("scroll", update, { passive: true });
window.addEventListener("resize", update);
update();
