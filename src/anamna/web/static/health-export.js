(() => {
  const form = document.querySelector('#health-export-form');
  if (!form) return;
  const options = [...form.querySelectorAll('[data-export-option]')];
  const groups = [...form.querySelectorAll('[data-export-group]')];
  const search = form.querySelector('[data-export-search]');
  const count = form.querySelector('[data-selected-count]');
  const dirty = form.querySelector('[data-export-dirty]');
  const noResults = form.querySelector('[data-no-results]');
  const selectedTemplate = count?.dataset.template || count?.textContent || '';

  const visibleOptions = () => options.filter(option => !option.hidden);
  const updateCount = () => {
    const selected = options.filter(option => option.querySelector('input').checked).length;
    if (count) count.textContent = selectedTemplate.replace('{count}', String(selected));
  };
  const changed = () => { updateCount(); if (dirty) dirty.hidden = false; };

  search?.addEventListener('input', () => {
    const needle = search.value.trim().toLocaleLowerCase();
    options.forEach(option => {
      option.hidden = Boolean(needle) && !option.textContent.toLocaleLowerCase().includes(needle);
    });
    groups.forEach(group => {
      group.hidden = !group.querySelector('[data-export-option]:not([hidden])');
    });
    if (noResults) noResults.hidden = visibleOptions().length > 0;
  });
  form.querySelector('[data-select-visible]')?.addEventListener('click', () => {
    visibleOptions().forEach(option => { option.querySelector('input').checked = true; });
    changed();
  });
  form.querySelector('[data-clear-visible]')?.addEventListener('click', () => {
    visibleOptions().forEach(option => { option.querySelector('input').checked = false; });
    changed();
  });
  options.forEach(option => option.querySelector('input').addEventListener('change', changed));
  form.querySelector('[name="aggregation"]')?.addEventListener('change', changed);
  form.querySelector('[data-export-print]')?.addEventListener('click', () => globalThis.print());

  // The PDF is rendered on the server and can take a while: fetched here so
  // the button stays busy for exactly as long as that takes, then saved under
  // the server's file name.  A refusal (nothing selected) shows the server's
  // own words; anything else, a retry hint.
  const pdfError = form.querySelector('[data-export-pdf-error]');
  form.addEventListener('submit', (event) => {
    const button = event.submitter;
    if (!button || !button.hasAttribute('data-export-pdf') || !globalThis.fetch || !globalThis.anamnaBusy) return;
    event.preventDefault();
    if (pdfError) pdfError.hidden = true;
    const url = `${button.getAttribute('formaction')}?${new URLSearchParams(new FormData(form))}`;
    anamnaBusy.track(button, async () => {
      const response = await fetch(url, {credentials: 'same-origin'});
      if (!response.ok) {
        const reason = response.status === 400 ? (await response.text()).trim() : '';
        throw new Error(reason);
      }
      const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || 'health-history.pdf';
      const link = document.createElement('a');
      link.href = URL.createObjectURL(await response.blob());
      link.download = name;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    }).catch((error) => {
      if (!pdfError) return;
      pdfError.textContent = error.message || pdfError.dataset.failed;
      pdfError.hidden = false;
    });
  });
})();
