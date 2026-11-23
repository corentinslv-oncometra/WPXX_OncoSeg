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

export function createLongitudinal({view, inspector, windowing, loadVolume, loadLabels, onChange, onRenumber, onError}) {
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
    date.slice = Math.max(0, Math.min(depth - 1, slice));
    paint(date);
  }

  function renderInspector() {
    const cards = rows.map((row) => lesionCard(row, dates)).join('');
    inspector.innerHTML = `<h2>Suivi longitudinal</h2><p class="fine-print">Toutes les lésions coupées par la vue sont affichées ensemble. Chaque barre fait défiler uniquement son examen. Le numéro d’une carte vaut pour toutes les dates.</p><div class="lesion-cards">${cards || '<p class="fine-print">Aucune lésion numérotée.</p>'}</div><canvas id="follow-chart" width="280" height="150" aria-label="Évolution des volumes"></canvas>`;
    drawChart();
    bindNumbers();
  }

  function bindNumbers() {
    inspector.querySelectorAll('.lesion-number input').forEach((input) => {
      input.addEventListener('wheel', (event) => event.preventDefault(), {passive: false});
      input.addEventListener('change', () => {
        submitNumber(input).catch((error) => onError?.(error));
      });
    });
  }

  async function submitNumber(input) {
    const source = Number(input.dataset.lesion);
    const target = Number(input.value);
    if (!Number.isInteger(target) || target < 1 || target > 65535 || target === source) {
      input.value = String(source);
      return;
    }
    input.disabled = true;
    try {
      const bundle = await onRenumber?.(source, target);
      if (!bundle || !active) {
        input.value = String(source);
        input.disabled = false;
        return;
      }
      await replace(bundle);
    } catch (error) {
      input.value = String(source);
      input.disabled = false;
      throw error;
    }
  }

  async function replace(bundle) {
    rows = bundle.rows || [];
    const slices = new Map(dates.map((date) => [date.time_id, date.slice]));
    const byTime = new Map((bundle.dates || []).map((date) => [date.time_id, date]));
    await Promise.all(dates.map(async (date) => {
      const fresh = byTime.get(date.time_id);
      if (fresh) {
        date.shift_mm = fresh.shift_mm;
        date.lesions = fresh.lesions;
      }
      const labels = await loadLabels(date.time_id);
      if (!active) return;
      date.labels = labels.length === date.volume.length ? labels : null;
      date.rasterKey = null;
      date.slice = slices.get(date.time_id) ?? date.slice;
    }));
    if (!active) return;
    renderInspector();
    redraw();
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
  const parts = sliceParts(date.labels, base, width, height, signX);
  ctx.font = '700 12px sans-serif';
  ctx.textBaseline = 'bottom';
  for (const mark of parts.sort((left, right) => left.label - right.label || left.x - right.x)) {
    const color = lesionColor(mark.label);
    const cx = left + (mark.x / mark.count + 0.5) * date.spacing_xyz[0] * scale;
    const cy = top + (mark.y / mark.count + 0.5) * date.spacing_xyz[1] * scale;
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = `rgb(${color.join(',')})`;
    ctx.fill();
    const name = `N${mark.label}`;
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#041014';
    ctx.strokeText(name, cx + 6, cy - 4);
    ctx.fillStyle = '#fff';
    ctx.fillText(name, cx + 6, cy - 4);
  }
}

function sliceParts(labels, base, width, height, signX) {
  const seen = new Uint8Array(width * height);
  const parts = [];
  const stack = [];
  const source = (x, y) => base + y * width + (signX < 0 ? width - 1 - x : x);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const start = y * width + x;
    if (seen[start]) continue;
    const label = labels[source(x, y)];
    if (!label) continue;
    seen[start] = 1;
    stack.push(x, y);
    let sumX = 0;
    let sumY = 0;
    let count = 0;
    while (stack.length) {
      const cy = stack.pop();
      const cx = stack.pop();
      sumX += cx;
      sumY += cy;
      count += 1;
      const neighbors = [cx - 1, cy, cx + 1, cy, cx, cy - 1, cx, cy + 1];
      for (let index = 0; index < neighbors.length; index += 2) {
        const nx = neighbors[index];
        const ny = neighbors[index + 1];
        if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
        const slot = ny * width + nx;
        if (seen[slot] || labels[source(nx, ny)] !== label) continue;
        seen[slot] = 1;
        stack.push(nx, ny);
      }
    }
    parts.push({label, x: sumX, y: sumY, count});
  }
  return parts;
}

function lesionCard(row, dates) {
  const color = lesionColor(row.lesion_id);
  const blocks = dates.map((date) => {
    const measure = row.measures?.[date.time_id];
    const title = escapeText(String(date.time_id).slice(0, 10));
    if (!measure || !measure.volume_cm3) {
      const note = measure && measure.status && measure.status !== 'disparue' ? escapeText(measure.status) : 'Absente';
      return `<section class="lesion-when"><h3>${title}</h3><p>${note}</p></section>`;
    }
    return `<section class="lesion-when"><h3>${title} · ${escapeText(measure.status || '—')}</h3><dl><dt>Volume</dt><dd>${formatVolume(measure.volume_cm3)} cm³</dd><dt>Grand axe</dt><dd>${formatMm(measure.long_axis_3d_mm)}</dd><dt>Axe axial</dt><dd>${formatMm(measure.long_axis_axial_mm)}</dd><dt>HU moyen</dt><dd>${formatHu(measure.hu_mean)}</dd></dl></section>`;
  }).join('');
  const link = lineage(row);
  return `<article class="lesion-card" style="border-color:rgb(${color.join(',')})"><header><span class="long-swatch" style="background:rgb(${color.join(',')})"></span><label class="lesion-number">N<input type="number" min="1" max="65535" step="1" value="${row.lesion_id}" data-lesion="${row.lesion_id}" aria-label="Numéro de N${row.lesion_id} pour toutes les dates" title="Ce numéro vaut pour toutes les dates"></label>${link ? `<span>${link}</span>` : ''}<span class="delta">${formatDelta(row.delta_percent)}</span></header>${blocks}</article>`;
}

function lineage(row) {
  const parents = Array.isArray(row.parent_ids) ? row.parent_ids : [];
  if (!parents.length) return '';
  const names = parents.map((id) => `N${id}`).join(' et ');
  if (row.event === 'division') return `division de ${names}`;
  if (row.event === 'fusion') return `fusion de ${names}`;
  return '';
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
