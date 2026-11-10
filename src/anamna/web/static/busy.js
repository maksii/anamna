/* Feedback for every server round trip, across the whole site.

   Native ones (a form submit, a link to another page) are covered here for
   every page: a thin bar runs along the top once the wait passes 150 ms (so
   an instant page never flashes it), the pressed control is marked busy (a
   spinner, see `[aria-busy]` in app.css), and a second press of the same
   form is ignored until the next page arrives.  A control with `data-busy`
   also says what is happening ("Building the plan...") while it waits.

   Scripts that call the server in place use the same look through
   `anamnaBusy.track(control, promise)`: the control is disabled and marked
   busy, the bar runs, and both are undone when the promise settles, whatever
   way it settles.  Error text stays the caller's job: it knows what failed. */
(() => {
  const DELAY = 150;
  // A response that downloads a file leaves this page in place: nothing
  // arrives to clear the bar, so it clears itself.
  const DOWNLOAD_RELEASE = 6000;
  const RELEASE = 20000;
  const FILE = /\.(pdf|csv|zip|json|txt|xlsx?)$/i;
  let bar = null;
  let timer = 0;
  let release = 0;
  let pending = 0;
  const marked = new Set();

  function showBar() {
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'an-progress';
      bar.setAttribute('role', 'progressbar');
      bar.setAttribute('aria-label', (globalThis.__HL_I18N__ || {})['busy.loading'] || 'Loading');
      document.body.append(bar);
    }
    bar.hidden = false;
  }

  function soon() {
    clearTimeout(timer);
    timer = setTimeout(showBar, DELAY);
  }

  function hideBar() {
    clearTimeout(timer);
    if (bar) bar.hidden = true;
  }

  function mark(control) {
    if (!control || control.nodeType !== 1) return;
    control.setAttribute('aria-busy', 'true');
    // `data-working` is the older spelling of the same thing.
    const saying = control.dataset.busy || control.dataset.working;
    if (saying && !('label' in control.dataset)) {
      control.dataset.label = control.textContent;
      control.textContent = saying;
    }
    marked.add(control);
  }

  function unmark(control) {
    control.removeAttribute('aria-busy');
    if ('label' in control.dataset) {
      control.textContent = control.dataset.label;
      delete control.dataset.label;
    }
  }

  // Leaving the page: the bar, the pressed control, the form locked.
  function navigating(control, wait = RELEASE) {
    mark(control);
    soon();
    clearTimeout(release);
    release = setTimeout(reset, wait);
  }

  function reset() {
    clearTimeout(release);
    if (!pending) hideBar();
    marked.forEach(unmark);
    marked.clear();
    document.querySelectorAll('form[data-submitting]').forEach((form) => delete form.dataset.submitting);
  }

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (form.dataset.submitting) {
      event.preventDefault();
      return;
    }
    // The page's own handlers run first; a submit they cancel (a search that
    // answers in place) is not a navigation.
    setTimeout(() => {
      if (event.defaultPrevented) return;
      const submitter = event.submitter;
      const target = (submitter && submitter.getAttribute('formtarget')) || form.getAttribute('target') || '_self';
      if (target !== '_self') return;
      const action = (submitter && submitter.getAttribute('formaction')) || form.getAttribute('action') || '';
      form.dataset.submitting = '1';
      navigating(submitter || form.querySelector('[type=submit]'), FILE.test(action.split(/[?#]/)[0]) ? DOWNLOAD_RELEASE : RELEASE);
    });
  });

  document.addEventListener('click', (event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest && event.target.closest('a[href]');
    if (!link || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !/^https?:$/.test(url.protocol)) return;
    // The same page with another anchor only scrolls.
    if (url.pathname === location.pathname && url.search === location.search) return;
    setTimeout(() => {
      if (event.defaultPrevented) return;
      const download = link.hasAttribute('download') || FILE.test(url.pathname);
      navigating(link, download ? DOWNLOAD_RELEASE : RELEASE);
    });
  });

  // Back and forward restore a page as it was left, mid-wait included.
  addEventListener('pageshow', reset);

  async function track(control, work) {
    const was = control && 'disabled' in control ? control.disabled : null;
    if (control && control.nodeType === 1) {
      mark(control);
      marked.delete(control);
      if (was === false) control.disabled = true;
    }
    pending += 1;
    soon();
    try {
      return await (typeof work === 'function' ? work() : work);
    } finally {
      pending -= 1;
      if (!pending) hideBar();
      if (control && control.nodeType === 1) {
        unmark(control);
        if (was === false) control.disabled = false;
      }
    }
  }

  // A form marked data-confirm asks first; the message is the attribute. A
  // cancelled submit stops here, before any other submit handler runs.
  document.addEventListener('submit', (event) => {
    const form = event.target;
    const message = form && form.getAttribute && form.getAttribute('data-confirm');
    if (message && !window.confirm(message)) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);

  // Controls that used to carry inline handlers (the strict CSP blocks those).
  // Focus does not bubble, so the focus listener captures.
  document.addEventListener('focus', (event) => {
    const node = event.target;
    if (node && node.dataset && node.dataset.action === 'select-all') node.select();
  }, true);
  document.addEventListener('change', (event) => {
    const node = event.target;
    if (node && node.dataset && node.dataset.action === 'token-kind' && node.form) {
      node.form.expires_on.required = node.value === 'guest';
    }
  });

  globalThis.anamnaBusy = { track, navigating, reset };
})();
