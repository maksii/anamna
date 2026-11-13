/* Diagnoses pages.  Three jobs, each only where its elements exist:

   - The code picker of the form: a search over the ICD-10 classification
     fills the code field.  The code field works on its own; the picker is an
     aid, and typing in the field clears the title line that describes it.
   - "Read my documents with AI": starts the reading on the server, shows how
     far it has got, and reloads the page when it ends so the list shows what
     was found.  The reading runs on the server and stores each document as it
     goes, so leaving the page loses nothing; coming back with a reading still
     running picks its progress up again.
   - The list's filter and order: typed words narrow the diagnoses shown, and
     the order sorts each list by date or by name.  Without the script the bar
     stays hidden and the list keeps the server's newest-first order.

   Every message comes from data attributes rendered by the template, so the
   script carries no text of its own.  Results are built with textContent. */
(() => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const search = document.getElementById('dx-code-search');
  const results = document.getElementById('dx-code-results');
  const codeInput = document.getElementById('dx-code');
  const codeTitle = document.getElementById('dx-code-title');
  if (search && results && codeInput && codeTitle) {
    const note = document.querySelector('[data-dx-codes-status]');
    let timer = 0;
    let controller = null;

    const say = (text) => {
      note.textContent = text || '';
      note.hidden = !text;
    };
    const clear = () => {
      results.replaceChildren();
      results.hidden = true;
    };
    const choose = (row) => {
      codeInput.value = row.code;
      codeTitle.textContent = row.name;
      clear();
      say('');
      codeInput.focus();
    };
    const render = (rows) => {
      results.replaceChildren(...rows.map((row) => {
        const item = document.createElement('li');
        item.setAttribute('role', 'option');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'dx-code-option';
        const code = document.createElement('strong');
        code.textContent = row.code;
        const name = document.createElement('span');
        name.textContent = row.name;
        button.append(code, name);
        button.addEventListener('click', () => choose(row));
        item.append(button);
        return item;
      }));
      results.hidden = !rows.length;
    };
    const lookup = async (query) => {
      controller?.abort();
      controller = new AbortController();
      say(search.dataset.searching);
      try {
        const reply = await fetch(`/diagnoses/codes?q=${encodeURIComponent(query)}`, {
          headers: {Accept: 'application/json'},
          signal: controller.signal,
        });
        if (!reply.ok) throw new Error(String(reply.status));
        const rows = await reply.json();
        // The person typed on while this was on its way: that answer is stale.
        if (search.value.trim() !== query) return;
        render(rows);
        say(rows.length ? '' : search.dataset.none);
      } catch (error) {
        if (error.name === 'AbortError') return;
        clear();
        say(search.dataset.error);
      }
    };

    search.addEventListener('input', () => {
      clearTimeout(timer);
      const query = search.value.trim();
      if (query.length < 2) {
        controller?.abort();
        clear();
        say('');
        return;
      }
      timer = setTimeout(() => lookup(query), 250);
    });
    codeInput.addEventListener('input', () => {
      codeTitle.textContent = '';
    });
  }

  const scan = document.getElementById('dx-scan');
  if (scan) {
    const form = scan.querySelector('[data-dx-scan-start]');
    const status = scan.querySelector('[data-dx-scan-status]');
    const button = form?.querySelector('button');
    const tell = (text) => {
      status.textContent = text || '';
      status.hidden = !text;
    };
    const idle = () => {
      if (button) button.disabled = false;
    };
    // A reason the reading stopped, in words. An unknown reason reads as lost.
    const failed = (reason) => {
      idle();
      tell(scan.getAttribute(`data-error-${reason}`) || scan.dataset.errorLost || '');
    };

    // One reply about the reading; a request that fails counts as lost.
    const readState = async (job) => {
      try {
        const reply = await fetch(`/diagnoses/found/scan/${encodeURIComponent(job)}`, {
          headers: {Accept: 'application/json'},
        });
        return reply.ok ? await reply.json() : {state: 'failed', error: 'lost'};
      } catch {
        return {state: 'failed', error: 'lost'};
      }
    };

    const follow = async (job) => {
      if (button) button.disabled = true;
      tell(scan.dataset.starting);
      let state = await readState(job);
      while (state.state === 'running') {
        if (state.total) {
          tell(scan.dataset.progress.replace('{done}', state.done).replace('{total}', state.total));
        }
        await wait(2000);
        state = await readState(job);
      }
      if (state.state === 'done' && !state.failed) {
        location.reload();
        return;
      }
      // Some documents were not read: the page keeps what was found, and the
      // message says how to see it and what to press to try the rest again.
      if (state.state === 'done') {
        idle();
        tell(scan.dataset.failed);
        return;
      }
      failed(state.error || 'lost');
    };

    if (form) {
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (button) button.disabled = true;
        tell(scan.dataset.starting);
        try {
          const reply = await fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: {Accept: 'application/json'},
          });
          const opened = await reply.json().catch(() => ({error: 'lost'}));
          if (opened.job) void follow(opened.job);
          else failed(opened.error || 'lost');
        } catch {
          failed('lost');
        }
      });
    }
    if (scan.dataset.job) void follow(scan.dataset.job);
  }

  // The list's filter and order.  Every diagnosis row carries its words, its
  // date and its name; the filter hides the rows that miss a typed word and the
  // groups left empty, the order moves rows within their own list.
  const bar = document.querySelector('[data-dx-filter]');
  if (bar) {
    const query = bar.querySelector('input[type="search"]');
    const order = bar.querySelector('select');
    const status = bar.querySelector('[role="status"]');
    const empty = bar.querySelector('[data-dx-filter-empty]');
    const rows = [...document.querySelectorAll('[data-dx-item]')];
    const past = document.getElementById('dx-past');
    const lang = document.documentElement.lang || undefined;

    const filter = () => {
      const words = query.value.toLocaleLowerCase(lang).split(/\s+/).filter(Boolean);
      let shown = 0;
      for (const row of rows) {
        const hit = words.every((word) => row.dataset.dxSearch.includes(word));
        row.hidden = !hit;
        if (hit) shown += 1;
      }
      for (const group of document.querySelectorAll('[data-dx-group]')) {
        group.hidden = !group.querySelector('[data-dx-item]:not([hidden])');
      }
      if (past && words.length && past.querySelector('[data-dx-item]:not([hidden])')) past.open = true;
      status.textContent = words.length
        ? bar.dataset.shown.replace('{shown}', String(shown)).replace('{total}', String(rows.length))
        : '';
      empty.hidden = !(words.length && shown === 0);
    };

    // An undated diagnosis goes last in either date order.
    const compare = {
      newest: (a, b) => (b.dataset.dxDay || '').localeCompare(a.dataset.dxDay || '') || (!a.dataset.dxDay) - (!b.dataset.dxDay),
      oldest: (a, b) => (!a.dataset.dxDay) - (!b.dataset.dxDay) || (a.dataset.dxDay || '').localeCompare(b.dataset.dxDay || ''),
      name: (a, b) => a.dataset.dxName.localeCompare(b.dataset.dxName, lang),
    };
    const sort = () => {
      const by = compare[order.value] || compare.newest;
      for (const list of document.querySelectorAll('[data-dx-sortable]')) {
        list.append(...[...list.children].sort(by));
      }
    };

    query.addEventListener('input', filter);
    order.addEventListener('change', sort);
    bar.hidden = false;
  }
})();
