import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Just enough page for medicine_info.js: a link, a dialog, a fetch and a parser.
function element(tag) {
  const attributes = new Map();
  const node = {
    tagName: tag.toUpperCase(), className: '', textContent: '', children: [], handlers: {}, open: false,
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    remove() { this.removed = true; },
    focus() { this.focused = true; },
    addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); },
    showModal() { this.open = true; },
    close() { this.open = false; (this.handlers.close || []).forEach((fn) => fn({target: this})); },
  };
  return node;
}

function load({reply, dialogs = true}) {
  const listeners = {};
  const appended = [];
  const fetched = [];
  const went = [];
  const article = {id: 'med-instruction', imported: false};
  const context = {
    document: {
      body: {append(...nodes) { appended.push(...nodes); }},
      createElement: (tag) => element(tag),
      importNode(node) { return {...node, imported: true}; },
      addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    },
    location: {assign(url) { went.push(url); }},
    fetch: async (url) => { fetched.push(url); return reply(); },
    DOMParser: class { parseFromString(text) { return {getElementById: (id) => (text.includes(id) ? article : null)}; } },
    __HL_I18N__: {'med.info.close': 'Закрити', 'med.info.loading': 'Читаємо інструкцію…'},
  };
  context.globalThis = context;
  if (dialogs) context.HTMLDialogElement = function HTMLDialogElement() {};
  vm.createContext(context);
  vm.runInContext(readFileSync(new URL('../../src/anamna/web/static/medicine_info.js', import.meta.url), 'utf8'), context);
  const link = element('a');
  link.href = '/medicines/m1/instruction';
  link.textContent = 'Instruction for use';
  link.closest = (selector) => (selector === 'a[data-med-info]' ? link : null);
  const click = (extra = {}) => {
    const event = {target: link, button: 0, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra};
    listeners.click.forEach((fn) => fn(event));
    return event;
  };
  return {link, click, appended, fetched, went};
}

const settle = () => new Promise((resolve) => setImmediate(resolve));
const page = (text) => () => ({ok: true, text: async () => text});

test('a click opens a dialog and puts the instruction of the linked page into it', async () => {
  const {click, appended, fetched} = load({reply: page('<article id="med-instruction"></article>')});
  const event = click();
  assert.equal(event.defaultPrevented, true);
  const dialog = appended[0];
  assert.equal(dialog.open, true);
  assert.equal(dialog.getAttribute('aria-label'), 'Instruction for use');
  assert.equal(dialog.children[1].children[0].textContent, 'Читаємо інструкцію…');
  assert.equal(dialog.children[0].children[0].textContent, 'Закрити');
  await settle();
  assert.deepEqual(fetched, ['/medicines/m1/instruction']);
  assert.equal(dialog.children[1].children[0].imported, true);
});

test('closing the dialog removes it and gives the focus back to the link', async () => {
  const {link, click, appended} = load({reply: page('<article id="med-instruction"></article>')});
  click();
  await settle();
  appended[0].close();
  assert.equal(appended[0].removed, true);
  assert.equal(link.focused, true);
});

test('a click with a modifier key, or in a browser without dialogs, is left to the browser', () => {
  const held = load({reply: page('')});
  assert.equal(held.click({ctrlKey: true}).defaultPrevented, false);
  assert.equal(held.appended.length, 0);
  const old = load({reply: page(''), dialogs: false});
  assert.equal(old.click().defaultPrevented, false);
  assert.equal(old.appended.length, 0);
});

test('when the page cannot be read the browser goes to it', async () => {
  const refused = load({reply: () => ({ok: false, status: 403, text: async () => ''})});
  refused.click();
  await settle();
  assert.deepEqual(refused.went, ['/medicines/m1/instruction']);
  const empty = load({reply: page('<main>signed out</main>')});
  empty.click();
  await settle();
  assert.deepEqual(empty.went, ['/medicines/m1/instruction']);
});
