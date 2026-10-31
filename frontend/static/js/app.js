/* Brightloop Subscription Management System — single-page frontend (no build step). */
'use strict';

const S = {
  token: localStorage.getItem('bl_token'),
  user: JSON.parse(localStorage.getItem('bl_user') || 'null'),
  cache: {},
  subFilter: { status: '', q: '', customer_id: '', offset: 0 },
  invFilter: { status: '', q: '', offset: 0 },
  dash: { date_from: '', date_to: '', plan_id: '', customer_id: '' },
};
const PAGE = 50;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ---------- utilities ----------
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function money(n) {
  return '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtDate(d) {
  if (!d) return '—';
  const dt = new Date(d.length === 10 ? d + 'T00:00:00' : d + 'Z');
  return dt.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}
const today = () => new Date().toISOString().slice(0, 10);
const label = s => String(s || '').replace(/_/g, ' ');
const badge = (s, text) => `<span class="badge b-${esc(s)}">${esc(label(text || s))}</span>`;
const isStaff = () => S.user && (S.user.role === 'admin' || S.user.role === 'staff');
const isAdmin = () => S.user && S.user.role === 'admin';
const FREQ = { daily: 'day', weekly: 'week', monthly: 'month', yearly: 'year' };
const TERMS = [['immediate', 'Immediate'], ['net_7', 'Net 7'], ['net_15', 'Net 15'], ['net_30', 'Net 30'], ['net_45', 'Net 45']];
const METHODS = [['bank_transfer', 'Bank transfer'], ['card', 'Card'], ['upi', 'UPI'], ['stripe', 'Stripe'], ['cash', 'Cash']];
const methodName = m => (METHODS.find(x => x[0] === m) || [m, label(m)])[1];

async function api(path, { method = 'GET', body, raw = false } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (S.token) headers.Authorization = 'Bearer ' + S.token;
  const res = await fetch('/api' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 401 && S.token) { logout(); throw new Error('Your session expired. Please sign in again.'); }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = Array.isArray(j.detail) ? j.detail.map(d => `${d.loc.slice(-1)[0]}: ${d.msg}`).join('; ') : (j.detail || msg);
    } catch (_) { /* not json */ }
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return raw ? res.text() : res.json();
}
function qs(obj) {
  const p = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => { if (v !== '' && v !== null && v !== undefined) p.set(k, v); });
  return p.toString();
}

function toast(msg, kind = 'ok') {
  const el = document.createElement('div');
  if (kind === 'error') el.className = 'error';
  const color = kind === 'error' ? '#e11d48' : kind === 'info' ? 'var(--slate-500)' : 'var(--brand-600)';
  el.innerHTML = `<span class="dot" style="background:${color}"></span><span>${esc(msg)}</span>`;
  $('#toast').appendChild(el);
  while ($('#toast').children.length > 3) $('#toast').firstChild.remove();
  setTimeout(() => el.remove(), kind === 'error' ? 6000 : 4500);
}

// ---------- theme ----------
const isDark = () => document.documentElement.classList.contains('dark');
function setTheme(dark) {
  document.documentElement.classList.toggle('dark', dark);
  try { localStorage.setItem('bl_theme', dark ? 'dark' : 'light'); } catch (_) { /* not persisted */ }
  $$('[data-theme-toggle]').forEach(b => { b.innerHTML = themeIcon(); b.title = dark ? 'Switch to light mode' : 'Switch to dark mode'; });
}
const themeIcon = () => `<i data-lucide="${isDark() ? 'sun' : 'moon'}" class="h-4 w-4"></i>`;
function themeButton(cls = '') {
  return `<button type="button" data-theme-toggle class="${cls}" title="${isDark() ? 'Switch to light mode' : 'Switch to dark mode'}" aria-label="Toggle dark mode">${themeIcon()}</button>`;
}
document.addEventListener('click', e => { if (e.target.closest('[data-theme-toggle]')) setTheme(!isDark()); });

// ---------- icons & glow ----------
const icon = (name, cls = '') => `<i data-lucide="${name}" class="${cls}"></i>`;
// Swap <i data-lucide> placeholders for SVGs whenever new markup lands in the page.
new MutationObserver(() => {
  if (window.lucide && document.querySelector('i[data-lucide]')) lucide.createIcons({ attrs: { 'stroke-width': 2 } });
}).observe(document.body, { childList: true, subtree: true });

// Glow cards: the border lights up on the side nearest the pointer (eased toward the target angle).
const glow = { x: 0, y: 0, raf: 0 };
function updateGlow() {
  glow.raf = 0;
  let moving = false;
  for (const el of document.querySelectorAll('.glow-card .glow')) {
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2, pad = 64;
    const near = glow.x > r.left - pad && glow.x < r.right + pad && glow.y > r.top - pad && glow.y < r.bottom + pad;
    const inCenter = Math.hypot(glow.x - cx, glow.y - cy) < 0.5 * Math.min(r.width, r.height) * 0.01;
    el.style.setProperty('--active', near && !inCenter ? '1' : '0');
    if (!near) continue;
    const target = (180 * Math.atan2(glow.y - cy, glow.x - cx)) / Math.PI + 90;
    const cur = parseFloat(el.style.getPropertyValue('--start')) || 0;
    const diff = ((target - cur + 540) % 360) - 180;
    if (Math.abs(diff) > 0.5) { el.style.setProperty('--start', String(cur + diff * 0.18)); moving = true; }
  }
  if (moving) glow.raf = requestAnimationFrame(updateGlow);
}
document.addEventListener('pointermove', e => { glow.x = e.clientX; glow.y = e.clientY; if (!glow.raf) glow.raf = requestAnimationFrame(updateGlow); }, { passive: true });

async function run(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { toast(e.message, 'error'); throw e; }
}

// ---------- modal & forms ----------
function openModal(title, bodyHtml, { wide = false, footer = '' } = {}) {
  const root = $('#modal-root');
  const wrap = document.createElement('div');
  wrap.className = 'modal-bg';
  wrap.innerHTML = `<div class="card w-full ${wide ? 'max-w-4xl' : 'max-w-xl'} shadow-xl">
      <div class="flex items-center justify-between px-5 py-3 border-b">
        <h3 class="font-semibold text-lg">${title}</h3>
        <button class="text-gray-400 hover:text-gray-700 text-2xl leading-none" data-close>&times;</button>
      </div>
      <div class="p-5 modal-body">${bodyHtml}</div>
      ${footer ? `<div class="px-5 py-3 border-t flex justify-end gap-2 bg-gray-50 rounded-b-lg">${footer}</div>` : ''}
    </div>`;
  const close = () => wrap.remove();
  wrap.addEventListener('click', e => { if (e.target === wrap || e.target.closest('[data-close]')) close(); });
  root.appendChild(wrap);
  return { el: wrap, close };
}

function field(f) {
  const v = f.value ?? '';
  const req = f.required ? 'required' : '';
  let input;
  if (f.type === 'select') {
    input = `<select class="input" name="${f.name}" ${req}>${f.blank !== false ? `<option value="">${esc(f.blank || '— select —')}</option>` : ''}
      ${f.options.map(([ov, ol]) => `<option value="${esc(ov)}" ${String(ov) === String(v) ? 'selected' : ''}>${esc(ol)}</option>`).join('')}</select>`;
  } else if (f.type === 'checkbox') {
    return `<label class="flex items-center gap-2 text-sm ${f.span || ''}"><input type="checkbox" name="${f.name}" ${v ? 'checked' : ''} class="h-4 w-4 accent-[#714B67]"> ${esc(f.label)}</label>`;
  } else if (f.type === 'textarea') {
    input = `<textarea class="input" rows="2" name="${f.name}">${esc(v)}</textarea>`;
  } else {
    input = `<input class="input" type="${f.type || 'text'}" name="${f.name}" value="${esc(v)}" ${req}
      ${f.step ? `step="${f.step}"` : ''} ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ''} ${f.list ? `list="${f.list}"` : ''}>`;
  }
  return `<div class="${f.span || ''}"><label class="label">${esc(f.label)}${f.required ? ' *' : ''}</label>${input}
    ${f.help ? `<p class="text-xs text-gray-500 mt-1">${esc(f.help)}</p>` : ''}</div>`;
}
function formGrid(fields) {
  return `<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">${fields.map(field).join('')}</div>`;
}
function readFields(root, fields) {
  const out = {};
  for (const f of fields) {
    const el = root.querySelector(`[name="${f.name}"]`);
    if (!el) continue;
    if (f.type === 'checkbox') out[f.name] = el.checked;
    else if (f.type === 'number') out[f.name] = el.value === '' ? (f.nullable ? null : 0) : Number(el.value);
    else if (f.type === 'select' && f.numeric) out[f.name] = el.value === '' ? null : Number(el.value);
    else out[f.name] = el.value === '' ? (f.nullable !== false ? null : '') : el.value;
  }
  return out;
}

/** Modal with a form; onSubmit(values) may throw to keep the modal open. */
function formModal(title, fields, onSubmit, { submitLabel = 'Save', extraHtml = '', wide = false, afterRender } = {}) {
  const m = openModal(title, `<form id="mf">${formGrid(fields)}${extraHtml}</form>`,
    { wide, footer: `<button class="btn btn-light" data-close>Cancel</button><button class="btn btn-primary" id="mf-submit">${esc(submitLabel)}</button>` });
  const form = $('#mf', m.el);
  if (afterRender) afterRender(m.el);
  const submit = async e => {
    e.preventDefault();
    if (!form.reportValidity()) return;
    const btn = $('#mf-submit', m.el);
    btn.disabled = true;
    try { await onSubmit(readFields(form, fields), m.el); m.close(); }
    catch (err) { toast(err.message, 'error'); }
    finally { btn.disabled = false; }
  };
  form.addEventListener('submit', submit);
  $('#mf-submit', m.el).addEventListener('click', submit);
  return m;
}

// ---------- reference data ----------
async function cached(key, loader, force = false) {
  if (force || !S.cache[key]) S.cache[key] = await loader();
  return S.cache[key];
}
const getProducts = f => cached('products', () => api('/products'), f);
const getPlans = f => cached('plans', () => api('/plans'), f);
const getTaxes = f => cached('taxes', () => api('/taxes'), f);
const getCustomers = f => cached('customers', () => api('/customers?limit=500').then(r => r.items), f);
function invalidate(...keys) { keys.forEach(k => delete S.cache[k]); }

