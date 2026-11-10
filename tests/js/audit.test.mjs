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
