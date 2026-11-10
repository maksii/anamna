import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Just enough DOM for busy.js: elements with attributes and a dataset,
// listeners on document and window, and timers that run when told to.
function element(tag = 'button') {
  const attributes = new Map();
  const node = {
    nodeType: 1, tagName: tag.toUpperCase(), dataset: {}, disabled: false, hidden: false, textContent: 'Go',
    className: '', id: '', type: '', children: [], handlers: {},
    setAttribute(name, value) {
      attributes.set(name, String(value));
      // As a browser does: data-foo-bar is dataset.fooBar.
      if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
    },
    getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
    removeAttribute(name) { attributes.delete(name); },
    querySelector() { return null; },
    append(...nodes) { this.children.push(...nodes); },
    remove() { this.removed = true; },
    focus() { this.focused = true; },
    addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); },
    fire(type) { (this.handlers[type] || []).forEach((fn) => fn({target: this})); },
  };
  if (tag === 'dialog') {
    Object.assign(node, {
      returnValue: '',
      showModal() { this.open = true; },
      close(value) { this.open = false; this.returnValue = value === undefined ? '' : String(value); this.fire('close'); },
    });
  }
  return node;
}

function load({dialogs = true, i18n = null, confirm = () => false} = {}) {
  const listeners = {};
  const timers = [];
  const forms = [];
  const appended = [];
  const confirmCalls = [];
  const document = {
    body: {append(...nodes) { appended.push(...nodes); }},
    createElement: (tag) => element(tag),
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    querySelectorAll: (selector) => (selector === 'form[data-submitting]' ? forms.filter((f) => f.dataset.submitting) : []),
  };
  const context = {
    document, location: {href: 'http://x/a', origin: 'http://x', pathname: '/a', search: ''}, URL,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    setTimeout(fn, delay = 0) { timers.push([fn, delay]); return timers.length; }, clearTimeout() {},
    confirm: (message) => { confirmCalls.push(message); return confirm(message); },
  };
  context.globalThis = context;
  context.window = context;
  if (dialogs) context.HTMLDialogElement = function HTMLDialogElement() {};
  if (i18n) context.__HL_I18N__ = i18n;
  vm.createContext(context);
  vm.runInContext(readFileSync(new URL('../../src/anamna/web/static/busy.js', import.meta.url), 'utf8'), context);
  // Runs what is due now and the 150 ms bar delay; never the long safety release.
  const flush = () => {
    for (let at = 0; at < timers.length; at += 1) if (timers[at][1] < 1000) timers[at][1] = Infinity, timers[at][0]();
  };
  return {busy: context.anamnaBusy, listeners, flush, forms, appended, confirmCalls};
}

// A form with its attributes, and the two methods busy.js calls on a form.
function fakeForm(attributes = {}) {
  const form = element('form');
  Object.entries(attributes).forEach(([name, value]) => form.setAttribute(name, value));
  return Object.assign(form, {
    requested: [],
    requestSubmit(submitter) { this.requested.push(submitter); },
    submit() { this.submitted = true; },
  });
}

function fakeSubmit(form, submitter = null) {
  return {
    target: form, submitter, defaultPrevented: false, stopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.stopped = true; },
  };
}

test('track marks the control busy and disabled, then restores it however the work ends', async () => {
  const {busy} = load();
  const button = element();
  let resolve;
  const work = busy.track(button, new Promise((r) => { resolve = r; }));
  assert.equal(button.getAttribute('aria-busy'), 'true');
  assert.equal(button.disabled, true);
  resolve('ok');
  assert.equal(await work, 'ok');
  assert.equal(button.getAttribute('aria-busy'), null);
  assert.equal(button.disabled, false);
  await assert.rejects(busy.track(button, Promise.reject(new Error('no'))));
  assert.equal(button.getAttribute('aria-busy'), null);
  assert.equal(button.disabled, false);
  // A control that was disabled before stays disabled after.
  button.disabled = true;
  await busy.track(button, Promise.resolve());
  assert.equal(button.disabled, true);
});