// ---------- line editor (subscriptions & templates) ----------
function productOptions(products) {
  const opts = [];
  products.filter(p => p.is_active).forEach(p => {
    opts.push([`${p.id}:`, `${p.name} — ${money(p.sales_price)}`]);
    p.variants.filter(v => v.is_active).forEach(v =>
      opts.push([`${p.id}:${v.id}`, `${p.name} · ${v.attribute_name}: ${v.variant_value} — ${money(v.effective_price)}`]));
  });
  return opts;
}
function lineRow(opts, l = {}) {
  const key = l.product_id ? `${l.product_id}:${l.variant_id || ''}` : '';
  return `<tr>
    <td class="pr-2 py-1"><select class="input" data-l="item" required><option value="">— product —</option>
      ${opts.map(([v, t]) => `<option value="${v}" ${v === key ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></td>
    <td class="pr-2 py-1 w-24"><input class="input" type="number" min="1" step="1" data-l="qty" value="${l.quantity || 1}" required></td>
    <td class="pr-2 py-1 w-36"><input class="input" type="number" min="0" step="0.01" data-l="price" placeholder="catalog" value="${l.unit_price ?? ''}"></td>
    <td class="py-1 w-8"><button type="button" class="text-red-500 hover:text-red-700 text-lg" data-l="del">&times;</button></td></tr>`;
}
function linesEditorHtml(products, lines) {
  const opts = productOptions(products);
  return `<div class="mt-5"><div class="flex items-center justify-between mb-2"><span class="label mb-0">Product lines</span>
    <button type="button" class="btn btn-light btn-sm" id="add-line">+ Add line</button></div>
    <table class="w-full text-sm"><thead><tr class="text-xs text-gray-500"><th class="text-left font-medium">Product / variant</th>
    <th class="text-left font-medium">Qty</th><th class="text-left font-medium">Unit price</th><th></th></tr></thead>
    <tbody id="lines-body">${(lines.length ? lines : [{}]).map(l => lineRow(opts, l)).join('')}</tbody></table>
    <p class="text-xs text-gray-500 mt-1">Leave unit price empty to use the catalog price (variant surcharges included).</p></div>`;
}
function wireLinesEditor(root, products) {
  const opts = productOptions(products);
  $('#add-line', root).addEventListener('click', () => $('#lines-body', root).insertAdjacentHTML('beforeend', lineRow(opts)));
  $('#lines-body', root).addEventListener('click', e => { if (e.target.dataset.l === 'del') e.target.closest('tr').remove(); });
}
function readLines(root) {
  return $$('#lines-body tr', root).map(tr => {
    const item = $('[data-l=item]', tr).value;
    if (!item) return null;
    const [pid, vid] = item.split(':');
    const price = $('[data-l=price]', tr).value;
    return { product_id: Number(pid), variant_id: vid ? Number(vid) : null,
             quantity: Number($('[data-l=qty]', tr).value || 1), unit_price: price === '' ? null : Number(price) };
  }).filter(Boolean);
}

// ---------- auth ----------
function saveSession(r) {
  S.token = r.access_token; S.user = r.user; S.cache = {};
  localStorage.setItem('bl_token', S.token);
  localStorage.setItem('bl_user', JSON.stringify(S.user));
}
function logout() {
  S.token = null; S.user = null; S.cache = {}; S.introDone = true;
  localStorage.removeItem('bl_token'); localStorage.removeItem('bl_user');
  location.hash = '';
  render();
}
function passwordIssues(p) {
  const out = [];
  if (p.length <= 8) out.push('more than 8 characters');
  if (!/[A-Z]/.test(p)) out.push('an uppercase letter');
  if (!/[a-z]/.test(p)) out.push('a lowercase letter');
  if (!/[^A-Za-z0-9]/.test(p)) out.push('a special character');
  return out;
}
function pwHint(input, hint) {
  const upd = () => {
    const issues = passwordIssues(input.value);
    hint.innerHTML = !input.value ? 'More than 8 characters, with uppercase, lowercase and a special character.'
      : issues.length ? `<span class="text-red-600">Still needs ${issues.join(', ')}.</span>` : '<span class="text-teal">Strong enough ✓</span>';
  };
  input.addEventListener('input', upd); upd();
}

const DEMO = [
  ['Admin', 'admin@brightloop.com', 'BrightloopAdmin#2026', 'b-admin'],
  ['Staff', 'staff@brightloop.com', 'BrightloopStaff#2026', 'b-staff'],
  ['Customer · Acme', 'acme@corp.com', 'CustomerPass#2026', 'b-customer'],
  ['Customer · Retail shop', 'retail@shop.com', 'CustomerPass#2026', 'b-customer'],
];

// ---------- perspective grid (login background) ----------
// An endless floor grid scrolling toward the horizon, drawn on a canvas. Stops by itself once the canvas leaves the page.
function perspectiveGrid(canvas, { color = [240, 160, 232], speed = 0.5, cell = 1, depth = 10, fade = 1.1, horizon = 0.55 } = {}) {
  const ctx = canvas.getContext('2d');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let w = 0, h = 0, start = performance.now();
  const resize = () => {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  const rgba = a => `rgba(${color[0]},${color[1]},${color[2]},${a.toFixed(3)})`;
  const frame = now => {
    if (!canvas.isConnected) { removeEventListener('resize', resize); return; }
    ctx.clearRect(0, 0, w, h);
    const hy = h * horizon;                 // screen y of the horizon
    const f = h * 0.9, camH = 1;            // focal length and camera height above the floor
    const near = 0.35, far = depth;
    const project = (x, z) => [w / 2 + (x * f) / z, hy + (camH * f) / z];
    const alpha = z => Math.max(0, 1 - z / far) ** fade;
    const step = cell;
    const t = still ? 0 : ((now - start) / 1000) * speed;
    ctx.lineWidth = 1.25;
    const zBottom = Math.max(near, (camH * f) / (h - hy));   // floor depth at the bottom edge of the screen
    // Lines running across the floor, sliding toward the viewer.
    for (let z = step - (t % step); z < far; z += step) {
      if (z < near) continue;
      const [, y] = project(0, z);
      ctx.strokeStyle = rgba(alpha(z));
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
    // Lines running toward the horizon, fading with distance.
    const span = Math.ceil(((w / 2) * zBottom) / f / step) + 1;
    for (let i = -span; i <= span; i++) {
      const x = i * step;
      const [x1, y1] = project(x, zBottom), [x2, y2] = project(x, far);
      const g = ctx.createLinearGradient(x1, y1, x2, y2);
      g.addColorStop(0, rgba(alpha(zBottom))); g.addColorStop(0.5, rgba(alpha((zBottom + far) / 3) * 0.8)); g.addColorStop(1, rgba(0));
      ctx.strokeStyle = g;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    }
    if (!still) requestAnimationFrame(frame);
  };
  resize();
  addEventListener('resize', resize);
  requestAnimationFrame(frame);
}

// ---------- intro screen ----------
// Shown once per visit before the login page; any key, click or tap moves on.
const INTRO_CARDS = [
  ['ic-plum', 'MRR', '$48,260', '↑ 12% this month', 'bars'], ['ic-paper', 'Invoice', 'INV-00042', '✓ Paid via UPI'],
  ['ic-teal', 'Billing run', '128', 'invoices created · 0 duplicates'], ['ic-ink', 'Subscription', 'SUB-00017', 'Active · billed monthly'],
  ['ic-sand', 'Variant', '+560', 'Odoo Brand Edition'], ['ic-rose', 'Overdue', '3', 'on the chase list'],
  ['ic-grey', 'Quotation', 'Sent', 'valid for 30 days'], ['ic-paper', 'ARR', '$579k', 'across 4 plans', 'bars'],
  ['ic-plum', 'Discount', 'SEATS10', '−10% on 10+ seats'], ['ic-teal', 'Payment', '$1,681.50', 'Bank transfer · matched'],
  ['ic-ink', 'brightloop.', '', 'subscriptions, billed right'], ['ic-sand', 'Tax', 'GST 18%', 'applied automatically'],
];
function introCard([cls, k, v, sub, extra]) {
  const bars = extra === 'bars' ? `<div class="intro-bars">${[30, 45, 38, 60, 52, 75, 90].map(h => `<span style="height:${h}%"></span>`).join('')}</div>` : '';
  return `<div class="intro-card ${cls}"><div class="k">${k}</div>${bars}<div><div class="v">${v}</div><div class="s">${sub}</div></div></div>`;
}
function renderIntro() {
  // 5 columns, each a shuffled copy of the deck repeated twice so the drift loops seamlessly.
  const cols = [0, 1, 2, 3, 4].map(c => {
    const deck = INTRO_CARDS.map((_, i) => INTRO_CARDS[(i * 5 + c * 3) % INTRO_CARDS.length]).slice(0, 6);
    return `<div class="intro-col">${[...deck, ...deck].map(introCard).join('')}</div>`;
  }).join('');
  const el = document.createElement('div');
  el.className = 'intro';
  el.innerHTML = `<div class="intro-stage"><div class="intro-wall">${cols}</div></div><div class="intro-shade"></div>
    <div class="intro-copy">
      <div class="flex items-center justify-between intro-rise">
        <span class="text-2xl font-bold tracking-tight">brightloop<span class="opacity-60">.</span></span>
        <span class="text-xs font-semibold uppercase tracking-[0.2em] text-white/50">Odoo × Make-A-Thon</span></div>
      <div><h1 class="intro-title intro-rise" style="animation-delay:.1s">Recurring revenue <em>you can trust.</em></h1>
        <p class="mt-6 max-w-md text-lg text-white/70 intro-rise" style="animation-delay:.2s">Plans, subscriptions, invoices and payments for Brightloop Software, in one place.</p></div>
      <div class="intro-hint intro-rise" style="animation-delay:.35s"><span class="intro-pulse"></span>
        Press <kbd>any key</kbd> or click to sign in</div></div>`;
  document.body.appendChild(el);
  let gone = false;
  const leave = e => {
    if (gone || (e.type === 'keydown' && ['Shift', 'Control', 'Alt', 'Meta'].includes(e.key))) return;
    gone = true;
    window.removeEventListener('keydown', leave);
    S.introDone = S.fromIntro = true;
    renderAuth();                 // login renders underneath while the overlay animates away
    el.classList.add('leaving');
    setTimeout(() => { el.remove(); S.fromIntro = false; }, 1100);
  };
  window.addEventListener('keydown', leave);
  el.addEventListener('pointerdown', leave);
}

function renderAuth(mode = 'login') {
  const resetToken = new URLSearchParams(location.search).get('reset_token');
  if (resetToken) mode = 'reset';
  const tabs = mode === 'reset' ? '' : `<div class="flex border-b mb-5">
      <a class="tab ${mode === 'login' ? 'active' : ''}" data-mode="login">Sign in</a>
      <a class="tab ${mode === 'register' ? 'active' : ''}" data-mode="register">Create account</a>
      <a class="tab ${mode === 'forgot' ? 'active' : ''}" data-mode="forgot">Forgot password</a></div>`;
  let body = '';
  if (mode === 'login') body = `<form id="af" class="space-y-4">
      ${field({ name: 'email', label: 'Email', type: 'email', required: true })}
      ${field({ name: 'password', label: 'Password', type: 'password', required: true })}
      <button class="btn btn-primary w-full justify-center">Sign in</button></form>
      <div class="mt-6"><p class="label">Demo accounts (one click)</p><div class="flex flex-wrap gap-2">
      ${DEMO.map(([n, e, p, c], i) => `<button class="badge ${c} cursor-pointer !text-xs !py-1 !px-3" data-demo="${i}">${n}</button>`).join('')}</div></div>`;
  if (mode === 'register') body = `<form id="af" class="space-y-4">
      ${field({ name: 'name', label: 'Your name', required: true })}
      ${field({ name: 'company_name', label: 'Company' })}
      ${field({ name: 'email', label: 'Email', type: 'email', required: true, help: 'Each email can belong to only one account.' })}
      <div>${field({ name: 'password', label: 'Password', type: 'password', required: true })}<p class="text-xs mt-1" id="pwh"></p></div>
      <button class="btn btn-primary w-full justify-center">Create account</button></form>`;
  if (mode === 'forgot') body = `<form id="af" class="space-y-4">
      <p class="text-sm text-gray-600">Enter your registered email and we will send you a link to reset your password.</p>
      ${field({ name: 'email', label: 'Email', type: 'email', required: true })}
      <button class="btn btn-primary w-full justify-center">Send reset link</button></form>`;
  if (mode === 'reset') body = `<form id="af" class="space-y-4">
      <p class="text-sm text-gray-600">Choose a new password for your account.</p>
      <div>${field({ name: 'new_password', label: 'New password', type: 'password', required: true })}<p class="text-xs mt-1" id="pwh"></p></div>
      <button class="btn btn-primary w-full justify-center">Set new password</button></form>`;

  $('#app').innerHTML = `<div class="auth-page ${S.fromIntro ? 'auth-enter' : ''}">
    <canvas id="login-grid" aria-hidden="true"></canvas>
    <div class="relative z-10 min-h-screen grid lg:grid-cols-2">
      <div class="hidden lg:flex text-white p-12 flex-col justify-between">
        <div class="text-2xl font-bold tracking-tight">brightloop<span class="opacity-60">.</span></div>
        <div class="pb-24"><h1 class="text-5xl font-semibold leading-[1.05] tracking-tight">Plans, subscriptions and recurring billing in one place.</h1>
          <ul class="mt-8 space-y-3 text-white/80 text-sm">
            <li>✓ Quotation templates → subscriptions in one click</li><li>✓ Billing day runs itself: never billed twice, never skipped</li>
            <li>✓ Taxes and discounts applied automatically</li><li>✓ Live MRR, ARR, collections and overdue chase list</li></ul></div>
        <div class="text-xs text-white/50">Brightloop Software · Subscription Management System</div></div>
      <div class="flex items-center justify-center p-6"><div class="w-full max-w-md">
        <div class="lg:hidden text-2xl font-bold text-white mb-6">brightloop<span class="opacity-60">.</span></div>
        <div class="auth-card">
          <h2 class="text-2xl font-semibold mb-1">${mode === 'reset' ? 'Reset password' : 'Welcome'}</h2>
          <p class="text-sm text-gray-500 mb-5">${mode === 'reset' ? '' : 'Sign in to your Brightloop account.'}</p>
          ${tabs}${body}</div></div></div></div></div>`;
  perspectiveGrid($('#login-grid'));

  $$('[data-mode]').forEach(a => a.addEventListener('click', () => renderAuth(a.dataset.mode)));
  $$('[data-demo]').forEach(b => b.addEventListener('click', async () => {
    const [, email, password] = DEMO[b.dataset.demo];
    const r = await run(() => api('/auth/login', { method: 'POST', body: { email, password } }));
    saveSession(r); render();
  }));
  if ($('#pwh')) pwHint($('[type=password]'), $('#pwh'));
  $('#af').addEventListener('submit', async e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.target));
    if (mode === 'login') {
      const r = await run(() => api('/auth/login', { method: 'POST', body: v })); saveSession(r); render();
    } else if (mode === 'register') {
      const issues = passwordIssues(v.password);
      if (issues.length) return toast('Password needs ' + issues.join(', '), 'error');
      const r = await run(() => api('/auth/register', { method: 'POST', body: v }), 'Account created. Welcome!');
      saveSession(r); render();
    } else if (mode === 'forgot') {
      const r = await run(() => api('/auth/forgot-password', { method: 'POST', body: v }));
      toast(r.message, 'info'); renderAuth('login');
    } else {
      await run(() => api('/auth/reset-password', { method: 'POST', body: { token: resetToken, new_password: v.new_password } }), 'Password updated. Please sign in.');
      history.replaceState(null, '', '/'); renderAuth('login');
    }
  });
}

// ---------- shell & routing ----------
// [route, label, icon, flow step]
const STAFF_NAV = [
  ['Overview'], ['dashboard', 'Dashboard', 'layout-dashboard'], ['forecast', 'AI revenue forecast', 'sparkles'], ['recommendations', 'Recommendations', 'lightbulb'],
  ['Revenue flow'], ['templates', 'Quotation templates', 'file-text', '01'], ['subscriptions', 'Subscriptions', 'repeat', '02'],
  ['invoices', 'Invoices', 'receipt', '03'], ['payments', 'Payments', 'wallet', '04'],
  ['Records'], ['customers', 'Customers', 'users'], ['products', 'Products', 'package'], ['plans', 'Plans', 'calendar-clock'],
  ['taxes', 'Taxes', 'percent'], ['discounts', 'Discounts', 'badge-percent'],
];
const ADMIN_NAV = [['Admin'], ['staff', 'Staff', 'user-cog'], ['outbox', 'Email outbox', 'mail'], ['settings', 'Mail Settings', 'settings']];
const CUSTOMER_NAV = [['my-subscriptions', 'My subscriptions'], ['timeline', 'Timeline'], ['guardian', 'Price guardian'],
  ['passes', 'QR passes'], ['my-invoices', 'Invoices'], ['my-payments', 'Payments'], ['subscribe', 'Subscribe'], ['profile', 'Profile']];

function route() {
  const [name, id] = (location.hash.replace(/^#\/?/, '') || '').split('/');
  return { name: name || (isStaff() ? 'dashboard' : 'my-subscriptions'), id };
}

function logo(light = true) {
  return `<a href="#/" class="shrink-0 text-xl font-bold tracking-tight ${light ? 'text-white' : 'text-brand-700'}">brightloop<span class="opacity-60">.</span></a>`;
}

function renderShell() {
  const r = route();
  if (!isStaff()) {
    $('#app').innerHTML = `
      <header class="bg-odoo text-white sticky top-0 z-40 shadow">
        <div class="max-w-[1400px] mx-auto px-4 flex items-center gap-4 h-14">
          <a href="#/" class="font-bold text-lg tracking-tight shrink-0">brightloop<span class="opacity-60">.</span>
            <span class="font-normal text-white/70 text-sm ml-1 hidden sm:inline">Customer portal</span></a>
          <nav class="flex gap-1 overflow-x-auto flex-1">${CUSTOMER_NAV.map(([k, t]) =>
            `<a href="#/${k}" class="nav-link ${r.name === k ? 'active' : ''}">${t}</a>`).join('')}</nav>
          <div class="flex items-center gap-3 shrink-0">
            <div class="text-right leading-tight hidden md:block"><div class="text-sm font-medium">${esc(S.user.name)}</div>
              <div class="text-xs text-white/70">${esc(S.user.email)}</div></div>
            ${themeButton('grid h-8 w-8 place-items-center rounded-lg text-white/80 hover:bg-white/10 hover:text-white')}
            <span class="badge bg-white/20 text-white">${S.user.role}</span>
            <button class="btn btn-sm bg-white/10 text-white hover:bg-white/20" data-logout>Sign out</button></div></div></header>
      <main id="main" class="max-w-[1400px] mx-auto p-4 md:p-6"></main>`;
    $$('[data-logout]').forEach(b => b.addEventListener('click', logout));
    return;
  }
  const nav = [...STAFF_NAV, ...(isAdmin() ? ADMIN_NAV : [])];
  const initials = S.user.name.split(' ').map(p => p[0]).slice(0, 2).join('').toUpperCase();
  const sidebar = `<nav class="flex h-full flex-col p-4 overflow-y-auto">
      <div class="mb-4 px-2 pt-1">${logo()}</div>
      ${nav.map(([k, t, ic, step]) => !t ? `<div class="side-group">${k}</div>` :
        `<a href="#/${k}" class="side-link ${r.name === k ? 'active' : ''}">${icon(ic)}<span class="flex-1">${t}</span>
          ${k === 'invoices' ? '<span id="nav-overdue"></span>' : ''}${step ? `<span class="step">${step}</span>` : ''}</a>`).join('')}
      <div class="mt-auto pt-4"><div class="rounded-xl bg-white/10 p-3 text-xs text-[#ead8e4]">
        <div class="flex items-center gap-2.5">
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-white/15 ring-2 ring-white/20 text-sm font-bold text-white">${esc(initials)}</span>
          <span class="min-w-0"><span class="block truncate font-semibold text-white">${esc(S.user.name)}</span>
            <span class="block truncate">${esc(S.user.email)}</span></span></div>
        <div class="mt-2 flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" id="live-dot" style="background:#a3a6ac"></span>
          <span id="live-text">Connecting…</span></div>
        <div class="mt-3 flex items-center justify-between">
          <button data-logout class="flex items-center gap-1.5 font-semibold text-white/90 hover:text-white">${icon('log-out', 'h-3.5 w-3.5')} Sign out</button>
          <span class="flex items-center gap-2">${themeButton('grid h-7 w-7 place-items-center rounded-lg text-white/80 hover:bg-white/10 hover:text-white')}
          <span class="badge ${S.user.role === 'admin' ? 'bg-white/20 text-white' : 'b-staff'}">${S.user.role}</span></span></div></div></div></nav>`;
  $('#app').innerHTML = `<div class="min-h-screen lg:pl-64">
    <aside class="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block" style="background:linear-gradient(to bottom, var(--brand-900), var(--night))">${sidebar}</aside>
    <div id="drawer" class="fixed inset-0 z-40 hidden lg:hidden"><div class="absolute inset-0 bg-black/40" data-close-drawer></div>
      <aside class="absolute inset-y-0 left-0 w-64" style="background:linear-gradient(to bottom, var(--brand-900), var(--night))">
        <button class="absolute right-3 top-4 text-white" data-close-drawer aria-label="Close menu">${icon('x')}</button>${sidebar}</aside></div>
    <header class="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-surface px-4 py-3 lg:hidden">
      <button id="open-drawer" aria-label="Open menu">${icon('menu')}</button>${logo(false)}${themeButton('ml-auto grid h-9 w-9 place-items-center rounded-lg text-slate-600 hover:bg-slate-100')}</header>
    <main id="main" class="mx-auto max-w-7xl px-4 py-8 sm:px-8"></main></div>`;
  $$('[data-logout]').forEach(b => b.addEventListener('click', logout));
  $('#open-drawer').addEventListener('click', () => $('#drawer').classList.remove('hidden'));
  $$('[data-close-drawer], #drawer .side-link').forEach(b => b.addEventListener('click', () => $('#drawer').classList.add('hidden')));
  // Status pill + overdue counter in the nav.
  fetch('/api/health').then(r => r.ok).catch(() => false).then(ok => {
    $$('#live-dot').forEach(d => { d.style.background = ok ? '#34d399' : '#a3a6ac'; });
    $$('#live-text').forEach(t => { t.textContent = ok ? 'Billing engine online' : 'Server unreachable'; });
  });
  api('/invoices?overdue=true&limit=1').then(d => {
    if (d.total) $$('#nav-overdue').forEach(n => { n.innerHTML = `<span class="rounded-full bg-rose-500 px-1.5 text-[11px] font-bold text-white">${d.total}</span>`; });
  }).catch(() => {});
}

const VIEWS = {
  dashboard: viewDashboard, forecast: viewForecast, recommendations: viewRecommendations, subscriptions: viewSubscriptions, templates: viewTemplates, invoices: viewInvoices,
  payments: viewPayments, customers: viewCustomers, products: viewProducts, plans: viewPlans, taxes: viewTaxes,
  discounts: viewDiscounts, staff: viewStaff, outbox: viewOutbox, settings: viewSettings,
  'my-subscriptions': viewMySubscriptions, 'my-invoices': viewMyInvoices, 'my-payments': viewMyPayments,
  timeline: viewTimeline, guardian: viewGuardian, passes: viewPasses,
  subscribe: viewSubscribe, profile: viewProfile,
};
const CUSTOMER_VIEWS = new Set(CUSTOMER_NAV.map(n => n[0]));

async function render() {
  if (!S.token || !S.user) {
    const resetLink = new URLSearchParams(location.search).has('reset_token');
    return S.introDone || resetLink ? renderAuth() : renderIntro();
  }
  renderShell();
  const r = route();
  let view = VIEWS[r.name];
  if (!view || (isStaff() === CUSTOMER_VIEWS.has(r.name))) { location.hash = isStaff() ? '#/dashboard' : '#/my-subscriptions'; return; }
  if (r.name === 'subscriptions' && r.id) view = viewSubscriptionDetail;
  const main = $('#main');
  main.innerHTML = '<div class="flex justify-center py-20"><div class="spinner"></div></div>';
  try { await view(main, r.id); }
  catch (e) { main.innerHTML = `<div class="card p-6 text-red-700">${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', render);
const refresh = () => render();

function pageHeader(title, sub, actions = '', eyebrow = '') {
  return `<div class="mb-6 flex flex-wrap items-end justify-between gap-4"><div>
    ${eyebrow ? `<div class="mb-1 text-xs font-bold uppercase tracking-widest text-brand-700">${eyebrow}</div>` : ''}
    <h1 class="text-2xl font-bold tracking-tight text-ink">${title}</h1>
    ${sub ? `<p class="mt-1 max-w-2xl text-sm text-slate-600">${sub}</p>` : ''}</div>
    <div class="flex flex-wrap gap-2">${actions}</div></div>`;
}
function emptyRow(cols, text = 'Nothing here yet.') {
  return `<tr><td colspan="${cols}" class="text-center text-slate-400 py-10">${text}</td></tr>`;
}
function stat(ic, label, value, sub, tone = 'brand') {
  return `<div class="glow-card"><div class="glow"></div><div class="inner">
    <div class="stat-icon tone-${tone}">${icon(ic)}</div>
    <div class="text-2xl font-bold tracking-tight text-ink tabular-nums">${value}</div>
    <div class="mt-0.5 text-sm font-medium text-slate-700">${label}</div>
    <div class="text-xs text-slate-500">${sub}</div></div></div>`;
}
const AGING_TONE = { '1-30': 'b-amber', '31-60': 'b-red', '60+': 'b-overdue' };

function pager(total, offset, onPage) {
  const id = 'pg' + Math.random().toString(36).slice(2, 7);
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    el.querySelector('[data-p=prev]')?.addEventListener('click', () => onPage(Math.max(0, offset - PAGE)));
    el.querySelector('[data-p=next]')?.addEventListener('click', () => onPage(offset + PAGE));
  });
  return `<div id="${id}" class="flex items-center justify-between px-4 py-3 text-sm text-gray-500 border-t">
    <span>${total ? `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total.toLocaleString()}` : '0 records'}</span>
    <div class="flex gap-2"><button class="btn btn-light btn-sm" data-p="prev" ${offset === 0 ? 'disabled' : ''}>‹ Prev</button>
    <button class="btn btn-light btn-sm" data-p="next" ${offset + PAGE >= total ? 'disabled' : ''}>Next ›</button></div></div>`;
}

