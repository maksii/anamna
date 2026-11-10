import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// chart.js only touches `document` inside functions, so an empty sandbox is enough to evaluate it.
function loadChart() {
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(new URL('../../src/anamna/web/static/chart.js', import.meta.url), 'utf8'), sandbox);
  return sandbox.AnamnaChart;
}

const C = loadChart();
const day = value => C.asDate(value).getTime();

test('timeX maps a moment between readings in proportion and clamps to the ends', () => {
  const x = C.timeX([0, 100, 300], [10, 20, 60]);
  assert.equal(x(0), 10);
  assert.equal(x(50), 15);
  assert.equal(x(100), 20);
  assert.equal(x(200), 40);
  assert.equal(x(300), 60);
  assert.equal(x(-500), 10);
  assert.equal(x(1000), 60);
});

test('timeX does not divide by zero for two readings at the same time', () => {
  const x = C.timeX([0, 100, 100, 300], [10, 20, 30, 60]);
  assert.equal(x(100), 20);
  assert.equal(x(150), 37.5);
  assert.ok(Number.isFinite(x(100)));
});

test('factorsIn keeps entries that overlap the span and drops those wholly outside it', () => {
  const from = day('2024-01-01');
  const to = day('2024-12-31');
  const kept = C.factorsIn([
    {name: 'ended mid-span', start: '2024-03-01', end: '2024-03-10', point: false},
    {name: 'ended on the last day', start: '2024-12-01', end: '2024-12-31', point: false},
    {name: 'ended on the first day', start: '2023-12-01', end: '2024-01-01', point: false},
    {name: 'ongoing since 2020', start: '2020-05-01', end: null, point: false},
    {name: 'point in June', start: '2024-06-01', end: null, point: true},
  ], from, to).map(item => item.name);
  assert.deepEqual(kept, ['ended mid-span', 'ended on the last day', 'ended on the first day', 'ongoing since 2020', 'point in June']);
});

test('factorsIn drops an entry that ended the day before the span starts', () => {
  const from = day('2024-01-01');
  const to = day('2024-12-31');
  assert.deepEqual(C.factorsIn([{name: 'ended 2023-12-31', start: '2023-06-01', end: '2023-12-31', point: false}], from, to), []);
});

test('factorsIn drops an entry that starts after the span and a point dated before it', () => {
  const from = day('2024-01-01');
  const to = day('2024-12-31');
  const kept = C.factorsIn([
    {name: 'starts 2025', start: '2025-02-01', end: null, point: false},
    {name: 'point in 2023', start: '2023-06-01', end: null, point: true},
  ], from, to);
  assert.deepEqual(kept, []);
});

test('factorRoom reserves one lane per entry up to six lanes', () => {
  assert.equal(C.factorRoom(0), 0);
  assert.equal(C.factorRoom(1), 23);
  assert.equal(C.factorRoom(6), 108);
  assert.equal(C.factorRoom(9), 108);
});
