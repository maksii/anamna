(() => {
  const strings = globalThis.__HL_I18N__ || {};
  const tr = (key, fallback) => strings[key] || fallback;
  const pageFromHash = (hash) => {
    const match = /page-?=?(\d+)/i.exec(String(hash || ""));
    return match ? Math.max(1, Number(match[1])) : null;
  };
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const pageUrl = (template, page) => String(template || "").replace("{page}", String(page));

  function createMedia({ mime, src, pageSrc, title, page }) {
    if (String(mime).startsWith("image/") || pageSrc) {
      const img = document.createElement("img");
      img.className = `viewer-media${pageSrc ? " rendered-page" : ""}`;
      img.dataset.sourceFrame = "";
      img.src = pageSrc ? pageUrl(pageSrc, page) : src;
      img.alt = `${title} · ${tr("viewer.page", "Page")} ${page}`;
      return img;
    }
    const frame = document.createElement("iframe");
    frame.className = "viewer-media";
    frame.dataset.sourceFrame = "";
    frame.title = title;
    frame.src = `${src}#page=${page}`;
    return frame;
  }

  function bindViewer(root) {
    const stage = root.querySelector("[data-viewer-stage]");
    const titleEl = root.querySelector("[data-viewer-title]");
    const openTab = root.querySelector("[data-open-tab]");
    const pager = root.querySelector("[data-pager]");
    const input = root.querySelector("[data-page-input]");
    const totalEl = root.querySelector("[data-page-total]");
    const prev = root.querySelector("[data-page-prev]");
    const next = root.querySelector("[data-page-next]");
    const zoomOut = root.querySelector("[data-zoom-out]");
    const zoomIn = root.querySelector("[data-zoom-in]");
    const fit = root.querySelector("[data-fit]");
    const rotate = root.querySelector("[data-rotate]");
    let page = pageFromHash(location.hash) || 1;
    let zoom = 1;
    let rotation = 0;
    // The printed row of the value the reader is on, as page fractions.
    let box = null;
    let revealBox = false;
    const reduceMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)");

    function state() {
      return {
        src: root.dataset.src,
        pageSrc: root.dataset.pageSrc || "",
        mime: root.dataset.mime || "",
        pages: Math.max(1, Number(root.dataset.pages || 1)),
        title: titleEl?.textContent?.trim() || tr("viewer.source_fallback", "Source"),
        isPaged: Boolean(root.dataset.pageSrc) || (root.dataset.mime || "").includes("pdf"),
      };
    }

    function applyView() {
      const media = stage?.querySelector("img[data-source-frame]");
      if (!media) {
        root.querySelector("[data-viewer-stage]")?.classList.remove("is-zoomable");
        return;
      }
      stage.classList.add("is-zoomable");
      media.style.width = zoom === 1 ? "calc(100% - 32px)" : `${zoom * 100}%`;
      media.style.maxWidth = "none";
      media.style.transform = `rotate(${rotation}deg)`;
      if (fit) fit.textContent = `${Math.round(zoom * 100)}%`;
      drawBox();
    }

    // The outline over the page image.  Drawn from the image's laid-out size,
    // so it follows zoom; hidden while the page is rotated, because the text
    // layer's coordinates are the upright page's and an outline in the wrong
    // place is worse than none.
    function drawBox() {
      const media = stage?.querySelector("img[data-source-frame]");
      let outline = stage?.querySelector("[data-viewer-mark]");
      if (!media || !box || rotation || !media.complete || !media.naturalWidth) {
        if (outline) outline.hidden = true;
        return;
      }
      if (!outline) {
        outline = document.createElement("div");
        outline.className = "viewer-mark";
        outline.dataset.viewerMark = "";
        outline.setAttribute("aria-hidden", "true");
        stage.append(outline);
      }
      const [x0, y0, x1, y1] = box;
      const width = media.offsetWidth;
      const height = media.offsetHeight;
      // A little air around the glyphs, so the outline frames the row
      // rather than cutting through its ascenders.
      const padX = 4;
      const padY = 3;
      outline.style.left = `${media.offsetLeft + x0 * width - padX}px`;
      outline.style.top = `${media.offsetTop + y0 * height - padY}px`;
      outline.style.width = `${(x1 - x0) * width + 2 * padX}px`;
      outline.style.height = `${(y1 - y0) * height + 2 * padY}px`;
      outline.hidden = false;
      if (!revealBox) return;
      revealBox = false;
      const top = media.offsetTop + y0 * height;
      const bottom = media.offsetTop + y1 * height;
      const left = media.offsetLeft + x0 * width;
      const right = media.offsetLeft + x1 * width;
      const target = { top: stage.scrollTop, left: stage.scrollLeft };
      // Only when it leaves the middle of the stage: one that jumps on every
      // card is one nobody can read, and a row parked on the bottom edge has
      // none of the rows after it in view.
      if (top < stage.scrollTop + stage.clientHeight * 0.12 || bottom > stage.scrollTop + stage.clientHeight * 0.75) {
        target.top = Math.max(0, top - stage.clientHeight * 0.3);
      }
      if (left < stage.scrollLeft || right > stage.scrollLeft + stage.clientWidth) {
        target.left = Math.max(0, left - 16);
      }
      if (target.top !== stage.scrollTop || target.left !== stage.scrollLeft) {
        stage.scrollTo({ ...target, behavior: reduceMotion?.matches ? "auto" : "smooth" });
      }
    }

    function mark(nextBox, { reveal = true } = {}) {
      const valid = Array.isArray(nextBox) && nextBox.length === 4 && nextBox.every(Number.isFinite);
      box = valid ? nextBox : null;
      revealBox = valid && reveal;
      drawBox();
    }

    function renderMedia(nextPage) {
      const currentState = state();
      if (!stage || !currentState.src) return;
      stage.classList.add("is-loading");
      const replacement = createMedia({ ...currentState, page: nextPage });
      if (replacement.tagName === "IMG") {
        replacement.addEventListener("load", () => {
          stage.classList.remove("is-loading");
          applyView();
        }, { once: true });
        replacement.addEventListener("error", () => stage.classList.remove("is-loading"), { once: true });
      } else {
        replacement.addEventListener("load", () => stage.classList.remove("is-loading"), { once: true });
      }
      stage.replaceChildren(replacement);
      applyView();
    }

    function setPage(nextPage, { syncHash = false, source = "" } = {}) {
      const currentState = state();
      const previous = page;
      page = clamp(Number(nextPage) || 1, 1, currentState.pages);
      box = null;
      zoom = 1;
      rotation = 0;
      if (input) {
        input.value = String(page);
        input.max = String(currentState.pages);
      }
      if (totalEl) totalEl.textContent = `/ ${currentState.pages}`;
      if (pager) pager.hidden = !currentState.isPaged || currentState.pages <= 1;
      if (prev) prev.disabled = page <= 1;
      if (next) next.disabled = page >= currentState.pages;
      renderMedia(page);
      if (syncHash) history.replaceState(null, "", `#page-${page}`);
      // Only a page the reader chose: a turn the results list asked for must
      // not be answered by the list scrolling to the page it is already on.
      if (source === "reader" && page !== previous) {
        root.dispatchEvent(new CustomEvent("hl:viewer-page", { detail: { page } }));
      }
    }

    function loadDocument({ src, pageSrc, mime, pages, title, page: startPage = 1, syncHash = false } = {}) {
      if (!src) return;
      root.dataset.src = src;
      root.dataset.pageSrc = pageSrc || "";
      root.dataset.mime = mime || "";
      root.dataset.pages = String(pages || 1);
      if (titleEl && title) titleEl.textContent = title;
      if (openTab) openTab.href = src;
      setPage(startPage, { syncHash });
    }

    function setZoom(value) {
      zoom = clamp(value, 0.5, 2.5);
      applyView();
    }

    root.goToPage = (n, opts) => setPage(n, opts);
    root.currentPage = () => page;
    root.mark = mark;
    root.loadDocument = loadDocument;
    const byReader = { syncHash: true, source: "reader" };
    prev?.addEventListener("click", () => setPage(page - 1, byReader));
    next?.addEventListener("click", () => setPage(page + 1, byReader));
    input?.addEventListener("change", () => setPage(input.value, byReader));
    input?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        setPage(input.value, byReader);
      }
    });
    zoomOut?.addEventListener("click", () => setZoom(zoom - 0.25));
    zoomIn?.addEventListener("click", () => setZoom(zoom + 0.25));
    fit?.addEventListener("click", () => { zoom = 1; rotation = 0; applyView(); });
    rotate?.addEventListener("click", () => { rotation = (rotation + 90) % 360; applyView(); });
    stage?.addEventListener("wheel", (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      setZoom(zoom + (event.deltaY < 0 ? 0.1 : -0.1));
    }, { passive: false });
    // Zoom animates the image width, and the stage resizes with the window:
    // either moves the row out from under the outline.
    if (stage && "ResizeObserver" in globalThis) {
      new ResizeObserver(() => drawBox()).observe(stage);
      stage.addEventListener("transitionend", () => drawBox());
    }
    setPage(page);
  }

  document.querySelectorAll("[data-source-viewer]").forEach(bindViewer);
  document.addEventListener("click", (event) => {
    const pageLink = event.target.closest("a.obs-page[data-page], a[href^='#page-']");
    if (pageLink) {
      // The review queue has no page-text section to anchor into, so the link
      // there points at the viewer itself and carries the page as data.
      const page = Number(pageLink.dataset.page) || pageFromHash(pageLink.getAttribute("href"));
      const viewer = pageLink.closest(".review-bench")?.querySelector("[data-source-viewer]") || document.querySelector("[data-source-viewer]");
      if (page && viewer?.goToPage) {
        event.preventDefault();
        viewer.goToPage(page, { syncHash: true });
      }
      return;
    }
    const section = event.target.closest("[data-start-page]");
    if (!section) return;
    const viewer = section.closest(".review-bench")?.querySelector("[data-source-viewer]") || document.querySelector("[data-source-viewer]");
    if (!viewer?.goToPage) return;
    viewer.goToPage(Number(section.dataset.startPage), { syncHash: true, source: "reader" });
    section.parentElement?.querySelectorAll("[data-start-page]").forEach((node) => node.classList.toggle("is-active", node === section));
  });
  globalThis.addEventListener("hashchange", () => {
    const page = pageFromHash(location.hash);
    const viewer = document.querySelector(".review-bench [data-source-viewer], [data-source-viewer]");
    if (page && viewer?.goToPage) viewer.goToPage(page, { source: "reader" });
  });
})();

