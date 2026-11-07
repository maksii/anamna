/* Descriptive summaries of the exact points already selected for the chart.
   No medical thresholds, source reconciliation, or stored data changes here. */
(() => {
  const periodSummary = (section, points) => {
    const target = section?.querySelector('[data-period-summary]');
    if (!target) return;
    const C = globalThis.AnamnaChart;
    const numeric = points.filter(point => point.value !== null && point.value !== undefined && Number.isFinite(Number(point.value)));
    const values = numeric.map(point => Number(point.value));
    const set = (key, value) => {
      const node = target.querySelector(`[data-stat="${key}"]`);
      if (node) node.textContent = value;
    };
    set('count', C.num(numeric.length, 0));
    set('mean', values.length ? C.num(values.reduce((a,b) => a+b,0) / values.length, 1) : '-');
    set('range', values.length ? `${C.num(Math.min(...values), 2)}-${C.num(Math.max(...values), 2)}` : '-');
    const dates = target.querySelector('[data-period-dates]');
    if (dates) {
      const unit = numeric.length && numeric[0].unit ? ` · ${numeric[0].unit}` : '';
      dates.textContent = numeric.length
        ? `${C.fullDate(C.asDate(numeric[0].date))} - ${C.fullDate(C.asDate(numeric.at(-1).date))}${unit}`
        : '';
    }
  };
  const timeTicks = (points, xAt, spacing = 92) => {
    if (!points.length) return [];
    const stops = [0];
    for (let index = 1; index < points.length - 1; index++) {
      if (xAt(index) - xAt(stops.at(-1)) >= spacing) stops.push(index);
    }
    const last = points.length - 1;
    if (last) {
      if (stops.length > 1 && xAt(last) - xAt(stops.at(-1)) < spacing) stops.pop();
      stops.push(last);
    }
    return stops;
  };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character]));
  const sourceLabel = (vendor, source) => {
    const manufacturer = String(vendor ?? '').trim();
    const name = String(source ?? '').trim();
    if (!name) return manufacturer;
    if (!manufacturer || name.toLocaleLowerCase().startsWith(manufacturer.toLocaleLowerCase())) return name;
    return `${manufacturer} · ${name}`;
  };
  const dailyWindow = (points, days, anchor) => {
    if (!days) return points;
    const cutoff = globalThis.AnamnaChart.asDate(anchor);
    cutoff.setDate(cutoff.getDate() - (days - 1));
    return points.filter(point => globalThis.AnamnaChart.asDate(point.date) >= cutoff && globalThis.AnamnaChart.asDate(point.date) <= globalThis.AnamnaChart.asDate(anchor));
  };
  const thinDaily = (points, limit) => {
    if (points.length <= limit) return points;
    const C = globalThis.AnamnaChart;
    const runs = [];
    points.forEach((point, index) => {
      const previous = points[index - 1];
      const gap = previous && C.asDate(point.date) - C.asDate(previous.date) > 36 * 3600000;
      const sourceChanged = previous && (point.vendor !== previous.vendor || point.source !== previous.source);
      if (!index || gap || sourceChanged) runs.push([]);
      runs.at(-1).push(point);
    });
    // Capacity is a visual budget, never a reason to combine disconnected
    // dates. Many separate runs can legitimately exceed that budget.
    return runs.flatMap(run => C.thin(run, Math.max(2, Math.floor(limit * run.length / points.length))));
  };
  const nearestPoint = (points, x, y) => {
    let nearest = null;
    let distance = Infinity;
    for (const point of points) {
      const candidate = (point.x - x) ** 2 + (point.y - y) ** 2;
      if (candidate < distance) { distance = candidate; nearest = point; }
    }
    return nearest;
  };
  globalThis.AnamnaExperience = {periodSummary, timeTicks, escape, sourceLabel, dailyWindow, thinDaily, nearestPoint};
  // aria-pressed follows existing chart controls without replacing their logic.
  const init = () => {
    document.querySelectorAll('.chart-controls, .an-source-controls').forEach(group => {
      const sync = () => group.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.classList.contains('active'))));
      sync();
      group.addEventListener('click', () => queueMicrotask(sync));
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
