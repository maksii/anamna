/* Device metric chart: reads the columnar series inlined by
   device_metric_detail.html and fetches the rest on demand (PERF-03).
   A static asset so the browser and the CDN cache it across pages. */
(() => {
  const C = globalThis.AnamnaChart;
  const esc = globalThis.AnamnaExperience.escape;
  const payload = JSON.parse(document.querySelector('#device-chart-data').textContent);
  const band = JSON.parse(document.querySelector('#device-chart-band').textContent);
  const svg = document.querySelector('#device-trend');
  const host = document.querySelector('#device-chart');
  const tip = document.querySelector('#device-tooltip');
  const i18n = globalThis.__HL_I18N__ || {};
  let days = 30;
  let activeSource = 'combined';
  let inspectPlot = null;
  let pending = '';
  // Every switch takes a number. Only the newest may clear the busy state, show
  // the failure note or repaint; an older fetch that lands late still fills the
  // cache, so switching back to its source is instant.
  let latest = 0;
  svg.addEventListener('click', event => { if (inspectPlot) inspectPlot(event); });

  // The payload is columnar (one array per field, sources as indexes into
  // `labels`); the chart code below reads point objects, built once here.
  const points = (columns, labels) => columns.d.map((date, index) => ({
    date, value: columns.v[index], unit: payload.unit, vendor: labels[columns.s[index]], source: '',
    sample_count: columns.n[index], minimum: columns.lo[index], maximum: columns.hi[index],
  }));
  const series = {combined: points(payload.combined, payload.labels)};
  const all = () => series[activeSource] || [];
  // The window ends on the shown series' own last record: a source that
  // stopped in August otherwise opened on thirty empty November days.
  const newest = () => all().map(point => point.date).sort().at(-1);
  const selected = () => globalThis.AnamnaExperience.dailyWindow(all(), days, newest());
  let complete = payload.complete;
  // Resolves true when this request is still the newest, so the caller repaints
  // only for the switch the reader actually made last.
  const load = id => {
    const mine = ++latest;
    // "All" on the selected series needs the years the page did not inline.
    const needAll = id === 'combined' && !days && !complete;
    const source = needAll ? {url: payload.full_url} : payload.sources.find(item => item.id === id);
    if (!source || (series[id] && !needAll)) {
      // Nothing to wait for, so an earlier fetch must not keep the page busy.
      pending = '';
      host.removeAttribute('aria-busy');
      return Promise.resolve(true);
    }
    pending = id;
    C.note(host, host.dataset.msgLoading);
    host.setAttribute('aria-busy', 'true');
    return fetch(source.url, {credentials: 'same-origin', headers: {Accept: 'application/json'}})
      .then(response => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then(data => {
        series[id] = points(data.points, data.labels);
        if (needAll) complete = true;
        return mine === latest;
      })
      .catch(() => {
        if (mine === latest) C.note(host, host.dataset.msgFailed);
        throw new Error('load');
      })
      .finally(() => {
        if (mine !== latest) return;
        pending = '';
        host.removeAttribute('aria-busy');
      });
  };
  const refresh = (button, id) => track(button, load(id)).then(fresh => { if (fresh) repaint(); }, () => {});

  const bound = value => (value ?? null) === null ? null : Number(value);
  const hasValue = value => value !== null && value !== undefined;
  const pointRadius = count => {
    if (count > 90) return 2;
    return count > 34 ? 3 : 6;
  };
  const anchorFor = (order, last) => {
    if (order === 0) return 'start';
    return order === last ? 'end' : 'middle';
  };
  // Straight segments, lifted wherever the series skips more than 36 hours.
  const linePath = (points, x, y) => points.map((point, index) => {
    const gap = index && C.asDate(point.hlFrom || point.date) - C.asDate(points[index - 1].hlTo || points[index - 1].date) > 36 * 3600000;
    return `${index && !gap ? 'L' : 'M'} ${x(index)} ${y(point.value)}`;
  }).join(' ');
  const tooltipHtml = (point, when, integral) => {
    let detail = '';
    if ((point.hlGroup ?? 1) <= 1) {
      const ranged = hasValue(point.minimum) && hasValue(point.maximum);
      const rangeDetail = ranged ? ` · ${i18n['device.range']} ${C.num(point.minimum)}-${C.num(point.maximum)} ${esc(point.unit)}` : '';
      detail = `<div>${i18n['device.samples']}: ${C.num(point.sample_count, 0)}${rangeDetail}</div>`;
    }
    const value = C.num(point.value, integral ? 0 : 4);
    const source = esc(globalThis.AnamnaExperience.sourceLabel(point.vendor, point.source));
    return `<span>${esc(when)}</span><strong>${value} <small>${esc(point.unit)}</small></strong><b>${source}</b>${detail}`;
  };
  // The band used to be an unnamed grey rectangle: colour carrying meaning
  // alone. Written inside the plot when it fits, under the chart when not.
  const drawBand = (geometry, notes) => {
    const {L, T, plot, A, y, bandLow, bandHigh} = geometry;
    const upper = y(bandHigh !== null ? Math.min(bandHigh, A.max) : A.max);
    const lower = y(bandLow !== null ? Math.max(bandLow, A.min) : A.min);
    svg.append(C.el('rect', {x: L, y: upper, width: plot, height: Math.max(1, lower - upper), class: 'chart-reference-band'}));
    if (!band.label) return;
    if (C.textWidth(svg, [band.label], 'chart-axis-label') > plot - 12) {
      notes.push(C.text('chart.band_here', {name: band.label}));
      return;
    }
    const label = C.el('text', {x: L + 6, y: Math.max(T + 10, upper - 5), class: 'chart-axis-label'});
    label.textContent = band.label; svg.append(label);
  };

  const draw = (W, H) => {
    inspectPlot = null;
    if (pending) return;
    const source = selected();
    globalThis.AnamnaExperience?.periodSummary(host.closest('section'), source);
    if (!source.length) { C.note(host, host.dataset.msgNoSelected); return; }
    const integral = source.every(point => Number.isInteger(Number(point.value)));
    const bandLow = bound(band?.low);
    const bandHigh = bound(band?.high);
    const domain = source.map(point => Number(point.value)).concat([bandLow, bandHigh].filter(value => value !== null));
    const lo = Math.min(...domain), hi = Math.max(...domain);
    // The axis is built from every reading in the window, so averaging the line
    // below never hides the true extremes. Steps and other counts are never
    // negative (audit C4) and never fractional.
    const A = C.axis(lo, hi, {integral, zeroFloor: lo >= 0});
    const L = C.textWidth(svg, A.ticks.map(A.format), 'chart-axis-label') + 12;
    const R = 14, T = 14, B = 30, plot = Math.max(40, W - L - R);
    const points = globalThis.AnamnaExperience.thinDaily(source, C.capacity(plot));
    const notes = points.length < source.length
      ? [C.text('chart.averaged', {total: source.length, shown: points.length})] : [];

    const startTime = C.asDate(points[0].date).getTime();
    const timeSpan = C.asDate(points.at(-1).date).getTime() - startTime;
    const x = index => !timeSpan ? L + plot / 2 : L + (C.asDate(points[index].date).getTime() - startTime) * plot / timeSpan;
    const y = value => T + (A.max - value) * (H - T - B) / (A.max - A.min);
    svg.append(C.el('rect', {x: L, y: T, width: plot, height: H - T - B, fill: 'transparent', 'pointer-events': 'all', 'aria-hidden': 'true'}));

    if (bandLow !== null || bandHigh !== null) drawBand({L, T, plot, A, y, bandLow, bandHigh}, notes);
    A.ticks.forEach(value => {
      const yy = y(value);
      svg.append(C.el('line', {x1: L, x2: W - R, y1: yy, y2: yy, class: 'chart-gridline'}));
      const label = C.el('text', {x: L - 8, y: yy + 4, class: 'chart-axis-label', 'text-anchor': 'end'});
      label.textContent = A.format(value); svg.append(label);
    });
    svg.append(C.el('path', {d: linePath(points, x, y), class: 'dynamic-trend-line'}));

    const radius = pointRadius(points.length);
    const hitPoints = [];
    points.forEach((point, index) => {
      const grouped = point.hlGroup > 1;
      const when = grouped
        ? C.text('chart.averaged_point', {count: point.hlGroup, from: C.fullDate(C.asDate(point.hlFrom)), to: C.fullDate(C.asDate(point.hlTo))})
        : C.fullDate(C.asDate(point.date));
      const reading = `${C.num(point.value, integral ? 0 : 4)} ${point.unit}`;
      const vendorSuffix = grouped ? '' : `, ${point.vendor}`;
      const node = C.el('g', {tabindex: '0', role: 'button', 'aria-label': `${when}, ${reading}${vendorSuffix}`});
      node.append(C.el('circle', {cx: x(index), cy: y(point.value), r: radius, class: 'dynamic-point information'}));
      const show = event => {
        event.preventDefault();
        tip.innerHTML = tooltipHtml(point, when, integral);
        tip.hidden = false;
        tip.style.left = `${Math.max(8, Math.min(host.clientWidth - 250, x(index) - 110))}px`;
        tip.style.top = `${Math.max(4, y(point.value) - 150)}px`;
      };
      node.addEventListener('mouseenter', show);
      node.addEventListener('focus', show);
      node.addEventListener('click', show);
      node.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') show(event); });
      hitPoints.push({x: x(index), y: y(point.value), show, node});
      svg.append(node);
    });
    // The whole plot is a touch target. A finger need not hit a six-pixel
    // glyph; keyboard focus on each individual point remains available.
    inspectPlot = event => {
      const rectangle = svg.getBoundingClientRect();
      if (!rectangle.width || !rectangle.height) return;
      const tappedX = (event.clientX - rectangle.left) * W / rectangle.width;
      const tappedY = (event.clientY - rectangle.top) * H / rectangle.height;
      if (tappedX < L || tappedX > W - R || tappedY < T || tappedY > H - B) return;
      const nearest = globalThis.AnamnaExperience.nearestPoint(hitPoints, tappedX, tappedY);
      if (nearest) { nearest.show(event); nearest.node.focus({preventScroll: true}); }
    };

    const format = C.dateLabel(C.span(points));
    const stops = globalThis.AnamnaExperience.timeTicks(points, x);
    C.xLabels(points, stops, format).forEach((text, order) => {
      if (!text) return;
      const label = C.el('text', {
        x: x(stops[order]), y: H - 9, class: 'chart-date-label',
        'text-anchor': anchorFor(order, stops.length - 1),
      });
      label.textContent = text; svg.append(label);
    });
    C.note(host, notes.join(' '));
  };

  const repaint = C.responsive(svg, host, draw);
  // A switch that needs the server marks its button busy until the data arrives.
  const track = (button, work) => globalThis.anamnaBusy ? globalThis.anamnaBusy.track(button, work) : work;
  document.querySelectorAll('[data-days]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-days]').forEach(node => node.classList.remove('active'));
    button.classList.add('active'); days = Number(button.dataset.days); tip.hidden = true;
    refresh(button, activeSource);
  }));
  document.querySelectorAll('[data-chart-source]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-chart-source]').forEach(node => node.classList.remove('active'));
    button.classList.add('active'); activeSource = button.dataset.chartSource; tip.hidden = true;
    refresh(button, activeSource);
  }));
  document.addEventListener('click', event => { if (!host.contains(event.target)) tip.hidden = true; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') tip.hidden = true; });
})();
