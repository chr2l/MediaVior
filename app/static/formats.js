// Choix du format (ou de la qualité) avec un « préféré » (signet).
// Remplace l'affichage d'une liste <select> par une liste maison : au survol, et sur le format
// choisi, un signet apparaît. Un clic sur le signet en fait le format préféré : il passe en
// haut de la liste et devient le choix par défaut. Un seul préféré à la fois : en marquer un
// autre enlève le précédent ; un nouveau clic sur le signet l'enlève.
// Le <select> reste dans la page (caché) : le reste du code continue de lire sa valeur.
// Styles : formats.css (couleurs réglées par chaque page avec les variables --mvf-…).
// Mêmes fichiers dans app/static/, relais/public/ (téléphone) et extension/ : garder les trois copies identiques.

(function () {
  if (window.MediaViorFormats) return;

  const NS = "http://www.w3.org/2000/svg";

  function svg(viewBox, attrs, d) {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", viewBox);
    s.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(NS, "path");
    for (const [k, v] of Object.entries(attrs)) p.setAttribute(k, v);
    p.setAttribute("d", d);
    s.append(p);
    return s;
  }

  // Signet : contour seul, ou plein pour le format préféré
  function bookmark(filled) {
    return svg("0 0 24 24", {
      fill: filled ? "currentColor" : "none", stroke: "currentColor", "stroke-width": "2",
      "stroke-linejoin": "round",
    }, "M6 3.5h12a1 1 0 0 1 1 1V21l-7-4.6L5 21V4.5a1 1 0 0 1 1-1z");
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  let uid = 0;

  // select : la liste à remplacer. options :
  //   favorite : valeur préférée au départ (ou null ; "" est une vraie valeur, ex. « Meilleure disponible »)
  //   onFavorite(value | null) : appelé quand la personne marque ou enlève le préféré
  //   texts : { favorite, mark, unmark } (textes déjà traduits)
  //   canFavorite : false = pas de signet (ex. téléphone relié à un PC trop ancien)
  function enhance(select, options = {}) {
    const texts = {
      favorite: "Préféré",
      mark: "Choisir comme format préféré",
      unmark: "Ne plus en faire le format préféré",
      ...(options.texts || {}),
    };
    let favorite = options.favorite == null ? null : options.favorite;
    let canFavorite = options.canFavorite !== false;
    const id = `mvf-${++uid}`;

    const wrap = el("div", "mvf" + (options.alignRight ? " mvf--right" : ""));
    const trigger = el("button", "mvf__trigger");
    trigger.type = "button";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", id);
    const value = el("span", "mvf__value");
    const mark = bookmark(true);
    mark.classList.add("mvf__mark");
    const chev = svg("0 0 12 8", { fill: "none", stroke: "currentColor", "stroke-width": "1.6" }, "M1 1l5 5 5-5");
    chev.classList.add("mvf__chev");
    trigger.append(value, mark, chev);
    const list = el("ul", "mvf__list");
    list.id = id;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrap.append(trigger, list);
    // Avant la liste d'origine : dans un <label>, un clic sur le texte ouvre alors cette liste-ci
    select.before(wrap);
    wrap.append(select);
    select.classList.add("mvf__native");
    select.tabIndex = -1;

    const usable = () => [...select.options].filter((o) => !o.disabled && !o.hidden);
    const has = (v) => usable().some((o) => o.value === v);

    // Le préféré en haut, puis les autres dans leur ordre habituel
    function ordered() {
      const opts = usable();
      const fav = opts.find((o) => o.value === favorite);
      return fav ? [fav, ...opts.filter((o) => o !== fav)] : opts;
    }

    function choose(v) {
      if (select.value === v) return;
      select.value = v;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function render() {
      const current = select.options[select.selectedIndex];
      value.textContent = current ? current.textContent : "";
      mark.style.display = canFavorite && current && current.value === favorite ? "" : "none";
      trigger.disabled = select.disabled;
      if (!list.hidden) renderList();
    }

    function renderList() {
      const focused = document.activeElement && list.contains(document.activeElement)
        ? document.activeElement.closest(".mvf__opt") : null;
      const focusedValue = focused ? focused.dataset.value : null;
      const focusedStar = Boolean(document.activeElement && document.activeElement.classList.contains("mvf__star"));
      list.replaceChildren(...ordered().map((o) => {
        const fav = canFavorite && o.value === favorite;
        const li = el("li", "mvf__opt" + (o.value === select.value ? " is-selected" : "") + (fav ? " is-fav" : ""));
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(o.value === select.value));
        li.tabIndex = -1;
        li.dataset.value = o.value;
        li.append(el("span", "mvf__label", o.textContent));
        if (fav) li.append(el("span", "mvf__tag", texts.favorite));
        if (canFavorite) {
          const star = el("button", "mvf__star");
          star.type = "button";
          star.title = fav ? texts.unmark : texts.mark;
          star.setAttribute("aria-label", star.title);
          star.setAttribute("aria-pressed", String(fav));
          star.append(bookmark(fav));
          li.append(star);
        }
        return li;
      }));
      if (focusedValue != null) {
        const again = list.querySelector(`.mvf__opt[data-value="${CSS.escape(focusedValue)}"]`);
        if (again) (focusedStar ? again.querySelector(".mvf__star") || again : again).focus();
      }
    }

    function open() {
      if (select.disabled || !list.hidden) return;
      list.hidden = false;
      wrap.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
      renderList();
      const sel = list.querySelector(".is-selected") || list.querySelector(".mvf__opt");
      if (sel) sel.focus({ preventScroll: true });
    }

    function close(focusTrigger) {
      if (list.hidden) return;
      list.hidden = true;
      wrap.classList.remove("is-open");
      trigger.setAttribute("aria-expanded", "false");
      if (focusTrigger) trigger.focus();
    }

    function toggleFavorite(v) {
      favorite = favorite === v ? null : v;
      if (favorite !== null) choose(favorite);
      render();
      if (options.onFavorite) options.onFavorite(favorite);
    }

    trigger.addEventListener("click", (e) => {
      e.preventDefault();
      if (list.hidden) open();
      else close(true);
    });
    trigger.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        open();
      }
    });

    list.addEventListener("click", (e) => {
      e.preventDefault(); // dans un <label> : pas de clic renvoyé vers le bouton
      e.stopPropagation();
      const li = e.target.closest(".mvf__opt");
      if (!li) return;
      if (e.target.closest(".mvf__star")) {
        toggleFavorite(li.dataset.value);
        return;
      }
      choose(li.dataset.value);
      close(true);
    });

    list.addEventListener("keydown", (e) => {
      const rows = [...list.querySelectorAll(".mvf__opt")];
      const li = document.activeElement && document.activeElement.closest(".mvf__opt");
      const i = rows.indexOf(li);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
        if (next) next.focus();
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close(true);
      } else if ((e.key === "Enter" || e.key === " ") && li && !e.target.closest(".mvf__star")) {
        e.preventDefault();
        choose(li.dataset.value);
        close(true);
      } else if (li && canFavorite && (e.key === "f" || e.key === "F")) {
        e.preventDefault();
        toggleFavorite(li.dataset.value);
      }
    });

    // Clic ailleurs ou focus parti ailleurs : on ferme
    const outside = (e) => {
      if (!wrap.isConnected) return document.removeEventListener("pointerdown", outside, true); // menu refermé
      if (!wrap.contains(e.target)) close(false);
    };
    document.addEventListener("pointerdown", outside, true);
    wrap.addEventListener("focusout", (e) => {
      if (e.relatedTarget && !wrap.contains(e.relatedTarget)) close(false);
    });

    // La liste d'origine change (tailles estimées, options cachées, valeur…) : on suit
    new MutationObserver(render).observe(select, {
      subtree: true, childList: true, characterData: true, attributes: true,
    });
    select.addEventListener("change", render);
    // Valeur changée par le code (select.value = …) : aucun événement, alors on l'intercepte
    const desc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
    Object.defineProperty(select, "value", {
      configurable: true,
      get() { return desc.get.call(this); },
      set(v) { desc.set.call(this, v); render(); },
    });
    render();

    return {
      render,
      close,
      get favorite() { return favorite; },
      // Préféré venu d'ailleurs (autre fenêtre, extension, téléphone). apply : le choisir aussi.
      setFavorite(v, apply) {
        favorite = v == null ? null : v;
        if (apply && favorite !== null && has(favorite)) choose(favorite);
        render();
      },
      setCanFavorite(on) {
        canFavorite = Boolean(on);
        render();
      },
    };
  }

  window.MediaViorFormats = { enhance };
})();