// ---------- dashboard ----------
function trendChart(trend) {
  const W = 720, H = 230, P = 40, max = Math.max(1, ...trend.flatMap(t => [t.invoiced, t.collected]));
  const bw = (W - P * 2) / trend.length;
  const y = v => H - 26 - (v / max) * (H - 50);
  const bars = trend.map((t, i) => {
    const x = P + i * bw;
    const m = new Date(t.month + '-01T00:00:00').toLocaleDateString('en-GB', { month: 'short' });
    return `<rect x="${x + bw * .16}" y="${y(t.invoiced)}" width="${bw * .32}" height="${H - 26 - y(t.invoiced)}" fill="var(--series-invoiced)" rx="3"><title>${m}: invoiced ${money(t.invoiced)}</title></rect>
      <rect x="${x + bw * .52}" y="${y(t.collected)}" width="${bw * .32}" height="${H - 26 - y(t.collected)}" fill="var(--series-collected)" rx="3"><title>${m}: collected ${money(t.collected)}</title></rect>
      <text x="${x + bw / 2}" y="${H - 6}" font-size="11" text-anchor="middle" fill="var(--slate-500)">${m}</text>`;
  }).join('');
  const grid = [0, .25, .5, .75, 1].map(f => `<line x1="${P}" x2="${W - P}" y1="${y(max * f)}" y2="${y(max * f)}" stroke="var(--slate-200)"/>
    <text x="${P - 8}" y="${y(max * f) + 4}" font-size="10" text-anchor="end" fill="var(--slate-400)">${max * f >= 1000 ? (max * f / 1000).toFixed(max >= 10000 ? 0 : 1) + 'k' : Math.round(max * f)}</text>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" class="w-full h-auto">${grid}${bars}</svg>`;
}

function runBillingDialog() {
  formModal('Run billing', [
    { name: 'as_of', label: 'Bill everything due on or before', type: 'date', required: true, value: today() },
    { name: 'auto_confirm', label: 'Confirm invoices straight away', type: 'checkbox', value: false },
  ], async v => {
    const r = await api('/billing/run', { method: 'POST', body: v });
    openModal('Billing run complete', `<div class="grid grid-cols-2 gap-3 text-sm">
      <div class="card kpi"><div class="k">Subscriptions due</div><div class="v">${r.subscriptions_scanned}</div></div>
      <div class="card kpi"><div class="k">Invoices created</div><div class="v text-teal">${r.invoices_created}</div></div>
      <div class="card kpi"><div class="k">Already invoiced (skipped)</div><div class="v">${r.skipped_existing}</div></div>
      <div class="card kpi"><div class="k">Auto-closed at expiry</div><div class="v">${r.subscriptions_closed}</div></div>
      ${r.subscriptions_resumed ? `<div class="card kpi col-span-2"><div class="k">Resumed from a pause</div><div class="v">${r.subscriptions_resumed}</div></div>` : ''}</div>
      ${r.invoice_numbers.length ? `<p class="text-sm text-slate-600 mt-4">New: ${r.invoice_numbers.slice(0, 30).join(', ')}${r.invoice_numbers.length > 30 ? '…' : ''}</p>`
        : '<p class="text-sm text-slate-500 mt-4">Nothing was due. Running it again is always safe.</p>'}`,
      { footer: '<button class="btn btn-primary" data-close>Done</button>' });
    refresh();
  }, { submitLabel: 'Run billing' });
}

async function viewDashboard(main) {
  const t0 = performance.now();
  const [s, overdue, plans, customers] = await Promise.all([
    api('/analytics/summary?' + qs(S.dash)), api('/analytics/overdue'), getPlans(), getCustomers()]);
  const ms = Math.round(performance.now() - t0);
  const statuses = ['active', 'paused', 'quotation', 'confirmed', 'draft', 'closed'];
  const totalSubs = statuses.reduce((a, k) => a + (s.subscriptions_by_status[k] || 0), 0) || 1;
  const planMax = Math.max(1, ...s.active_by_plan.map(p => p.count));
  const methodTotal = Object.values(s.collected_by_method).reduce((a, b) => a + b, 0) || 1;
  const collectRate = s.invoiced_amount ? Math.min(1, s.revenue_collected / s.invoiced_amount) : 0;
  const filtersOn = Object.values(S.dash).some(Boolean);
  const label2 = (t, v) => `<div class="flex justify-between gap-3 text-sm"><span class="text-slate-500">${t}</span><span class="text-right font-medium text-slate-800">${v}</span></div>`;

  main.innerHTML = pageHeader('Finance overview',
    'Active subscriptions, recurring revenue, collections and overdue invoices in one place. Figures are live from the billing ledger.',
    `<button class="btn btn-light" id="go-invoices">${icon('receipt')} Invoices</button><button class="btn btn-primary" id="run-billing">${icon('play')} Run billing</button>`,
    `Overview · Loaded in ${ms} ms`) + `

    <div class="card mb-6 overflow-hidden">
      <div class="card-head"><div class="t">${icon('sliders-horizontal')} Filters</div>
        <div class="s">Date range applies to invoiced and collected amounts</div>
        ${filtersOn ? '<span class="badge b-teal ml-auto">Filtered</span>' : ''}</div>
      <form id="df" class="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1.3fr_1.3fr_auto] items-end">
        <label class="block"><span class="label">From</span><input type="date" class="input" name="date_from" value="${S.dash.date_from}"></label>
        <label class="block"><span class="label">To</span><input type="date" class="input" name="date_to" value="${S.dash.date_to}"></label>
        <label class="block"><span class="label">Plan</span><select class="input" name="plan_id"><option value="">All plans</option>
          ${plans.map(p => `<option value="${p.id}" ${String(p.id) === S.dash.plan_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
        <label class="block"><span class="label">Customer</span><select class="input" name="customer_id"><option value="">All customers</option>
          ${customers.map(c => `<option value="${c.id}" ${String(c.id) === S.dash.customer_id ? 'selected' : ''}>${esc(c.company_name || c.name)}</option>`).join('')}</select></label>
        <div class="flex gap-2"><button class="btn btn-primary">Apply</button><button type="button" class="btn btn-ghost" id="dreset">Reset</button></div>
      </form></div>

    <div class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      ${stat('repeat', 'Active subscriptions', s.active_subscriptions.toLocaleString(), `${s.subscriptions_by_status.paused || 0} paused · ${s.subscriptions_by_status.quotation || 0} quotes out`)}
      ${stat('trending-up', 'Monthly recurring revenue', money(s.mrr), 'Normalised across billing frequencies', 'green')}
      ${stat('calendar-range', 'Annual recurring revenue', money(s.arr), 'MRR × 12', 'blue')}
      ${stat('wallet', 'Revenue collected', money(s.revenue_collected), `${s.payments_count} payments · ${Math.round(collectRate * 100)}% of invoiced`, 'green')}
      ${stat('hourglass', 'Outstanding', money(s.outstanding_amount), `${s.outstanding_count} confirmed invoices unpaid`, 'amber')}
      ${stat('alert-triangle', 'Overdue', money(s.overdue_amount), `${s.overdue_count} invoices past their due date`, s.overdue_count ? 'red' : 'green')}
    </div>
    <div id="dash-recs"></div>

    <div class="mb-6 grid gap-6 lg:grid-cols-3">
      <div class="card overflow-hidden lg:col-span-2">
        <div class="card-head"><div class="t">${icon('bar-chart-3')} Invoiced vs collected</div><div class="s">Last 12 months</div>
          <div class="ml-auto flex gap-3 text-xs text-slate-500">
            <span class="flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-sm" style="background:var(--series-invoiced)"></span>Invoiced</span>
            <span class="flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-sm" style="background:var(--series-collected)"></span>Collected</span></div></div>
        <div class="p-4 sm:p-6">${trendChart(s.trend)}</div>
        <div class="grid grid-cols-3 border-t border-slate-100 text-center">
          <div class="p-4"><div class="text-xs text-slate-500">Invoiced</div><div class="font-semibold tabular-nums">${money(s.invoiced_amount)}</div></div>
          <div class="p-4 border-x border-slate-100"><div class="text-xs text-slate-500">Collected</div><div class="font-semibold tabular-nums">${money(s.revenue_collected)}</div></div>
          <div class="p-4"><div class="text-xs text-slate-500">Collection rate</div><div class="font-semibold tabular-nums">${Math.round(collectRate * 100)}%</div></div></div>
      </div>
      <div class="card overflow-hidden">
        <div class="card-head"><div class="t">${icon('pie-chart')} Subscriptions</div><div class="s">${totalSubs} total</div></div>
        <div class="space-y-5 p-6">
          <div class="space-y-2.5">${statuses.map(k => `<div class="flex items-center gap-3 text-sm">
            <span class="w-24">${badge(k)}</span><div class="progress flex-1"><div style="width:${(s.subscriptions_by_status[k] || 0) / totalSubs * 100}%"></div></div>
            <span class="w-6 text-right font-semibold tabular-nums">${s.subscriptions_by_status[k] || 0}</span></div>`).join('')}</div>
          <div class="border-t border-slate-100 pt-4"><div class="mb-2 text-sm font-medium text-slate-700">Active by plan</div>
            <div class="space-y-2">${s.active_by_plan.map(p => `<div><div class="flex justify-between text-sm"><span class="text-slate-600">${esc(p.plan)}</span><b>${p.count}</b></div>
              <div class="progress mt-1"><div style="width:${p.count / planMax * 100}%"></div></div></div>`).join('') || '<p class="text-sm text-slate-400">No active subscriptions</p>'}</div></div>
          <div class="border-t border-slate-100 pt-4 space-y-2"><div class="text-sm font-medium text-slate-700">Collected by method</div>
            ${Object.entries(s.collected_by_method).sort((a, b) => b[1] - a[1]).map(([m, a]) => label2(`${methodName(m)} <span class="text-xs text-slate-400">${Math.round(a / methodTotal * 100)}%</span>`, money(a))).join('') || '<p class="text-sm text-slate-400">No payments yet</p>'}</div>
        </div></div>
    </div>

    <div class="card overflow-hidden">
      <div class="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
        <h2 class="font-semibold text-ink">${overdue.length} overdue invoice${overdue.length === 1 ? '' : 's'}</h2>
        ${overdue.length ? `<span class="text-sm text-slate-500">${money(overdue.reduce((a, o) => a + o.balance_due, 0))} to chase</span>` : ''}
        <div class="search ml-auto">${icon('search')}<input class="input w-56" id="od-q" placeholder="Search…"></div>
        <select class="input w-36" id="od-b"><option value="">All ages</option><option>1-30</option><option>31-60</option><option>60+</option></select>
      </div>
      <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Invoice</th><th>Balance</th><th>Aging</th><th>Due</th><th>Contact</th><th></th></tr></thead>
      <tbody id="od-body"></tbody></table></div></div>`;

  const odRows = list => list.map(o => `<tr class="clickable" data-inv="${o.invoice_id}">
      <td><div class="font-medium text-ink">${esc(o.company_name || o.customer_name)}</div><div class="mt-0.5 text-xs text-slate-500">${o.invoice_number}</div></td>
      <td class="font-semibold text-ink tabular-nums">${money(o.balance_due)}</td>
      <td><span class="badge normal-case ${AGING_TONE[o.bucket]}">${o.days_overdue} day${o.days_overdue === 1 ? '' : 's'} · ${o.bucket}</span></td>
      <td class="text-slate-600">${fmtDate(o.due_date)}</td>
      <td><div class="text-slate-700">${esc(o.email)}</div><div class="text-xs text-slate-400">${esc(o.phone || '')}</div></td>
      <td class="text-right"><button class="btn btn-ghost btn-sm" data-pay="${o.invoice_id}">${icon('hand-coins')} Record payment</button></td></tr>`).join('')
    || emptyRow(6, overdue.length ? 'No overdue invoices match.' : 'No overdue invoices. Everyone is paid up.');
  const drawOverdue = () => {
    const q = $('#od-q').value.toLowerCase(), b = $('#od-b').value;
    $('#od-body').innerHTML = odRows(overdue.filter(o => (!b || o.bucket === b) &&
      `${o.invoice_number} ${o.customer_name} ${o.company_name} ${o.email}`.toLowerCase().includes(q)));
    $$('#od-body [data-inv]').forEach(tr => tr.addEventListener('click', () => showInvoice(tr.dataset.inv)));
    $$('#od-body [data-pay]').forEach(btn => btn.addEventListener('click', async e => {
      e.stopPropagation(); paymentForm(await api('/invoices/' + btn.dataset.pay));
    }));
  };
  drawOverdue();
  $('#od-q').addEventListener('input', drawOverdue);
  $('#od-b').addEventListener('change', drawOverdue);
  $('#df').addEventListener('submit', e => { e.preventDefault(); Object.assign(S.dash, Object.fromEntries(new FormData(e.target))); refresh(); });
  $('#dreset').addEventListener('click', () => { S.dash = { date_from: '', date_to: '', plan_id: '', customer_id: '' }; refresh(); });
  $('#run-billing').addEventListener('click', runBillingDialog);
  api('/recommendations').then(d => {
    const top = d.items.filter(r => !r.dismissed).slice(0, 2);
    if (!top.length || !$('#dash-recs')) return;
    $('#dash-recs').innerHTML = `<div class="mb-6"><div class="mb-3 flex items-center justify-between"><h2 class="flex items-center gap-2 font-semibold">${icon('lightbulb', 'h-4 w-4 text-brand-700')} Recommended next</h2>
      <a href="#/recommendations" class="text-sm text-brand-700">All ${d.open} recommendations →</a></div>
      <div class="grid gap-4 lg:grid-cols-2">${top.map(r => recCard(r, true)).join('')}</div></div>`;
    wireRecs($('#dash-recs'));
  }).catch(() => {});
  $('#go-invoices').addEventListener('click', () => { location.hash = '#/invoices'; });
}

// ---------- revenue forecast (Monte Carlo) ----------
const FC_DEFAULT = { months: 12, sims: 2000, churn: 1, growth: 1, collection: null, target_arr: '', seed: 42 };
const compact = v => {
  const a = Math.abs(v);
  return (v < 0 ? '-' : '') + (a >= 1e6 ? '$' + (a / 1e6).toFixed(2) + 'M' : a >= 1e3 ? '$' + (a / 1e3).toFixed(a >= 1e5 ? 0 : 1) + 'k' : '$' + Math.round(a));
};
const monthShort = m => new Date(m + '-01T00:00:00').toLocaleDateString('en-GB', { month: 'short', year: '2-digit' });

function fanChart(history, bands) {
  const hist = history.slice(-13);
  const W = 760, H = 300, L = 58, R = 16, T = 16, B = 30;
  const n = hist.length + bands.length;
  const max = Math.max(1, ...hist.map(h => h.mrr), ...bands.map(b => b.p95)) * 1.06;
  const x = i => L + (i * (W - L - R)) / (n - 1);
  const y = v => T + (H - T - B) * (1 - v / max);
  const start = hist.length - 1, cur = hist[start].mrr;
  const pts = (arr, key, from) => arr.map((b, i) => `${x(from + i)},${y(b[key])}`);
  // Polygon: out along the upper percentile, back along the lower one, anchored at today's MRR.
  const band = (lo, hi) => `M${x(start)},${y(cur)} L${pts(bands, hi, start + 1).join(' L')} L${pts(bands, lo, start + 1).reverse().join(' L')} Z`;
  const grid = [0, .25, .5, .75, 1].map(f => `<line x1="${L}" x2="${W - R}" y1="${y(max * f)}" y2="${y(max * f)}" stroke="var(--slate-200)"/>
    <text x="${L - 8}" y="${y(max * f) + 4}" font-size="10" text-anchor="end" fill="var(--slate-400)">${compact(max * f)}</text>`).join('');
  const labels = [...hist.map(h => h.month), ...bands.map(b => b.month)].map((m, i) =>
    i % 3 === 0 || i === start ? `<text x="${x(i)}" y="${H - 8}" font-size="10" text-anchor="middle" fill="var(--slate-500)">${monthShort(m)}</text>` : '').join('');
  const histLine = hist.map((h, i) => `${i ? 'L' : 'M'}${x(i)},${y(h.mrr)}`).join(' ');
  const median = `M${x(start)},${y(cur)} L${pts(bands, 'p50', start + 1).join(' L')}`;
  const dots = bands.map((b, i) => `<circle cx="${x(start + 1 + i)}" cy="${y(b.p50)}" r="9" fill="transparent">
    <title>${monthShort(b.month)}: median ${money(b.p50)} MRR · 50% range ${money(b.p25)}–${money(b.p75)} · 90% range ${money(b.p5)}–${money(b.p95)}</title></circle>`).join('');
  const histDots = hist.map((h, i) => `<circle cx="${x(i)}" cy="${y(h.mrr)}" r="8" fill="transparent"><title>${monthShort(h.month)}: ${money(h.mrr)} MRR · ${h.new_deals} new, ${h.churned_deals} churned</title></circle>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" class="w-full h-auto">${grid}
    <path d="${band('p5', 'p95')}" fill="var(--brand-500)" opacity=".16"/>
    <path d="${band('p25', 'p75')}" fill="var(--brand-500)" opacity=".32"/>
    <line x1="${x(start)}" x2="${x(start)}" y1="${T}" y2="${H - B}" stroke="var(--slate-400)" stroke-dasharray="3 4"/>
    <text x="${x(start) + 6}" y="${T + 10}" font-size="10" fill="var(--slate-500)">Today</text>
    <path d="${histLine}" fill="none" stroke="var(--ink)" stroke-width="2.2" stroke-linejoin="round"/>
    <path d="${median}" fill="none" stroke="var(--brand-700)" stroke-width="2.2" stroke-dasharray="6 5"/>
    ${labels}${histDots}${dots}</svg>`;
}

function arrHistogram(hist, target, start) {
  const W = 380, H = 220, L = 8, R = 8, T = 12, B = 34;
  const max = Math.max(1, ...hist.map(h => h.count));
  const lo = hist[0].from, hi = hist[hist.length - 1].to;
  const bw = (W - L - R) / hist.length;
  const xv = v => L + ((v - lo) / (hi - lo || 1)) * (W - L - R);
  const bars = hist.map((h, i) => `<rect x="${L + i * bw + 1}" y="${T + (H - T - B) * (1 - h.count / max)}" width="${bw - 2}"
    height="${(H - T - B) * h.count / max}" rx="2" fill="${h.from >= target ? 'var(--brand-600)' : 'var(--series-invoiced)'}">
    <title>${compact(h.from)}–${compact(h.to)} ARR: ${h.count} simulations</title></rect>`).join('');
  const marker = (v, label, color) => v >= lo && v <= hi ? `<line x1="${xv(v)}" x2="${xv(v)}" y1="${T}" y2="${H - B}" stroke="${color}" stroke-width="1.5" stroke-dasharray="4 3"/>
    <text x="${Math.min(W - 4, Math.max(4, xv(v)))}" y="${T + 9}" font-size="10" text-anchor="${xv(v) > W / 2 ? 'end' : 'start'}" fill="${color}">${label}</text>` : '';
  return `<svg viewBox="0 0 ${W} ${H}" class="w-full h-auto">${bars}
    ${marker(target, ' Target ' + compact(target) + ' ', '#e11d48')}${marker(start, ' Today ' + compact(start) + ' ', 'var(--slate-500)')}
    <text x="${L}" y="${H - 10}" font-size="10" fill="var(--slate-500)">${compact(lo)}</text>
    <text x="${W - R}" y="${H - 10}" font-size="10" text-anchor="end" fill="var(--slate-500)">${compact(hi)}</text></svg>`;
}

const INSIGHT_ICON = { green: ['trending-up', 'green'], red: ['alert-triangle', 'red'], amber: ['alert-circle', 'amber'],
  blue: ['target', 'blue'], brand: ['zap', 'brand'], slate: ['info', 'brand'] };

async function viewForecast(main) {
  S.fc = S.fc || { ...FC_DEFAULT };
  const f = S.fc;
  main.innerHTML = pageHeader('AI Revenue Forecast',
    'A Monte Carlo simulation fitted to your own history: churn, new business, deal sizes and collections. Thousands of possible futures, summarised.',
    `<button class="btn btn-light" id="fc-reset">${icon('rotate-ccw')} Reset</button><button class="btn btn-primary" id="fc-rerun">${icon('dices')} Re-run simulation</button>`,
    'Forecast · Monte Carlo') + `
    <div id="fc-callout"></div>
    <div class="card mb-6 overflow-hidden">
      <div class="card-head"><div class="t">${icon('sliders-horizontal')} What if…</div><div class="s">Adjust the assumptions; the simulation re-runs instantly</div></div>
      <form id="fc-form" class="grid gap-x-8 gap-y-5 p-6 sm:grid-cols-2 lg:grid-cols-3">
        <label class="block"><span class="label flex justify-between">Horizon <b id="fc-months-l"></b></span>
          <input type="range" name="months" min="3" max="36" step="1" value="${f.months}" class="w-full accent-[var(--brand-600)]"></label>
        <label class="block"><span class="label flex justify-between">Churn <b id="fc-churn-l"></b></span>
          <input type="range" name="churn" min="0" max="2" step="0.05" value="${f.churn}" class="w-full accent-[var(--brand-600)]"></label>
        <label class="block"><span class="label flex justify-between">New business <b id="fc-growth-l"></b></span>
          <input type="range" name="growth" min="0" max="2" step="0.05" value="${f.growth}" class="w-full accent-[var(--brand-600)]"></label>
        <label class="block"><span class="label flex justify-between">Collection rate <b id="fc-coll-l"></b></span>
          <input type="range" name="collection" min="0.5" max="1" step="0.01" value="${f.collection ?? 0.95}" class="w-full accent-[var(--brand-600)]"></label>
        <label class="block"><span class="label">ARR target</span>
          <input class="input" type="number" name="target_arr" min="0" step="1000" placeholder="Auto: +25% on today" value="${f.target_arr}"></label>
        <label class="block"><span class="label">Simulations</span><select class="input" name="sims">
          ${[500, 1000, 2000, 5000, 10000].map(n => `<option value="${n}" ${n === f.sims ? 'selected' : ''}>${n.toLocaleString()} futures</option>`).join('')}</select></label>
      </form></div>
    <div id="fc-results" class="transition-opacity"><div class="flex justify-center py-20"><div class="spinner"></div></div></div>`;

  let model = null, timer = 0, reqId = 0;
  const labels = () => {
    const v = readFc();
    $('#fc-months-l').textContent = `${v.months} months`;
    $('#fc-churn-l').textContent = `×${v.churn.toFixed(2)}${model ? ` · ${(model.churn_mean * v.churn * 100).toFixed(1)}%/mo` : ''}`;
    $('#fc-growth-l').textContent = `×${v.growth.toFixed(2)}${model ? ` · ${(model.deals_per_month * v.growth).toFixed(1)} deals/mo` : ''}`;
    $('#fc-coll-l').textContent = f.collection === null && model ? `fitted ${Math.round(model.collection_rate * 100)}%` : `${Math.round(v.collection * 100)}%`;
  };
  const readFc = () => {
    const fd = new FormData($('#fc-form'));
    return { months: +fd.get('months'), churn: +fd.get('churn'), growth: +fd.get('growth'), collection: +fd.get('collection'),
      target_arr: fd.get('target_arr'), sims: +fd.get('sims') };
  };
  const load = async () => {
    const id = ++reqId;
    $('#fc-results').style.opacity = '.55';
    const t0 = performance.now();
    try {
      const d = await api('/forecast?' + qs({ months: f.months, sims: f.sims, churn: f.churn, growth: f.growth,
        collection: f.collection ?? '', target_arr: f.target_arr, seed: f.seed }));
      if (id !== reqId || !$('#fc-results')) return;
      model = d.model;
      if (f.collection === null) $('[name=collection]').value = model.collection_rate.toFixed(2);
      labels();
      renderForecast(d, Math.round(performance.now() - t0));
    } catch (e) { toast(e.message, 'error'); }
    finally { if ($('#fc-results')) $('#fc-results').style.opacity = '1'; }
  };
  $('#fc-form').addEventListener('input', e => {
    if (e.target.name === 'collection') f.collection = +e.target.value;
    labels();
  });
  $('#fc-form').addEventListener('change', () => {
    const v = readFc();
    Object.assign(f, { months: v.months, churn: v.churn, growth: v.growth, sims: v.sims, target_arr: v.target_arr });
    clearTimeout(timer); timer = setTimeout(load, 120);
  });
  $('#fc-form').addEventListener('submit', e => e.preventDefault());
  $('#fc-rerun').addEventListener('click', () => { f.seed = Math.floor(Math.random() * 1e6); load(); });
  $('#fc-reset').addEventListener('click', () => { S.fc = { ...FC_DEFAULT }; refresh(); });
  labels();
  await load();
}

function renderForecast(d, ms) {
  const s = d.summary, m = d.model;
  $('#fc-callout').innerHTML = !d.simulation_data_loaded && isAdmin() ? `
    <div class="card mb-6 flex flex-wrap items-center gap-4 p-4">
      <div class="stat-icon tone-amber !mb-0">${icon('flask-conical')}</div>
      <div class="flex-1 min-w-[240px]"><div class="font-semibold">${m.months_of_history < 6 ? 'Not much history to learn from yet' : 'Want a bigger book to forecast?'}</div>
        <div class="text-sm text-slate-500">Load 18 months of simulated customers (sign-ups, churn, renewals, upsells, billing and payments) so the model has a realistic history.</div></div>
      <button class="btn btn-primary" id="fc-sim">${icon('database')} Load simulation data</button></div>` : '';
  $('#fc-sim')?.addEventListener('click', async e => {
    e.target.closest('button').disabled = true;
    e.target.closest('button').innerHTML = '<span class="spinner !h-4 !w-4 !border-2"></span> Simulating 18 months…';
    try {
      const r = await api('/forecast/simulation-data', { method: 'POST', body: {} });
      toast(`Loaded ${r.customers} customers: ${r.churned} churned, ${r.renewed} renewed, ${r.payments} payments`);
      invalidate('customers'); refresh();
    } catch (err) { toast(err.message, 'error'); e.target.closest('button').disabled = false; }
  });

  const tone = s.growth_pct >= 0 ? 'green' : 'red';
  $('#fc-results').innerHTML = `
    <div class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      ${stat('gauge', 'MRR today', money(s.start_mrr), `${compact(s.start_arr)} ARR · ${m.active_customers} customers`)}
      ${stat('trending-up', `Median MRR in ${d.months} months`, money(s.median_mrr), `${s.growth_pct >= 0 ? '+' : ''}${s.growth_pct ?? 0}% · ${compact(s.median_arr)} ARR`, tone)}
      ${stat('target', `Chance of ${compact(s.target_arr)} ARR`, `${Math.round(s.p_target * 100)}%`, `${Math.round(s.p_decline * 100)}% chance ARR falls`, 'blue')}
      ${stat('shield-alert', 'Downside ARR (P5)', compact(s.p5_arr), `Upside (P95) ${compact(s.p95_arr)}`, 'amber')}
      ${stat('wallet', 'Expected cash', compact(s.expected_cash), `over ${d.months} months at ${Math.round((d.assumptions.collection ?? m.collection_rate) * 100)}% collected`)}
    </div>
    <div class="mb-6 grid gap-6 lg:grid-cols-3">
      <div class="card overflow-hidden lg:col-span-2">
        <div class="card-head"><div class="t">${icon('area-chart')} MRR: history and ${d.sims.toLocaleString()} simulated futures</div>
          <div class="ml-auto flex flex-wrap gap-3 text-xs text-slate-500">
            <span class="flex items-center gap-1.5"><span class="h-0.5 w-4" style="background:var(--ink)"></span>Actual</span>
            <span class="flex items-center gap-1.5"><span class="h-0.5 w-4 border-t-2 border-dashed" style="border-color:var(--brand-700)"></span>Median</span>
            <span class="flex items-center gap-1.5"><span class="h-2.5 w-4 rounded-sm" style="background:var(--brand-500);opacity:.45"></span>50%</span>
            <span class="flex items-center gap-1.5"><span class="h-2.5 w-4 rounded-sm" style="background:var(--brand-500);opacity:.2"></span>90%</span></div></div>
        <div class="p-4 sm:p-6">${fanChart(d.history, d.bands)}</div></div>
      <div class="card overflow-hidden">
        <div class="card-head"><div class="t">${icon('bar-chart-3')} ARR in ${d.months} months</div><div class="s">distribution</div></div>
        <div class="p-4 sm:p-6">${arrHistogram(d.histogram, s.target_arr, s.start_arr)}
          <p class="mt-3 text-xs text-slate-500">Each bar counts simulated futures ending in that ARR range. Purple bars reach the target.</p></div></div>
    </div>
    <div class="grid gap-6 lg:grid-cols-3">
      <div class="card overflow-hidden lg:col-span-2">
        <div class="card-head"><div class="t">${icon('sparkles')} Insights</div><div class="s">Written from this run's numbers</div></div>
        <div class="grid gap-4 p-6 md:grid-cols-2">${d.insights.map(i => {
          const [ic, t] = INSIGHT_ICON[i.tone] || INSIGHT_ICON.slate;
          return `<div class="flex gap-3"><div class="stat-icon tone-${t} !mb-0 h-fit">${icon(ic)}</div>
            <div><div class="font-semibold text-sm">${esc(i.title)}</div><p class="mt-0.5 text-sm text-slate-600">${esc(i.body)}</p></div></div>`;
        }).join('')}</div></div>
      <div class="card overflow-hidden">
        <div class="card-head"><div class="t">${icon('cpu')} Model</div><div class="s">fitted ${fmtDate(d.as_of)} · ${ms} ms</div></div>
        <div class="space-y-2.5 p-6 text-sm">
          ${[['Months of history', m.months_of_history], ['Subscriptions learned from', m.subscriptions_seen],
             ['Monthly churn', `${(m.churn_mean * 100).toFixed(1)}% ± ${(m.churn_sd * 100).toFixed(1)}`],
             ['New deals / month', `${m.deals_per_month.toFixed(1)} (${m.deals_trend >= 0 ? '+' : ''}${m.deals_trend.toFixed(2)}/mo trend)`],
             ['Typical deal', `${money(m.median_deal_mrr)} MRR`], ['Deal sizes resampled', m.deals_sampled],
             ['Collection rate', `${(m.collection_rate * 100).toFixed(1)}%`], ['Largest customer', `${(m.top_customer_share * 100).toFixed(1)}% of MRR`],
             ['Futures simulated', d.sims.toLocaleString()], ['Random seed', d.seed]]
            .map(([k, v]) => `<div class="flex justify-between gap-3"><span class="text-slate-500">${k}</span><span class="text-right font-medium">${v}</span></div>`).join('')}
          <p class="border-t border-slate-100 pt-3 text-xs text-slate-500">Each future: churn drawn from a Beta distribution, new deals from a Poisson process with a damped trend,
            deal sizes resampled from real subscriptions, cash = MRR × collection rate.</p></div></div>
    </div>`;
}

// ---------- black box ----------
const BB_STYLE = {
  created: ['file-plus', 'brand'], quotation_sent: ['send', 'brand'], confirmed: ['check', 'brand'], activated: ['play', 'green'],
  self_service: ['user-plus', 'green'], terms_changed: ['pencil', 'brand'], reverted_to_draft: ['undo-2', 'brand'],
  paused: ['pause', 'amber'], resumed: ['play', 'green'], renewed: ['refresh-cw', 'green'], closed: ['square', 'red'],
  cancelled: ['x', 'red'], declined: ['x', 'red'], invoice_issued: ['file-text', 'blue'], invoice_confirmed: ['file-check', 'blue'],
  invoice_sent: ['mail', 'blue'], invoice_cancelled: ['file-x', 'red'], payment_received: ['banknote', 'green'],
  invoice_paid: ['badge-check', 'green'], reminder_sent: ['bell', 'amber'], outreach_sent: ['mail', 'brand'],
};
async function openBlackboxReport(id) {
  const html = await run(() => api(`/subscriptions/${id}/blackbox/report`, { raw: true }));
  const w = window.open('', '_blank');
  if (!w) return toast('Allow pop-ups to open the report', 'error');
  w.document.open(); w.document.write(html); w.document.close();
}
async function exportBlackbox(id, number) {
  const data = await run(() => api(`/subscriptions/${id}/blackbox`));
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: `${number}-blackbox.json` });
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}
async function loadBlackbox(sub) {
  const card = $('#bb-card');
  let d;
  try { d = await api(`/subscriptions/${sub.id}/blackbox`); } catch (e) { if (card) card.innerHTML = `<p class="p-4 text-sm text-red-700">${esc(e.message)}</p>`; return; }
  if (!$('#bb-card')) return;
  const v = d.verification;
  const recent = d.entries.slice().reverse();
  const show = 12;
  $('#bb-card').innerHTML = `
    <div class="card-head"><div class="t">${icon('box')} Black box</div>
      <span class="badge ${v.ok ? 'b-green' : 'b-red'} ml-auto">${icon(v.ok ? 'shield-check' : 'shield-alert', 'h-3.5 w-3.5')} ${v.ok ? `Verified · ${v.entries}` : `Broken at #${v.broken_at}`}</span></div>
    ${v.ok ? '' : `<div class="border-b border-slate-100 bg-rose-50 px-4 py-2 text-xs text-rose-700">${esc(v.reason)}. Entries after #${v.broken_at} can't be trusted.</div>`}
    <ol class="divide-y divide-slate-100 text-sm">${recent.slice(0, show).map(e => {
      const [ic, tone] = BB_STYLE[e.event_type] || ['circle', 'brand'];
      return `<li class="flex gap-3 px-4 py-2.5"><span class="stat-icon tone-${tone} !mb-0 !p-1.5 h-fit">${icon(ic, '!h-3.5 !w-3.5')}</span>
        <div class="min-w-0 flex-1"><div class="flex justify-between gap-2"><span class="font-medium">${esc(e.summary)}</span>
          ${e.amount != null ? `<span class="tabular-nums text-slate-600">${money(e.amount)}</span>` : ''}</div>
        <div class="text-xs text-slate-500">#${e.seq} · ${fmtDate(e.occurred_on)} · ${esc(e.actor_email)}${e.internal ? ' · internal' : ''}${e.data.reconstructed ? ' · reconstructed' : ''}
          <span class="font-mono" title="${e.hash}">· ${e.hash.slice(0, 8)}</span></div></div></li>`;
    }).join('') || '<li class="px-4 py-6 text-center text-slate-400">Nothing recorded yet.</li>'}</ol>
    ${recent.length > show ? `<div class="px-4 py-2 text-xs text-slate-500">+ ${recent.length - show} earlier events in the full report</div>` : ''}
    <div class="flex flex-wrap gap-2 border-t border-slate-100 bg-slate-50 px-4 py-3">
      <button class="btn btn-primary btn-sm" id="bb-report">${icon('file-text')} Flight recorder report</button>
      <button class="btn btn-light btn-sm" id="bb-json">${icon('download')} Export JSON</button></div>`;
  $('#bb-report').addEventListener('click', () => openBlackboxReport(sub.id));
  $('#bb-json').addEventListener('click', () => exportBlackbox(sub.id, sub.subscription_number));
}

// ---------- recommendations ----------
const REC_CATEGORY = { Collections: ['hand-coins', 'red'], Operations: ['settings-2', 'blue'], Renewals: ['refresh-cw', 'amber'],
  Retention: ['life-buoy', 'red'], Growth: ['rocket', 'green'], Sales: ['handshake', 'brand'], Pricing: ['tag', 'brand'] };
const PRIORITY_BADGE = { high: 'b-red', medium: 'b-amber', low: 'b-slate' };

function recCard(r, compact = false) {
  const [ic, tone] = REC_CATEGORY[r.category] || ['lightbulb', 'brand'];
  const act = r.action;
  const actBtn = !act ? '' : act.type === 'link'
    ? `<a class="btn btn-light btn-sm" href="${act.href}">${icon('arrow-right')} ${esc(act.label)}</a>`
    : `<button class="btn btn-primary btn-sm" data-rec-run="${r.key}">${icon(act.safe ? 'zap' : 'send')} ${esc(act.label)}</button>`;
  const items = r.items.map(it => `<tr${it.invoice_id ? ` class="clickable" data-inv="${it.invoice_id}"` : it.subscription_id ? ` class="clickable" data-sub="${it.subscription_id}"` : ''}>
      <td>${esc(it.label)}</td><td class="text-slate-500">${esc(it.note || '')}</td><td class="num">${it.value != null ? money(it.value) : ''}</td></tr>`).join('');
  return `<div class="card overflow-hidden ${r.dismissed ? 'opacity-60' : ''}">
    <div class="flex flex-wrap items-start gap-4 p-5">
      <div class="stat-icon tone-${tone} !mb-0">${icon(ic)}</div>
      <div class="min-w-[220px] flex-1">
        <div class="mb-1 flex flex-wrap items-center gap-2"><span class="badge ${PRIORITY_BADGE[r.priority]}">${r.priority}</span>
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-500">${esc(r.category)}</span>
          ${r.dismissed ? '<span class="badge b-slate">snoozed</span>' : ''}${act && act.safe ? '<span class="badge b-teal">autopilot</span>' : ''}</div>
        <div class="font-semibold text-ink">${esc(r.title)}</div>
        <p class="mt-1 text-sm text-slate-600">${esc(r.detail)}</p></div>
      ${r.impact ? `<div class="text-right"><div class="text-xl font-bold tabular-nums">${compact_(r.impact)}</div><div class="text-xs text-slate-500">${esc(r.impact_label)}</div></div>` : ''}
    </div>
    ${compact ? '' : `<details class="border-t border-slate-100"><summary class="cursor-pointer px-5 py-2.5 text-sm text-slate-500 hover:text-ink">
        ${r.item_count} record${r.item_count === 1 ? '' : 's'}${r.item_count > r.items.length ? ` (showing ${r.items.length})` : ''}</summary>
      <div class="overflow-x-auto"><table class="tbl"><tbody>${items}</tbody></table></div></details>`}
    <div class="flex flex-wrap items-center gap-2 border-t border-slate-100 bg-slate-50 px-5 py-3">${actBtn}
      ${compact ? '' : r.dismissed ? `<button class="btn btn-ghost btn-sm" data-rec-restore="${r.key}">Restore</button>`
        : `<button class="btn btn-ghost btn-sm" data-rec-dismiss="${r.key}">Snooze 30 days</button>`}</div></div>`;
}
const compact_ = v => (Math.abs(v) >= 1e6 ? '$' + (v / 1e6).toFixed(2) + 'M' : Math.abs(v) >= 1e4 ? '$' + Math.round(v / 1e3) + 'k' : money(v));

function wireRecs(root) {
  $$('[data-rec-run]', root).forEach(b => b.addEventListener('click', async () => {
    b.disabled = true;
    const r = await run(() => api(`/recommendations/${b.dataset.recRun}/run`, { method: 'POST' })).catch(() => null);
    if (r) { toast(r.summary); refresh(); } else b.disabled = false;
  }));
  $$('[data-rec-dismiss]', root).forEach(b => b.addEventListener('click', async () => {
    await run(() => api(`/recommendations/${b.dataset.recDismiss}/dismiss`, { method: 'POST' }), 'Snoozed for 30 days'); refresh();
  }));
  $$('[data-rec-restore]', root).forEach(b => b.addEventListener('click', async () => {
    await run(() => api(`/recommendations/${b.dataset.recRestore}/restore`, { method: 'POST' })); refresh();
  }));
  $$('[data-inv]', root).forEach(tr => tr.addEventListener('click', () => showInvoice(tr.dataset.inv)));
  $$('[data-sub]', root).forEach(tr => tr.addEventListener('click', () => { location.hash = '#/subscriptions/' + tr.dataset.sub; }));
}

async function viewRecommendations(main) {
  const data = await api('/recommendations');
  const open = data.items.filter(r => !r.dismissed);
  const snoozed = data.items.filter(r => r.dismissed);
  const byCat = {};
  open.forEach(r => { byCat[r.category] = (byCat[r.category] || 0) + 1; });
  const high = open.filter(r => r.priority === 'high').length;
  const safe = open.filter(r => r.action && r.action.safe).length;
  main.innerHTML = pageHeader('Recommendations',
    'Checked against live data every time you open this page: what to chase, who to renew, who to upsell and what\'s waiting. Act in one click, or let autopilot handle the routine ones.',
    isAdmin() ? `<button class="btn btn-primary" id="autopilot" ${safe ? '' : 'disabled'}>${icon('bot')} Run autopilot${safe ? ` (${safe})` : ''}</button>` : '',
    'Automation · Recommendations') + `
    <div class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      ${stat('lightbulb', 'Open recommendations', open.length, `${snoozed.length} snoozed`)}
      ${stat('flame', 'High priority', high, 'act on these first', high ? 'red' : 'green')}
      ${stat('bot', 'Autopilot-ready', safe, 'reminders, follow-ups, billing', 'blue')}
      ${stat('history', 'Automations run', data.activity.length, data.activity[0] ? `last: ${new Date(data.activity[0].created_at + 'Z').toLocaleString()}` : 'none yet', 'amber')}
    </div>
    <div class="grid gap-6 lg:grid-cols-3">
      <div class="space-y-4 lg:col-span-2" id="rec-list">
        ${Object.keys(byCat).length ? `<div class="flex flex-wrap gap-2">${Object.entries(byCat).map(([c, n]) => `<span class="badge b-slate">${esc(c)} · ${n}</span>`).join('')}</div>` : ''}
        ${open.map(r => recCard(r)).join('') || `<div class="card flex flex-col items-center px-6 py-14 text-center">
          <div class="stat-icon tone-green">${icon('check-circle-2')}</div><div class="font-semibold">All clear</div>
          <p class="mt-1 max-w-sm text-sm text-slate-600">Nothing needs attention right now. New recommendations appear as invoices age, contracts approach expiry and customers change.</p></div>`}
        ${snoozed.length ? `<details class="mt-2"><summary class="cursor-pointer text-sm text-slate-500">${snoozed.length} snoozed</summary>
          <div class="mt-4 space-y-4">${snoozed.map(r => recCard(r)).join('')}</div></details>` : ''}
      </div>
      <div class="card h-fit overflow-hidden">
        <div class="card-head"><div class="t">${icon('history')} Automation activity</div></div>
        <ol class="space-y-3 p-5 text-sm">${data.activity.map(a => `<li class="flex gap-3">
          <span class="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full ${a.autopilot ? 'tone-blue' : 'tone-brand'}">${icon(a.autopilot ? 'bot' : 'user', 'h-3.5 w-3.5')}</span>
          <div><div class="font-medium">${esc(a.summary)}</div><div class="text-xs text-slate-500">${new Date(a.created_at + 'Z').toLocaleString()} · ${a.autopilot ? 'autopilot' : esc(a.actor_email)}</div></div></li>`).join('')
          || '<li class="text-slate-400">Nothing has run yet.</li>'}</ol></div>
    </div>`;
  wireRecs(main);
  $('#autopilot')?.addEventListener('click', async e => {
    const b = e.target.closest('button'); b.disabled = true;
    b.innerHTML = '<span class="spinner !h-4 !w-4 !border-2"></span> Running…';
    const r = await run(() => api('/recommendations/autopilot', { method: 'POST' })).catch(() => null);
    if (r) toast(r.actions.length ? r.actions.map(a => a.summary).join(' · ') : 'Nothing needed doing', 'ok');
    refresh();
  });
}

// ---------- pause dialog ----------
function pauseDialog(sub) {
  const max = sub.max_pause_days;
  const iso = d => d.toISOString().slice(0, 10);
  const plus = n => { const d = new Date(); d.setDate(d.getDate() + n); return iso(d); };
  const presets = [[14, '2 weeks'], [30, '1 month'], [60, '2 months'], [90, '3 months']].filter(([n]) => !max || n <= max);
  formModal(`Pause ${sub.subscription_number}`, [
    { name: 'resume_on', label: 'Resume automatically on', type: 'date', value: max ? plus(Math.min(30, max)) : '', span: 'sm:col-span-2',
      help: max ? `This plan allows pauses of up to ${max} days.` : 'Leave empty to pause until someone resumes it.' },
    { name: 'reason', label: 'Reason (optional)', type: 'select', blank: '— none —', span: 'sm:col-span-2',
      options: ['Seasonal business', 'Budget freeze', 'Temporarily not using it', 'Switching tools', 'Other'].map(r => [r, r]) },
  ], async v => {
    await api(`/subscriptions/${sub.id}/actions/pause`, { method: 'POST', body: { resume_on: v.resume_on, reason: v.reason } });
    toast(v.resume_on ? `Paused. Billing resumes on ${fmtDate(v.resume_on)}` : 'Paused until resumed');
    refresh();
  }, {
    submitLabel: 'Pause subscription',
    extraHtml: `<div class="mt-4 flex flex-wrap gap-2">${presets.map(([n, l]) => `<button type="button" class="btn btn-light btn-sm" data-preset="${n}">${l}</button>`).join('')}
      ${max ? '' : '<button type="button" class="btn btn-light btn-sm" data-preset="0">Until resumed</button>'}</div>
      <p class="mt-4 text-sm text-slate-500">No invoices are issued while paused. When it resumes, billing restarts from that day, so the paused time is never charged.</p>`,
    afterRender: el => {
      const input = $('[name=resume_on]', el);
      input.min = plus(1); if (max) input.max = plus(max);
      $$('[data-preset]', el).forEach(b => b.addEventListener('click', () => { input.value = +b.dataset.preset ? plus(+b.dataset.preset) : ''; }));
    },
  });
}
function pauseBanner(s) {
  if (s.status !== 'paused') return '';
  return `<div class="mb-4 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-sm" style="border-color:var(--brand-100);background:var(--brand-50)">
    <span class="text-brand-700">${icon('pause-circle', 'h-5 w-5')}</span>
    <span><b>Paused</b>${s.paused_at ? ` since ${fmtDate(s.paused_at)}` : ''}${s.pause_reason ? ` · ${esc(s.pause_reason)}` : ''}</span>
    <span class="ml-auto font-medium">${s.resume_on ? `Resumes automatically on ${fmtDate(s.resume_on)}` : 'Paused until resumed'}</span></div>`;
}

// ---------- subscriptions ----------
const SUB_STATES = ['draft', 'quotation', 'confirmed', 'active', 'paused', 'closed'];
const ACTION_LABEL = {
  send_quotation: ['Send quotation', 'btn-primary'], revert_to_draft: ['Back to draft', 'btn-light'],
  confirm: ['Confirm', 'btn-primary'], activate: ['Activate', 'btn-teal'], pause: ['Pause', 'btn-light'],
  resume: ['Resume', 'btn-teal'], renew: ['Renew', 'btn-light'], close: ['Close', 'btn-danger'],
  cancel: ['Cancel', 'btn-danger'], decline: ['Decline quote', 'btn-danger'],
};
const CUSTOMER_LABEL = { confirm: 'Accept quotation' };

async function viewSubscriptions(main) {
  const f = S.subFilter;
  const [data, customers] = await Promise.all([api('/subscriptions?' + qs({ ...f, limit: PAGE })), getCustomers()]);
  const cust = customers.find(c => String(c.id) === String(f.customer_id));
  main.innerHTML = pageHeader('Subscriptions', 'Every contract and where it stands: Draft → Quotation → Confirmed → Active → Closed',
    `<button class="btn btn-light" id="verify-bb">${icon('shield-check')} Verify black boxes</button><button class="btn btn-light" id="from-tpl">From template</button><button class="btn btn-primary" id="new-sub">+ New subscription</button>`) + `
    <div class="card">
      <div class="flex flex-wrap items-center gap-2 px-3 pt-2 border-b">
        ${['', ...SUB_STATES].map(s => `<a class="tab ${f.status === s ? 'active' : ''}" data-st="${s}">${s ? label(s) : 'All'}</a>`).join('')}
        <form id="sf" class="ml-auto flex gap-2 pb-2">${cust ? `<span class="badge b-confirmed self-center">${esc(cust.company_name || cust.name)} <a class="cursor-pointer ml-1" id="clr-c">×</a></span>` : ''}
          <input class="input !w-60" name="q" placeholder="Search number or customer…" value="${esc(f.q)}"></form></div>
      <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Number</th><th>Customer</th><th>Plan</th><th>Status</th><th>Start</th><th>Expiry</th>
        <th>Next invoice</th><th class="num">Recurring</th></tr></thead><tbody>
        ${data.items.map(s => `<tr class="clickable" data-id="${s.id}"><td class="font-medium text-odoo">${s.subscription_number}</td>
          <td>${esc(s.customer_name)}</td><td>${esc(s.plan_name)}</td><td>${badge(s.status)}</td><td>${fmtDate(s.start_date)}</td>
          <td>${fmtDate(s.expiry_date)}</td><td>${s.status === 'paused' ? `<span class="text-slate-500">${s.resume_on ? 'resumes ' + fmtDate(s.resume_on) : 'paused'}</span>` : fmtDate(s.next_billing_date)}</td>
          <td class="num">${money(s.recurring_amount)}<span class="text-gray-400 text-xs"> /${FREQ[s.billing_frequency]}</span></td></tr>`).join('') || emptyRow(8)}
      </tbody></table></div>${pager(data.total, f.offset, o => { f.offset = o; refresh(); })}</div>`;
  $$('[data-st]').forEach(a => a.addEventListener('click', () => { f.status = a.dataset.st; f.offset = 0; refresh(); }));
  $('#sf').addEventListener('submit', e => { e.preventDefault(); f.q = e.target.q.value; f.offset = 0; refresh(); });
  $('#clr-c')?.addEventListener('click', () => { f.customer_id = ''; refresh(); });
  $$('[data-id]', main).forEach(tr => tr.addEventListener('click', () => { location.hash = '#/subscriptions/' + tr.dataset.id; }));
  $('#new-sub').addEventListener('click', () => subscriptionForm());
  $('#from-tpl').addEventListener('click', () => useTemplateDialog());
  $('#verify-bb').addEventListener('click', async () => {
    const r = await run(() => api('/blackbox/verify'));
    if (r.broken.length) toast(`${r.broken.length} recorder${r.broken.length === 1 ? '' : 's'} failed: ${r.broken.map(b => b.subscription_number).join(', ')}`, 'error');
    else toast(`All ${r.subscriptions} black boxes verified · ${r.entries.toLocaleString()} events intact`);
  });
}

async function subscriptionForm(sub) {
  const [customers, plans, products] = await Promise.all([getCustomers(), getPlans(), getProducts()]);
  const fields = [
    { name: 'customer_id', label: 'Customer', type: 'select', numeric: true, required: true, value: sub?.customer_id,
      options: customers.map(c => [c.id, `${c.company_name || c.name} (${c.email})`]) },
    { name: 'plan_id', label: 'Plan', type: 'select', numeric: true, required: true, value: sub?.plan_id,
      options: plans.filter(p => p.is_active).map(p => [p.id, `${p.name} — ${money(p.cost)}/${FREQ[p.billing_frequency]}`]) },
    { name: 'start_date', label: 'Start date', type: 'date', required: true, value: sub?.start_date || today() },
    { name: 'expiry_date', label: 'Expiry date', type: 'date', value: sub?.expiry_date, help: 'Leave empty for an open-ended subscription.' },
    { name: 'payment_terms', label: 'Payment terms', type: 'select', blank: false, value: sub?.payment_terms || 'net_30', options: TERMS },
    { name: 'notes', label: 'Notes', type: 'textarea', value: sub?.notes },
  ];
  if (sub) fields.splice(0, 2);
  formModal(sub ? `Edit ${sub.subscription_number}` : 'New subscription', fields, async (v, root) => {
    v.lines = readLines(root);
    const r = sub ? await api(`/subscriptions/${sub.id}`, { method: 'PATCH', body: v })
      : await api('/subscriptions', { method: 'POST', body: v });
    toast(sub ? 'Subscription updated' : `${r.subscription_number} created as draft`);
    location.hash = '#/subscriptions/' + r.id; if (sub) refresh();
  }, { wide: true, extraHtml: linesEditorHtml(products, sub?.lines || []), afterRender: el => wireLinesEditor(el, products) });
}

async function useTemplateDialog(templateId) {
  const [templates, customers] = await Promise.all([api('/templates'), getCustomers()]);
  formModal('Create quotation from template', [
    { name: 'template_id', label: 'Template', type: 'select', numeric: true, required: true, value: templateId, span: 'sm:col-span-2',
      options: templates.map(t => [t.id, `${t.name} · ${t.plan_name} · valid ${t.validity_days} days`]) },
    { name: 'customer_id', label: 'Customer', type: 'select', numeric: true, required: true,
      options: customers.map(c => [c.id, `${c.company_name || c.name} (${c.email})`]) },
    { name: 'start_date', label: 'Start date', type: 'date', value: today() },
  ], async v => {
    const r = await api(`/templates/${v.template_id}/use`, { method: 'POST', body: { customer_id: v.customer_id, start_date: v.start_date } });
    toast(`${r.subscription_number} created from template`);
    location.hash = '#/subscriptions/' + r.id;
  }, { submitLabel: 'Create' });
}

function pipeline(status) {
  const flow = ['draft', 'quotation', 'confirmed', 'active', 'closed'];
  const cur = status === 'paused' ? 3 : flow.indexOf(status);
  return `<div class="pipeline">${flow.map((s, i) => `<span class="${i < cur ? 'done' : i === cur ? 'current' : ''}">${i === 3 && status === 'paused' ? 'Paused' : label(s)}</span>`).join('')}</div>`;
}

function subActions(sub) {
  return sub.allowed_actions.map(a => {
    const [t, c] = ACTION_LABEL[a] || [a, 'btn-light'];
    return `<button class="btn ${c}" data-act="${a}">${S.user.role === 'customer' ? (CUSTOMER_LABEL[a] || t) : t}</button>`;
  }).join('');
}
async function doSubAction(sub, action) {
  if (action === 'pause') return pauseDialog(sub);
  const destructive = ['close', 'cancel', 'decline'].includes(action);
  if (destructive && !confirm(`${label(action)} ${sub.subscription_number}? This cannot be undone.`)) return;
  await run(() => api(`/subscriptions/${sub.id}/actions/${action}`, { method: 'POST' }), `${sub.subscription_number}: ${label(action)} done`);
  invalidate('customers');
  refresh();
}

async function viewSubscriptionDetail(main, id) {
  const [sub, invs] = await Promise.all([api('/subscriptions/' + id), api(`/invoices?subscription_id=${id}&limit=100`)]);
  const taxTotal = sub.lines.reduce((a, l) => a + l.tax_amount, 0);
  main.innerHTML = `<a href="#/subscriptions" class="text-sm text-odoo">← Subscriptions</a>
    <div class="flex flex-wrap items-center justify-between gap-3 mt-2 mb-4">
      <div><h1 class="text-2xl font-semibold">${sub.subscription_number} ${badge(sub.status)}</h1>
        <p class="text-sm text-gray-500">${esc(sub.customer_name)} · ${esc(sub.plan_name)}</p></div>
      <div class="flex flex-wrap gap-2">${subActions(sub)}
        ${['draft', 'quotation'].includes(sub.status) ? '<button class="btn btn-light" id="edit-sub">Edit</button>' : ''}
        ${sub.status === 'active' && sub.next_billing_date ? '<button class="btn btn-light" id="bill-now">Invoice next period now</button>' : ''}</div></div>
    <div class="card p-4 mb-4">${pipeline(sub.status)}</div>
    ${pauseBanner(sub)}
    <div class="grid lg:grid-cols-3 gap-4">
      <div class="lg:col-span-2 space-y-4">
        <div class="card"><div class="px-4 py-3 border-b font-semibold">Order lines</div><div class="overflow-x-auto"><table class="tbl">
          <thead><tr><th>Product</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Tax</th><th class="num">Amount</th></tr></thead>
          <tbody>${sub.lines.map(l => `<tr><td>${esc(l.product_name)}${l.variant_label ? `<div class="text-xs text-gray-500">${esc(l.variant_label)}</div>` : ''}</td>
            <td class="num">${l.quantity}</td><td class="num">${money(l.unit_price)}</td><td class="num">${l.tax_rate}%</td><td class="num">${money(l.amount)}</td></tr>`).join('')
            || emptyRow(5, `No lines: the plan price of ${money(sub.recurring_amount)} is billed.`)}</tbody>
          <tfoot><tr><td colspan="4" class="num text-gray-500">Untaxed / ${FREQ[sub.billing_frequency]}</td><td class="num font-semibold">${money(sub.recurring_amount)}</td></tr>
          <tr><td colspan="4" class="num text-gray-500">Estimated tax</td><td class="num">${money(taxTotal)}</td></tr></tfoot></table></div></div>
        <div class="card"><div class="px-4 py-3 border-b font-semibold">Invoices (${invs.total})</div><div class="overflow-x-auto"><table class="tbl">
          <thead><tr><th>Invoice</th><th>Period</th><th>Due</th><th>Status</th><th class="num">Total</th><th class="num">Balance</th></tr></thead>
          <tbody>${invs.items.map(i => `<tr class="clickable" data-inv="${i.id}"><td class="font-medium">${i.invoice_number}</td>
            <td>${fmtDate(i.period_start)} – ${fmtDate(i.period_end)}</td><td>${fmtDate(i.due_date)}</td>
            <td>${badge(i.status)} ${i.is_overdue ? badge('overdue') : ''}</td><td class="num">${money(i.total_amount)}</td><td class="num">${money(i.balance_due)}</td></tr>`).join('') || emptyRow(6, 'Not invoiced yet.')}</tbody></table></div></div></div>
      <div class="space-y-4">
        <div class="card p-4 text-sm space-y-2">${[
          ['Customer', `${esc(sub.customer_name)}<div class="text-xs text-gray-500">${esc(sub.customer_email)}</div>`],
          ['Plan', `${esc(sub.plan_name)} <span class="text-gray-500">(billed ${sub.billing_frequency})</span>`],
          ['Start date', fmtDate(sub.start_date)], ['Expiry date', fmtDate(sub.expiry_date)],
          ['Payment terms', label(sub.payment_terms)], ['Quotation valid until', fmtDate(sub.quotation_valid_until)],
          ['Renewal Lock', sub.price_lock_until && sub.price_lock_until >= today() ? `<span class="badge b-green">until ${fmtDate(sub.price_lock_until)}</span> <button class="text-xs text-red-600 underline" id="unlock">release</button>` : '—'],
          ['Last invoiced period', fmtDate(sub.last_billing_date)], ['Next invoice', fmtDate(sub.next_billing_date)],
        ].map(([k, v]) => `<div class="flex justify-between gap-4"><span class="text-gray-500">${k}</span><span class="text-right">${v}</span></div>`).join('')}
        ${sub.notes ? `<div class="pt-2 border-t text-gray-600">${esc(sub.notes)}</div>` : ''}</div>
        <div class="card overflow-hidden" id="bb-card"><div class="card-head"><div class="t">${icon('box')} Black box</div></div>
          <div class="flex justify-center py-8"><div class="spinner"></div></div></div></div></div>`;
  loadBlackbox(sub);
  $('#unlock')?.addEventListener('click', async () => {
    if (!confirm('Release this Renewal Lock? Deferred price changes will apply on the next billing run.')) return;
    await run(() => api(`/subscriptions/${sub.id}/renewal-lock`, { method: 'DELETE' }), 'Renewal Lock released'); refresh();
  });
  $$('[data-act]', main).forEach(b => b.addEventListener('click', () => doSubAction(sub, b.dataset.act)));
  $$('[data-inv]', main).forEach(tr => tr.addEventListener('click', () => showInvoice(tr.dataset.inv)));
  $('#edit-sub')?.addEventListener('click', () => subscriptionForm(sub));
  $('#bill-now')?.addEventListener('click', async () => {
    const r = await run(() => api(`/subscriptions/${sub.id}/bill-now`, { method: 'POST' }));
    toast(`${r.invoice_number} created`); refresh(); showInvoice(r.invoice_id);
  });
}

// ---------- quotation templates ----------
async function viewTemplates(main) {
  const templates = await api('/templates');
  main.innerHTML = pageHeader('Quotation templates', 'Ready-made offers with a plan and product lines; start a quote in one click.',
    '<button class="btn btn-primary" id="new-tpl">+ New template</button>') + `
    <div class="grid md:grid-cols-2 xl:grid-cols-3 gap-4">${templates.map(t => `<div class="card p-4 flex flex-col">
      <div class="flex justify-between items-start"><h3 class="font-semibold">${esc(t.name)}</h3><span class="badge b-confirmed">valid ${t.validity_days} days</span></div>
      <p class="text-sm text-gray-500 mt-1">${esc(t.plan_name)} · ${t.contract_months}-month contract · ${label(t.payment_terms)}</p>
      <ul class="text-sm mt-3 space-y-1 flex-1">${t.lines.map(l => `<li class="flex justify-between"><span>${l.quantity} × ${esc(l.product_name)}${l.variant_label ? ` <span class="text-gray-500">(${esc(l.variant_label)})</span>` : ''}</span>
        <span class="text-gray-500">${l.unit_price != null ? money(l.unit_price) : 'catalog'}</span></li>`).join('')}</ul>
      <div class="flex gap-2 mt-4"><button class="btn btn-primary btn-sm" data-use="${t.id}">Use for a customer</button>
        <button class="btn btn-light btn-sm" data-edit="${t.id}">Edit</button><button class="btn btn-danger btn-sm" data-del="${t.id}">Delete</button></div></div>`).join('')
      || '<div class="card p-10 text-center text-gray-400 md:col-span-3">No templates yet.</div>'}</div>`;
  $('#new-tpl').addEventListener('click', () => templateForm());
  $$('[data-use]').forEach(b => b.addEventListener('click', () => useTemplateDialog(Number(b.dataset.use))));
  $$('[data-edit]').forEach(b => b.addEventListener('click', () => templateForm(templates.find(t => t.id == b.dataset.edit))));
  $$('[data-del]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Delete this template? Subscriptions created from it are kept.')) return;
    await run(() => api('/templates/' + b.dataset.del, { method: 'DELETE' }), 'Template deleted'); refresh();
  }));
}
async function templateForm(t) {
  const [plans, products] = await Promise.all([getPlans(), getProducts()]);
  formModal(t ? 'Edit template' : 'New quotation template', [
    { name: 'name', label: 'Template name', required: true, value: t?.name, span: 'sm:col-span-2' },
    { name: 'plan_id', label: 'Plan', type: 'select', numeric: true, required: true, value: t?.plan_id,
      options: plans.map(p => [p.id, `${p.name} (${p.billing_frequency})`]) },
    { name: 'payment_terms', label: 'Payment terms', type: 'select', blank: false, value: t?.payment_terms || 'net_30', options: TERMS },
    { name: 'validity_days', label: 'Quotation valid for (days)', type: 'number', min: 1, required: true, value: t?.validity_days ?? 30 },
    { name: 'contract_months', label: 'Contract length (months)', type: 'number', min: 1, required: true, value: t?.contract_months ?? 12 },
    { name: 'notes', label: 'Notes', type: 'textarea', value: t?.notes, span: 'sm:col-span-2' },
  ], async (v, root) => {
    v.lines = readLines(root);
    await api(t ? '/templates/' + t.id : '/templates', { method: t ? 'PUT' : 'POST', body: v });
    toast('Template saved'); refresh();
  }, { wide: true, extraHtml: linesEditorHtml(products, t?.lines || []), afterRender: el => wireLinesEditor(el, products) });
}

// ---------- invoices ----------
async function viewInvoices(main) {
  const f = S.invFilter;
  const params = { q: f.q, offset: f.offset, limit: PAGE };
  if (f.status === 'overdue') params.overdue = true; else params.status = f.status;
  const data = await api('/invoices?' + qs(params));
  const tabs = [['', 'All'], ['draft', 'Draft'], ['outstanding', 'Outstanding'], ['overdue', 'Overdue'], ['paid', 'Paid'], ['cancelled', 'Cancelled']];
  main.innerHTML = pageHeader('Invoices', 'Created from subscriptions on billing day; nothing billed twice, nothing skipped.',
    `<button class="btn btn-primary" id="run-billing">${icon('play')} Run billing</button>`) + `
    <div class="card"><div class="flex flex-wrap items-center gap-2 px-3 pt-2 border-b">
      ${tabs.map(([k, t]) => `<a class="tab ${f.status === k ? 'active' : ''}" data-st="${k}">${t}</a>`).join('')}
      <form id="if" class="ml-auto pb-2"><input class="input !w-60" name="q" placeholder="Search number or customer…" value="${esc(f.q)}"></form></div>
      <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Invoice</th><th>Customer</th><th>Subscription</th><th>Issued</th><th>Due</th>
        <th>Status</th><th class="num">Total</th><th class="num">Balance</th></tr></thead><tbody>
      ${data.items.map(i => `<tr class="clickable" data-inv="${i.id}"><td class="font-medium text-odoo">${i.invoice_number}</td><td>${esc(i.customer_name)}</td>
        <td>${i.subscription_number}</td><td>${fmtDate(i.issue_date)}</td><td>${fmtDate(i.due_date)}</td>
        <td>${badge(i.status)} ${i.is_overdue ? `<span class="badge b-overdue">${i.days_overdue}d overdue</span>` : ''}${i.sent_at ? ' <span title="Sent" class="text-xs text-gray-400">✉</span>' : ''}</td>
        <td class="num">${money(i.total_amount)}</td><td class="num ${i.balance_due > 0 && i.status === 'confirmed' ? 'font-semibold' : 'text-gray-400'}">${money(i.balance_due)}</td></tr>`).join('') || emptyRow(8)}
      </tbody></table></div>${pager(data.total, f.offset, o => { f.offset = o; refresh(); })}</div>`;
  $$('[data-st]').forEach(a => a.addEventListener('click', () => { f.status = a.dataset.st; f.offset = 0; refresh(); }));
  $('#if').addEventListener('submit', e => { e.preventDefault(); f.q = e.target.q.value; f.offset = 0; refresh(); });
  $$('[data-inv]', main).forEach(tr => tr.addEventListener('click', () => showInvoice(tr.dataset.inv)));
  $('#run-billing').addEventListener('click', runBillingDialog);
}

async function showInvoice(id) {
  const inv = await run(() => api('/invoices/' + id));
  const staff = isStaff();
  const btns = [];
  if (staff && inv.status === 'draft') btns.push('<button class="btn btn-primary" data-ia="confirm">Confirm</button>');
  if (staff && inv.status === 'confirmed') btns.push('<button class="btn btn-teal" data-ia="pay">Register payment</button>');
  if (!staff && inv.status === 'confirmed') btns.push('<button class="btn btn-teal" data-ia="portal-pay">Pay now</button>');
  if (staff && ['draft', 'confirmed', 'paid'].includes(inv.status)) btns.push(`<button class="btn btn-light" data-ia="send">${inv.sent_at ? 'Resend' : 'Send'} by email</button>`);
  btns.push('<button class="btn btn-light" data-ia="print">Print / PDF</button>');
  if (staff && ['draft', 'confirmed'].includes(inv.status) && !inv.payments.length) btns.push('<button class="btn btn-danger" data-ia="cancel">Cancel invoice</button>');
  const m = openModal(`${inv.invoice_number} ${badge(inv.status)} ${inv.is_overdue ? `<span class="badge b-overdue">${inv.days_overdue} days overdue</span>` : ''}`, `
    <div class="grid sm:grid-cols-2 gap-4 text-sm mb-4">
      <div><div class="label">Billed to</div><b>${esc(inv.customer_name)}</b><div class="text-gray-500">${esc(inv.customer_email)}</div></div>
      <div class="sm:text-right"><div><span class="text-gray-500">Subscription</span> ${inv.subscription_number}</div>
        <div><span class="text-gray-500">Period</span> ${fmtDate(inv.period_start)} – ${fmtDate(inv.period_end)}</div>
        <div><span class="text-gray-500">Issued</span> ${fmtDate(inv.issue_date)} · <span class="text-gray-500">Due</span> ${fmtDate(inv.due_date)}</div>
        ${inv.sent_at ? `<div class="text-xs text-gray-500">Emailed ${new Date(inv.sent_at + 'Z').toLocaleString()}</div>` : ''}</div></div>
    <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Product</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Discount</th><th class="num">Tax</th><th class="num">Total</th></tr></thead>
      <tbody>${inv.lines.map(l => `<tr><td>${esc(l.product_name)}${l.variant_name ? `<div class="text-xs text-gray-500">${esc(l.variant_name)}</div>` : ''}</td>
        <td class="num">${l.quantity}</td><td class="num">${money(l.unit_price)}</td><td class="num">${l.line_discount ? '-' + money(l.line_discount) : '—'}</td>
        <td class="num">${money(l.line_tax)} <span class="text-xs text-gray-400">${l.tax_rate}%</span></td><td class="num">${money(l.line_total)}</td></tr>`).join('')}</tbody></table></div>
    <div class="flex justify-end mt-3"><table class="text-sm w-64">
      <tr><td class="text-gray-500 py-0.5">Subtotal</td><td class="num">${money(inv.subtotal)}</td></tr>
      ${inv.discount_amount ? `<tr><td class="text-gray-500 py-0.5">Discount <span class="badge b-confirmed">${esc(inv.discount_code)}</span></td><td class="num">-${money(inv.discount_amount)}</td></tr>` : ''}
      <tr><td class="text-gray-500 py-0.5">Tax</td><td class="num">${money(inv.tax_amount)}</td></tr>
      <tr class="border-t font-semibold"><td class="py-1">Total</td><td class="num">${money(inv.total_amount)}</td></tr>
      ${inv.payments.map(p => `<tr class="text-teal"><td class="py-0.5">Paid ${fmtDate(p.payment_date)} · ${methodName(p.payment_method)}</td><td class="num">-${money(p.amount)}</td></tr>`).join('')}
      <tr class="font-semibold"><td class="py-1">Balance due</td><td class="num">${money(inv.balance_due)}</td></tr></table></div>`,
    { wide: true, footer: btns.join('') });
  const done = msg => { toast(msg); m.close(); refresh(); };
  $$('[data-ia]', m.el).forEach(b => b.addEventListener('click', async () => {
    const a = b.dataset.ia;
    if (a === 'print') return printInvoice(inv.id);
    if (a === 'pay') { m.close(); return paymentForm(inv); }
    if (a === 'portal-pay') { m.close(); return portalPay(inv); }
    if (a === 'cancel' && !confirm(`Cancel ${inv.invoice_number}?`)) return;
    await run(() => api(`/invoices/${inv.id}/${a}`, { method: 'POST' }));
    done({ confirm: 'Invoice confirmed', send: `Emailed to ${inv.customer_email}`, cancel: 'Invoice cancelled' }[a]);
  }));
}
async function printInvoice(id) {
  const html = await run(() => api(`/invoices/${id}/print`, { raw: true }));
  const w = window.open('', '_blank');
  if (!w) return toast('Allow pop-ups to print invoices', 'error');
  w.document.open(); w.document.write(html); w.document.close();
}

// ---------- payments ----------
async function paymentForm(inv) {
  let options = [];
  if (!inv) {
    const open = await api('/invoices?status=outstanding&limit=500');
    if (!open.items.length) return toast('No outstanding invoices to pay', 'info');
    options = open.items.map(i => [i.id, `${i.invoice_number} · ${i.customer_name} · ${money(i.balance_due)} due`]);
  }
  const fields = [
    ...(inv ? [] : [{ name: 'invoice_id', label: 'Invoice', type: 'select', numeric: true, required: true, options, span: 'sm:col-span-2' }]),
    { name: 'amount', label: 'Amount', type: 'number', step: '0.01', min: 0.01, required: true, value: inv?.balance_due },
    { name: 'payment_method', label: 'Method', type: 'select', blank: false, value: 'bank_transfer', options: METHODS },
    { name: 'payment_date', label: 'Payment date', type: 'date', required: true, value: today() },
    { name: 'note', label: 'Note / reference', value: '' },
  ];
  formModal(inv ? `Register payment · ${inv.invoice_number}` : 'Record a payment', fields, async v => {
    if (inv) v.invoice_id = inv.id;
    const p = await api('/payments', { method: 'POST', body: v });
    toast(`${p.payment_number} recorded`); refresh();
  }, {
    submitLabel: 'Record payment',
    afterRender: el => {
      const sel = $('[name=invoice_id]', el);
      sel?.addEventListener('change', async () => {
        if (!sel.value) return;
        const i = await api('/invoices/' + sel.value); $('[name=amount]', el).value = i.balance_due;
      });
    },
  });
}
async function viewPayments(main) {
  const data = await api('/payments?limit=200');
  main.innerHTML = pageHeader('Payments', 'Every payment, by method, matched to its invoice.',
    '<button class="btn btn-primary" id="new-pay">+ Record payment</button>') + paymentsTable(data, true);
  $('#new-pay').addEventListener('click', () => paymentForm());
  $$('[data-inv]', main).forEach(tr => tr.addEventListener('click', () => showInvoice(tr.dataset.inv)));
}
function paymentsTable(data, showCustomer) {
  return `<div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Payment</th><th>Date</th>${showCustomer ? '<th>Customer</th>' : ''}<th>Invoice</th>
    <th>Method</th><th>Note</th><th class="num">Amount</th></tr></thead><tbody>
    ${data.items.map(p => `<tr class="clickable" data-inv="${p.invoice_id}"><td class="font-medium">${p.payment_number}</td><td>${fmtDate(p.payment_date)}</td>
      ${showCustomer ? `<td>${esc(p.customer_name)}</td>` : ''}<td>${p.invoice_number}</td><td>${methodName(p.payment_method)}</td>
      <td class="text-gray-500">${esc(p.note || '')}</td><td class="num font-semibold text-teal">${money(p.amount)}</td></tr>`).join('') || emptyRow(7)}
    </tbody></table>${data.total > data.items.length ? `<p class="text-xs text-gray-500 p-3">Showing latest ${data.items.length} of ${data.total}.</p>` : ''}</div>`;
}

// ---------- customers ----------
async function viewCustomers(main) {
  const customers = await getCustomers(true);
  main.innerHTML = pageHeader('Customers', `${customers.length} customer accounts`, '<button class="btn btn-primary" id="new-cust">+ New customer</button>') + `
    <div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Company</th><th>Contact</th><th>Email</th><th>Phone</th><th>Location</th><th>GSTIN</th><th>Since</th><th></th></tr></thead><tbody>
    ${customers.map(c => `<tr><td class="font-medium">${esc(c.company_name || '—')}</td><td>${esc(c.name)}</td><td>${esc(c.email)}</td><td>${esc(c.phone || '')}</td>
      <td>${esc([c.city, c.state].filter(Boolean).join(', ') || '—')}</td><td class="font-mono text-xs">${esc(c.tax_id || '—')}</td><td>${fmtDate(c.created_at)}</td><td class="text-right whitespace-nowrap"><button class="btn btn-light btn-sm" data-subs="${c.id}">Subscriptions</button>
      <button class="btn btn-light btn-sm" data-ed="${c.id}">Edit</button></td></tr>`).join('') || emptyRow(8)}</tbody></table></div>`;
  $('#new-cust').addEventListener('click', () => formModal('New customer account', [
    { name: 'company_name', label: 'Company' }, { name: 'name', label: 'Contact name', required: true },
    { name: 'email', label: 'Email', type: 'email', required: true }, { name: 'phone', label: 'Phone' },
    { name: 'password', label: 'Initial password', type: 'password', required: true, help: 'More than 8 chars, upper, lower and special. The customer can reset it by email.' },
  ], async v => { await api('/customers', { method: 'POST', body: v }); invalidate('customers'); toast('Customer created'); refresh(); }));
  $$('[data-subs]').forEach(b => b.addEventListener('click', () => {
    S.subFilter = { status: '', q: '', customer_id: b.dataset.subs, offset: 0 }; location.hash = '#/subscriptions';
  }));
  $$('[data-ed]').forEach(b => b.addEventListener('click', () => {
    const c = customers.find(x => x.id == b.dataset.ed);
    const sec = profileSections(c);
    const fields = [...sec.contact, ...sec.company, ...sec.address, ...sec.billing,
      { name: 'is_active', label: 'Account active', type: 'checkbox', value: c.is_active, span: 'sm:col-span-2' }];
    const group = (t, f) => `<div class="mb-2 mt-6 text-xs font-semibold uppercase tracking-wider text-slate-500">${t}</div>${formGrid(f)}`;
    const m = openModal(`Edit ${esc(c.company_name || c.name)}`, `<form id="ce">${group('Contact', sec.contact)}${group('Company', sec.company)}
      ${group('Billing address', sec.address)}${statesDatalist()}${group('Preferences', [...sec.billing, fields[fields.length - 1]])}</form>`,
      { wide: true, footer: '<button class="btn btn-light" data-close>Cancel</button><button class="btn btn-primary" id="ce-save">Save</button>' });
    $('#ce-save', m.el).addEventListener('click', async () => {
      if (!$('#ce', m.el).reportValidity()) return;
      await run(() => api('/users/' + c.id, { method: 'PATCH', body: readFields($('#ce', m.el), fields) }), 'Customer saved');
      m.close(); invalidate('customers'); refresh();
    });
  }));
}

// ---------- products ----------
async function viewProducts(main) {
  const [products, taxes] = await Promise.all([getProducts(true), getTaxes(true)]);
  const admin = isAdmin();
  main.innerHTML = pageHeader('Products', admin ? 'Catalog with variants; variant surcharges are added to the sales price.' : 'Read-only: only the admin can change the catalog.',
    admin ? '<button class="btn btn-primary" id="new-prod">+ New product</button>' : '') + `
    <div id="pc-card"></div>
    <div class="grid md:grid-cols-2 gap-4">${products.map(p => `<div class="card ${p.is_active ? '' : 'opacity-60'}">
      <div class="p-4 flex justify-between gap-3"><div><h3 class="font-semibold">${esc(p.name)} ${p.is_active ? '' : badge('closed', 'archived')}</h3>
        <p class="text-xs text-gray-500 capitalize">${p.product_type} · tax: ${esc(taxes.find(t => t.id === p.tax_rule_id)?.name || 'default')}</p>
        ${p.notes ? `<p class="text-sm text-gray-600 mt-1">${esc(p.notes)}</p>` : ''}</div>
        <div class="text-right shrink-0"><div class="text-lg font-semibold">${money(p.sales_price)}</div><div class="text-xs text-gray-500">cost ${money(p.cost_price)}</div></div></div>
      <div class="border-t"><table class="tbl"><thead><tr><th>Variant</th><th class="num">Surcharge</th><th class="num">Price</th>${admin ? '<th></th>' : ''}</tr></thead><tbody>
        ${p.variants.map(v => `<tr class="${v.is_active ? '' : 'opacity-50'}"><td>${esc(v.attribute_name)}: <b>${esc(v.variant_value)}</b></td><td class="num">+${money(v.surcharge)}</td>
          <td class="num font-medium">${money(v.effective_price)}</td>${admin ? `<td class="text-right"><button class="text-xs text-odoo" data-ev="${v.id}" data-p="${p.id}">edit</button></td>` : ''}</tr>`).join('')
          || `<tr><td colspan="4" class="text-gray-400 text-sm">No variants</td></tr>`}</tbody></table></div>
      ${admin ? `<div class="p-3 border-t flex gap-2"><button class="btn btn-light btn-sm" data-edp="${p.id}">Edit product</button>
        <button class="btn btn-light btn-sm" data-av="${p.id}">+ Variant</button>
        <button class="btn btn-light btn-sm" data-pc="${p.id}">${icon('trending-up')} Price change</button>
        ${p.is_active ? `<button class="btn btn-danger btn-sm ml-auto" data-arch="${p.id}">Archive</button>` : ''}</div>` : ''}</div>`).join('')}</div>`;
  if (!admin) return;
  const prodFields = p => [
    { name: 'name', label: 'Name', required: true, value: p?.name, span: 'sm:col-span-2' },
    { name: 'product_type', label: 'Type', type: 'select', blank: false, value: p?.product_type || 'software',
      options: [['software', 'Software'], ['addon', 'Add-on'], ['service', 'Service']] },
    { name: 'tax_rule_id', label: 'Tax rule', type: 'select', numeric: true, blank: 'System default', value: p?.tax_rule_id,
      options: taxes.map(t => [t.id, `${t.name} (${t.rate_percentage}%)`]) },
    { name: 'sales_price', label: 'Sales price', type: 'number', step: '0.01', min: 0, required: true, value: p?.sales_price },
    { name: 'cost_price', label: 'Cost price', type: 'number', step: '0.01', min: 0, value: p?.cost_price ?? 0 },
    { name: 'notes', label: 'Notes', type: 'textarea', value: p?.notes, span: 'sm:col-span-2' },
    { name: 'is_active', label: 'Active (available for sale)', type: 'checkbox', value: p ? p.is_active : true },
  ];
  const varFields = v => [
    { name: 'attribute_name', label: 'Attribute', required: true, value: v?.attribute_name || 'Brand', placeholder: 'e.g. Brand' },
    { name: 'variant_value', label: 'Value', required: true, value: v?.variant_value, placeholder: 'e.g. Odoo Brand Edition' },
    { name: 'surcharge', label: 'Extra price', type: 'number', step: '0.01', min: 0, value: v?.surcharge ?? 0 },
    { name: 'is_active', label: 'Active', type: 'checkbox', value: v ? v.is_active : true },
  ];
  const saved = msg => { invalidate('products'); toast(msg); refresh(); };
  priceChangesCard(products);
  $$('[data-pc]').forEach(b => b.addEventListener('click', () => priceChangeDialog(products.find(x => x.id == b.dataset.pc))));
  $('#new-prod').addEventListener('click', () => formModal('New product', prodFields(), async v => {
    await api('/products', { method: 'POST', body: v }); saved('Product created');
  }));
  $$('[data-edp]').forEach(b => b.addEventListener('click', () => {
    const p = products.find(x => x.id == b.dataset.edp);
    formModal('Edit product', prodFields(p), async v => { await api('/products/' + p.id, { method: 'PUT', body: v }); saved('Product saved'); });
  }));
  $$('[data-av]').forEach(b => b.addEventListener('click', () => formModal('Add variant', varFields(), async v => {
    await api(`/products/${b.dataset.av}/variants`, { method: 'POST', body: v }); saved('Variant added');
  })));
  $$('[data-ev]').forEach(b => b.addEventListener('click', () => {
    const v = products.find(x => x.id == b.dataset.p).variants.find(x => x.id == b.dataset.ev);
    formModal('Edit variant', varFields(v), async val => { await api('/variants/' + v.id, { method: 'PUT', body: val }); saved('Variant saved'); });
  }));
  $$('[data-arch]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Archive this product? Existing subscriptions keep it.')) return;
    await run(() => api('/products/' + b.dataset.arch, { method: 'DELETE' })); saved('Product archived');
  }));
}

// ---------- plans ----------
async function viewPlans(main) {
  const plans = await getPlans(true);
  const admin = isAdmin();
  const yes = b => b ? '<span class="text-teal">✓</span>' : '<span class="text-gray-300">—</span>';
  main.innerHTML = pageHeader('Plans', 'Price, billing frequency and lifecycle rules, decided plan by plan.',
    admin ? '<button class="btn btn-primary" id="new-plan">+ New plan</button>' : '') + `
    <div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Plan</th><th class="num">Price</th><th>Billing</th><th class="num">Min qty</th><th>Available</th>
      <th>Auto-close</th><th>Close early</th><th>Pause</th><th>Renew</th>${admin ? '<th></th>' : ''}</tr></thead><tbody>
    ${plans.map(p => `<tr class="${p.is_active ? '' : 'opacity-50'}"><td class="font-medium">${esc(p.name)}</td><td class="num">${money(p.cost)}</td><td class="capitalize">${p.billing_frequency}</td>
      <td class="num">${p.min_quantity}</td><td class="text-xs">${p.start_date || p.end_date ? `${fmtDate(p.start_date)} → ${fmtDate(p.end_date)}` : 'Always'}</td>
      <td>${yes(p.auto_close_on_expiry)}</td><td>${yes(p.allow_early_close)}</td><td>${p.allow_pause ? `${yes(true)}${p.max_pause_days ? ` <span class="text-xs text-slate-500">≤${p.max_pause_days}d</span>` : ''}` : yes(false)}</td><td>${yes(p.allow_renewal)}</td>
      ${admin ? `<td class="text-right"><button class="btn btn-light btn-sm" data-ed="${p.id}">Edit</button></td>` : ''}</tr>`).join('') || emptyRow(10)}</tbody></table></div>`;
  if (!admin) return;
  const fields = p => [
    { name: 'name', label: 'Plan name', required: true, value: p?.name, span: 'sm:col-span-2' },
    { name: 'cost', label: 'Price per period', type: 'number', step: '0.01', min: 0, required: true, value: p?.cost },
    { name: 'billing_frequency', label: 'Billing frequency', type: 'select', blank: false, value: p?.billing_frequency || 'monthly',
      options: [['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly'], ['yearly', 'Yearly']] },
    { name: 'min_quantity', label: 'Minimum quantity', type: 'number', min: 1, value: p?.min_quantity ?? 1 },
    { name: 'is_active', label: 'Active', type: 'checkbox', value: p ? p.is_active : true },
    { name: 'start_date', label: 'Available from', type: 'date', value: p?.start_date },
    { name: 'end_date', label: 'Available until', type: 'date', value: p?.end_date },
    { name: 'auto_close_on_expiry', label: 'Close automatically at expiry', type: 'checkbox', value: p ? p.auto_close_on_expiry : true },
    { name: 'allow_early_close', label: 'Can be closed early', type: 'checkbox', value: p ? p.allow_early_close : true },
    { name: 'allow_pause', label: 'Can be paused', type: 'checkbox', value: p ? p.allow_pause : false },
    { name: 'allow_renewal', label: 'Can be renewed', type: 'checkbox', value: p ? p.allow_renewal : true },
    { name: 'max_pause_days', label: 'Longest pause (days)', type: 'number', min: 1, nullable: true, value: p?.max_pause_days, help: 'Empty = no limit.' },
  ];
  const save = p => async v => { await api(p ? '/plans/' + p.id : '/plans', { method: p ? 'PUT' : 'POST', body: v }); invalidate('plans'); toast('Plan saved'); refresh(); };
  $('#new-plan').addEventListener('click', () => formModal('New plan', fields(), save()));
  $$('[data-ed]').forEach(b => b.addEventListener('click', () => { const p = plans.find(x => x.id == b.dataset.ed); formModal('Edit plan', fields(p), save(p)); }));
}

// ---------- taxes ----------
async function viewTaxes(main) {
  const taxes = await getTaxes(true);
  const admin = isAdmin();
  main.innerHTML = pageHeader('Tax rules', 'Applied automatically to every invoice line: the product\'s own rule, else the default.',
    admin ? '<button class="btn btn-primary" id="new-tax">+ New tax rule</button>' : '') + `
    <div class="card overflow-x-auto max-w-3xl"><table class="tbl"><thead><tr><th>Name</th><th class="num">Rate</th><th>Default</th><th>Active</th>${admin ? '<th></th>' : ''}</tr></thead><tbody>
    ${taxes.map(t => `<tr><td class="font-medium">${esc(t.name)}</td><td class="num">${t.rate_percentage}%</td><td>${t.is_default ? badge('active', 'default') : ''}</td>
      <td>${t.is_active ? '✓' : '—'}</td>${admin ? `<td class="text-right"><button class="btn btn-light btn-sm" data-ed="${t.id}">Edit</button></td>` : ''}</tr>`).join('') || emptyRow(5)}</tbody></table></div>`;
  if (!admin) return;
  const fields = t => [
    { name: 'name', label: 'Name', required: true, value: t?.name }, { name: 'rate_percentage', label: 'Rate (%)', type: 'number', step: '0.01', min: 0, required: true, value: t?.rate_percentage },
    { name: 'is_default', label: 'Default for products without a rule', type: 'checkbox', value: t?.is_default }, { name: 'is_active', label: 'Active', type: 'checkbox', value: t ? t.is_active : true },
  ];
  const save = t => async v => { await api(t ? '/taxes/' + t.id : '/taxes', { method: t ? 'PUT' : 'POST', body: v }); invalidate('taxes'); toast('Tax rule saved'); refresh(); };
  $('#new-tax').addEventListener('click', () => formModal('New tax rule', fields(), save()));
  $$('[data-ed]').forEach(b => b.addEventListener('click', () => { const t = taxes.find(x => x.id == b.dataset.ed); formModal('Edit tax rule', fields(t), save(t)); }));
}

// ---------- discounts ----------
async function viewDiscounts(main) {
  const [rules, products] = await Promise.all([api('/discounts'), getProducts()]);
  const admin = isAdmin();
  const now = today();
  const state = r => !r.is_active ? badge('closed', 'inactive') : (r.max_uses && r.current_uses >= r.max_uses) ? badge('closed', 'used up')
    : (r.end_date && r.end_date < now) ? badge('closed', 'expired') : (r.start_date && r.start_date > now) ? badge('quotation', 'scheduled') : badge('active', 'live');
  main.innerHTML = pageHeader('Discount rules', 'Applied to the next invoice automatically (best eligible rule wins); stop on expiry or when used up.',
    admin ? '<button class="btn btn-primary" id="new-disc">+ New discount</button>' : '') + `
    <div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Code</th><th>Discount</th><th>Applies to</th><th>Conditions</th><th>Window</th><th>Uses</th><th>State</th>${admin ? '<th></th>' : ''}</tr></thead><tbody>
    ${rules.map(r => `<tr><td><b>${esc(r.code)}</b><div class="text-xs text-gray-500">${esc(r.description || '')}</div></td>
      <td>${r.discount_type === 'percentage' ? r.value + '%' : money(r.value)}</td>
      <td>${r.target_type === 'product' ? esc(products.find(p => p.id === r.product_id)?.name || 'product') : r.subscription_id ? 'Subscription #' + r.subscription_id : 'Any subscription'}</td>
      <td class="text-xs">${r.min_purchase ? `min ${money(r.min_purchase)}` : ''} ${r.min_quantity ? `min qty ${r.min_quantity}` : ''}${!r.min_purchase && !r.min_quantity ? '—' : ''}</td>
      <td class="text-xs">${r.start_date || r.end_date ? `${fmtDate(r.start_date)} → ${fmtDate(r.end_date)}` : 'Always'}</td>
      <td>${r.current_uses}${r.max_uses ? ' / ' + r.max_uses : ''}</td><td>${state(r)}</td>
      ${admin ? `<td class="text-right"><button class="btn btn-light btn-sm" data-ed="${r.id}">Edit</button></td>` : ''}</tr>`).join('') || emptyRow(8)}</tbody></table></div>`;
  if (!admin) return;
  const fields = r => [
    { name: 'code', label: 'Code', required: true, value: r?.code }, { name: 'description', label: 'Description', value: r?.description },
    { name: 'discount_type', label: 'Type', type: 'select', blank: false, value: r?.discount_type || 'percentage', options: [['percentage', 'Percentage'], ['fixed', 'Fixed amount']] },
    { name: 'value', label: 'Value', type: 'number', step: '0.01', min: 0.01, required: true, value: r?.value },
    { name: 'target_type', label: 'Applies to', type: 'select', blank: false, value: r?.target_type || 'subscription', options: [['subscription', 'Whole subscription'], ['product', 'Specific product']] },
    { name: 'product_id', label: 'Product (if specific)', type: 'select', numeric: true, value: r?.product_id, options: products.map(p => [p.id, p.name]) },
    { name: 'subscription_id', label: 'Only subscription ID (optional)', type: 'number', nullable: true, value: r?.subscription_id, help: 'Empty = every subscription.' },
    { name: 'min_purchase', label: 'Minimum purchase', type: 'number', step: '0.01', min: 0, value: r?.min_purchase ?? 0 },
    { name: 'min_quantity', label: 'Minimum quantity', type: 'number', min: 0, value: r?.min_quantity ?? 0 },
    { name: 'max_uses', label: 'Max uses', type: 'number', min: 1, nullable: true, value: r?.max_uses, help: 'Empty = unlimited.' },
    { name: 'start_date', label: 'Starts', type: 'date', value: r?.start_date }, { name: 'end_date', label: 'Ends', type: 'date', value: r?.end_date },
    { name: 'is_active', label: 'Active', type: 'checkbox', value: r ? r.is_active : true },
  ];
  const save = r => async v => { await api(r ? '/discounts/' + r.id : '/discounts', { method: r ? 'PUT' : 'POST', body: v }); toast('Discount saved'); refresh(); };
  $('#new-disc').addEventListener('click', () => formModal('New discount rule', fields(), save()));
  $$('[data-ed]').forEach(b => b.addEventListener('click', () => { const r = rules.find(x => x.id == b.dataset.ed); formModal('Edit discount', fields(r), save(r)); }));
}

// ---------- admin: staff & outbox ----------
async function viewStaff(main) {
  const staff = await api('/staff');
  main.innerHTML = pageHeader('Internal team', 'Only the admin can add staff. Staff run day-to-day work; catalog, plans, taxes and discounts stay with the admin.',
    '<button class="btn btn-primary" id="new-staff">+ Add staff member</button>') + `
    <div class="card overflow-x-auto max-w-4xl"><table class="tbl"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>
    ${staff.map(u => `<tr><td class="font-medium">${esc(u.name)}</td><td>${esc(u.email)}</td><td>${badge(u.role)}</td><td>${u.is_active ? 'Active' : 'Disabled'}</td>
      <td class="text-right">${u.id !== S.user.id ? `<button class="btn btn-light btn-sm" data-tg="${u.id}" data-on="${u.is_active}">${u.is_active ? 'Disable' : 'Enable'}</button>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
  $('#new-staff').addEventListener('click', () => formModal('Add staff member', [
    { name: 'name', label: 'Name', required: true }, { name: 'email', label: 'Email', type: 'email', required: true },
    { name: 'phone', label: 'Phone' }, { name: 'password', label: 'Initial password', type: 'password', required: true, help: 'More than 8 chars, upper, lower and special.' },
  ], async v => { await api('/staff', { method: 'POST', body: v }); toast('Staff member added'); refresh(); }));
  $$('[data-tg]').forEach(b => b.addEventListener('click', async () => {
    await run(() => api('/users/' + b.dataset.tg, { method: 'PATCH', body: { is_active: b.dataset.on !== 'true' } }), 'Updated'); refresh();
  }));
}
async function viewOutbox(main) {
  const mails = await api('/emails?limit=100');
  main.innerHTML = pageHeader('Email outbox', 'Everything the system has emailed. Set SMTP_HOST to deliver for real.') +
    `<div class="space-y-3">${mails.map(m => `<details class="card p-4"><summary class="cursor-pointer flex flex-wrap gap-x-3 items-center">
      <b>${esc(m.subject)}</b><span class="text-sm text-gray-500">to ${esc(m.to_email)}</span>
      <span class="text-xs text-gray-400 ml-auto">${new Date(m.created_at + 'Z').toLocaleString()} · ${m.delivered ? 'delivered' : 'logged only'}</span></summary>
      <pre class="whitespace-pre-wrap text-sm mt-3 text-gray-700 font-sans">${esc(m.body).replace(/(https?:\/\/\S+)/g, '<a class="text-odoo underline break-all" href="$1" target="_blank">$1</a>')}</pre></details>`).join('')
      || '<div class="card p-10 text-center text-gray-400">No emails yet.</div>'}</div>`;
}


async function viewSettings(main) {
  const s = await api('/settings/mail');
  main.innerHTML = pageHeader('Mail Settings', 'Configure dynamic email routing, dummy mail redirection, and live SMTP test delivery.', '', 'Admin \u2022 Mail Settings') + `
    <div class="grid gap-6 max-w-4xl">
      <div class="card p-6">
        <div class="flex items-center justify-between border-b pb-4 mb-4">
          <div>
            <h3 class="font-semibold text-lg text-slate-900">SMTP Server Status</h3>
            <p class="text-sm text-slate-500">Live outgoing email transport configuration</p>
          </div>
          <span class="badge ${s.smtp_configured ? 'b-emerald' : 'b-amber'} font-medium">
            ${s.smtp_configured ? 'Active & Configured' : 'Offline Mode (Outbox Only)'}
          </span>
        </div>
        <div class="grid sm:grid-cols-2 gap-4 text-sm">
          <div><span class="text-slate-500">Host:</span> <code class="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded">${esc(s.smtp_host)}</code></div>
          <div><span class="text-slate-500">Port:</span> <code class="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded">${esc(s.smtp_port)}</code></div>
          <div><span class="text-slate-500">Sender Address:</span> <code class="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded">${esc(s.smtp_from)}</code></div>
          <div><span class="text-slate-500">Security:</span> <span class="text-slate-700">TLS Enabled</span></div>
        </div>
      </div>

      <div class="card p-6">
        <h3 class="font-semibold text-lg text-slate-900 mb-1">Dummy Email Redirection</h3>
        <p class="text-sm text-slate-500 mb-4">Route all emails generated for dummy accounts (Acme, Globex, etc.) to your real inbox so you receive all invoices, reminders, and notices without fake address bounces.</p>
        <form id="mail-routing-form" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-slate-700 mb-1">Target / Real Email Address</label>
            <input type="email" name="target_email" value="${esc(s.target_email || '')}" required class="input max-w-md w-full" placeholder="you@domain.com">
            <p class="text-xs text-slate-400 mt-1">All simulated customer emails will forward to this inbox.</p>
          </div>
          <div class="flex items-center gap-2">
            <input type="checkbox" id="redirect_dummy" name="redirect_dummy" ${s.redirect_dummy ? 'checked' : ''} class="rounded text-brand focus:ring-brand">
            <label for="redirect_dummy" class="text-sm font-medium text-slate-700">Enable automatic dummy email redirection</label>
          </div>
          <div class="flex gap-3 pt-2">
            <button type="submit" class="btn btn-primary">Save Routing Preferences</button>
            <button type="button" id="btn-update-customers" class="btn btn-light">Apply to All Customer Accounts</button>
          </div>
        </form>
      </div>

      <div class="card p-6">
        <h3 class="font-semibold text-lg text-slate-900 mb-1">Diagnostic Dispatch</h3>
        <p class="text-sm text-slate-500 mb-4">Send a live test email through the server's SMTP pipeline right now.</p>
        <form id="mail-test-form" class="flex flex-wrap gap-3 items-end">
          <div class="flex-1 min-w-[240px]">
            <label class="block text-sm font-medium text-slate-700 mb-1">Recipient</label>
            <input type="email" name="test_to" value="${esc(s.target_email || '')}" required class="input w-full" placeholder="recipient@example.com">
          </div>
          <button type="submit" class="btn btn-brand">Send Test Email</button>
        </form>
      </div>
    </div>
  `;

  $('#mail-routing-form').addEventListener('submit', async e => {
    e.preventDefault();
    const target_email = e.target.target_email.value.trim();
    const redirect_dummy = e.target.redirect_dummy.checked;
    await api('/settings/mail', { method: 'POST', body: { target_email, redirect_dummy } });
    toast('Mail settings saved successfully');
    viewSettings(main);
  });

  $('#btn-update-customers').addEventListener('click', async () => {
    const target_email = $('#mail-routing-form').target_email.value.trim();
    if (!target_email) return alert('Please enter a target email first');
    if (!confirm(`Update all customer accounts in the database to receive billing emails at ${target_email}?`)) return;
    const r = await api('/settings/update-customer-emails', { method: 'POST', body: { target_email } });
    toast(r.message);
  });

  $('#mail-test-form').addEventListener('submit', async e => {
    e.preventDefault();
    const to_email = e.target.test_to.value.trim();
    const r = await api('/emails/test', {
      method: 'POST',
      body: { to_email, subject: 'Brightloop Mail Diagnostic Check', body: 'This test confirms that your Brightloop transactional email pipeline is operating cleanly.' }
    });
    toast(r.delivered ? `Delivered to ${to_email} over SMTP!` : `Logged in outbox (SMTP offline)`);
  });
}

// ---------- customer window: timeline ----------
const TL_STYLE = {
  ...BB_STYLE, invoice_due: ['calendar-clock', 'blue'], contract_end: ['flag', 'amber'], lock_ends: ['lock-open', 'amber'],
  resumes: ['play', 'green'], quote_expires: ['hourglass', 'amber'], price_change: ['trending-up', 'red'],
  renewal_locked: ['lock', 'green'], renewal_unlocked: ['lock-open', 'amber'], price_change_notice: ['megaphone', 'amber'],
  price_changed: ['tag', 'brand'], price_change_cancelled: ['undo-2', 'green'], pass_reissued: ['qr-code', 'brand'],
};
async function viewTimeline(main) {
  S.tl = S.tl || { view: 'all', sub: '' };
  const t = await api('/portal/timeline?months=6');
  const subs = [...new Map(t.items.map(i => [i.subscription_id, i.subscription_number])).entries()];
  const past = t.items.filter(i => !i.future);
  main.innerHTML = pageHeader('Your timeline', 'Everything that has happened on your subscriptions, and what\'s coming in the next six months.', '', 'Customer window · Timeline') + `
    <div class="mb-6 grid gap-4 sm:grid-cols-3">
      ${stat('calendar-clock', 'Next payment', t.next_payment ? money(t.next_payment.amount) : '—', t.next_payment ? `${fmtDate(t.next_payment.date)} · ${t.next_payment.subscription_number}` : 'nothing scheduled', 'blue')}
      ${stat('wallet', 'Next 6 months', money(t.upcoming_total), 'estimated invoices incl. tax, before discounts')}
      ${stat('history', 'Events on record', past.length, `across ${subs.length} subscription${subs.length === 1 ? '' : 's'}`, 'green')}
    </div>
    <div class="card mb-6 flex flex-wrap items-center gap-2 p-3">
      ${[['all', 'Everything'], ['future', 'Coming up'], ['past', 'History']].map(([k, l]) => `<button class="btn btn-sm ${S.tl.view === k ? 'btn-primary' : 'btn-ghost'}" data-tlv="${k}">${l}</button>`).join('')}
      <select class="input ml-auto !w-56" id="tl-sub"><option value="">All subscriptions</option>
        ${subs.map(([id, n]) => `<option value="${id}" ${String(id) === S.tl.sub ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
    <div id="tl-body"></div>`;
  const draw = () => {
    const items = t.items.filter(i => (S.tl.view === 'all' || (S.tl.view === 'future') === i.future) && (!S.tl.sub || String(i.subscription_id) === S.tl.sub));
    let html = '', month = '', todayDone = false;
    for (const i of items) {
      if (!todayDone && i.future) {
        html += `<div id="tl-today" class="relative my-6 flex items-center gap-3"><span class="h-px flex-1 bg-brand-600"></span>
          <span class="badge b-teal">${icon('map-pin', 'h-3 w-3')} Today · ${fmtDate(t.today)}</span><span class="h-px flex-1 bg-brand-600"></span></div>`;
        todayDone = true;
      }
      const m = i.date.slice(0, 7);
      if (m !== month) {
        month = m;
        html += `<div class="mb-2 mt-6 text-xs font-bold uppercase tracking-widest text-slate-500">${new Date(m + '-01T00:00:00').toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })}</div>`;
      }
      const [ic, tone] = TL_STYLE[i.kind] || ['circle', 'brand'];
      html += `<div class="relative flex gap-4 pb-3 pl-1">
        <div class="flex flex-col items-center"><span class="stat-icon tone-${tone} !mb-0 !p-1.5 ${i.future ? 'ring-1 ring-dashed ring-slate-300' : ''}">${icon(ic, '!h-4 !w-4')}</span>
          <span class="mt-1 w-px flex-1 ${i.future ? 'border-l border-dashed border-slate-300' : 'bg-slate-200'}"></span></div>
        <div class="card mb-1 flex-1 px-4 py-3 ${i.future ? 'border-dashed' : ''}">
          <div class="flex flex-wrap justify-between gap-2"><span class="font-medium">${esc(i.title)}</span>
            ${i.amount != null ? `<span class="font-semibold tabular-nums ${i.kind === 'price_change' ? 'text-red-600' : ''}">${i.kind === 'price_change' && i.amount > 0 ? '+' : ''}${money(i.amount)}</span>` : ''}</div>
          <div class="text-xs text-slate-500">${fmtDate(i.date)} · ${i.subscription_number}${i.future ? ' · upcoming' : ''}</div></div></div>`;
    }
    $('#tl-body').innerHTML = html || '<div class="card p-10 text-center text-slate-400">Nothing to show for this filter.</div>';
    $('#tl-today')?.scrollIntoView({ block: 'center' });
  };
  $$('[data-tlv]').forEach(b => b.addEventListener('click', () => { S.tl.view = b.dataset.tlv; viewTimeline(main); }));
  $('#tl-sub').addEventListener('change', e => { S.tl.sub = e.target.value; draw(); });
  draw();
}

// ---------- customer window: Price Change Guardian + Renewal Lock ----------
function lockDialog(o) {
  openModal(`Renewal Lock · ${o.subscription_number}`, `
    <div class="flex gap-4"><div class="stat-icon tone-green !mb-0 h-fit">${icon('lock')}</div><div class="text-sm">
      <p class="font-semibold text-base">Lock today's price until ${fmtDate(o.lock_until)}</p>
      <p class="mt-2 text-slate-600">Your current ${money(o.recurring_amount)} per ${FREQ[o.frequency]} stays the same through your next renewal,
        even if Brightloop raises prices.${o.would_save ? ` On the changes already announced, that saves you about <b>${money(o.would_save)}</b>.` : ''}</p>
      <p class="mt-2 text-slate-600">In return you agree to keep the subscription until then: you won't be able to cancel early while the lock is on.
        Pausing still works if your plan allows it.</p></div></div>`,
    { footer: `<button class="btn btn-light" data-close>Not now</button><button class="btn btn-primary" id="do-lock">${icon('lock')} Lock my price</button>` });
  $('#do-lock').addEventListener('click', async () => {
    await run(() => api(`/subscriptions/${o.subscription_id}/renewal-lock`, { method: 'POST' }), `Price locked until ${fmtDate(o.lock_until)}`);
    document.querySelector('.modal-bg')?.remove(); refresh();
  });
}
async function viewGuardian(main) {
  const g = await api('/portal/guardian');
  const banner = {
    clear: ['shield-check', 'green', 'All clear', 'No price changes or discount endings ahead on your subscriptions.'],
    protected: ['shield-check', 'green', 'You\'re protected', 'Price changes have been announced, but your Renewal Lock keeps your current prices.'],
    attention: ['shield-alert', 'amber', 'Changes ahead', 'Something will change what you pay. Here\'s exactly what, when and by how much.'],
  }[g.status];
  const locks = g.locks;
  main.innerHTML = pageHeader('Price Change Guardian', 'We watch for anything that changes what you pay and tell you before it happens.', '', 'Customer window · Guardian') + `
    <div class="card mb-6 flex flex-wrap items-center gap-4 p-5">
      <div class="stat-icon tone-${banner[1]} !mb-0">${icon(banner[0])}</div>
      <div class="flex-1"><div class="text-lg font-semibold">${banner[2]}</div><div class="text-sm text-slate-600">${banner[3]}</div></div>
      ${g.yearly_exposure ? `<div class="text-right"><div class="text-2xl font-bold text-red-600 tabular-nums">+${money(g.yearly_exposure)}</div><div class="text-xs text-slate-500">a year if nothing changes</div></div>` : ''}
      ${g.yearly_protected ? `<div class="text-right"><div class="text-2xl font-bold text-teal tabular-nums">${money(g.yearly_protected)}</div><div class="text-xs text-slate-500">a year held off by your lock</div></div>` : ''}
    </div>
    <div class="grid gap-6 lg:grid-cols-3">
      <div class="space-y-6 lg:col-span-2">
        <div class="card overflow-hidden"><div class="card-head"><div class="t">${icon('megaphone')} Price changes ahead</div></div>
          ${g.changes.map(c => `<div class="flex flex-wrap items-center gap-4 border-b border-slate-100 p-5 last:border-0">
            <div class="min-w-[220px] flex-1"><div class="font-semibold">${esc(c.product)} <span class="text-sm font-normal text-slate-500">on ${c.subscription_number}</span></div>
              <div class="mt-1 text-sm"><span class="text-slate-500 line-through">${money(c.old_unit)}</span> → <b>${money(c.new_unit)}</b> per unit
                ${c.change_pct != null ? `<span class="badge ${c.change_pct > 0 ? 'b-red' : 'b-green'} ml-1">${c.change_pct > 0 ? '+' : ''}${c.change_pct}%</span>` : ''} · ${c.quantity} unit${c.quantity === 1 ? '' : 's'}</div>
              <div class="mt-1 text-xs text-slate-500">Announced ${fmtDate(c.announced_on)}${c.note ? ` · ${esc(c.note)}` : ''}</div></div>
            <div class="text-right"><div class="font-semibold tabular-nums ${c.per_month > 0 ? 'text-red-600' : 'text-teal'}">${c.per_month > 0 ? '+' : ''}${money(c.per_month)}/mo</div>
              <div class="text-xs text-slate-500">${c.per_year > 0 ? '+' : ''}${money(c.per_year)} a year</div></div>
            <div class="w-full sm:w-auto text-right">${c.deferred_by_lock
              ? `<span class="badge b-green">${icon('lock', 'h-3 w-3')} Locked until ${fmtDate(new Date(new Date(c.your_effective_on).getTime() - 864e5).toISOString().slice(0, 10))}</span>`
              : `<div class="text-sm font-medium">From ${fmtDate(c.your_effective_on)}</div><div class="text-xs text-slate-500">in ${c.days_until} days</div>
                 ${c.lock_would_save ? `<button class="btn btn-primary btn-sm mt-2" data-lock="${c.subscription_id}">${icon('lock')} Lock & save ${money(c.lock_would_save)}</button>` : ''}`}</div>
          </div>`).join('') || `<div class="p-6 text-sm text-slate-500">No price changes have been announced for anything you use.</div>`}</div>
        <div class="card overflow-hidden"><div class="card-head"><div class="t">${icon('receipt')} Your next invoices</div><div class="s">estimates incl. tax, before discounts</div></div>
          <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Subscription</th><th>Date</th><th class="num">Last invoice</th><th class="num">Next (est.)</th><th class="num">Change</th></tr></thead><tbody>
          ${g.forecasts.map(f => `<tr><td><b>${f.subscription_number}</b><div class="text-xs text-slate-500">${esc(f.plan)}</div></td><td>${fmtDate(f.on)}</td>
            <td class="num">${f.last_total != null ? money(f.last_total) : '—'}</td><td class="num font-semibold">${money(f.estimate)}</td>
            <td class="num ${f.change > 0.5 ? 'text-red-600' : f.change < -0.5 ? 'text-teal' : 'text-slate-500'}">${f.change == null ? '—' : (f.change > 0 ? '+' : '') + money(f.change)}</td></tr>`).join('') || emptyRow(5, 'No upcoming invoices.')}
          </tbody></table></div></div>
        ${g.alerts.length ? `<div class="card overflow-hidden"><div class="card-head"><div class="t">${icon('bell')} Watch list</div></div>
          <div class="space-y-4 p-5">${g.alerts.map(a => `<div class="flex gap-3"><div class="stat-icon tone-${a.tone} !mb-0 h-fit">${icon(a.tone === 'blue' ? 'info' : 'alert-circle')}</div>
            <div><div class="text-sm font-semibold">${esc(a.title)} <span class="font-normal text-slate-500">· ${a.subscription_number}</span></div><p class="text-sm text-slate-600">${esc(a.body)}</p></div></div>`).join('')}</div></div>` : ''}
      </div>
      <div class="card h-fit overflow-hidden"><div class="card-head"><div class="t">${icon('lock')} Renewal Lock</div></div>
        <div class="space-y-3 p-5">
          <p class="text-sm text-slate-600">Lock today's price through your next renewal. In exchange, you keep the subscription until then.</p>
          ${locks.map(o => `<div class="rounded-xl border border-slate-200 p-4">
            <div class="flex items-center justify-between"><b>${o.subscription_number}</b>${o.locked ? `<span class="badge b-green">${icon('lock', 'h-3 w-3')} Locked</span>` : ''}</div>
            <div class="text-xs text-slate-500">${esc(o.plan)} · ${money(o.recurring_amount)}/${FREQ[o.frequency]}</div>
            ${o.locked ? `<div class="mt-2 text-sm">Price fixed until <b>${fmtDate(o.locked_until)}</b></div>`
              : o.can_lock ? `<button class="btn btn-light btn-sm mt-3 w-full" data-lock="${o.subscription_id}">${icon('lock')} Lock until ${fmtDate(o.lock_until)}${o.would_save ? ` · save ${money(o.would_save)}` : ''}</button>`
              : `<div class="mt-2 text-xs text-slate-500">${esc(o.reason)}</div>`}</div>`).join('') || '<p class="text-sm text-slate-400">No active subscriptions.</p>'}
        </div></div>
    </div>`;
  $$('[data-lock]', main).forEach(b => b.addEventListener('click', () => lockDialog(locks.find(o => o.subscription_id == b.dataset.lock))));
}

// ---------- customer window: QR passes ----------
async function viewPasses(main) {
  const subs = (await api('/subscriptions?limit=200')).items.filter(s => ['active', 'paused', 'closed', 'confirmed'].includes(s.status));
  const passes = await Promise.all(subs.map(s => api(`/subscriptions/${s.id}/pass`)));
  const tone = { valid: 'linear-gradient(150deg,#8d5d80,#4a2f43 70%,#2a1826)', paused: 'linear-gradient(150deg,#b7893a,#5c4413)',
    pending: 'linear-gradient(150deg,#6b6f76,#2a2c30)', invalid: 'linear-gradient(150deg,#6b6f76,#2a2c30)' };
  main.innerHTML = pageHeader('Subscription passes', 'Show the QR code to prove your subscription is active. Scanning it opens a live check, with no prices or personal details.', '', 'Customer window · QR pass') + `
    <div class="grid gap-6 md:grid-cols-2 xl:grid-cols-3">${passes.map(p => `
      <div class="overflow-hidden rounded-3xl text-white shadow-xl" style="background:${tone[p.state]}">
        <div class="flex items-center justify-between px-6 pt-5"><span class="text-lg font-bold tracking-tight">brightloop<span class="opacity-60">.</span></span>
          <span class="rounded-full bg-white/15 px-3 py-1 text-xs font-semibold">${esc(p.label)}</span></div>
        <div class="px-6 pt-4"><div class="text-xs uppercase tracking-widest text-white/60">Subscription pass</div>
          <div class="mt-1 text-2xl font-semibold leading-tight">${esc(p.plan)}</div>
          <div class="mt-1 text-sm text-white/75">${esc(p.holder)}</div></div>
        <div class="grid grid-cols-3 gap-2 px-6 pt-4 text-xs">
          <div><div class="text-white/55 uppercase tracking-wider">Pass</div><div class="font-semibold">${p.subscription_number}</div></div>
          <div><div class="text-white/55 uppercase tracking-wider">Since</div><div class="font-semibold">${fmtDate(p.since)}</div></div>
          <div><div class="text-white/55 uppercase tracking-wider">${p.rolling ? 'Renews' : p.state === 'invalid' ? 'Ended' : 'Valid to'}</div><div class="font-semibold">${fmtDate(p.valid_through)}</div></div></div>
        ${p.price_locked_until ? `<div class="mx-6 mt-3 rounded-lg bg-white/10 px-3 py-1.5 text-xs">${icon('lock', 'h-3 w-3 inline')} Price locked until ${fmtDate(p.price_locked_until)}</div>` : ''}
        <div class="relative mx-6 my-5 border-t border-dashed border-white/30"></div>
        <div class="flex items-center gap-4 px-6 pb-6">
          <div class="qr shrink-0 rounded-xl bg-white p-2" style="width:132px;height:132px">${p.qr_svg}</div>
          <div class="min-w-0 space-y-2 text-sm">
            <a class="flex items-center gap-1.5 text-white/90 hover:text-white" href="${p.verify_url}" target="_blank" rel="noopener">${icon('external-link', 'h-4 w-4')} Open check page</a>
            <button class="flex items-center gap-1.5 text-white/90 hover:text-white" data-dl="${p.subscription_id}">${icon('download', 'h-4 w-4')} Download QR</button>
            <button class="flex items-center gap-1.5 text-white/90 hover:text-white" data-reissue="${p.subscription_id}">${icon('refresh-cw', 'h-4 w-4')} Reissue pass</button>
            <div class="text-[11px] text-white/50">v${p.version} · reissuing cancels older codes</div></div></div>
      </div>`).join('') || '<div class="card p-10 text-center text-slate-400 md:col-span-3">No subscriptions with a pass yet.</div>'}</div>`;
  $$('.qr svg', main).forEach(svg => { svg.setAttribute('width', '100%'); svg.setAttribute('height', '100%'); });
  $$('[data-dl]', main).forEach(b => b.addEventListener('click', () => {
    const p = passes.find(x => x.subscription_id == b.dataset.dl);
    const url = URL.createObjectURL(new Blob([p.qr_svg], { type: 'image/svg+xml' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: `${p.subscription_number}-pass.svg` });
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }));
  $$('[data-reissue]', main).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Reissue this pass? The old QR code will stop working.')) return;
    await run(() => api(`/subscriptions/${b.dataset.reissue}/pass/regenerate`, { method: 'POST' }), 'New pass issued; the old code no longer verifies');
    refresh();
  }));
}

// ---------- admin: price changes ----------
async function priceChangesCard(products) {
  const changes = await api('/price-changes');
  if (!$('#pc-card')) return;
  $('#pc-card').innerHTML = !changes.length ? '' : `<div class="card mb-6 overflow-hidden">
    <div class="card-head"><div class="t">${icon('megaphone')} Price changes</div><div class="s">customers are notified and see them in their Price Guardian</div></div>
    <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Product</th><th class="num">Old</th><th class="num">New</th><th>Effective</th><th>Customers</th><th>Status</th><th></th></tr></thead><tbody>
    ${changes.map(c => `<tr><td class="font-medium">${esc(c.product_name)}${c.note ? `<div class="text-xs text-slate-500">${esc(c.note)}</div>` : ''}</td>
      <td class="num">${money(c.old_price)}</td><td class="num font-semibold">${money(c.new_price)}</td><td>${fmtDate(c.effective_on)}</td>
      <td>${c.subscriptions} subscription${c.subscriptions === 1 ? '' : 's'}${c.deferred ? ` · <span class="text-teal">${c.deferred} locked</span>` : ''}</td>
      <td>${badge(c.status === 'scheduled' ? 'quotation' : c.status === 'applied' ? 'active' : 'closed', c.status)}</td>
      <td class="text-right">${c.status === 'scheduled' && isAdmin() ? `<button class="btn btn-danger btn-sm" data-pc-cancel="${c.id}">Cancel</button>` : ''}</td></tr>`).join('')}
    </tbody></table></div></div>`;
  $$('[data-pc-cancel]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Withdraw this price change? Affected customers keep their current price.')) return;
    await run(() => api(`/price-changes/${b.dataset.pcCancel}/cancel`, { method: 'POST' }), 'Price change cancelled'); refresh();
  }));
}
function priceChangeDialog(p) {
  const d = new Date(); d.setDate(d.getDate() + 30);
  formModal(`Schedule a price change · ${p.name}`, [
    { name: 'new_price', label: `New price (now ${money(p.sales_price)})`, type: 'number', step: '0.01', min: 0, required: true },
    { name: 'effective_on', label: 'Effective from', type: 'date', required: true, value: d.toISOString().slice(0, 10), help: '30 days\' notice is the default.' },
    { name: 'note', label: 'Reason shown to customers', span: 'sm:col-span-2', placeholder: 'e.g. Annual list price review' },
  ], async v => {
    const r = await api('/price-changes', { method: 'POST', body: { product_id: p.id, ...v } });
    toast(`Scheduled. ${r.subscriptions} subscription${r.subscriptions === 1 ? '' : 's'} notified${r.deferred ? `, ${r.deferred} protected by a Renewal Lock` : ''}`);
    invalidate('products'); refresh();
  }, { submitLabel: 'Schedule and notify customers',
       extraHtml: '<p class="mt-4 text-sm text-slate-500">Existing subscribers are emailed now and move to the new price on the effective date (negotiated prices change by the same percentage). Subscriptions with a Renewal Lock keep their price until the lock ends.</p>' });
}

// ---------- customer portal ----------
async function viewMySubscriptions(main) {
  const data = await api('/subscriptions?limit=200');
  main.innerHTML = pageHeader(`Hello, ${esc(S.user.name.split(' ')[0])}`, 'Your subscriptions. Manage them here, no email needed.',
    '<a href="#/subscribe" class="btn btn-primary">+ Subscribe to a plan</a>') +
    `<div class="grid lg:grid-cols-2 gap-4">${data.items.map(s => `<div class="card p-5" data-sid="${s.id}">
      <div class="flex justify-between items-start gap-3"><div><div class="text-xs text-gray-500">${s.subscription_number}</div>
        <h3 class="font-semibold text-lg">${esc(s.plan_name)}</h3></div><div class="flex flex-wrap justify-end gap-1">${badge(s.status)}
        ${s.price_lock_until && s.price_lock_until >= today() ? `<span class="badge b-green">${icon('lock', 'h-3 w-3')} Locked to ${fmtDate(s.price_lock_until)}</span>` : ''}</div></div>
      <div class="text-2xl font-semibold mt-2">${money(s.recurring_amount)}<span class="text-sm text-gray-500 font-normal"> + tax / ${FREQ[s.billing_frequency]}</span></div>
      <div class="grid grid-cols-3 gap-2 text-sm mt-3">
        <div><div class="label">Started</div>${fmtDate(s.start_date)}</div><div><div class="label">Expires</div>${fmtDate(s.expiry_date)}</div>
        <div><div class="label">${s.status === 'quotation' ? 'Quote valid until' : s.status === 'paused' ? 'Resumes' : 'Next invoice'}</div>${s.status === 'paused' ? (s.resume_on ? fmtDate(s.resume_on) : 'when you resume') : fmtDate(s.status === 'quotation' ? s.quotation_valid_until : s.next_billing_date)}</div></div>
      ${s.status === 'paused' ? `<div class="mt-3">${pauseBanner(s)}</div>` : ''}
      <div class="lines text-sm mt-3 text-gray-600"></div>
      <div class="flex flex-wrap gap-2 mt-4">${subActions(s)}
        <a class="btn btn-ghost" href="#/passes">${icon('qr-code')} QR pass</a>
        ${['active', 'paused'].includes(s.status) && !(s.price_lock_until && s.price_lock_until >= today()) ? `<a class="btn btn-ghost" href="#/guardian">${icon('lock')} Lock price</a>` : ''}
        <button class="btn btn-ghost" data-bb="${s.id}">${icon('box')} Billing record</button></div></div>`).join('')
      || '<div class="card p-10 text-center text-gray-400 lg:col-span-2">You have no subscriptions yet. <a class="text-odoo" href="#/subscribe">Browse plans →</a></div>'}</div>`;
  for (const s of data.items) {
    const card = $(`[data-sid="${s.id}"]`, main);
    $$('[data-act]', card).forEach(b => b.addEventListener('click', () => doSubAction(s, b.dataset.act)));
    $$('[data-bb]', card).forEach(b => b.addEventListener('click', () => openBlackboxReport(s.id)));
    api('/subscriptions/' + s.id).then(d => {
      $('.lines', card).innerHTML = d.lines.map(l => `<div class="flex justify-between"><span>${l.quantity} × ${esc(l.product_name)}${l.variant_label ? ` (${esc(l.variant_label)})` : ''}</span><span>${money(l.amount)}</span></div>`).join('');
    });
  }
}
async function viewMyInvoices(main) {
  const data = await api('/invoices?limit=200');
  const owed = data.items.filter(i => i.status === 'confirmed').reduce((a, i) => a + i.balance_due, 0);
  main.innerHTML = pageHeader('Invoices', owed ? `You owe ${money(owed)} in total.` : 'You are all paid up. Thank you!') + `
    <div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Invoice</th><th>Subscription</th><th>Period</th><th>Due</th><th>Status</th><th class="num">Total</th><th class="num">Balance</th><th></th></tr></thead><tbody>
    ${data.items.map(i => `<tr class="clickable" data-inv="${i.id}"><td class="font-medium text-odoo">${i.invoice_number}</td><td>${i.subscription_number}</td>
      <td>${fmtDate(i.period_start)} – ${fmtDate(i.period_end)}</td><td>${fmtDate(i.due_date)}</td>
      <td>${badge(i.status)} ${i.is_overdue ? badge('overdue') : ''}</td><td class="num">${money(i.total_amount)}</td><td class="num">${money(i.balance_due)}</td>
      <td class="text-right">${i.status === 'confirmed' ? `<button class="btn btn-teal btn-sm" data-pay="${i.id}">Pay</button>` : ''}</td></tr>`).join('') || emptyRow(8)}</tbody></table></div>`;
  $$('[data-pay]', main).forEach(b => b.addEventListener('click', e => { e.stopPropagation(); portalPay(data.items.find(i => i.id == b.dataset.pay)); }));
  $$('[data-inv]', main).forEach(tr => tr.addEventListener('click', () => showInvoice(tr.dataset.inv)));
}
function portalPay(inv) {
  formModal(`Pay ${inv.invoice_number}`, [
    { name: 'payment_method', label: 'Pay with', type: 'select', blank: false, value: 'card', options: METHODS.filter(m => m[0] !== 'cash'), span: 'sm:col-span-2' },
  ], async v => {
    await api(`/portal/invoices/${inv.id}/pay`, { method: 'POST', body: v });
    toast(`Payment of ${money(inv.balance_due)} received. Thank you!`); refresh();
  }, { submitLabel: `Pay ${money(inv.balance_due)}`,
       extraHtml: `<p class="text-sm text-gray-500 mt-4">Demo checkout: no real card is charged. The full balance of ${money(inv.balance_due)} is settled.</p>` });
}
async function viewMyPayments(main) {
  const data = await api('/payments?limit=200');
  main.innerHTML = pageHeader('Payments', 'Every payment we have received from you.') + paymentsTable(data, false);
  $$('[data-inv]', main).forEach(tr => tr.addEventListener('click', () => showInvoice(tr.dataset.inv)));
}
async function viewSubscribe(main) {
  const [plans, products] = await Promise.all([getPlans(), getProducts()]);
  main.innerHTML = pageHeader('Subscribe', 'Pick a plan, then the product it covers.') +
    `<div class="grid md:grid-cols-2 xl:grid-cols-4 gap-4">${plans.map(p => `<div class="card p-5 flex flex-col">
      <h3 class="font-semibold">${esc(p.name)}</h3><div class="text-sm text-gray-500 capitalize">Billed ${p.billing_frequency}</div>
      <ul class="text-sm text-gray-600 mt-3 space-y-1 flex-1"><li>Minimum ${p.min_quantity} unit${p.min_quantity > 1 ? 's' : ''}</li>
        <li>${p.allow_pause ? '✓ Pause any time' : '✗ Cannot be paused'}</li><li>${p.allow_early_close ? '✓ Cancel any time' : '✗ Fixed term'}</li>
        <li>${p.allow_renewal ? '✓ Renewable' : '✗ Not renewable'}</li></ul>
      <button class="btn btn-primary mt-4 justify-center" data-plan="${p.id}">Choose</button></div>`).join('')}</div>`;
  $$('[data-plan]').forEach(b => b.addEventListener('click', () => {
    const plan = plans.find(p => p.id == b.dataset.plan);
    const opts = productOptions(products);
    formModal(`Subscribe to ${plan.name}`, [
      { name: 'item', label: 'Product', type: 'select', required: true, options: opts, span: 'sm:col-span-2' },
      { name: 'quantity', label: 'Quantity', type: 'number', min: plan.min_quantity, required: true, value: plan.min_quantity },
    ], async v => {
      const [pid, vid] = v.item.split(':');
      const s = await api('/portal/subscribe', { method: 'POST', body: { plan_id: plan.id, product_id: Number(pid), variant_id: vid ? Number(vid) : null, quantity: v.quantity } });
      toast(`You're subscribed! ${s.subscription_number} is active.`); location.hash = '#/my-subscriptions';
    }, { submitLabel: 'Subscribe now', extraHtml: '<p class="text-xs text-gray-500 mt-4">Your subscription starts today; your first invoice is issued on the next billing run.</p>' });
  }));
}
// ---------- customer profile fields (shared by the portal profile and staff edit) ----------
const INDUSTRIES = ['Retail', 'Manufacturing', 'Healthcare', 'Education', 'Finance', 'Logistics', 'Hospitality', 'Technology',
  'Media', 'Construction', 'Agriculture', 'Professional services', 'Non-profit', 'Other'];
