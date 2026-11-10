/* "Found in your documents": starts the reading of the documents, shows how
   far it is, and reloads the page when it ends so the list shows what was
   found.  The reading runs on the server and stores each document as it goes,
   so leaving the page loses nothing; coming back with a reading still running
   picks its progress up again.  Also the "tick all" box of the list. */
(() => {
  const panel = document.querySelector('[data-found-scan]');
  if (!panel) return;
  const form = panel.querySelector('[data-found-start]');
  const status = panel.querySelector('[data-found-status]');
  const button = form?.querySelector('button');
  const tell = (text, state) => { status.textContent = text; status.hidden = !text; status.dataset.state = state || ''; };
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const failed = reason => {
    button.disabled = false;
    tell(panel.getAttribute(`data-error-${reason}`) || panel.dataset.errorLost || '', 'error');
  };

  // One reply about the reading; a request that fails counts as lost.
  const readState = async job => {
    try {
      const reply = await fetch(`/medicines/found/scan/${encodeURIComponent(job)}`, {headers: {Accept: 'application/json'}});
      return reply.ok ? await reply.json() : {state: 'failed', error: 'lost'};
    } catch {
      return {state: 'failed', error: 'lost'};
    }
  };
  // Done, or stopped part of the way: either way what was stored is on
  // the page after a reload.  A failure says why first.
  const settle = state => {
    if (state.state === 'done') { location.assign('/medicines/found' + (state.failed ? '?error=found_unread' : '')); return; }
    if (state.done) { location.assign('/medicines/found?error=found_stopped'); return; }
    failed(state.error || 'lost');
  };
  // follow() reports its own failures on the page, so its promise is not awaited.
  const follow = async job => {
    button.disabled = true;
    tell(panel.dataset.starting, 'running');
    let state = await readState(job);
    while (state.state === 'running') {
      if (state.total) tell(panel.dataset.progress.replace('{done}', state.done).replace('{total}', state.total), 'running');
      await wait(2000);
      state = await readState(job);
    }
    settle(state);
  };

  if (form) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      button.disabled = true;
      tell(panel.dataset.starting, 'running');
      try {
        const reply = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}});
        const opened = reply.ok ? await reply.json() : {error: 'lost'};
        if (opened.job) void follow(opened.job); else failed(opened.error || 'lost');
      } catch {
        failed('lost');
      }
    });
    if (panel.dataset.job) void follow(panel.dataset.job);
  }

  const list = document.querySelector('[data-found-form]');
  const all = list?.querySelector('[data-found-all]');
  if (all) {
    const boxes = () => [...list.querySelectorAll('input[name="key"]')];
    all.addEventListener('change', () => boxes().forEach(box => { box.checked = all.checked; }));
    list.addEventListener('change', event => {
      if (event.target.name === 'key') all.checked = boxes().every(box => box.checked);
    });
  }
})();
