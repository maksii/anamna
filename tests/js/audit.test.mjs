import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Text-level guards: each assertion names a fix that a revert would undo. The
// browser behaviour itself is exercised by the page checks, not here.
const read = name => readFileSync(new URL(`../../src/anamna/web/static/${name}`, import.meta.url), 'utf8');

test('uploads.js retries a failed poll and says so after a run of failures', () => {
  const src = read('uploads.js');
  const poll = src.slice(src.indexOf('async function poll()'), src.indexOf('function stop()'));
  // The catch that follows the fetch must count the failure, not stop at once.
  const catchBlock = poll.slice(poll.indexOf('} catch {'), poll.indexOf('failures = 0;'));
  assert.match(catchBlock, /failures \+= 1/);
  assert.match(poll, /failures < FAILURES_BEFORE_STALLED/);
  assert.doesNotMatch(catchBlock, /return stop\(\);/);
  // The stalled line comes from the template and is written as text, never HTML.
  assert.match(src, /section\.dataset\.msgStalled/);
  assert.match(src, /summary\.textContent = text;/);
});

test('device-chart.js lets only the newest source or range switch touch the page state', () => {
  const src = read('device-chart.js');
  assert.match(src, /let latest = 0;/);
  assert.match(src, /const mine = \+\+latest;/);
  assert.match(src, /mine !== latest/);
  // Both switches go through the guarded loader, so neither can bypass it.
  assert.equal([...src.matchAll(/refresh\(button, activeSource\)/g)].length, 2);
});

test('app.css gives every 100vh declaration a 100dvh twin on the next line', () => {
  const lines = read('app.css').split('\n');
  const vh = lines.flatMap((line, index) => (line.includes('100vh') ? [index] : []));
  assert.ok(vh.length > 0, 'expected at least one 100vh declaration');
  for (const index of vh) {
    assert.match(lines[index + 1] ?? '', /100dvh/, `line ${index + 1} has 100vh but line ${index + 2} has no 100dvh`);
  }
});

test('app.css colours the agreed_ua_us vaccination agreement pill', () => {
  assert.match(read('app.css'), /data-vax-agreement="agreed_ua_us"/);
});

test('app.css styles the first-run welcome steps inside the 1100px breakpoint', () => {
  const src = read('app.css');
  assert.match(src, /\.an-home-welcome__steps \{/);
  // Link labels are sentences: they wrap, and the step links keep their text inside the rule.
  const linkRule = src.match(/\.an-home-welcome__steps a \{[^}]*\}/);
  assert.ok(linkRule, 'expected a .an-home-welcome__steps a rule');
  assert.match(linkRule[0], /white-space: normal/);
  assert.match(src, /@media \(min-width: 1100px\) \{\s*\.an-home-welcome__steps \{ grid-template-columns: repeat\(3, minmax\(0, 1fr\)\); \}/);
  // No 720px block may carry the three-column welcome steps any more.
  for (const block of src.matchAll(/@media \(min-width: 720px\) \{/g)) {
    // A top-level media block closes with a bare '}' at the start of a line.
    const end = src.indexOf('\n}', block.index);
    assert.ok(end > block.index, 'expected the 720px block to close');
    assert.doesNotMatch(src.slice(block.index, end), /\.an-home-welcome__steps/);
  }
});

// The rest need a DOM to run against, which this harness does not stub; each
// asserts on the source instead, so a revert of the fix fails the test.

test('uploads.js updates queue rows in place instead of replacing the whole list each poll', () => {
  const src = read('uploads.js');
  // The old poll rebuilt every row, so the screen reader re-read the queue and
  // keyboard focus inside a row was lost every 1.2 s.
  assert.doesNotMatch(src, /replaceChildren\(\.\.\.payload\.jobs\.map\(render\)\)/);
  assert.match(src, /sync\(payload\.jobs\);/);
  // An unchanged row is kept as the same node; a changed one is swapped alone.
  assert.match(src, /if \(node\.outerHTML === fresh\.outerHTML\) \{\s*target = node;/);
  assert.match(src, /item\.dataset\.job = job\.id;/);
  assert.match(src, /if \(!wanted\.has\(id\)\) node\.remove\(\);/);
  // The focused link is found again in the new row.
  assert.match(src, /restoreFocus\(focused, fresh\)/);
});

test('uploads.js writes progress to the bar only and says the queue count only when it moves', () => {
  const src = read('uploads.js');
  const show = src.slice(src.indexOf('const show = (percent) =>'), src.indexOf('const announce = (text) =>'));
  assert.doesNotMatch(show, /chosen/);
  assert.match(src, /bar\.value = percent/);
  assert.match(src, /getElementById\("an-upload-status"\)/);
  assert.match(src, /strings\["upload\.announce_done"\]/);
  assert.match(src, /if \(counts === spokenCounts\) return;/);
});

test('device-chart.js makes only the newest point a Tab stop and walks the rest with the arrow keys', () => {
  const src = read('device-chart.js');
  assert.doesNotMatch(src, /tabindex: '0', role: 'button'/);
  assert.match(src, /tabindex: index === points\.length - 1 \? '0' : '-1'/);
  assert.match(src, /ArrowLeft: at - 1, ArrowRight: at \+ 1, Home: 0, End: last/);
  assert.match(src, /node\.addEventListener\('focus', \(\) => moveStop\(node\)\);/);
});

test('source-viewer.js marks the pager edge with aria-disabled, never the disabled property', () => {
  const src = read('source-viewer.js');
  assert.doesNotMatch(src, /\.disabled =/);
  assert.match(src, /button\.setAttribute\("aria-disabled", "true"\)/);
  assert.match(src, /if \(!isBlocked\(prev\)\) setPage/);
  assert.match(src, /if \(!isBlocked\(next\)\) setPage/);
});

test('chat.js announces a finished answer and makes errors alerts', () => {
  const src = read('chat.js');
  assert.match(src, /answered \? say\("chat\.answer_ready"\) : ""/);
  assert.match(src, /note\.setAttribute\("role", "alert"\)/);
});