const SIZES = ['1-10', '11-50', '51-200', '201-1000', '1000+'];
const COUNTRIES = ['India', 'United States', 'United Kingdom', 'United Arab Emirates', 'Singapore', 'Australia', 'Canada', 'Germany', 'France', 'Other'];
const IN_STATES = ['Andhra Pradesh', 'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra',
  'Odisha', 'Puducherry', 'Punjab', 'Rajasthan', 'Tamil Nadu', 'Telangana', 'Uttar Pradesh', 'West Bengal'];
function profileSections(u) {
  return {
    contact: [
      { name: 'name', label: 'Full name', required: true, value: u.name },
      { name: 'job_title', label: 'Job title', value: u.job_title, placeholder: 'e.g. Head of Finance' },
      { name: 'phone', label: 'Phone', type: 'tel', value: u.phone, placeholder: '+91 98400 00000' },
      { name: 'billing_email', label: 'Billing email', type: 'email', value: u.billing_email, placeholder: u.email,
        help: 'Invoices, receipts and reminders go here. Leave empty to use your login email.' },
    ],
    company: [
      { name: 'company_name', label: 'Company name', value: u.company_name, span: 'sm:col-span-2' },
      { name: 'industry', label: 'Industry', type: 'select', blank: '— choose —', value: u.industry, options: INDUSTRIES.map(i => [i, i]) },
      { name: 'company_size', label: 'Company size', type: 'select', blank: '— choose —', value: u.company_size, options: SIZES.map(s => [s, `${s} people`]) },
      { name: 'website', label: 'Website', value: u.website, placeholder: 'example.com' },
      { name: 'tax_id', label: 'GSTIN / Tax ID', value: u.tax_id, placeholder: '33ABCDE1234F1Z5', help: 'Printed on your invoices.' },
    ],
    address: [
      { name: 'address_line1', label: 'Address line 1', value: u.address_line1, span: 'sm:col-span-2', placeholder: 'Building, street' },
      { name: 'address_line2', label: 'Address line 2', value: u.address_line2, span: 'sm:col-span-2', placeholder: 'Area, landmark (optional)' },
      { name: 'city', label: 'City', value: u.city },
      { name: 'state', label: 'State / region', value: u.state, list: 'states-list' },
      { name: 'postal_code', label: 'PIN / postal code', value: u.postal_code },
      { name: 'country', label: 'Country', type: 'select', blank: '— choose —', value: u.country, options: COUNTRIES.map(c => [c, c]) },
    ],
    billing: [
      { name: 'preferred_payment_method', label: 'Preferred payment method', type: 'select', blank: '— no preference —',
        value: u.preferred_payment_method, options: METHODS, span: 'sm:col-span-2' },
      { name: 'notify_offers', label: 'Send me offers and product news', type: 'checkbox', value: u.notify_offers !== false, span: 'sm:col-span-2' },
    ],
  };
}
const statesDatalist = () => `<datalist id="states-list">${IN_STATES.map(s => `<option value="${s}">`).join('')}</datalist>`;
function addressPreview(u) {
  const city = [u.city, u.postal_code].filter(Boolean).join(' ');
  const lines = [u.company_name || u.name, u.address_line1, u.address_line2, [city, u.state].filter(Boolean).join(', '), u.country].filter(Boolean);
  return lines.length > 1 ? lines.map(esc).join('<br>') + (u.tax_id ? `<br><span class="text-slate-500">GSTIN ${esc(u.tax_id)}</span>` : '')
    : '<span class="text-slate-400">Add your address to see how it appears on invoices.</span>';
}

