import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

function chartContext(formats={}, locale='en') {
  // The scripts read globalThis, which inside a vm context is the context itself.
  const context = {__HL_I18N__: {_formats:formats}, __HL_LOCALE__:locale, document: {readyState:'loading', addEventListener() {}}};
  context.window = context;
  vm.createContext(context);
  for (const asset of ['chart.js', 'patient-experience.js']) {
    vm.runInContext(readFileSync(new URL(`../../src/anamna/web/static/${asset}`, import.meta.url), 'utf8'), context);
  }
  return context.window;
}

test('chart uses configured English and Ukrainian month spellings including September', () => {
  for (const [locale, months] of [
    ['en', ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']],
    ['uk', ['січ.','лют.','бер.','квіт.','трав.','черв.','лип.','серп.','вер.','жовт.','лист.','груд.']],
  ]) {
    const {AnamnaChart:C} = chartContext({months_short:months}, locale);
    months.forEach((month, index) => {
      const date = C.asDate(`2026-${String(index+1).padStart(2,'0')}-08`);
      assert.equal(C.fullDate(date), `08 ${month} 2026`);
      assert.equal(C.dateLabel(30)(date), `8 ${month}`);
      assert.equal(C.dateLabel(365)(date), `${month} 2026`);
    });
  }
});

function points(count, start='2024-01-01') {
  const base = Date.parse(`${start}T12:00:00Z`);
  return Array.from({length:count}, (_, index) => ({date:new Date(base+index*86400000).toISOString().slice(0,10), value:index, vendor:'Apple Health',source:'Apple Watch'}));
}

test('period summaries use exact chosen points and replace prior summaries on empty selection', () => {
  const context = {
    AnamnaChart: {num: (value, digits) => Number(value).toFixed(digits), asDate: value => value, fullDate: value => value},
    document: {readyState: 'loading', addEventListener() {}},
  };
  context.window = context;
  vm.runInNewContext(readFileSync(new URL('../../src/anamna/web/static/patient-experience.js', import.meta.url), 'utf8'), context);
  const nodes = Object.fromEntries(['count','mean','range'].map(key => [`[data-stat="${key}"]`, {textContent: ''}]));
  nodes['[data-period-dates]'] = {textContent: ''};
  const section = {querySelector: () => ({querySelector: selector => nodes[selector]})};
  context.window.AnamnaExperience.periodSummary(section, [
    {date:'2026-09-01',value:0,unit:'steps'},
    {date:'2026-09-04',value:9000,unit:'steps'},
  ]);
  assert.equal(nodes['[data-stat="count"]'].textContent, '2');
  assert.equal(nodes['[data-stat="mean"]'].textContent, '4500.0');
  assert.equal(nodes['[data-stat="range"]'].textContent, '0.00-9000.00');
  assert.equal(nodes['[data-period-dates]'].textContent, '2026-09-01 - 2026-09-04 · steps');
  context.window.AnamnaExperience.periodSummary(section, []);
  assert.equal(nodes['[data-stat="count"]'].textContent, '0');
  assert.equal(nodes['[data-stat="mean"]'].textContent, '-');
  assert.equal(nodes['[data-stat="range"]'].textContent, '-');
  assert.equal(nodes['[data-period-dates]'].textContent, '');
  context.window.AnamnaExperience.periodSummary(section, [{date:'2026-09-01', value:null}]);
  assert.equal(nodes['[data-stat="count"]'].textContent, '0');
  assert.deepEqual(Array.from(context.window.AnamnaExperience.timeTicks([1,2,3,4], index => [0,5,10,220][index])), [0,3]);
  assert.equal(context.window.AnamnaExperience.escape('<img src="x">&'), '&lt;img src=&quot;x&quot;&gt;&amp;');
});

test('800 daily values yield exactly the latest 30 dates and unchanged raw period statistics', () => {
  const {AnamnaExperience:E} = chartContext();
  const all = points(800);
  const selected = E.dailyWindow(all, 30, all.at(-1).date);
  assert.equal(selected.length, 30);
  assert.equal(selected[0].date, all[770].date);
  assert.equal(selected.at(-1).date, all.at(-1).date);
  assert.equal(selected.reduce((sum, point) => sum+point.value, 0)/selected.length, 784.5);
  assert.equal(E.dailyWindow(all, 365, all.at(-1).date).length, 365);
  assert.equal(E.dailyWindow(all, 0, all.at(-1).date).length, 800);
  const sourceWithMissingLastDay = all.slice(0,-1);
  assert.equal(E.dailyWindow(sourceWithMissingLastDay, 30, all.at(-1).date).length, 29);
});

test('daily thinning retains missing-day gaps and does not average across source changes', () => {
  const {AnamnaExperience:E} = chartContext();
  const all = points(100);
  const withGap = [...all.slice(0,40), ...all.slice(60)];
  const before = JSON.stringify(withGap);
  const thinned = E.thinDaily(withGap, 8);
  assert.ok(thinned.length < withGap.length);
  assert.equal(JSON.stringify(withGap), before);
  assert.equal(thinned.reduce((sum, point) => sum+(point.hlGroup || 1), 0), withGap.length);
  for (const point of thinned) {
    assert.ok(!(point.hlFrom < all[40].date && point.hlTo > all[59].date), 'a bucket must not span the missing interval');
  }
  assert.ok(thinned.some((point,index) => index && Date.parse(point.hlFrom || point.date)-Date.parse(thinned[index-1].hlTo || thinned[index-1].date)>86400000));
  const alternating = all.map((point,index) => ({...point,source:index%2?'Oura':'Apple Watch'}));
  assert.equal(E.thinDaily(alternating, 8).length, alternating.length);
});

test('nearest plot point can be selected away from its small glyph', () => {
  const {AnamnaExperience:E} = chartContext();
  const positions = [{id:'first',x:20,y:30}, {id:'second',x:140,y:70}, {id:'third',x:260,y:120}];
  assert.equal(E.nearestPoint(positions,170,100).id,'second');
  assert.equal(E.nearestPoint(positions,250,50).id,'third');
  assert.equal(E.nearestPoint([],120,80),null);
});

test('device source labels avoid repeated vendor names while retaining different sources', () => {
  const {AnamnaExperience:E} = chartContext();
  assert.equal(E.sourceLabel('Oura','Oura'), 'Oura');
  assert.equal(E.sourceLabel('Oura','Oura Ring'), 'Oura Ring');
  assert.equal(E.sourceLabel('OpenWearables','OpenWearables · Oura'), 'OpenWearables · Oura');
  assert.equal(E.sourceLabel('Apple Health','Apple Watch'), 'Apple Health · Apple Watch');
});
