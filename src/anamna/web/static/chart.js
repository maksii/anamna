/* Trend chart primitives shared by the three SVG charts (lab metric, device
   metric, blood pressure).

   The charts used to carry a fixed viewBox="0 0 1000 380". On a 390px phone
   that box painted at 278x106 CSS px - a 3.6x downscale - so `font-size: 10`
   reached the screen as 2.78px and every axis label was unreadable. Here the
   viewBox is sized from the container's own pixel width, so one user unit is
   exactly one CSS pixel and `font-size: 11px` is 11px at every viewport. */
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const i18n = globalThis.__HL_I18N__ || {};
  const F = i18n._formats || {};
  const LOCALE = globalThis.__HL_LOCALE__ || 'en';

  const el = (name, attrs = {}) => {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };

  /* Locale number. `fixed` keeps trailing zeros, because an axis whose ticks
     print 2dp, 1dp and 0dp reads as three different quantities. */
  const trimZeros = text => {
    if (!text.includes('.')) return text;
    let end = text.length;
    while (text[end - 1] === '0') end--;
    if (text[end - 1] === '.') end--;
    return text.slice(0, end);
  };
  const groupThousands = (whole, separator) => {
    if (!/^-?\d+$/.test(whole)) return whole;
    let grouped = '';
    for (let end = whole.length; end > 0; end -= 3) {
      const part = whole.slice(Math.max(0, end - 3), end);
      grouped = grouped ? `${part}${separator}${grouped}` : part;
    }
    return grouped;
  };
  const num = (value, digits = 2, fixed = false) => {
    let text = Number(value).toFixed(digits);
    if (!fixed) text = trimZeros(text);
    const [whole, fraction] = text.split('.');
    const grouped = groupThousands(whole, F.group ?? ',');
    return fraction ? `${grouped}${F.decimal ?? '.'}${fraction}` : grouped;
  };

  const asDate = value => new Date(
    String(value).includes('T') ? value : `${String(value).slice(0, 10)}T00:00:00`,
  );
  const M = F.months_short;
  const monthYear = date => M
    ? `${M[date.getMonth()]} ${date.getFullYear()}`
    : date.toLocaleDateString(LOCALE, {month: 'short', year: 'numeric'});
  const dayMonth = date => M
    ? `${date.getDate()} ${M[date.getMonth()]}`
    : date.toLocaleDateString(LOCALE, {day: 'numeric', month: 'short'});
  const fullDate = (date, withTime) => {
    const base = M
      ? `${String(date.getDate()).padStart(2, '0')} ${M[date.getMonth()]} ${date.getFullYear()}`
      : date.toLocaleDateString(LOCALE, {day: '2-digit', month: 'short', year: 'numeric'});
    return withTime
      ? `${base} ${date.toLocaleTimeString(LOCALE, {hour: '2-digit', minute: '2-digit'})}`
      : base;
  };

  /* A 30-day window labelled "Jun 2026 / Jul 2026" tells the reader nothing
     about where they are, so the granularity follows the visible span. */
  const dateLabel = spanDays => {
    if (spanDays <= 70) return dayMonth;
    if (spanDays <= 800) return monthYear;
    return date => String(date.getFullYear());
  };

  const niceStep = raw => {
    const power = Math.pow(10, Math.floor(Math.log10(raw)));
    const scaled = raw / power;
    const multiple = [1, 2, 5].find(step => scaled <= step) ?? 10;
    return multiple * power;
  };

  /* Round ticks at a single precision. `integral` keeps counts (steps, flights,
     beats) off fractional axis labels; `zeroFloor` keeps a never-negative
     measurement off a negative baseline. */
  const axis = (lo, hi, options = {}) => {
    const count = options.count || 4;
    let span = hi - lo;
    if (span <= 0 || Number.isNaN(span)) {
      span = Math.max(Math.abs(hi) * 0.1, 1);
      lo -= span / 2;
      hi += span / 2;
    }
    let step = niceStep(span / count);
    if (options.integral) step = Math.max(1, Math.round(step));
    let min = Math.floor(lo / step) * step;
    let max = Math.ceil(hi / step) * step;
    if (max === min) max += step;
    if (options.zeroFloor && min < 0 && lo >= 0) min = 0;
    const digits = Math.max(0, Math.min(4, -Math.floor(Math.log10(step) + 1e-9)));
    const ticks = [];
    for (let value = min; value <= max + step / 2; value += step) {
      ticks.push(Math.round(value / step) * step);
    }
    return {min, max, step, digits, ticks, format: value => num(value, digits, true)};
  };

  /* The value domain for a series: its own spread plus padding. A reference
     bound widens it only when it lies within half the data's spread of the
     data - further out the band squashed 146-159 g/L onto a 130-170 axis and
     LDL 2.7-5.5 onto 0-6 - and is otherwise clipped by the caller. Mirrors
     `fit_domain` in web/app.py; keep the two in step. */
  const fitDomain = (values, bounds = []) => {
    let lo = Math.min(...values), hi = Math.max(...values);
    const spread = (hi - lo) || Math.max(Math.abs(hi) * 0.1, 1e-6);
    const reach = spread * 0.5;
    bounds.filter(bound => bound !== null && bound !== undefined && Number.isFinite(Number(bound)))
      .map(Number)
      .forEach(bound => {
        if (bound >= lo - reach && bound <= hi + reach) { lo = Math.min(lo, bound); hi = Math.max(hi, bound); }
      });
    const pad = ((hi - lo) || spread) * 0.08;
    let min = lo - pad;
    if (Math.min(...values) >= 0 && min < 0) min = 0;
    return {min, max: hi + pad};
  };

  /* Time positions as fractions of the plot, with long silences shortened.
     Five draws in the last year after two in 2015 put 85 % of a linear axis
     over empty years and the recent five in its last sliver. A gap longer
     than max(1 year, twice the typical gap) is drawn as that cap and listed
     in `breaks` (the index of the point after it) so the caller can mark it.
     `span` is the drawn span in days, for the label granularity. */
  const timeScale = points => {
    const DAY = 86400000;
    const times = points.map(point => asDate(point.date).getTime());
    const gaps = times.slice(1).map((time, index) => time - times[index]);
    const sorted = [...gaps].sort((a, b) => a - b);
    const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
    const cap = Math.max(365 * DAY, 2 * median);
    const breaks = [];
    const offsets = [0];
    gaps.forEach((gap, index) => {
      if (gap > cap) breaks.push(index + 1);
      offsets.push(offsets[index] + Math.min(gap, cap));
    });
    const total = offsets.at(-1);
    return {
      at: index => total ? offsets[index] / total : 0.5,
      breaks,
      span: total / DAY,
    };
  };

  /* Width of the widest of `strings` when painted as `cls`, so the left gutter
     fits the labels instead of guessing at them. */
  const textWidth = (svg, strings, cls) => {
    const probe = el('text', {class: cls, x: -9999, y: -9999});
    svg.append(probe);
    const width = strings.reduce((widest, text) => {
      probe.textContent = text;
      return Math.max(widest, probe.getComputedTextLength());
    }, 0);
    probe.remove();
    return Math.ceil(width);
  };

  /* 227 daily points drawn into 230px is 1.2px per point: a scribble, not a
     trend. Collapse to bucket means and let the caller say so - the reading
     tables below every chart still list each value. */
  const thin = (points, limit) => {
    if (limit < 2 || points.length <= limit) return points;
    const size = Math.ceil(points.length / limit);
    const out = [];
    for (let index = 0; index < points.length; index += size) {
      const chunk = points.slice(index, index + size);
      const mean = chunk.reduce((sum, point) => sum + Number(point.value), 0) / chunk.length;
      out.push({
        ...chunk[Math.floor(chunk.length / 2)],
        value: mean,
        hlGroup: chunk.length,
        hlFrom: chunk[0].date,
        hlTo: chunk[chunk.length - 1].date,
      });
    }
    return out;
  };

  /* The note lives with the chart, not in the template, because only the
     browser knows how many points survived the available width. */
  const note = (host, text) => {
    let node = host.querySelector('.chart-note');
    if (!node) {
      node = document.createElement('p');
      node.className = 'chart-note';
      host.append(node);
    }
    node.textContent = text || '';
    node.hidden = !text;
  };

  /* Size the viewBox from the container so one unit is one CSS pixel, and give
     the svg the height it actually paints - the old `min-height: 380px` left up
     to 270px of empty card under a 106px chart. */
  const responsive = (svg, host, draw, size) => {
    let painted = -1;
    const paint = () => {
      const width = Math.max(240, Math.round(host.clientWidth || svg.clientWidth || 320));
      // `size(width)` lets a page whose chart is the point of the page take
      // the room it needs; the default stays the compact secondary chart.
      const height = size ? size(width) : Math.max(200, Math.min(340, Math.round(width * 0.52)));
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      svg.setAttribute('height', height);
      svg.replaceChildren();
      draw(width, height);
      painted = width;
    };
    paint();
    if (globalThis.ResizeObserver) {
      new ResizeObserver(() => {
        if (Math.abs((host.clientWidth || 0) - painted) > 1) paint();
      }).observe(host);
    } else {
      globalThis.addEventListener('resize', paint);
    }
    return paint;
  };

  globalThis.AnamnaChart = {
    NS, el, num, asDate, monthYear, dayMonth, fullDate, dateLabel,
    axis, fitDomain, timeScale, textWidth, thin, note, responsive,
    /* Evenly spaced indices, first and last always included. */
    tickIndices: (length, wanted) => {
      const count = Math.max(2, Math.min(wanted, length));
      if (length < 2) return [0];
      return [...new Set(Array.from({length: count},
        (_, step) => Math.round(step * (length - 1) / (count - 1))))];
    },
    /* How many points this plot width can show without turning into a smear. */
    capacity: plotWidth => Math.max(8, Math.round(plotWidth / 6.5)),
    /* Days between the oldest and newest reading behind these points - bucket
       edges, not bucket midpoints, or an averaged series reports itself as
       shorter than it is. */
    span: points => (asDate(points.at(-1).hlTo || points.at(-1).date)
      - asDate(points[0].hlFrom || points[0].date)) / 86400000,
    /* Tick text for `indices`. The ends read the true first and last reading of
       their bucket, and a label that repeats the one before it is dropped
       rather than printed twice ("2022, 2022"). */
    xLabels: (points, indices, format) => {
      const seen = new Set();
      return indices.map((index, order) => {
        const point = points[index];
        let raw = point.date;
        if (order === 0) raw = point.hlFrom || point.date;
        else if (order === indices.length - 1) raw = point.hlTo || point.date;
        const text = format(asDate(raw));
        if (seen.has(text)) return null;
        seen.add(text);
        return text;
      });
    },
    text: (key, values = {}) => Object.entries(values).reduce(
      (text, [name, value]) => text.replace(`{${name}}`, value),
      i18n[key] || key,
    ),
  };
})();
