/* The name field of the medicine form: suggestions from the reference site as
   the person types.  Picking one links the official instruction to the entry
   (two hidden fields); typing on after that drops the link, so a name can never
   stay tied to the instruction of a different medicine.  Without this script
   the field is a plain text input and the entry saves the same. */
(() => {
  const input = document.querySelector('[data-med-lookup]');
  const list = document.querySelector('#med-lookup-list');
  if (!input || !list) return;
  const form = input.form;
  const status = document.querySelector('#med-lookup-status');
  const linked = document.querySelector('#med-linked');
  const linkedText = linked.querySelector('[data-med-linked-text]');
  const refName = form.elements.reference_name;
  const refCode = form.elements.reference_code;
  const i18n = globalThis.__HL_I18N__ || {};
  const say = (key, name) => (i18n[key] || '').replace('{name}', name || '');
  let items = [], active = -1, timer = 0, asked = 0, chosen = refName.value ? input.value : null;

  // Only a medicine or a supplement has an instruction to look up.
  const applies = () => ['medicine', 'supplement'].includes(form.elements.kind.value);

  const close = () => {
    list.hidden = true; list.replaceChildren(); items = []; active = -1;
    input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant');
  };
  const unlink = () => { refName.value = ''; refCode.value = ''; chosen = null; linked.hidden = true; };
  const choose = item => {
    input.value = item.name;
    refName.value = item.reference_name;
    refCode.value = item.kind === 'product' ? item.code : '';
    chosen = item.name;
    linkedText.textContent = say('med.lookup.linked', item.name);
    linked.hidden = false; status.textContent = '';
    close(); input.focus();
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
      note.textContent = item.kind === 'product' ? item.maker : say('med.lookup.trade_name');
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
    if (!applies() || text.length < 3) { close(); status.textContent = ''; return; }
    const mine = ++asked;
    try {
      const reply = await fetch(`/medicines/lookup?q=${encodeURIComponent(text)}`, {headers: {Accept: 'application/json'}});
      const data = reply.ok ? await reply.json() : {items: [], error: 'unavailable'};
      if (mine !== asked) return;   // a later keystroke already asked again
      show(data.items || []);
      if (data.error === 'unavailable') status.textContent = say('med.lookup.unavailable');
      else status.textContent = (data.items || []).length || data.error ? '' : say('med.lookup.none');
    } catch {
      if (mine === asked) { close(); status.textContent = say('med.lookup.unavailable'); }
    }
  };

  input.addEventListener('input', () => {
    if (chosen !== null && input.value !== chosen) unlink();
    clearTimeout(timer); timer = setTimeout(ask, 300);
  });
  input.addEventListener('keydown', event => {
    if (list.hidden) return;
    if (event.key === 'ArrowDown') { event.preventDefault(); mark((active + 1) % items.length); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); mark((active - 1 + items.length) % items.length); }
    else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); choose(items[active]); }
    else if (event.key === 'Escape') close();
  });
  input.addEventListener('blur', () => setTimeout(close, 150));
  linked.querySelector('[data-med-unlink]').addEventListener('click', unlink);
  // Switching to a kind with no instruction drops a link made for a medicine.
  form.addEventListener('change', event => { if (event.target.name === 'kind' && !applies()) { unlink(); close(); } });
})();
