/* The form of one entry on the Medicines page.

   Four things, each working on its own so a page without one of them (no
   lookup, no AI) still runs the rest:
   - the pickers: a number with a button on each side, the exact-time rows, and
     the line that multiplies the dose by the strength;
   - the name lookup: suggestions from the reference site as the person types;
     picking one links the official instruction and fills the form and strength;
   - the AI panel: asks the server to research what is in the form now, waits
     by polling, and answers into the form.  An empty field is filled and
     marked; a field the person wrote is offered a replacement and never
     overwritten without a press;
   - nothing is saved by any of it.  Save posts the form as the person left it.

   Without this script the form is plain inputs and saves the same. */
(() => {
  const form = document.querySelector('[data-med-form]');
  if (!form) return;
  const field = name => form.elements[name];
  const i18n = globalThis.__HL_I18N__ || {};
  const say = (key, values = {}) => Object.entries(values)
    .reduce((text, [name, value]) => text.replace(`{${name}}`, value), i18n[key] || '');
  const kind = () => (form.querySelector('[name="kind"]:checked') || {}).value || '';
  const isDrug = () => ['medicine', 'supplement'].includes(kind());
  const number = value => Number.parseFloat(String(value).replace(',', '.'));
  // A number as the page's language writes it: Ukrainian uses a decimal comma.
  const shown = value => String(Math.round(value * 1000) / 1000)
    .replace('.', document.documentElement.lang === 'uk' ? ',' : '.');

  /* ---- Pickers ---------------------------------------------------------- */

  const changed = node => node.dispatchEvent(new Event('change', {bubbles: true}));

  for (const box of form.querySelectorAll('[data-stepper]')) {
    const input = box.querySelector('input');
    const min = number(box.dataset.min), max = number(box.dataset.max);
    for (const button of box.querySelectorAll('[data-stepper-by]')) {
      button.addEventListener('click', () => {
        // A dose moves by halves for tablets and by ones for everything else.
        const step = input.name === 'dose_amount' && field('dose_unit').value === 'tablet' ? 0.5 : number(box.dataset.step) || 1;
        const now = number(input.value);
        const next = Number.isFinite(now) ? now + step * number(button.dataset.stepperBy) : Math.max(min, step);
        input.value = String(Math.min(max, Math.max(input.name === 'dose_amount' ? step : min, Math.round(next * 1000) / 1000)));
        changed(input);
      });
    }
  }

  const clocks = form.querySelector('[data-med-clocks]');
  const perDay = field('per_day');
  // "Times a day" can never be fewer than the times the person named.
  const countTimes = () => {
    if (!perDay) return;
    const named = form.querySelectorAll('[name="day_part"]:checked').length
      + [...form.querySelectorAll('[name="clock"]')].filter(node => node.value).length;
    if (named > number(perDay.value || 0)) perDay.value = String(named);
  };
  if (clocks) {
    const template = document.querySelector('#med-clock-template');
    clocks.addEventListener('click', event => {
      const add = event.target.closest('[data-med-clock-add]');
      const remove = event.target.closest('[data-med-clock-remove]');
      if (add) {
        const row = template.content.firstElementChild.cloneNode(true);
        add.before(row); row.querySelector('input').focus();
      } else if (remove) {
        remove.closest('.an-med-clock').remove(); clocks.querySelector('[data-med-clock-add]').focus(); total();
      }
    });
  }

  /* The dose times the strength, so the person sees the amount a doctor would
     ask about.  Only when the strength is one plain figure per unit of the
     chosen kind: "160 mg" for a tablet, "500 mg/ml" for millilitres. */
  const totalLine = form.querySelector('[data-med-total]');
  const STRENGTH = /^\s*(\d+(?:[.,]\d+)?)\s*([^\d\s/]+)(?:\s*\/\s*(мл|ml))?\s*$/u;
  function total() {
    if (!totalLine) return;
    countTimes();
    const amount = number(field('dose_amount').value);
    const unit = field('dose_unit').value;
    const match = STRENGTH.exec(field('strength').value);
    const perUnit = match && (match[3] ? unit === 'ml' : ['tablet', 'capsule', 'sachet', 'suppository', 'patch', 'injection', 'piece'].includes(unit));
    if (!isDrug() || !perUnit || !(amount > 0)) { totalLine.hidden = true; return; }
    const each = number(match[1]) * amount;
    const repeat = field('repeat').value;
    const times = number(perDay.value);
    const text = repeat === 'daily' && times > 0
      ? totalLine.dataset.day.replace('{each}', `${shown(each)} ${match[2]}`).replace('{day}', `${shown(each * times)} ${match[2]}`)
      : totalLine.dataset.each.replace('{each}', `${shown(each)} ${match[2]}`);
    totalLine.textContent = text; totalLine.hidden = false;
  }
  form.addEventListener('change', total);
  form.addEventListener('input', event => { if (['dose_amount', 'strength', 'per_day', 'clock'].includes(event.target.name)) total(); });
  total();

  /* ---- Name lookup ------------------------------------------------------ */

  const input = form.querySelector('[data-med-lookup]');
  const list = document.querySelector('#med-lookup-list');
  const refName = field('reference_name'), refCode = field('reference_code');
  const linked = document.querySelector('#med-linked');
  const strengthHelp = document.querySelector('#med-strength-help');
  let chosen = refName.value ? field('name').value : null;
  const unlink = () => {
    refName.value = ''; refCode.value = ''; chosen = null; linked.hidden = true;
    strengthHelp.textContent = strengthHelp.dataset.default;
  };
  linked.querySelector('[data-med-unlink]').addEventListener('click', unlink);

  if (input && list) {
    const status = document.querySelector('#med-lookup-status');
    const linkedText = linked.querySelector('[data-med-linked-text]');
    let items = [], active = -1, timer = 0, asked = 0;

    const close = () => {
      list.hidden = true; list.replaceChildren(); items = []; active = -1;
      input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant');
    };
    const choose = item => {
      input.value = item.name;
      refName.value = item.reference_name;
      refCode.value = item.kind === 'product' ? item.code : '';
      chosen = item.name;
      linkedText.textContent = say('med.lookup.linked', {name: item.name});
      linked.hidden = false; status.textContent = '';
      // What the name itself says: the strength, and what one dose is counted in.
      if (item.strength) { field('strength').value = item.strength; strengthHelp.textContent = strengthHelp.dataset.picked; }
      if (item.unit) {
        field('dose_unit').value = item.unit;
        if (!field('dose_amount').value && ['tablet', 'capsule', 'sachet', 'suppository', 'patch'].includes(item.unit)) field('dose_amount').value = '1';
      }
      close(); total(); input.focus();
    };
    const mark = index => {
      active = index;
      [...list.children].forEach((node, order) => node.setAttribute('aria-selected', String(order === index)));
      if (index < 0) { input.removeAttribute('aria-activedescendant'); return; }
      input.setAttribute('aria-activedescendant', list.children[index].id);
      list.children[index].scrollIntoView({block: 'nearest'});
    };
    const show = found => {
      items = found;
      list.replaceChildren(...found.map((item, index) => {
        const node = document.createElement('li');
        node.id = `med-lookup-${index}`; node.setAttribute('role', 'option'); node.setAttribute('aria-selected', 'false');
        const name = document.createElement('strong'); name.textContent = item.name;
        const note = document.createElement('span');
        note.textContent = [item.kind === 'product' ? item.maker : say('med.lookup.trade_name'), item.kind === 'product' ? '' : item.strength]
          .filter(Boolean).join(' · ');
        node.append(name, note);
        // mousedown, not click: the input must not lose focus before the choice lands.
        node.addEventListener('mousedown', event => { event.preventDefault(); choose(item); });
        return node;
      }));
      list.hidden = !found.length; active = -1;
      input.setAttribute('aria-expanded', String(Boolean(found.length)));
    };
    const ask = async () => {
      const text = input.value.trim();
      if (!isDrug() || text.length < 3 || text === chosen) { close(); status.textContent = ''; return; }
      const mine = ++asked;
      status.textContent = say('med.lookup.searching');
      try {
        const reply = await fetch(`/medicines/lookup?q=${encodeURIComponent(text)}`, {headers: {Accept: 'application/json'}});
        const data = reply.ok ? await reply.json() : {items: [], error: 'unavailable'};
        if (mine !== asked) return;   // a later keystroke already asked again
        show(data.items || []);
        if (data.error === 'paused') status.textContent = say('med.lookup.paused', {minutes: data.minutes || 1});
        else if (data.error === 'unavailable') status.textContent = say('med.lookup.unavailable');
        else status.textContent = (data.items || []).length || data.error ? '' : say('med.lookup.none');
      } catch {
        if (mine === asked) { close(); status.textContent = say('med.lookup.unavailable'); }
      }
    };
    input.addEventListener('input', () => {
      if (chosen !== null && input.value !== chosen) unlink();
      // Half a second of quiet before asking: one request per word, not per letter.
      clearTimeout(timer); timer = setTimeout(ask, 500);
    });
    input.addEventListener('keydown', event => {
      if (list.hidden) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); mark((active + 1) % items.length); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); mark((active - 1 + items.length) % items.length); }
      else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); choose(items[active]); }
      else if (event.key === 'Escape') close();
    });
    input.addEventListener('blur', () => setTimeout(close, 150));
    // Switching to a kind with no instruction drops a link made for a medicine.
    form.addEventListener('change', event => { if (event.target.name === 'kind' && !isDrug()) { unlink(); close(); } });
  }

  /* ---- AI panel --------------------------------------------------------- */

  const panel = form.querySelector('[data-med-ai]');
  if (!panel) return;
  const start = panel.querySelector('[data-med-ai-start]');
  const cancel = panel.querySelector('[data-med-ai-cancel]');
  const statusLine = panel.querySelector('[data-med-ai-status]');
  const sourceLine = panel.querySelector('[data-med-ai-source]');
  const effectsBox = form.querySelector('[data-med-ai-effects]');
  const regimenOffer = form.querySelector('[data-med-ai-regimen]');
  const aiFields = field('ai_fields');
  const accepted = new Map();   // field name -> the AI text now sitting in it
  let run = 0, clock = 0;

  const tell = (text, state = '') => {
    statusLine.textContent = text; statusLine.hidden = !text; statusLine.dataset.state = state;
  };
  const template = id => document.querySelector(id).content.firstElementChild.cloneNode(true);
  const quoteInto = (node, quote, sourced) => {
    const block = node.querySelector('[data-slot="quote"]');
    const none = node.querySelector('[data-slot="unquoted"]');
    block.hidden = !quote; if (quote) block.querySelector('q').textContent = quote;
    // "Not in the instruction" is only a statement when there was an instruction.
    none.hidden = Boolean(quote) || !sourced;
  };
  const sync = () => {
    // Only a text the person has not touched since stays marked as the AI's.
    for (const [name, text] of accepted) if (field(name).value !== text) accepted.delete(name);
    aiFields.value = [...accepted.keys()].join(',');
  };
  form.addEventListener('submit', sync);
  const wrap = name => form.querySelector(`[data-ai-field="${name}"]`);
  const clearNote = name => wrap(name).querySelector('[data-ai-note]')?.remove();
  const put = (name, entry, sourced) => {
    const control = field(name);
    control.value = entry.text; accepted.set(name, entry.text);
    clearNote(name);
    const note = template('#med-ai-filled-template');
    quoteInto(note, entry.quote, sourced);
    note.querySelector('[data-act="clear"]').addEventListener('click', () => {
      control.value = ''; accepted.delete(name); note.remove(); control.focus();
    });
    wrap(name).append(note);
  };
  const offer = (name, entry, sourced) => {
    clearNote(name);
    const note = template('#med-ai-offer-template');
    note.querySelector('[data-slot="text"]').textContent = entry.text;
    quoteInto(note, entry.quote, sourced);
    note.querySelector('[data-act="replace"]').addEventListener('click', () => put(name, entry, sourced));
    note.querySelector('[data-act="dismiss"]').addEventListener('click', () => { note.remove(); field(name).focus(); });
    wrap(name).append(note);
  };

  const apply = suggestion => {
    const sourced = Boolean(suggestion.source);
    let any = false;
    for (const [name, entry] of Object.entries(suggestion.fields || {})) {
      if (!wrap(name) || !entry.text) continue;
      const mine = field(name).value.trim();
      if (mine === entry.text.trim()) continue;
      any = true;
      // An empty field, or one still holding the AI's earlier text, is filled.
      // What the person wrote is offered a replacement and left alone.
      if (!mine || accepted.get(name) === field(name).value) put(name, entry, sourced); else offer(name, entry, sourced);
    }
    const atc = field('atc_code');
    if (suggestion.atc_code && !atc.value) { atc.value = suggestion.atc_code; form.querySelector('[data-med-ai-atc]').hidden = false; any = true; }

    const rows = effectsBox.querySelector('ul');
    rows.replaceChildren(...(suggestion.effects || []).map(effect => {
      const row = template('#med-ai-effect-template');
      row.querySelector('input').value = JSON.stringify({
        concept_id: effect.concept_id || null, label: effect.label, direction: effect.direction,
        note: effect.note || '', quote: effect.quote || '',
      });
      const chip = row.querySelector('[data-slot="chip"]');
      chip.dataset.direction = effect.direction;
      const arrow = document.createElement('span');
      arrow.className = 'an-effect__arrow'; arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = {raises: '↑', lowers: '↓'}[effect.direction] || '↕';
      chip.append(arrow, `${effect.direction_label} ${effect.label}`);
      row.querySelector('[data-slot="note"]').textContent = effect.note || '';
      quoteInto(row, effect.quote, sourced);
      return row;
    }));
    effectsBox.hidden = !rows.children.length;
    any = any || Boolean(rows.children.length);

    const usual = suggestion.regimen;
    regimenOffer.hidden = !(usual && usual.text && isDrug());
    if (!regimenOffer.hidden) {
      any = true;
      regimenOffer.querySelector('[data-slot="text"]').textContent = usual.text;
      regimenOffer.querySelector('q').textContent = usual.quote || '';
      regimenOffer.querySelector('[data-act="use"]').onclick = () => {
        if (usual.dose_amount) field('dose_amount').value = String(usual.dose_amount);
        if (usual.dose_unit) field('dose_unit').value = usual.dose_unit;
        if (usual.repeat) field('repeat').value = usual.repeat;
        if (usual.every) field('every').value = String(usual.every);
        if (usual.per_day) perDay.value = String(usual.per_day);
        regimenOffer.hidden = true; changed(field('repeat'));
      };
    }

    const link = sourceLine.querySelector('a');
    sourceLine.querySelector('span').textContent = !sourced ? panel.dataset.noSource
      : suggestion.source.shown_for ? panel.dataset.source.replace('{name}', suggestion.source.shown_for) : panel.dataset.sourcePlain;
    link.hidden = !sourced; if (sourced) link.href = suggestion.source.url;
    sourceLine.hidden = false;
    tell(any ? panel.dataset.done : panel.dataset.doneEmpty, 'done');
    sync();
  };

  const finish = () => {
    clearInterval(clock); run += 1;
    start.disabled = false; start.textContent = panel.dataset.again;
    cancel.hidden = true;
  };
  const fail = reason => { finish(); tell(panel.getAttribute(`data-error-${reason}`) || panel.getAttribute('data-error-lost'), 'error'); };
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

  const research = async () => {
    if (!field('name').value.trim()) { tell(panel.dataset.needName, 'error'); field('name').focus(); return; }
    const mine = ++run;
    const began = Date.now();
    start.disabled = true; cancel.hidden = false; sourceLine.hidden = true;
    const tick = () => tell(panel.dataset.running.replace('{seconds}', String(Math.round((Date.now() - began) / 1000))), 'running');
    tick(); clock = setInterval(tick, 1000);
    try {
      const body = new FormData(form);
      body.delete('action');
      const asked = await fetch('/medicines/suggest', {method: 'POST', body, headers: {Accept: 'application/json'}});
      const opened = asked.ok ? await asked.json() : {error: 'lost'};
      if (mine !== run) return;
      if (!opened.job) { fail(opened.error || 'lost'); return; }
      // Poll rather than hold one request open: a phone that sleeps mid-wait
      // picks the answer up when it wakes.
      for (;;) {
        await wait(1500);
        if (mine !== run) return;
        const reply = await fetch(`/medicines/suggest/${encodeURIComponent(opened.job)}`, {headers: {Accept: 'application/json'}});
        const state = reply.ok ? await reply.json() : {state: 'failed', error: 'lost'};
        if (mine !== run) return;
        if (state.state === 'running') continue;
        if (state.state === 'done') { finish(); apply(state.suggestion); } else fail(state.error || 'lost');
        return;
      }
    } catch {
      if (mine === run) fail('lost');
    }
  };
  start.addEventListener('click', research);
  cancel.addEventListener('click', () => { finish(); tell(''); });
  if ('autostart' in panel.dataset) research();
})();
