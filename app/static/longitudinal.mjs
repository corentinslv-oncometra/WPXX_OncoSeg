const COLORS = [[255, 99, 71], [255, 193, 7], [0, 188, 255], [186, 104, 200], [129, 199, 132], [255, 138, 101], [144, 202, 249], [244, 143, 177]];

export function lesionColor(id) {
  return COLORS[(Math.max(1, id) - 1) % COLORS.length];
}

export function nativeZ(slice, geometry) {
  const step = geometry.spacing_xyz[2] * geometry.direction[8];
  return geometry.origin_xyz[2] + slice * step;
}

export function sliceForRegistered(target, geometry, shift) {
  const step = geometry.spacing_xyz[2] * geometry.direction[8];
  const count = geometry.size_xyz[2];
  if (!count || Math.abs(step) < 1e-6) return 0;
  const index = Math.round((target - shift - geometry.origin_xyz[2]) / step);
  return Math.max(0, Math.min(count - 1, index));
}

function escapeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
}

export function createLongitudinal({view, inspector, windowing, loadVolume, loadLabels, onChange}) {
  let active = false;
  let dates = [];
  let rows = [];
  let registeredZ = null;
  let drawing = false;

  function redraw() {
    if (!active || drawing) return;
    drawing = true;
    for (const date of dates) paint(date);
    drawing = false;
  }

  function paint(date) {
    const canvas = date.canvas;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height || !date.volume) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#050809';
    ctx.fillRect(0, 0, rect.width, rect.height);
    const [width, height, depth] = date.size_xyz;
    const slice = Math.max(0, Math.min(depth - 1, date.slice | 0));
    date.slice = slice;
    const {width: windowWidth, level} = windowing();
    const low = level - windowWidth / 2;
    const key = [slice, low, windowWidth, date.volume, date.labels];
    if (!date.rasterKey || key.some((value, index) => value !== date.rasterKey[index])) {
      date.bitmap.width = width;
      date.bitmap.height = height;
      const pixels = date.bitmap.getContext('2d').createImageData(width, height);
      const base = slice * height * width;
      const signX = date.direction[0] < 0 ? -1 : 1;
      for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
        const sourceX = signX < 0 ? width - 1 - x : x;
        const index = base + y * width + sourceX;
        const gray = Math.max(0, Math.min(255, (date.volume[index] - low) * 255 / windowWidth));
        const label = date.labels ? date.labels[index] : 0;
        const color = label ? lesionColor(label) : null;
        const pixel = (y * width + x) * 4;
        if (color) {
          pixels.data[pixel] = gray * 0.45 + color[0] * 0.55;
          pixels.data[pixel + 1] = gray * 0.45 + color[1] * 0.55;
          pixels.data[pixel + 2] = gray * 0.45 + color[2] * 0.55;
        } else {
          pixels.data[pixel] = pixels.data[pixel + 1] = pixels.data[pixel + 2] = gray;
        }
        pixels.data[pixel + 3] = 255;
      }
      date.bitmap.getContext('2d').putImageData(pixels, 0, 0);
      date.rasterKey = key;
    }
    const scale = Math.max(0.01, Math.min((rect.width - 16) / (width * date.spacing_xyz[0]), (rect.height - 16) / (height * date.spacing_xyz[1])));
    const dw = width * date.spacing_xyz[0] * scale;
    const dh = height * date.spacing_xyz[1] * scale;
    ctx.imageSmoothingEnabled = true;
    const left = (rect.width - dw) / 2;
    const top = (rect.height - dh) / 2;
    ctx.drawImage(date.bitmap, left, top, dw, dh);
    markVisibleLesions(ctx, date, left, top, scale);
    const badge = date.node.querySelector('.long-slice');
    const z = nativeZ(slice, date);
    badge.textContent = `${slice + 1}/${depth} · ${z.toFixed(1)} mm`;
    date.slider.max = String(depth - 1);
    date.slider.value = String(slice);
  }

  function align(target) {
    registeredZ = target;
    for (const date of dates) date.slice = sliceForRegistered(target, date, date.shift_mm);
    redraw();
  }

  function showEveryLesion() {
    const reference = dates.find((date) => date.labels);
    if (!reference) {
      redraw();
      return;
    }
    const slice = busiestSlice(reference);
    align(nativeZ(slice, reference) + reference.shift_mm);
    reference.slice = slice;
    redraw();
  }

  function move(date, slice) {
    const depth = date.size_xyz[2];
    const next = Math.max(0, Math.min(depth - 1, slice));
    align(nativeZ(next, date) + date.shift_mm);
    date.slice = next;
    redraw();
  }

  function renderInspector() {
    const cards = rows.map((row) => lesionCard(row, dates)).join('');
    inspector.innerHTML = `<h2>Suivi longitudinal</h2><p class="fine-print">Toutes les lésions coupées par la vue sont affichées ensemble. Le défilement aligne les dates sur la position Z recalée.</p><div class="lesion-cards">${cards || '<p class="fine-print">Aucune lésion numérotée.</p>'}</div><canvas id="follow-chart" width="280" height="150" aria-label="Évolution des volumes"></canvas>`;
    drawChart();
  }

  function drawChart() {
    const canvas = inspector.querySelector('#follow-chart');
    if (!canvas || !dates.length) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#10181c';
    ctx.fillRect(0, 0, width, height);
    const values = rows.flatMap((row) => dates.map((date) => row.volumes[date.time_id])).filter((value) => typeof value === 'number');
    const max = Math.max(0.1, ...values);
    const left = 28;
    const top = 12;
    const plotWidth = width - left - 10;
    const plotHeight = height - top - 22;
    ctx.strokeStyle = '#2c3c42';
    ctx.strokeRect(left, top, plotWidth, plotHeight);
    ctx.fillStyle = '#8aa';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    dates.forEach((date, index) => {
      const x = left + (dates.length === 1 ? plotWidth / 2 : index * plotWidth / (dates.length - 1));
      ctx.fillText(date.time_id.slice(0, 10), x, height - 6);
    });
    for (const row of rows) {
      const color = lesionColor(row.lesion_id);
      ctx.strokeStyle = `rgb(${color.join(',')})`;
      ctx.fillStyle = ctx.strokeStyle;
      ctx.lineWidth = 2;
      ctx.beginPath();
      dates.forEach((date, index) => {
        const volume = row.volumes[date.time_id];
        if (typeof volume !== 'number') return;
        const x = left + (dates.length === 1 ? plotWidth / 2 : index * plotWidth / (dates.length - 1));
        const y = top + plotHeight - (volume / max) * plotHeight;
        if (index === 0 || typeof row.volumes[dates[index - 1].time_id] !== 'number') ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      dates.forEach((date, index) => {
        const volume = row.volumes[date.time_id];
        if (typeof volume !== 'number') return;
        const x = left + (dates.length === 1 ? plotWidth / 2 : index * plotWidth / (dates.length - 1));
        const y = top + plotHeight - (volume / max) * plotHeight;
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
      });
    }
  }

  async function enter(bundle) {
    exit();
    active = true;
    rows = bundle.rows || [];
    dates = (bundle.dates || []).map((date) => ({...date, volume: null, labels: null, slice: 0, bitmap: document.createElement('canvas'), rasterKey: null}));
    view.replaceChildren();
    for (const date of dates) {
      const panel = document.createElement('article');
      panel.className = 'long-panel';
      panel.innerHTML = `<header><b>${escapeText(date.time_id)}</b><span class="long-slice">Chargement…</span></header><canvas aria-label="Coupe axiale ${escapeText(date.time_id)}"></canvas><input type="range" min="0" value="0" aria-label="Coupe de ${escapeText(date.time_id)}">`;
      date.node = panel;
      date.canvas = panel.querySelector('canvas');
      date.slider = panel.querySelector('input');
      date.slider.addEventListener('input', () => move(date, Number(date.slider.value)));
      panel.addEventListener('wheel', (event) => {
        event.preventDefault();
        move(date, date.slice + (event.deltaY > 0 ? 1 : -1));
      }, {passive: false});
      view.append(panel);
    }
    onChange(true);
    renderInspector();
    await Promise.all(dates.map(async (date) => {
      const [volume, labels] = await Promise.all([loadVolume(date.study_id), loadLabels(date.time_id)]);
      if (!active) return;
      date.volume = volume.volume;
      date.labels = labels.length === volume.volume.length ? labels : null;
      date.slice = Math.floor(date.size_xyz[2] / 2);
    }));
    if (!active) return;
    showEveryLesion();
  }

  function exit() {
    if (!active && !dates.length) return;
    active = false;
    dates = [];
    rows = [];
    registeredZ = null;
    view.replaceChildren();
    inspector.innerHTML = '';
    onChange(false);
  }

  return {enter, exit, redraw, active: () => active};
}

function busiestSlice(date) {
  const [width, height, depth] = date.size_xyz;
  if (!date.labels || !depth) return Math.floor((depth - 1) / 2);
  let best = 0;
  let bestCount = -1;
  for (let z = 0; z < depth; z++) {
    const seen = new Set();
    const base = z * height * width;
    for (let index = 0; index < height * width; index++) {
      const label = date.labels[base + index];
      if (label) seen.add(label);
    }
    if (seen.size > bestCount) {
      bestCount = seen.size;
      best = z;
    }
  }
  return best;
}

function markVisibleLesions(ctx, date, left, top, scale) {
  if (!date.labels) return;
  const [width, height] = date.size_xyz;
  const base = date.slice * height * width;
  const signX = date.direction[0] < 0 ? -1 : 1;
  const sums = new Map();
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const sourceX = signX < 0 ? width - 1 - x : x;
    const label = date.labels[base + y * width + sourceX];
    if (!label) continue;
    const mark = sums.get(label) || {x: 0, y: 0, count: 0};
    mark.x += x;
    mark.y += y;
    mark.count += 1;
    sums.set(label, mark);
  }
  ctx.font = '700 12px sans-serif';
  ctx.textBaseline = 'bottom';
  for (const [label, mark] of [...sums.entries()].sort((left, right) => left[0] - right[0])) {
    const color = lesionColor(label);
    const cx = left + (mark.x / mark.count + 0.5) * date.spacing_xyz[0] * scale;
    const cy = top + (mark.y / mark.count + 0.5) * date.spacing_xyz[1] * scale;
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = `rgb(${color.join(',')})`;
    ctx.fill();
    const name = `N${label}`;
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#041014';
    ctx.strokeText(name, cx + 6, cy - 4);
    ctx.fillStyle = '#fff';
    ctx.fillText(name, cx + 6, cy - 4);
  }
}

