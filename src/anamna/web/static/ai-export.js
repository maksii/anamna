/* The AI hand-off modal.

   The dialog itself is native: <dialog>.showModal() already gives a focus
   trap, a backdrop, Escape-to-close and inertness behind it. This file does
   the three things the platform does not: fetch the prompt, keep it in step
   with the checkboxes, and copy it. */
(() => {
  const strings = globalThis.__HL_I18N__ || {};
  const tr = (key, fallback) => strings[key] || fallback;
  const modal = document.querySelector("[data-ai-modal]");
  /* One opener per layout (header row, account sheet on a phone); the
     stylesheet shows one of them. Focus returns to whichever was used. */
  const openers = [...document.querySelectorAll("[data-ai-open]")];
  if (!modal || !openers.length) return;
  let opener = openers[0];

  const text = modal.querySelector("[data-ai-text]");
  const size = modal.querySelector("[data-ai-size]");
  const status = modal.querySelector("[data-ai-status]");
  const copy = modal.querySelector("[data-ai-copy]");
  const sections = [...modal.querySelectorAll("[data-ai-section]")];
  const scopes = [...modal.querySelectorAll("[data-ai-scope]")];
  const recordOptions = modal.querySelector("[data-ai-record-options]");
  let pending = null;
  let loaded = "";

  const chosen = () => sections.filter((box) => box.checked).map((box) => box.value).join(",");
  /* "page" only exists on detail pages; everywhere else the radios are not
     rendered and the whole record is the one honest answer. */
  const scope = () => scopes.find((radio) => radio.checked)?.value || "record";

  function say(message, tone) {
    status.textContent = message || "";
    status.dataset.tone = tone || "";
  }

  /* Characters are exact; tokens are not, and are labelled "roughly" in both
     languages. Four characters per token is the usual English rule of thumb;
     Cyrillic runs denser, so the same divisor would understate a Ukrainian
     export by about half. */
  function measure(value) {
    const cyrillic = (value.match(/[Ѐ-ӿ]/g) || []).length;
    const perToken = cyrillic > value.length / 4 ? 2.2 : 4;
    const format = (n) => n.toLocaleString(globalThis.__HL_LOCALE__ || "en-GB");
    size.textContent = tr("ai.size", "{chars} characters · roughly {tokens} tokens")
      .replace("{chars}", format(value.length))
      .replace("{tokens}", format(Math.round(value.length / perToken / 100) * 100));
  }

  async function load() {
    /* A slow record must not answer an older request last: each load owns a
       token and a stale one discards its own result. */
    const token = {};
    pending = token;
    say("");
    text.value = tr("ai.loading", "Assembling your record...");
    size.textContent = "";
    copy.disabled = true;
    /* The record-only checkboxes disappear while the excerpt is selected:
       they trim a prompt the excerpt does not build. */
    if (recordOptions) recordOptions.hidden = scope() === "page";
    const query = new URLSearchParams({ include: chosen(), path: location.pathname, scope: scope() });
    try {
      const response = await fetch(`/api/ai-export?${query}`, { headers: { Accept: "text/plain" } });
      if (!response.ok) throw new Error(String(response.status));
      const body = await response.text();
      if (pending !== token) return;
      loaded = body;
      text.value = body;
      measure(body);
      copy.disabled = false;
    } catch {
      if (pending !== token) return;
      text.value = "";
      say(tr("ai.error", "The prompt could not be built. Reload the page and try again."), "error");
    }
  }

  openers.forEach((button) => button.addEventListener("click", () => {
    opener = button;
    modal.showModal();
    load().catch(console.error);
  }));

  sections.forEach((box) => box.addEventListener("change", load));
  scopes.forEach((radio) => radio.addEventListener("change", load));

  copy.addEventListener("click", async () => {
    try {
      /* Only over https or localhost; everywhere else the API is absent and
         the reader is told to select the text rather than left with a button
         that silently does nothing. */
      await navigator.clipboard.writeText(loaded);
      say(tr("ai.copied", "Copied"), "good");
    } catch {
      text.focus();
      text.select();
      say(tr("ai.copy_failed", "Copying was blocked. Select the text below and copy it manually."), "error");
    }
  });

  /* Clicking the backdrop closes it. The dialog's own box is excluded by
     hit-testing its rectangle: the click target for the backdrop is the
     <dialog> element itself. */
  modal.addEventListener("click", (event) => {
    if (event.target !== modal) return;
    const box = modal.getBoundingClientRect();
    const outside =
      event.clientX < box.left || event.clientX > box.right ||
      event.clientY < box.top || event.clientY > box.bottom;
    if (outside) modal.close();
  });

  modal.addEventListener("close", () => {
    pending = null;
    opener.focus();
  });
})();
