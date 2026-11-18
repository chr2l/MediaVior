// Infos d'un son (titre, interprètes, album, année, pochette) : recherche sur MusicBrainz et Deezer,
// retouche à la main, écriture dans le fichier. Et « Ajouter mes sons » : ses propres fichiers au coffre.

const tagsDialog = document.getElementById("tagsDialog");
const tagsForm = document.getElementById("tagsForm");
const tagsCover = document.getElementById("tagsCover");
const tagsFile = document.getElementById("tagsFile");
const tagsQuery = document.getElementById("tagsQuery");
const tagsSearchBtn = document.getElementById("tagsSearch");
const tagsInfo = document.getElementById("tagsInfo");
const tagsResults = document.getElementById("tagsResults");
const tagsError = document.getElementById("tagsError");
const tagsSave = document.getElementById("tagsSave");
const TAG_KEYS = ["title", "artist", "album", "album_artist", "year", "track", "genre"];

let tagsItem = null; // le son ouvert
let tagsCoverUrl = null; // pochette choisie dans les suggestions (pas encore enregistrée)
let tagsDuration = null;

document.getElementById("tagsClose").append(icon("close"));
document.getElementById("tagsClose").addEventListener("click", () => tagsDialog.close());
tagsDialog.addEventListener("click", (e) => e.target === tagsDialog && tagsDialog.close());

function showTagsCover(src) {
  tagsCover.replaceChildren(src
    ? h("img", { src, alt: "", referrerpolicy: "no-referrer", onerror: (e) => e.target.replaceWith(icon("music")) })
    : icon("music"));
}

function showTagsError(message) {
  tagsError.textContent = message || "";
  tagsError.classList.toggle("hidden", !message);
}

async function openTags(item) {
  tagsItem = item;
  tagsCoverUrl = null;
  tagsDuration = item.duration || null;
  tagsForm.reset();
  tagsFile.textContent = item.filename;
  tagsInfo.textContent = "";
  tagsResults.replaceChildren();
  tagsQuery.value = "";
  showTagsError("");
  showTagsCover(null);
  tagsSave.disabled = true;
  if (!tagsDialog.open) tagsDialog.showModal();
  try {
    const data = await api(`/api/library/${item.id}/tags`);
    if (tagsItem !== item) return;
    TAG_KEYS.forEach((k) => (tagsForm.elements[k].value = data.tags[k] || ""));
    tagsDuration = data.duration || tagsDuration;
    showTagsCover(data.tags.cover ? `/api/library/${item.id}/cover?v=${Date.now()}` : null);
    tagsQuery.value = [data.guess.artist, data.guess.title].filter(Boolean).join(" - ");
    tagsSave.disabled = false;
    // Champ vide ou mal fait : on cherche tout de suite des suggestions
    if (Object.values(data.noisy).some(Boolean) && tagsQuery.value) searchTags();
  } catch (e) {
    showTagsError(e.message);
  }
}

function splitQuery(text) {
  const m = text.match(/^(.+?)\s+[-–—]\s+(.+)$/);
  return m ? { artist: m[1].trim(), title: m[2].trim() } : { artist: "", title: text.trim() };
}

async function searchTags() {
  const { artist, title } = splitQuery(tagsQuery.value);
  if (!title) {
    tagsQuery.focus();
    return;
  }
  const item = tagsItem;
  tagsSearchBtn.disabled = true;
  tagsInfo.textContent = t("Recherche sur MusicBrainz et Deezer…");
  tagsResults.replaceChildren();
  try {
    const params = new URLSearchParams({ artist, title });
    if (tagsDuration) params.set("duration", Math.round(tagsDuration));
    const data = await api(`/api/tags/search?${params}`);
    if (tagsItem !== item) return;
    tagsInfo.textContent = data.results.length
      ? t("Choisis le bon morceau : ses infos remplissent les champs, que tu peux encore retoucher.")
      : t("Rien trouvé. Essaie « Artiste - Titre » autrement, ou remplis les champs à la main.");
    tagsResults.replaceChildren(...data.results.map(tagsResultRow));
  } catch (e) {
    tagsInfo.textContent = e.message;
  } finally {
    tagsSearchBtn.disabled = false;
  }
}

function tagsResultRow(r) {
  const meta = [
    r.album, r.year, r.genre,
    r.duration ? formatDuration(r.duration) : null,
    r.source,
  ].filter(Boolean).join(" · ");
  const row = h("li", { class: "yt-results__item tags-result" },
    h("div", { class: "tags-result__cover" }, r.cover
      ? h("img", { src: r.cover, alt: "", loading: "lazy", referrerpolicy: "no-referrer", onerror: (e) => e.target.replaceWith(icon("music")) })
      : icon("music")),
    h("div", { class: "yt-results__body" },
      h("div", { class: "yt-results__title" }, `${r.title} — ${r.artist}`),
      h("div", { class: "yt-results__meta" }, meta)),
    h("button", { type: "button", class: "btn btn--ghost btn--sm", onclick: () => useTagsResult(r, row) }, t("Utiliser")));
  return row;
}