// The results list and the page beside it move together.
//
// A document's values are checked against the page they were printed on, and
// with fifty values over seven pages the reviewer used to turn pages by hand
// and hunt for each row.  Now the card at the top of the visible list is the
// current one: the viewer shows its page and outlines its printed row, and
// turning the page in the viewer brings that page's first card to the top.
//
// Every scroll this code makes is flagged (`quietUntil`) so that the list
// answering the viewer does not make the viewer answer the list.
(() => {
  const bench = document.querySelector(".review-bench");
  const viewer = bench?.querySelector("[data-source-viewer]");
  // Read live, not once: a checked value is swapped for its re-rendered row
  // and a folded group adds rows when opened, and a list captured on load
  // would keep following the rows that are gone.
  const allCards = () => (bench ? [...bench.querySelectorAll("[data-obs-page]")] : []);
  if (!viewer?.goToPage || !viewer.mark || !allCards().length) return;
  const reduceMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)");
  const behavior = () => (reduceMotion?.matches ? "auto" : "smooth");
  const frame = viewer.closest(".review-bench-main") || viewer;
  const topbar = document.querySelector(".topbar");
  let current = null;
  let quietUntil = 0;
  let lastScroll = 0;
  let pending = 0;

  const pageOf = (card) => Number(card.dataset.obsPage) || 0;
  const boxOf = (card) => (card.dataset.box ? card.dataset.box.split(",").map(Number) : null);
  const shown = (card) => card.offsetParent !== null;

  // The element the list scrolls in: its own panel on a wide screen, the
  // window once the bench stacks.
  function scroller() {
    for (let node = allCards()[0]?.parentElement; node && node !== document.body; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1) return node;
    }
    return null;
  }

  // Where the visible part of the list begins: below the sticky header, and
  // below the viewer when the viewer is stuck above the list rather than
  // beside it.
  function visibleTop() {
    const own = scroller();
    let top = own ? own.getBoundingClientRect().top : 0;
    if (topbar) top = Math.max(top, topbar.getBoundingClientRect().bottom);
    const box = frame.getBoundingClientRect();
    const list = (allCards()[0]?.parentElement || frame).getBoundingClientRect();
    const stacked = box.left < list.right && box.right > list.left;
    if (stacked && box.bottom > top) top = Math.max(top, box.bottom);
    return top;
  }

  function choose(card, { turn = true, reveal = true } = {}) {
    if (current !== card) {
      current?.classList.remove("is-current");
      current?.removeAttribute("aria-current");
      card.classList.add("is-current");
      card.setAttribute("aria-current", "true");
      current = card;
    }
    if (pageOf(card) !== viewer.currentPage()) {
      if (!turn) return;
      viewer.goToPage(pageOf(card));
    }
    viewer.mark(boxOf(card), { reveal });
  }

  // The first card still substantially in view.  A tall card whose last few
  // buttons are all that is left under the viewer is one the reader has
  // finished with.
  function cardAtTop() {
    const top = visibleTop();
    return allCards().find((card) => {
      if (!shown(card)) return false;
      const rect = card.getBoundingClientRect();
      return rect.bottom > top + Math.min(rect.height * 0.5, 140) && rect.top < globalThis.innerHeight;
    });
  }

  function follow() {
    pending = 0;
    if (Date.now() < quietUntil) return;
    const card = cardAtTop();
    if (card && card !== current) choose(card);
  }

  document.addEventListener("scroll", (event) => {
    // The viewer's own stage scrolling is not the reader moving the list.
    if (event.target instanceof Element && viewer.contains(event.target)) return;
    lastScroll = Date.now();
    if (Date.now() < quietUntil) {
      // Still settling from a scroll this code started: stay quiet until it stops.
      quietUntil = Date.now() + 160;
      return;
    }
    if (!pending) pending = requestAnimationFrame(follow);
  }, { capture: true, passive: true });

  // The reader turned the page: bring that page's first value to the top.
  // A page with no values leaves the list where it is.
  viewer.addEventListener("hl:viewer-page", (event) => {
    const page = Number(event.detail?.page);
    const card = allCards().find((item) => pageOf(item) === page && shown(item));
    if (!card) return;
    const own = scroller();
    const delta = card.getBoundingClientRect().top - visibleTop() - 8;
    quietUntil = Date.now() + 400;
    // Several screens away is a jump, not a glide: animating past forty cards
    // only delays the one the reader asked for.
    const far = Math.abs(delta) > globalThis.innerHeight * 2;
    (own || globalThis).scrollBy({ top: delta, behavior: far ? "auto" : behavior() });
    choose(card);
  });

  // Tabbing into a card, or clicking it, makes it current at once.  The
  // browser scrolls a focused card into view; that scroll is not a choice.
  bench.addEventListener("focusin", (event) => {
    const card = event.target.closest?.("[data-obs-page]");
    if (!card) return;
    quietUntil = Date.now() + 300;
    choose(card);
  });
  bench.addEventListener("click", (event) => {
    const card = event.target.closest?.("[data-obs-page]");
    if (card) choose(card);
  });
  // Pointing at a card outlines its row when that row is on the page in view.
  // It never turns the page: while the wheel scrolls the list, cards slide
  // under a still pointer, and each would flip the page back and forth.
  bench.addEventListener("mouseover", (event) => {
    const card = event.target.closest?.("[data-obs-page]");
    if (!card || Date.now() - lastScroll < 250 || pageOf(card) !== viewer.currentPage()) return;
    viewer.mark(boxOf(card), { reveal: false });
  });
  bench.addEventListener("mouseout", (event) => {
    const card = event.target.closest?.("[data-obs-page]");
    if (!card || card.contains(event.relatedTarget)) return;
    if (current && pageOf(current) === viewer.currentPage()) viewer.mark(boxOf(current), { reveal: false });
  });

  // On arrival, outline the first value of the page the viewer opened on,
  // without moving anything.
  const first = allCards().find((card) => pageOf(card) === viewer.currentPage() && shown(card));
  if (first) choose(first, { turn: false, reveal: false });
})();

// Keep the review queue where the reader left it.
//
// Each entry is a real link, so opening file 74 of 85 is a full page load and
// the list comes back scrolled to the top -- with the file you just opened
// somewhere far below, and the one you were working through nowhere in sight.
// Nothing is lost, but every step of a long pass costs a hunt for your place.
//
// `block: "nearest"` so a file already on screen does not jump, and `auto`
// rather than a smooth scroll because this runs on load, where an animation
// would just be the page moving under the reader.
(() => {
  const active = document.querySelector(".review-file-list .review-file.is-active");
  if (!active) return;
  const list = active.closest(".review-file-list");
  // Only when the list is its own scroll area: on a phone it is not, and
  // scrolling the whole document to the queue would skip the report itself.
  if (!list || list.scrollHeight <= list.clientHeight + 1) return;
  active.scrollIntoView({ block: "nearest", behavior: "auto" });
})();