test('a control with data-busy says what is happening and gets its label back', () => {
  const {busy} = load();
  const button = element();
  button.textContent = 'Build the plan';
  button.dataset.busy = 'Building the plan...';
  busy.navigating(button);
  assert.equal(button.textContent, 'Building the plan...');
  busy.reset();
  assert.equal(button.textContent, 'Build the plan');
  assert.equal(button.getAttribute('aria-busy'), null);
});

test('a second submit of the same form is ignored until the page changes', () => {
  const {listeners, flush, forms} = load();
  const form = element('form');
  forms.push(form);
  const submitter = element();
  const submit = () => {
    const event = {target: form, submitter, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }};
    listeners.submit.forEach((fn) => fn(event));
    flush();
    return event;
  };
  assert.equal(submit().defaultPrevented, false);
  assert.equal(form.dataset.submitting, '1');
  assert.equal(submitter.getAttribute('aria-busy'), 'true');
  assert.equal(submit().defaultPrevented, true);
  // Back to this page from history: everything is released.
  listeners.pageshow.forEach((fn) => fn({}));
  assert.equal(form.dataset.submitting, undefined);
  assert.equal(submit().defaultPrevented, false);
});

test('a submit the page answers in place is not treated as navigation', () => {
  const {listeners, flush} = load();
  const form = element('form');
  const event = {target: form, submitter: null, defaultPrevented: true, preventDefault() {}};
  listeners.submit.forEach((fn) => fn(event));
  flush();
  assert.equal(form.dataset.submitting, undefined);
});

// listeners.submit[0] is the submitting listener, listeners.submit[1] the confirm listener
// (the harness ignores the capture flag, so both land in one array in registration order).

test('a form with data-confirm opens a dialog instead of submitting, and never calls window.confirm', () => {
  const {listeners, appended, confirmCalls} = load();
  const form = fakeForm({'data-confirm': 'Delete this?'});
  const submitter = element();
  submitter.textContent = '  Delete  ';
  submitter.form = form;
  const event = fakeSubmit(form, submitter);
  listeners.submit[1](event);
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.stopped, true);
  assert.equal(confirmCalls.length, 0);
  assert.equal(appended.length, 1);
  const [dialog] = appended;
  assert.equal(dialog.tagName, 'DIALOG');
  assert.equal(dialog.className, 'an-confirm');
  assert.equal(dialog.getAttribute('role'), 'alertdialog');
  assert.equal(dialog.open, true);
  const [text, actions] = dialog.children;
  assert.equal(text.tagName, 'P');
  assert.equal(text.textContent, 'Delete this?');
  const [no, yes] = actions.children;
  assert.equal(no.textContent, 'Cancel');
  assert.equal(yes.textContent, 'Delete');
  assert.equal(no.focused, true);
  assert.equal(form.requested.length, 0);
});

test('pressing the dialog\'s yes button sends the form once with the pressed button', () => {
  const {listeners, appended} = load();
  const form = fakeForm({'data-confirm': 'Delete this?'});
  const submitter = element();
  submitter.textContent = '  Delete  ';
  submitter.form = form;
  listeners.submit[1](fakeSubmit(form, submitter));
  const [dialog] = appended;
  const yes = dialog.children[1].children[1];
  yes.fire('click');
  assert.equal(dialog.removed, true);
  assert.equal(form.dataset.confirmed, '1');
  assert.deepEqual(form.requested, [submitter]);
  // The confirmed re-submit goes through: no preventDefault, no second dialog.
  const again = fakeSubmit(form, submitter);
  listeners.submit[1](again);
  assert.equal(again.defaultPrevented, false);
  assert.equal('confirmed' in form.dataset, false);
  assert.equal(appended.length, 1);
});

test('pressing cancel, or closing the dialog with Escape, sends nothing', () => {
  {
    const {listeners, appended} = load();
    const form = fakeForm({'data-confirm': 'Delete this?'});
    listeners.submit[1](fakeSubmit(form, null));
    const [dialog] = appended;
    dialog.children[1].children[0].fire('click');
    assert.equal(dialog.removed, true);
    assert.equal(form.requested.length, 0);
    assert.equal('confirmed' in form.dataset, false);
  }
  {
    // Escape closes a <dialog> with no return value; that is a "no".
    const {listeners, appended} = load();
    const form = fakeForm({'data-confirm': 'Delete this?'});
    listeners.submit[1](fakeSubmit(form, null));
    const [dialog] = appended;
    dialog.close();
    assert.equal(dialog.removed, true);
    assert.equal(form.requested.length, 0);
    assert.equal('confirmed' in form.dataset, false);
  }
});

