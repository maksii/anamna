import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Just enough DOM for busy.js: elements with attributes and a dataset,
// listeners on document and window, and timers that run when told to.
function element(tag = 'button') {
  const attributes = new Map();
  return {
    nodeType: 1, tagName: tag.toUpperCase(), dataset: {}, disabled: false, hidden: false, textContent: 'Go',
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
    removeAttribute(name) { attributes.delete(name); },
    querySelector() { return null; },
  };
}

function load() {
  const listeners = {};
  const timers = [];
  const forms = [];
  const document = {
    body: {append() {}},
    createElement: (tag) => element(tag),
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    querySelectorAll: (selector) => (selector === 'form[data-submitting]' ? forms.filter((f) => f.dataset.submitting) : []),
  };
  const context = {
    document, location: {href: 'http://x/a', origin: 'http://x', pathname: '/a', search: ''}, URL,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    setTimeout(fn, delay = 0) { timers.push([fn, delay]); return timers.length; }, clearTimeout() {},
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(readFileSync(new URL('../../src/anamna/web/static/busy.js', import.meta.url), 'utf8'), context);
  // Runs what is due now and the 150 ms bar delay; never the long safety release.
  const flush = () => {
    for (let at = 0; at < timers.length; at += 1) if (timers[at][1] < 1000) timers[at][1] = Infinity, timers[at][0]();
  };
  return {busy: context.anamnaBusy, listeners, flush, forms};
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