async function viewProfile(main) {
  const [me, acct] = await Promise.all([api('/auth/me'), api('/portal/account')]);
  const sec = profileSections(me);
  const initials = me.name.split(' ').map(p => p[0]).slice(0, 2).join('').toUpperCase();
  const card = (id, ic, title, sub, body, extra = '') => `<form class="card overflow-hidden" id="${id}">
    <div class="card-head"><div class="t">${icon(ic)} ${title}</div>${sub ? `<div class="s">${sub}</div>` : ''}</div>
    <div class="p-6">${body}${extra}</div>
    <div class="flex justify-end border-t border-slate-100 bg-slate-50 px-6 py-3"><button class="btn btn-primary btn-sm">${icon('save')} Save</button></div></form>`;
  main.innerHTML = `
    <div class="card mb-6 overflow-hidden">
      <div class="h-20" style="background:linear-gradient(120deg, var(--brand-900), var(--brand-solid))"></div>
      <div class="flex flex-wrap items-end gap-5 px-6 pb-5">
        <div class="-mt-10 grid h-20 w-20 shrink-0 place-items-center rounded-2xl text-2xl font-bold text-white ring-4" style="background:var(--brand-solid);--tw-ring-color:var(--surface)">${esc(initials)}</div>
        <div class="min-w-[220px] flex-1 pt-3">
          <h1 class="text-2xl font-bold tracking-tight">${esc(me.name)}</h1>
          <div class="text-sm text-slate-600">${[me.job_title, me.company_name].filter(Boolean).map(esc).join(' · ') || 'Add your job title and company below'}</div>
          <div class="mt-2 flex flex-wrap gap-2 text-xs">
            <span class="badge normal-case b-slate">${acct.customer_id}</span><span class="badge normal-case b-slate">${icon('mail', 'h-3 w-3')} ${esc(me.email)}</span>
            <span class="badge normal-case b-slate">Customer since ${fmtDate(acct.member_since)}</span>
            ${me.tax_id ? `<span class="badge normal-case b-teal">GSTIN ${esc(me.tax_id)}</span>` : ''}</div></div>
        <div class="w-full sm:w-56"><div class="mb-1 flex justify-between text-xs"><span class="text-slate-500">Profile complete</span><b>${acct.profile_complete}%</b></div>
          <div class="progress"><div style="width:${acct.profile_complete}%"></div></div></div>
      </div></div>

    <div class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      ${stat('repeat', 'Active subscriptions', acct.active, `${acct.subscriptions} in total${acct.paused ? ` · ${acct.paused} paused` : ''}`)}
      ${stat('calendar-clock', 'Monthly spend', money(acct.monthly_spend), 'before tax, across active plans', 'blue')}
      ${stat('wallet', 'Paid to date', money(acct.lifetime_paid), acct.last_payment ? `last ${money(acct.last_payment.amount)} on ${fmtDate(acct.last_payment.date)}` : 'no payments yet', 'green')}
      ${stat('hourglass', 'Outstanding', money(acct.outstanding), acct.overdue ? `${money(acct.overdue)} overdue` : 'nothing overdue', acct.overdue ? 'red' : 'amber')}
    </div>

    <div class="grid gap-6 lg:grid-cols-2">
      ${card('pf-contact', 'user', 'Contact details', '', formGrid(sec.contact) + `<div class="mt-4 text-xs text-slate-500">Login email: <b>${esc(me.email)}</b> (used to sign in; contact us to change it)</div>`)}
      ${card('pf-company', 'building-2', 'Company', 'shown on invoices', formGrid(sec.company))}
      ${card('pf-address', 'map-pin', 'Billing address', '', formGrid(sec.address) + statesDatalist(),
        `<div class="mt-5 rounded-xl border border-dashed border-slate-300 p-4 text-sm"><div class="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">On your invoices</div><div id="addr-preview">${addressPreview(me)}</div></div>`)}
      ${card('pf-billing', 'credit-card', 'Billing preferences', '', formGrid(sec.billing),
        `<div class="mt-5 space-y-2 text-sm"><div class="text-xs font-semibold uppercase tracking-wider text-slate-500">Always sent</div>
          ${['Invoices and payment receipts', 'Payment reminders for overdue invoices', 'Price change notices (at least 30 days ahead)', 'Password reset links']
            .map(t => `<div class="flex items-center gap-2 text-slate-600">${icon('check-circle-2', 'h-4 w-4 text-teal')} ${t}</div>`).join('')}
          <p class="text-xs text-slate-500">These are part of your account, so they can't be switched off.</p></div>`)}
      <form id="cp" class="card overflow-hidden"><div class="card-head"><div class="t">${icon('key-round')} Change password</div></div>
        <div class="space-y-4 p-6">${field({ name: 'current_password', label: 'Current password', type: 'password', required: true })}
          <div>${field({ name: 'new_password', label: 'New password', type: 'password', required: true })}<p class="text-xs mt-1" id="pwh"></p></div></div>
        <div class="flex justify-end border-t border-slate-100 bg-slate-50 px-6 py-3"><button class="btn btn-primary btn-sm">${icon('key-round')} Change password</button></div></form>
      <div class="card h-fit overflow-hidden"><div class="card-head"><div class="t">${icon('shield')} Account</div></div>
        <div class="space-y-2.5 p-6 text-sm">${[['Customer ID', acct.customer_id], ['Account type', 'Customer'], ['Sign-in email', esc(me.email)],
          ['Customer since', fmtDate(acct.member_since)], ['Lifetime billed', money(acct.lifetime_billed)], ['Subscriptions', acct.subscriptions]]
          .map(([k, v]) => `<div class="flex justify-between gap-3"><span class="text-slate-500">${k}</span><span class="text-right font-medium">${v}</span></div>`).join('')}
          <div class="flex flex-wrap gap-2 pt-3"><a class="btn btn-light btn-sm" href="#/my-invoices">${icon('receipt')} Invoices</a>
            <a class="btn btn-light btn-sm" href="#/passes">${icon('qr-code')} QR passes</a><a class="btn btn-light btn-sm" href="#/timeline">${icon('history')} Timeline</a></div></div></div>
    </div>`;

  const wire = (id, fields) => $('#' + id).addEventListener('submit', async e => {
    e.preventDefault();
    if (!e.target.reportValidity()) return;
    const body = readFields(e.target, fields);
    const u = await run(() => api('/auth/me', { method: 'PATCH', body }), 'Saved');
    S.user = u; localStorage.setItem('bl_user', JSON.stringify(u)); refresh();
  });
  wire('pf-contact', sec.contact); wire('pf-company', sec.company); wire('pf-address', sec.address); wire('pf-billing', sec.billing);
  $('#pf-address').addEventListener('input', () => {
    const v = readFields($('#pf-address'), sec.address);
    $('#addr-preview').innerHTML = addressPreview({ ...me, ...Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x || ''])) });
  });
  pwHint($('[name=new_password]'), $('#pwh'));
  $('#cp').addEventListener('submit', async e => {
    e.preventDefault();
    await run(() => api('/auth/change-password', { method: 'POST', body: Object.fromEntries(new FormData(e.target)) }), 'Password changed');
    e.target.reset();
  });
}

render();
