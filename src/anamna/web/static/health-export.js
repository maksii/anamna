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
})();