function useTagsResult(r, row) {
  TAG_KEYS.forEach((k) => {
    if (r[k]) tagsForm.elements[k].value = r[k];
  });
  if (!r.album_artist && r.album) tagsForm.elements.album_artist.value = r.artist;
  if (r.cover_full) {
    tagsCoverUrl = r.cover_full;
    showTagsCover(r.cover);
  }
  tagsResults.querySelectorAll(".is-playing").forEach((el) => el.classList.remove("is-playing"));
  row.classList.add("is-playing");
  tagsInfo.textContent = t("Suggestion reprise. Vérifie les champs, puis Enregistrer.");
}

tagsSearchBtn.addEventListener("click", searchTags);
tagsQuery.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    searchTags();
  }
});

tagsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!tagsItem) return;
  const body = Object.fromEntries(TAG_KEYS.map((k) => [k, tagsForm.elements[k].value.trim()]));
  body.rename = tagsForm.elements.rename.checked;
  if (tagsCoverUrl) body.cover_url = tagsCoverUrl;
  tagsSave.disabled = true;
  tagsSave.classList.add("is-loading");
  showTagsError("");
  try {
    await api(`/api/library/${tagsItem.id}/tags`, { method: "PUT", body });
    tagsDialog.close();
    showToast(t("Infos enregistrées dans le fichier."));
    loadLibrary();
  } catch (err) {
    showTagsError(err.message);
  } finally {
    tagsSave.disabled = false;
    tagsSave.classList.remove("is-loading");
  }
});

// ---------------------------------------------------------------------------
// Ajouter mes sons : fichiers de l'ordinateur → coffre, infos complétées toutes seules
// ---------------------------------------------------------------------------

const importBtn = document.getElementById("importBtn");
const importInput = document.getElementById("importInput");
const AUDIO_FILE = /\.(mp3|aiff?|wav|flac|m4a|opus|ogg|aac)$/i;
let importing = false;

async function importOne(file) {
  const res = await fetchOrRetry(`/api/library/import?name=${encodeURIComponent(file.name)}`, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/octet-stream" },
  });
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    /* réponse vide */
  }
  if (!res.ok) {
    if (data && data.apercu) document.getElementById("showcasePrompt")?.click();
    throw new Error(data && typeof data.detail === "string" ? t(data.detail) : t("Le serveur a renvoyé une erreur."));
  }
  return data;
}

async function importFiles(list) {
  const files = [...list].filter((f) => AUDIO_FILE.test(f.name));
  if (!files.length) {
    showToast(t("Seuls les fichiers son sont acceptés (MP3, AIFF, WAV, FLAC, M4A, Opus, Ogg)."));
    return;
  }
  if (importing) return;
  importing = true;
  importBtn.disabled = true;
  showView("bibliotheque");
  const added = [];
  const failures = [];
  let filled = 0;
  for (const [i, file] of files.entries()) {
    importBtn.textContent = t("Ajout {i}/{n}…", { i: i + 1, n: files.length });
    try {
      const data = await importOne(file);
      added.push(data.item);
      if (data.filled) filled += 1;
    } catch (e) {
      failures.push(`${file.name} : ${e.message}`);
    }
  }
  importing = false;
  importBtn.disabled = false;
  importBtn.textContent = t("Ajouter mes sons");
  await loadLibrary(added.map((i) => i.id));
  const n = added.length;
  if (n) {
    const text = t(n > 1 ? "{n} sons ajoutés au coffre" : "{n} son ajouté au coffre", { n })
      + (filled ? t(filled > 1 ? ", {k} complétés tout seuls." : ", {k} complété tout seul.", { k: filled }) : ".");
    if (n === 1) showToast(text, t("Voir les infos"), () => openTags(added[0]));
    else showToast(text);
  }
  if (failures.length) alert(`${t("Impossible d'ajouter :")}\n${failures.join("\n")}`);
}

importBtn.addEventListener("click", () => importInput.click());
importInput.addEventListener("change", () => {
  importFiles(importInput.files);
  importInput.value = "";
});

// Glisser-déposer des sons sur le coffre
const libraryPane = document.getElementById("library");
libraryPane.addEventListener("dragover", (e) => {
  if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
  e.preventDefault();
  libraryPane.classList.add("is-dropping");
});
libraryPane.addEventListener("dragleave", (e) => {
  if (!libraryPane.contains(e.relatedTarget)) libraryPane.classList.remove("is-dropping");
});
libraryPane.addEventListener("drop", (e) => {
  if (!e.dataTransfer?.files?.length) return;
  e.preventDefault();
  libraryPane.classList.remove("is-dropping");
  importFiles(e.dataTransfer.files);
});
