// /chat: send a question, stream the answer into the page.
//
// Without this script the composer still works: it posts, the server answers
// in full and redirects back to the conversation.  With it the answer arrives
// as server-sent events over the same POST: `conversation` (the id, once),
// `status` / `compacted` (earlier messages being summarised), `tool` (a record
// lookup started), `text` (a piece of the answer), then `done` (the final
// answer, rendered by the server) or `error`.
(function () {
  "use strict";

  const log = document.querySelector("[data-chat-log]");
  const composer = document.querySelector("[data-chat-composer]");
  const template = document.querySelector("template[data-chat-bubble]");
  if (!log || !template || !composer) return;
  const i18n = globalThis.__HL_I18N__ || {};
  const say = (key, values) => {
    let text = i18n[key] || key;
    Object.entries(values || {}).forEach(([name, value]) => { text = text.split(`{${name}}`).join(value); });
    return text;
  };
  const status = composer.querySelector("[data-chat-status]");
  const submit = composer.querySelector("[data-chat-submit]");
  const textarea = composer.querySelector("textarea");
  let busy = false;

  function bubble(role, text) {
    const item = template.content.firstElementChild.cloneNode(true);
    item.classList.add(`an-chat-msg--${role}`);
    item.querySelector(".visually-hidden").textContent = say(role === "user" ? "chat.you" : "chat.assistant") + ":";
    const body = item.querySelector(".an-chat-msg__body");
    if (role === "user") body.classList.add("an-chat-msg__body--plain");
    body.textContent = text || "";
    log.appendChild(item);
    return item;
  }

  // The newest message, not the composer: the composer is sticky, so it is
  // always "in view" and scrolling to it moves nothing.
  function scrollToEnd(smooth) {
    const last = log.lastElementChild;
    if (!last) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    last.scrollIntoView({ block: "end", behavior: smooth && !reduced ? "smooth" : "auto" });
  }

  function setBusy(state, message) {
    busy = state;
    log.setAttribute("aria-busy", state ? "true" : "false");
    submit.disabled = state;
    status.textContent = message || "";
  }

  function addTools(item, labels, summary) {
    if (!labels || !labels.length) return;
    const details = document.createElement("details");
    details.className = "an-chat-msg__tools";
    const title = document.createElement("summary");
    title.textContent = summary;
    const list = document.createElement("ul");
    labels.forEach((label) => {
      const entry = document.createElement("li");
      entry.textContent = label;
      list.appendChild(entry);
    });
    details.append(title, list);
    item.appendChild(details);
  }

  function showError(item, message, html) {
    const body = item.querySelector(".an-chat-msg__body");
    // The server's rendering of whatever was written before the failure.
    if (html) body.innerHTML = html;
    if (!body.textContent.trim()) body.remove();
    const note = document.createElement("p");
    note.className = "an-chat-msg__error";
    // Announced when it appears: a screen-reader user is not watching the bubble.
    note.setAttribute("role", "alert");
    note.textContent = message;
    item.classList.add("an-chat-msg--error");
    item.appendChild(note);
  }

  function remember(conversation) {
    composer.querySelector("[data-chat-conversation]").value = conversation.id;
    if (window.location.pathname !== conversation.url) window.history.replaceState(null, "", conversation.url);
    const heading = document.getElementById("chat-current");
    if (heading && conversation.title) heading.textContent = conversation.title;
  }

  // What the last answer read, and how full the history is before it is
  // summarised; the wording comes from the server in the page's language.
  function showContext(context) {
    const box = composer.querySelector("[data-chat-context]");
    if (!box || !context || !context.tokens) return;
    box.hidden = false;
    box.title = context.label;
    box.querySelector("[data-chat-context-label]").textContent = context.label;
    box.querySelector("[data-chat-context-text]").textContent = context.text;
    box.querySelector("[data-chat-context-meter]").style.width = `${context.percent}%`;
  }

  function markCompacted(event) {
    // Drawn where the summary ends; a message added in this visit has no id
    // yet, and the marker then appears on the next load.
    const after = log.querySelector(`[data-message-id="${event.after_id}"]`);
    if (!after) return;
    log.querySelectorAll("[data-chat-mark]").forEach((mark) => mark.remove());
    const mark = document.createElement("li");
    mark.className = "an-chat-mark";
    mark.dataset.chatMark = "";
    mark.textContent = event.label;
    after.after(mark);
  }

  async function send() {
    const data = new FormData(composer);
    const question = String(data.get("message") || "").trim();
    if (!question || busy) return;
    bubble("user", question);
    const answer = bubble("assistant", "");
    const body = answer.querySelector(".an-chat-msg__body");
    setBusy(true, say("chat.thinking"));
    textarea.value = "";
    resize();
    scrollToEnd(true);
    let finished = false;
    let answered = false;
    try {
      const response = await fetch(composer.action, {
        method: "POST", body: data, headers: { Accept: "text/event-stream" }, credentials: "same-origin",
      });
      if (!response.ok || !response.body) throw new Error(String(response.status));
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          if (!chunk.startsWith("data:")) continue;
          const event = JSON.parse(chunk.slice(5));
          if (event.type === "conversation") remember(event);
          else if (event.type === "status") status.textContent = event.label;
          else if (event.type === "compacted") markCompacted(event);
          else if (event.type === "text") {
            body.textContent += event.text;
            status.textContent = say("chat.writing");
          } else if (event.type === "tool") {
            status.textContent = say("chat.reading", { label: event.label });
          } else if (event.type === "done") {
            body.innerHTML = event.html;
            addTools(answer, event.tools, event.tools_summary);
            showContext(event.context);
            finished = true;
            answered = true;
          } else if (event.type === "error") {
            showError(answer, event.message, event.html);
            finished = true;
          }
        }
      }
      if (!finished) throw new Error("stream ended early");
    } catch (_error) {
      showError(answer, say("chat.error_network"), "");
      if (!textarea.value) textarea.value = question;
      resize();
    } finally {
      // The status line is the only thing a screen reader hears about the
      // answer, so a finished answer is named there rather than cleared.
      setBusy(false, answered ? say("chat.answer_ready") : "");
      scrollToEnd(true);
      textarea.focus();
    }
  }

  // Grows with what is typed up to the CSS max-height, where `field-sizing`
  // is not supported (Safari).
  function resize() {
    if (CSS.supports("field-sizing", "content")) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight + 2}px`;
  }

  composer.addEventListener("submit", (event) => {
    if (!window.fetch || !window.TextDecoder) return; // let the form post
    event.preventDefault();
    send();
  });
  textarea.addEventListener("input", resize);
  // Enter makes a new line (a phone keyboard has no other way to); Ctrl or
  // Cmd with Enter sends, as the info panel says.
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      composer.requestSubmit();
    }
  });
  // A conversation opens at its newest message, also on reload, where the
  // browser would otherwise restore wherever the page was last scrolled.
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  scrollToEnd(false);
  window.addEventListener("load", () => scrollToEnd(false));
})();