function lesionCard(row, dates) {
  const color = lesionColor(row.lesion_id);
  const blocks = dates.map((date) => {
    const measure = row.measures?.[date.time_id];
    const title = escapeText(String(date.time_id).slice(0, 10));
    if (!measure || !measure.volume_cm3) {
      return `<section class="lesion-when"><h3>${title}</h3><p>Absente</p></section>`;
    }
    return `<section class="lesion-when"><h3>${title} · ${escapeText(measure.status || '—')}</h3><dl><dt>Volume</dt><dd>${formatVolume(measure.volume_cm3)} cm³</dd><dt>Grand axe</dt><dd>${formatMm(measure.long_axis_3d_mm)}</dd><dt>Axe axial</dt><dd>${formatMm(measure.long_axis_axial_mm)}</dd><dt>HU moyen</dt><dd>${formatHu(measure.hu_mean)}</dd></dl></section>`;
  }).join('');
  return `<article class="lesion-card" style="border-color:rgb(${color.join(',')})"><header><span class="long-swatch" style="background:rgb(${color.join(',')})"></span><b>N${row.lesion_id}</b><span class="delta">${formatDelta(row.delta_percent)}</span></header>${blocks}</article>`;
}

function formatVolume(value) {
  if (typeof value !== 'number') return '—';
  return value.toLocaleString('fr-FR', {maximumFractionDigits: 2});
}

function formatMm(value) {
  if (typeof value !== 'number') return '—';
  return `${value.toLocaleString('fr-FR', {maximumFractionDigits: 1})} mm`;
}

function formatHu(value) {
  if (typeof value !== 'number') return '—';
  return value.toLocaleString('fr-FR', {maximumFractionDigits: 0});
}

function formatDelta(value) {
  if (typeof value !== 'number') return '—';
  const text = value.toLocaleString('fr-FR', {maximumFractionDigits: 1, signDisplay: 'exceptZero'});
  return `${text} %`;
}