test('the dialog\'s words come from the page\'s translations', () => {
  const {listeners, appended} = load({i18n: {'confirm.cancel': 'Скасувати', 'confirm.yes': 'Так, продовжити'}});
  const form = fakeForm({'data-confirm': 'Видалити?'});
  listeners.submit[1](fakeSubmit(form, null));
  const [dialog] = appended;
  const [no, yes] = dialog.children[1].children;
  assert.equal(no.textContent, 'Скасувати');
  assert.equal(yes.textContent, 'Так, продовжити');
  yes.fire('click');
  // Submitted with Enter, so there is no pressed button to pass on.
  assert.equal(form.requested.length, 1);
  assert.equal(form.requested[0], undefined);
});

test('a form without data-confirm is left alone by the confirm listener', () => {
  const {listeners, appended, confirmCalls} = load();
  const form = fakeForm();
  const event = fakeSubmit(form, null);
  listeners.submit[1](event);
  assert.equal(event.defaultPrevented, false);
  assert.equal(event.stopped, false);
  assert.equal(appended.length, 0);
  assert.equal(confirmCalls.length, 0);
  assert.equal(form.submitted, undefined);
  assert.equal(form.requested.length, 0);
});

test('without <dialog> support the browser\'s own box is the fallback', () => {
  {
    const {listeners, appended, confirmCalls} = load({dialogs: false, confirm: () => true});
    const form = fakeForm({'data-confirm': 'Delete this?'});
    const event = fakeSubmit(form, null);
    listeners.submit[1](event);
    assert.equal(event.defaultPrevented, true);
    assert.deepEqual(confirmCalls, ['Delete this?']);
    assert.equal(form.submitted, true);
    assert.equal(form.requested.length, 0);
    assert.equal(appended.length, 0);
  }
  {
    const {listeners, appended, confirmCalls} = load({dialogs: false, confirm: () => false});
    const form = fakeForm({'data-confirm': 'Delete this?'});
    listeners.submit[1](fakeSubmit(form, null));
    assert.deepEqual(confirmCalls, ['Delete this?']);
    assert.notEqual(form.submitted, true);
    assert.equal(appended.length, 0);
  }
});

test('a form that only closes a dialog is not treated as a navigation', () => {
  const {listeners, flush} = load();
  const submitter = element();
  const dialogForm = fakeForm({method: 'DIALOG'});
  listeners.submit[0](fakeSubmit(dialogForm, submitter));
  flush();
  assert.equal('submitting' in dialogForm.dataset, false);
  assert.equal(submitter.getAttribute('aria-busy'), null);
  // Mirror: an ordinary form is a navigation and is marked.
  const form = fakeForm({action: '/x'});
  listeners.submit[0](fakeSubmit(form, submitter));
  flush();
  assert.equal(form.dataset.submitting, '1');
});

test('a question on the pressed button is asked only for that button', () => {
  const {listeners, appended} = load();
  const form = fakeForm();
  const add = Object.assign(element(), {form, textContent: 'Add'});
  const dismiss = Object.assign(element(), {form, textContent: 'Dismiss'});
  dismiss.setAttribute('data-confirm', 'Dismiss the ticked items?');
  // The button without a question sends the form at once.
  const plain = fakeSubmit(form, add);
  listeners.submit[1](plain);
  assert.equal(plain.defaultPrevented, false);
  assert.equal(appended.length, 0);
  // The button with one asks first, in its own words.
  const asked = fakeSubmit(form, dismiss);
  listeners.submit[1](asked);
  assert.equal(asked.defaultPrevented, true);
  assert.equal(appended.length, 1);
  assert.equal(appended[0].children[0].textContent, 'Dismiss the ticked items?');
  appended[0].children[1].children[1].fire('click');
  assert.equal(form.requested.length, 1);
  assert.equal(form.requested[0], dismiss);
});
