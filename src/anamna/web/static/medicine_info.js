// A medicine's stored instruction in a dialog. The link is a real page
// (/medicines/<id>/instruction): without this script, with a modified click,
// or when the page cannot be read, the browser simply goes there.
(() => {
  'use strict';

  const plainClick = (event) => event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;

  async function show(link) {
    const words = globalThis.__HL_I18N__ || {};
    const dialog = document.createElement('dialog');
    dialog.className = 'an-med-info-dialog';
    dialog.setAttribute('aria-label', link.getAttribute('aria-label') || link.textContent.trim());

    const bar = document.createElement('form');
    bar.method = 'dialog';
    bar.className = 'an-med-info-dialog__bar';
    const close = document.createElement('button');
    close.className = 'secondary';
    close.textContent = words['med.info.close'] || 'Close';
    bar.append(close);

    const body = document.createElement('div');
    body.className = 'an-med-info-dialog__body';
    const waiting = document.createElement('p');
    waiting.setAttribute('role', 'status');
    waiting.textContent = words['med.info.loading'] || 'Reading the instruction…';
    body.append(waiting);

    dialog.append(bar, body);
    dialog.addEventListener('close', () => { dialog.remove(); link.focus(); });
    // A click on the backdrop lands on the dialog element itself.
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
    document.body.append(dialog);
    dialog.showModal();

    try {
      const reply = await fetch(link.href, { credentials: 'same-origin', headers: { Accept: 'text/html' } });
      if (!reply.ok) throw new Error(String(reply.status));
      const page = new DOMParser().parseFromString(await reply.text(), 'text/html');
      const article = page.getElementById('med-instruction');
      if (!article) throw new Error('no instruction on the page');
      if (dialog.open) body.replaceChildren(document.importNode(article, true));
    } catch {
      // The page itself says what went wrong (signed out, gone, unreadable).
      location.assign(link.href);
    }
  }

  document.addEventListener('click', (event) => {
    const link = event.target.closest?.('a[data-med-info]');
    if (!link || event.defaultPrevented || !plainClick(event) || typeof HTMLDialogElement !== 'function') return;
    event.preventDefault();
    void show(link); // nothing waits for it: show() handles its own failure
  });
})();
