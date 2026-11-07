/* The processing area.
 *
 * The server sends every string already translated, so this file holds no
 * wording of its own - there is no second copy of the catalogue to drift out
 * of step with the page it is replacing.
 *
 * Polling stops when nothing is running, so an open tab on a finished queue
 * costs one request, not one per second forever.
 */
(() => {
  const list = document.getElementById("an-queue");
  const summary = document.getElementById("an-queue-summary");
  const section = document.getElementById("processing");
  if (!list || !section) return;

  /* Queue completion refreshes the server-rendered recent list. Preserve the
   * reader's exact disclosures and position across that refresh, ordinary
   * uploads, deletes, and back/forward navigation. The processing disclosure
   * must not snap shut merely because its final job changed state. */
  const STATE_KEY = "anamna:upload-page-state";
  const disclosures = [...document.querySelectorAll("[data-upload-disclosure]")];
  const anchors = [
    document.getElementById("upload-form"),
    ...disclosures,
  ].filter(Boolean);

  const savedState = () => {
    try {
      return JSON.parse(sessionStorage.getItem(STATE_KEY) || "null");
    } catch {
      return null;
    }
  };

  const savePageState = () => {
    const above = anchors.filter((node) => node.getBoundingClientRect().top <= 24);
    const anchor = above.at(-1) || anchors[0];
    try {
      sessionStorage.setItem(STATE_KEY, JSON.stringify({
        open: Object.fromEntries(disclosures.map((node) => [node.id, node.open])),
        scrollY: globalThis.scrollY,
        anchor: anchor ? anchor.id : "",
        anchorTop: anchor ? anchor.getBoundingClientRect().top : 0,
      }));
    } catch {
      // Private browsing can disable storage; the upload and queue still work.
    }
  };

  const restorePageState = () => {
    const state = savedState();
    if (!state) return;
    disclosures.forEach((node) => {
      if (typeof state.open?.[node.id] === "boolean") node.open = state.open[node.id];
    });
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    const restoreScroll = () => {
      const anchor = state.anchor ? document.getElementById(state.anchor) : null;
      if (anchor && Number.isFinite(state.anchorTop)) {
        globalThis.scrollBy(0, anchor.getBoundingClientRect().top - state.anchorTop);
      } else if (Number.isFinite(state.scrollY)) {
        globalThis.scrollTo(0, state.scrollY);
      }
    };
    requestAnimationFrame(() => {
      restoreScroll();
      requestAnimationFrame(restoreScroll);
    });
  };

  restorePageState();
  disclosures.forEach((node) => node.addEventListener("toggle", savePageState));
  document.querySelectorAll("form").forEach((node) => node.addEventListener("submit", savePageState));
  globalThis.addEventListener("pagehide", savePageState);

  const IDLE_STOP = 2; // quiet polls before standing down, so a job that is
                       // enqueued a moment after the last one finishes is seen
  let quiet = 0;
  let timer = null;

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };

  /* Finished rows past the newest few fold behind "Show all", the same rule
   * the server applied on load; running, waiting and failed rows never do. */
  const keep = Number(list.dataset.keep) || 5;
  const showAll = document.querySelector("[data-queue-all]");
  let unfolded = false;
  function fold() {
    let finished = 0;
    let folded = 0;
    for (const item of list.children) {
      const hide = !unfolded && item.dataset.finished !== undefined && ++finished > keep;
      item.hidden = hide;
      if (hide) folded += 1;
    }
    if (showAll) {
      showAll.parentElement.hidden = !folded;
      showAll.textContent = showAll.dataset.template.replace("{count}", list.children.length);
    }
  }
  showAll?.addEventListener("click", () => {
    unfolded = true;
    fold();
    // The button hides itself; focus moves to the first row it revealed
    // rather than falling back to the top of the document.
    const first = list.querySelectorAll("[data-finished]")[keep];
    if (first) { first.tabIndex = -1; first.focus(); }
  });

  function render(job) {
    const item = el("li", `an-queue__item is-${job.tone}`);
    item.dataset.job = job.id;
    if (job.finished) item.dataset.finished = "";
    item.append(
      el("span", "an-queue__kind", job.kind_text),
      el("span", "an-queue__name", job.filename),
      el("span", `an-queue__state an-queue__state--${job.tone}`, job.state_text),
      el("span", "an-queue__detail", job.detail_text),
    );
    const meta = el("span", "an-queue__meta");
    if (job.summary_text) meta.append(el("strong", "", job.summary_text));
    if (job.size_text) meta.append(el("small", "", job.size_text));
    if (job.url) {
      const link = el("a", "", section.dataset.openLabel);
      link.href = job.url;
      meta.append(link);
    }
    item.append(meta);
    item.title = job.filename;
    return item;
  }

  function renderSummary(payload) {
    if (!summary?.dataset.template) return;
    summary.textContent = summary.dataset.template
      .replace("{active}", payload.active)
      .replace("{done}", payload.done)
      .replace("{failed}", payload.failed);
  }

  // Real failures are said above the drop zone and on the section's own
  // line; a file a device export carried and nobody imported is not one.
  function renderFailures(payload) {
    const alert = document.getElementById("an-upload-failed");
    const pill = document.getElementById("an-queue-failed-pill");
    [alert, pill].forEach((node) => { if (node) node.hidden = !payload.failed; });
    if (alert && payload.failed) alert.querySelector("[data-failed-text]").textContent = payload.failed_text;
    if (pill && payload.failed) pill.textContent = payload.failed_text;
  }

  async function poll() {
    let payload;
    try {
      const response = await fetch("/api/uploads/queue", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(String(response.status));
      payload = await response.json();
    } catch {
      // A failed poll is not a failed import: the worker is server-side and
      // keeps going. Stop refreshing rather than blanking what is on screen.
      return stop();
    }
    const empty = document.getElementById("an-queue-empty");
    if (empty && payload.jobs.length) empty.remove();
    list.replaceChildren(...payload.jobs.map(render));
    fold();
    list.setAttribute("aria-busy", payload.active ? "true" : "false");
    renderSummary(payload);
    renderFailures(payload);
    if (payload.active) {
      quiet = 0;
    } else if (++quiet >= IDLE_STOP) {
      // Everything that was running has produced a document, a device import
      // or an error. The finished list arrives with this answer, rendered by
      // the server's own macro, so nothing reloads and nothing moves.
      stop();
      running = false;
      const recent = document.getElementById("an-upload-recent-body");
      if (recent && typeof payload.recent_html === "string") recent.innerHTML = payload.recent_html;
      if (payload.failed) section.open = true;
    }
  }

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  function start() {
    if (timer) return;
    quiet = 0;
    timer = setInterval(poll, 1200);
    poll().catch(stop);
  }

  let running = section.dataset.queueActive !== "0";
  if (running && !document.hidden) start();
  // A tab in the background polls nothing; it catches up the moment it is
  // looked at again.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      running = running || Boolean(timer);
      stop();
    } else if (running) {
      running = false;
      start();
    }
  });

  document.querySelector("[data-open-processing]")?.addEventListener("click", () => { section.open = true; });

  /* Saying how many files were picked, before anything is sent. A native file
   * input announces "12 files" only inside its own shadow text, which a
   * screen reader reaches inconsistently and which vanishes under the custom
   * drop target. Ukrainian has three plural forms, so the page hands over all
   * three rather than letting this file guess with an `n === 1` test. */
  const picker = document.getElementById("an-upload-file");
  const chosen = document.getElementById("an-upload-selected");
  if (picker && chosen) {
    // Mirrors i18n.plural_form exactly, including its English branch: applying
    // the Ukrainian rule to English turns 21 into "21 file".
    const plural = (n) => {
      if (document.documentElement.lang !== "uk") return n === 1 ? "one" : "many";
      const mod10 = n % 10;
      const mod100 = n % 100;
      if (mod10 === 1 && mod100 !== 11) return "one";
      if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "few";
      return "many";
    };
    picker.addEventListener("change", () => {
      const count = picker.files ? picker.files.length : 0;
      chosen.textContent = count
        ? chosen.dataset[plural(count)].replace("{count}", String(count))
        : chosen.dataset.none;
    });
  }

  /* Sending past the proxy's ceiling. Cloudflare fronts the public host and
   * answers any single request over ~100 MB with its own 413, so a submission
   * bigger than the threshold goes up in slices to /upload/chunk and the
   * assembled files join the same queue. Both numbers come from the server;
   * this file holds neither wording nor limits of its own. */
  const form = document.querySelector("form.an-upload");
  if (form && picker && globalThis.crypto && crypto.randomUUID) {
    const sliceSize = Number(form.dataset.chunkSize) || 0;
    const threshold = Number(form.dataset.chunkThreshold) || 0;
    const button = form.querySelector("button[type=submit]");

    const send = async (files, total) => {
      const session = crypto.randomUUID();
      let sent = 0;
      for (const file of files) {
        for (let offset = 0; offset === 0 || offset < file.size; offset += sliceSize) {
          const part = file.slice(offset, offset + sliceSize);
          const body = new FormData();
          body.append("csrf_token", form.elements.csrf_token.value);
          body.append("session", session);
          body.append("kind", form.elements.kind.value);
          body.append("filename", file.name);
          body.append("offset", String(offset));
          body.append("final", offset + sliceSize >= file.size ? "1" : "0");
          body.append("chunk", part, file.name);
          const response = await fetch("/upload/chunk", { method: "POST", body });
          const payload = await response.json();
          if (!response.ok) throw payload;
          sent += part.size;
          if (chosen) {
            chosen.textContent = form.dataset.progress
              .replace("{name}", file.name)
              .replace("{percent}", String(Math.min(100, Math.round((sent / total) * 100))));
          }
          if (payload.status === "rejected") {
            // The queue row already says why; move on to the next file.
            sent += Math.max(0, file.size - offset - part.size);
            break;
          }
        }
      }
      globalThis.location.assign("/upload?batch=" + session);
    };

    form.addEventListener("submit", (event) => {
      const files = picker.files ? [...picker.files] : [];
      const total = files.reduce((sum, item) => sum + item.size, 0);
      if (!sliceSize || !files.length || total <= threshold) return; // one ordinary request
      event.preventDefault();
      if (button) button.disabled = true;
      send(files, total).catch((error_) => {
        if (button) button.disabled = false;
        if (error_?.error) {
          // The server named the problem; the page renders it the usual way.
          globalThis.location.assign("/upload?upload_error=" + encodeURIComponent(error_.error));
        } else if (chosen) {
          chosen.textContent = form.dataset.chunkError;
        }
      });
    });
  }
})();
