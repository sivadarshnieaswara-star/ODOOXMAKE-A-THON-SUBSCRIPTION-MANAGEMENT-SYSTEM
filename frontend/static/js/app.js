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
  el.style.background = kind === 'error' ? '#b91c1c' : kind === 'info' ? '#374151' : '#017E84';
  el.textContent = msg;
  $('#toast').appendChild(el);
  setTimeout(() => el.remove(), kind === 'error' ? 6000 : 3500);
}
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
      ${f.step ? `step="${f.step}"` : ''} ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ''}>`;
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
  S.token = null; S.user = null; S.cache = {};
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

  $('#app').innerHTML = `<div class="min-h-screen grid lg:grid-cols-2">
    <div class="hidden lg:flex bg-odoo text-white p-12 flex-col justify-between">
      <div class="text-2xl font-bold tracking-tight">brightloop<span class="opacity-60">.</span></div>
      <div><h1 class="text-4xl font-semibold leading-tight">Plans, subscriptions and recurring billing in one place.</h1>
        <ul class="mt-8 space-y-3 text-white/85 text-sm">
          <li>✓ Quotation templates → subscriptions in one click</li><li>✓ Billing day runs itself: never billed twice, never skipped</li>
          <li>✓ Taxes and discounts applied automatically</li><li>✓ Live MRR, ARR, collections and overdue chase list</li></ul></div>
      <div class="text-xs text-white/60">Brightloop Software · Subscription Management System</div></div>
    <div class="flex items-center justify-center p-6"><div class="w-full max-w-md">
      <div class="lg:hidden text-2xl font-bold text-odoo mb-6">brightloop.</div>
      <h2 class="text-2xl font-semibold mb-1">${mode === 'reset' ? 'Reset password' : 'Welcome'}</h2>
      <p class="text-sm text-gray-500 mb-5">${mode === 'reset' ? '' : 'Sign in to your Brightloop account.'}</p>
      ${tabs}${body}</div></div></div>`;

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
const STAFF_NAV = [
  ['dashboard', 'Dashboard'], ['subscriptions', 'Subscriptions'], ['templates', 'Quotation templates'], ['invoices', 'Invoices'],
  ['payments', 'Payments'], ['customers', 'Customers'], ['products', 'Products'], ['plans', 'Plans'], ['taxes', 'Taxes'],
  ['discounts', 'Discounts'],
];
const ADMIN_NAV = [['staff', 'Staff'], ['outbox', 'Email outbox']];
const CUSTOMER_NAV = [['my-subscriptions', 'My subscriptions'], ['my-invoices', 'Invoices'], ['my-payments', 'Payments'],
  ['subscribe', 'Subscribe'], ['profile', 'Profile']];

function route() {
  const [name, id] = (location.hash.replace(/^#\/?/, '') || '').split('/');
  return { name: name || (isStaff() ? 'dashboard' : 'my-subscriptions'), id };
}

function renderShell() {
  const nav = isStaff() ? [...STAFF_NAV, ...(isAdmin() ? ADMIN_NAV : [])] : CUSTOMER_NAV;
  const r = route();
  $('#app').innerHTML = `
    <header class="bg-odoo text-white sticky top-0 z-40 shadow">
      <div class="max-w-[1400px] mx-auto px-4 flex items-center gap-4 h-14">
        <a href="#/" class="font-bold text-lg tracking-tight shrink-0">brightloop<span class="opacity-60">.</span>
          <span class="font-normal text-white/70 text-sm ml-1 hidden sm:inline">${isStaff() ? 'Subscriptions' : 'Customer portal'}</span></a>
        <nav class="flex gap-1 overflow-x-auto flex-1">${nav.map(([k, t]) =>
          `<a href="#/${k}" class="nav-link ${r.name === k ? 'active' : ''}">${t}</a>`).join('')}</nav>
        <div class="flex items-center gap-3 shrink-0">
          <div class="text-right leading-tight hidden md:block"><div class="text-sm font-medium">${esc(S.user.name)}</div>
            <div class="text-xs text-white/70">${esc(S.user.email)}</div></div>
          <span class="badge bg-white/20 text-white">${S.user.role}</span>
          <button class="btn btn-sm bg-white/10 text-white hover:bg-white/20" id="logout">Sign out</button></div></div></header>
    <main id="main" class="max-w-[1400px] mx-auto p-4 md:p-6"></main>`;
  $('#logout').addEventListener('click', logout);
}

const VIEWS = {
  dashboard: viewDashboard, subscriptions: viewSubscriptions, templates: viewTemplates, invoices: viewInvoices,
  payments: viewPayments, customers: viewCustomers, products: viewProducts, plans: viewPlans, taxes: viewTaxes,
  discounts: viewDiscounts, staff: viewStaff, outbox: viewOutbox,
  'my-subscriptions': viewMySubscriptions, 'my-invoices': viewMyInvoices, 'my-payments': viewMyPayments,
  subscribe: viewSubscribe, profile: viewProfile,
};
const CUSTOMER_VIEWS = new Set(CUSTOMER_NAV.map(n => n[0]));

async function render() {
  if (!S.token || !S.user) return renderAuth();
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

function pageHeader(title, sub, actions = '') {
  return `<div class="flex flex-wrap items-end justify-between gap-3 mb-5"><div><h1 class="text-2xl font-semibold">${title}</h1>
    ${sub ? `<p class="text-sm text-gray-500 mt-0.5">${sub}</p>` : ''}</div><div class="flex flex-wrap gap-2">${actions}</div></div>`;
}
function emptyRow(cols, text = 'Nothing here yet.') {
  return `<tr><td colspan="${cols}" class="text-center text-gray-400 py-10">${text}</td></tr>`;
}
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
  const W = 720, H = 220, P = 36, max = Math.max(1, ...trend.flatMap(t => [t.invoiced, t.collected]));
  const bw = (W - P * 2) / trend.length;
  const y = v => H - 24 - (v / max) * (H - 48);
  const bars = trend.map((t, i) => {
    const x = P + i * bw;
    const m = new Date(t.month + '-01T00:00:00').toLocaleDateString('en-GB', { month: 'short' });
    return `<rect x="${x + bw * .14}" y="${y(t.invoiced)}" width="${bw * .34}" height="${H - 24 - y(t.invoiced)}" fill="#c9b3c3" rx="2"><title>${m}: invoiced ${money(t.invoiced)}</title></rect>
      <rect x="${x + bw * .52}" y="${y(t.collected)}" width="${bw * .34}" height="${H - 24 - y(t.collected)}" fill="#017E84" rx="2"><title>${m}: collected ${money(t.collected)}</title></rect>
      <text x="${x + bw / 2}" y="${H - 6}" font-size="11" text-anchor="middle" fill="#6b7280">${m}</text>`;
  }).join('');
  const grid = [0, .5, 1].map(f => `<line x1="${P}" x2="${W - P}" y1="${y(max * f)}" y2="${y(max * f)}" stroke="#eee"/>
    <text x="${P - 6}" y="${y(max * f) + 4}" font-size="10" text-anchor="end" fill="#9ca3af">${max * f >= 1000 ? Math.round(max * f / 1000) + 'k' : Math.round(max * f)}</text>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" class="w-full h-auto">${grid}${bars}</svg>`;
}

async function viewDashboard(main) {
  const t0 = performance.now();
  const [s, overdue, plans, customers] = await Promise.all([
    api('/analytics/summary?' + qs(S.dash)), api('/analytics/overdue'), getPlans(), getCustomers()]);
  const ms = Math.round(performance.now() - t0);
  const kpi = (k, v, sub, color = '') => `<div class="card kpi"><div class="k">${k}</div><div class="v ${color}">${v}</div>
    <div class="text-xs text-gray-500 mt-1">${sub}</div></div>`;
  const statuses = ['draft', 'quotation', 'confirmed', 'active', 'paused', 'closed'];
  const totalSubs = statuses.reduce((a, k) => a + (s.subscriptions_by_status[k] || 0), 0) || 1;
  main.innerHTML = pageHeader('Finance overview', `Loaded in ${ms} ms · figures update live as invoices and payments are recorded`) + `
    <form id="df" class="card p-3 mb-5 flex flex-wrap items-end gap-3">
      <div><label class="label">From</label><input type="date" class="input" name="date_from" value="${S.dash.date_from}"></div>
      <div><label class="label">To</label><input type="date" class="input" name="date_to" value="${S.dash.date_to}"></div>
      <div class="min-w-[180px]"><label class="label">Plan</label><select class="input" name="plan_id"><option value="">All plans</option>
        ${plans.map(p => `<option value="${p.id}" ${String(p.id) === S.dash.plan_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>
      <div class="min-w-[200px]"><label class="label">Customer</label><select class="input" name="customer_id"><option value="">All customers</option>
        ${customers.map(c => `<option value="${c.id}" ${String(c.id) === S.dash.customer_id ? 'selected' : ''}>${esc(c.company_name || c.name)}</option>`).join('')}</select></div>
      <button class="btn btn-primary">Apply</button><button type="button" class="btn btn-light" id="dreset">Reset</button>
      <span class="text-xs text-gray-500 ml-auto">Date range applies to invoiced and collected amounts.</span></form>
    <div class="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-5">
      ${kpi('Active subscriptions', s.active_subscriptions.toLocaleString(), `${(s.subscriptions_by_status.paused || 0)} paused`)}
      ${kpi('MRR', money(s.mrr), 'Monthly recurring revenue', 'text-odoo')}
      ${kpi('ARR', money(s.arr), 'MRR × 12')}
      ${kpi('Collected', money(s.revenue_collected), `${s.payments_count} payments`, 'text-teal')}
      ${kpi('Outstanding', money(s.outstanding_amount), `${s.outstanding_count} open invoices`)}
      ${kpi('Overdue', money(s.overdue_amount), `${s.overdue_count} invoices past due`, s.overdue_count ? 'text-red-700' : '')}
    </div>
    <div class="grid lg:grid-cols-3 gap-4 mb-5">
      <div class="card p-4 lg:col-span-2"><div class="flex justify-between items-center mb-2"><h3 class="font-semibold">Invoiced vs collected, last 12 months</h3>
        <div class="flex gap-3 text-xs text-gray-500"><span><i class="inline-block w-3 h-3 rounded-sm align-middle" style="background:#c9b3c3"></i> Invoiced</span>
        <span><i class="inline-block w-3 h-3 rounded-sm align-middle" style="background:#017E84"></i> Collected</span></div></div>${trendChart(s.trend)}</div>
      <div class="card p-4 space-y-5">
        <div><h3 class="font-semibold mb-3">Subscriptions by status</h3>
          <div class="flex h-3 rounded overflow-hidden mb-3">${statuses.map(k => `<div class="b-${k}" style="width:${(s.subscriptions_by_status[k] || 0) / totalSubs * 100}%"></div>`).join('')}</div>
          <div class="grid grid-cols-2 gap-y-1 text-sm">${statuses.map(k => `<div>${badge(k)} <span class="ml-1 font-medium">${s.subscriptions_by_status[k] || 0}</span></div>`).join('')}</div></div>
        <div><h3 class="font-semibold mb-2">Active by plan</h3>${s.active_by_plan.map(p => `<div class="flex justify-between text-sm py-0.5"><span>${esc(p.plan)}</span><b>${p.count}</b></div>`).join('') || '<p class="text-sm text-gray-400">None</p>'}</div>
        <div><h3 class="font-semibold mb-2">Collected by method</h3>${Object.entries(s.collected_by_method).map(([m, a]) => `<div class="flex justify-between text-sm py-0.5"><span>${methodName(m)}</span><b>${money(a)}</b></div>`).join('') || '<p class="text-sm text-gray-400">None</p>'}</div>
      </div></div>
    <div class="card"><div class="px-4 py-3 border-b flex items-center justify-between"><h3 class="font-semibold">Overdue chase list</h3>
      <a href="#/invoices" class="text-sm text-odoo" id="see-overdue">Open in invoices →</a></div>
      <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Invoice</th><th>Customer</th><th>Contact</th><th>Due</th><th>Aging</th><th class="num">Balance</th></tr></thead>
      <tbody>${overdue.map(o => `<tr class="clickable" data-inv="${o.invoice_id}"><td class="font-medium">${o.invoice_number}</td>
        <td>${esc(o.company_name || o.customer_name)}</td><td class="text-xs">${esc(o.email)}<br>${esc(o.phone || '')}</td><td>${fmtDate(o.due_date)}</td>
        <td><span class="badge b-overdue">${o.days_overdue} days · ${o.bucket}</span></td><td class="num font-semibold">${money(o.balance_due)}</td></tr>`).join('') || emptyRow(6, 'No overdue invoices. 🎉')}</tbody></table></div></div>`;
  $('#df').addEventListener('submit', e => { e.preventDefault(); Object.assign(S.dash, Object.fromEntries(new FormData(e.target))); refresh(); });
  $('#dreset').addEventListener('click', () => { S.dash = { date_from: '', date_to: '', plan_id: '', customer_id: '' }; refresh(); });
  $('#see-overdue').addEventListener('click', () => { S.invFilter = { status: 'overdue', q: '', offset: 0 }; });
  $$('[data-inv]', main).forEach(tr => tr.addEventListener('click', () => showInvoice(tr.dataset.inv)));
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
    `<button class="btn btn-light" id="from-tpl">From template</button><button class="btn btn-primary" id="new-sub">+ New subscription</button>`) + `
    <div class="card">
      <div class="flex flex-wrap items-center gap-2 px-3 pt-2 border-b">
        ${['', ...SUB_STATES].map(s => `<a class="tab ${f.status === s ? 'active' : ''}" data-st="${s}">${s ? label(s) : 'All'}</a>`).join('')}
        <form id="sf" class="ml-auto flex gap-2 pb-2">${cust ? `<span class="badge b-confirmed self-center">${esc(cust.company_name || cust.name)} <a class="cursor-pointer ml-1" id="clr-c">×</a></span>` : ''}
          <input class="input !w-60" name="q" placeholder="Search number or customer…" value="${esc(f.q)}"></form></div>
      <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Number</th><th>Customer</th><th>Plan</th><th>Status</th><th>Start</th><th>Expiry</th>
        <th>Next invoice</th><th class="num">Recurring</th></tr></thead><tbody>
        ${data.items.map(s => `<tr class="clickable" data-id="${s.id}"><td class="font-medium text-odoo">${s.subscription_number}</td>
          <td>${esc(s.customer_name)}</td><td>${esc(s.plan_name)}</td><td>${badge(s.status)}</td><td>${fmtDate(s.start_date)}</td>
          <td>${fmtDate(s.expiry_date)}</td><td>${fmtDate(s.next_billing_date)}</td>
          <td class="num">${money(s.recurring_amount)}<span class="text-gray-400 text-xs"> /${FREQ[s.billing_frequency]}</span></td></tr>`).join('') || emptyRow(8)}
      </tbody></table></div>${pager(data.total, f.offset, o => { f.offset = o; refresh(); })}</div>`;
  $$('[data-st]').forEach(a => a.addEventListener('click', () => { f.status = a.dataset.st; f.offset = 0; refresh(); }));
  $('#sf').addEventListener('submit', e => { e.preventDefault(); f.q = e.target.q.value; f.offset = 0; refresh(); });
  $('#clr-c')?.addEventListener('click', () => { f.customer_id = ''; refresh(); });
  $$('[data-id]', main).forEach(tr => tr.addEventListener('click', () => { location.hash = '#/subscriptions/' + tr.dataset.id; }));
  $('#new-sub').addEventListener('click', () => subscriptionForm());
  $('#from-tpl').addEventListener('click', () => useTemplateDialog());
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
          ['Last invoiced period', fmtDate(sub.last_billing_date)], ['Next invoice', fmtDate(sub.next_billing_date)],
        ].map(([k, v]) => `<div class="flex justify-between gap-4"><span class="text-gray-500">${k}</span><span class="text-right">${v}</span></div>`).join('')}
        ${sub.notes ? `<div class="pt-2 border-t text-gray-600">${esc(sub.notes)}</div>` : ''}</div>
        <div class="card p-4"><h3 class="font-semibold mb-3">History</h3><ol class="space-y-3 text-sm">
          ${sub.events.slice().reverse().map(e => `<li class="flex gap-3"><span class="mt-1.5 w-2 h-2 rounded-full bg-[#714B67] shrink-0"></span>
            <div><div><b class="capitalize">${label(e.action)}</b> → ${badge(e.to_status)}</div>
            <div class="text-xs text-gray-500">${new Date(e.created_at + 'Z').toLocaleString()} · ${esc(e.actor_email)}</div></div></li>`).join('')}</ol></div></div></div>`;
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
    '<button class="btn btn-teal" id="run-billing">▶ Run billing</button>') + `
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
  $('#run-billing').addEventListener('click', () => formModal('Run billing', [
    { name: 'as_of', label: 'Bill everything due on or before', type: 'date', required: true, value: today() },
    { name: 'auto_confirm', label: 'Confirm invoices straight away', type: 'checkbox', value: false },
  ], async v => {
    const r = await api('/billing/run', { method: 'POST', body: v });
    openModal('Billing run complete', `<div class="grid grid-cols-2 gap-3 text-sm">
      <div class="card kpi"><div class="k">Subscriptions due</div><div class="v">${r.subscriptions_scanned}</div></div>
      <div class="card kpi"><div class="k">Invoices created</div><div class="v text-teal">${r.invoices_created}</div></div>
      <div class="card kpi"><div class="k">Already invoiced (skipped)</div><div class="v">${r.skipped_existing}</div></div>
      <div class="card kpi"><div class="k">Auto-closed at expiry</div><div class="v">${r.subscriptions_closed}</div></div></div>
      ${r.invoice_numbers.length ? `<p class="text-sm text-gray-600 mt-4">New: ${r.invoice_numbers.slice(0, 30).join(', ')}${r.invoice_numbers.length > 30 ? '…' : ''}</p>`
        : '<p class="text-sm text-gray-500 mt-4">Nothing was due. Running it again is always safe.</p>'}`,
      { footer: '<button class="btn btn-primary" data-close>Done</button>' });
    refresh();
  }, { submitLabel: 'Run billing' }));
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
    <div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Company</th><th>Contact</th><th>Email</th><th>Phone</th><th>Since</th><th></th></tr></thead><tbody>
    ${customers.map(c => `<tr><td class="font-medium">${esc(c.company_name || '—')}</td><td>${esc(c.name)}</td><td>${esc(c.email)}</td><td>${esc(c.phone || '')}</td>
      <td>${fmtDate(c.created_at)}</td><td class="text-right whitespace-nowrap"><button class="btn btn-light btn-sm" data-subs="${c.id}">Subscriptions</button>
      <button class="btn btn-light btn-sm" data-ed="${c.id}">Edit</button></td></tr>`).join('') || emptyRow(6)}</tbody></table></div>`;
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
    formModal('Edit customer', [
      { name: 'company_name', label: 'Company', value: c.company_name }, { name: 'name', label: 'Contact name', required: true, value: c.name },
      { name: 'phone', label: 'Phone', value: c.phone }, { name: 'is_active', label: 'Account active', type: 'checkbox', value: c.is_active },
    ], async v => { await api('/users/' + c.id, { method: 'PATCH', body: v }); invalidate('customers'); toast('Saved'); refresh(); });
  }));
}

// ---------- products ----------
async function viewProducts(main) {
  const [products, taxes] = await Promise.all([getProducts(true), getTaxes(true)]);
  const admin = isAdmin();
  main.innerHTML = pageHeader('Products', admin ? 'Catalog with variants; variant surcharges are added to the sales price.' : 'Read-only: only the admin can change the catalog.',
    admin ? '<button class="btn btn-primary" id="new-prod">+ New product</button>' : '') + `
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
      <td>${yes(p.auto_close_on_expiry)}</td><td>${yes(p.allow_early_close)}</td><td>${yes(p.allow_pause)}</td><td>${yes(p.allow_renewal)}</td>
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

// ---------- customer portal ----------
async function viewMySubscriptions(main) {
  const data = await api('/subscriptions?limit=200');
  main.innerHTML = pageHeader(`Hello, ${esc(S.user.name.split(' ')[0])}`, 'Your subscriptions. Manage them here, no email needed.',
    '<a href="#/subscribe" class="btn btn-primary">+ Subscribe to a plan</a>') +
    `<div class="grid lg:grid-cols-2 gap-4">${data.items.map(s => `<div class="card p-5" data-sid="${s.id}">
      <div class="flex justify-between items-start gap-3"><div><div class="text-xs text-gray-500">${s.subscription_number}</div>
        <h3 class="font-semibold text-lg">${esc(s.plan_name)}</h3></div>${badge(s.status)}</div>
      <div class="text-2xl font-semibold mt-2">${money(s.recurring_amount)}<span class="text-sm text-gray-500 font-normal"> + tax / ${FREQ[s.billing_frequency]}</span></div>
      <div class="grid grid-cols-3 gap-2 text-sm mt-3">
        <div><div class="label">Started</div>${fmtDate(s.start_date)}</div><div><div class="label">Expires</div>${fmtDate(s.expiry_date)}</div>
        <div><div class="label">${s.status === 'quotation' ? 'Quote valid until' : 'Next invoice'}</div>${fmtDate(s.status === 'quotation' ? s.quotation_valid_until : s.next_billing_date)}</div></div>
      <div class="lines text-sm mt-3 text-gray-600"></div>
      <div class="flex flex-wrap gap-2 mt-4">${subActions(s)}</div></div>`).join('')
      || '<div class="card p-10 text-center text-gray-400 lg:col-span-2">You have no subscriptions yet. <a class="text-odoo" href="#/subscribe">Browse plans →</a></div>'}</div>`;
  for (const s of data.items) {
    const card = $(`[data-sid="${s.id}"]`, main);
    $$('[data-act]', card).forEach(b => b.addEventListener('click', () => doSubAction(s, b.dataset.act)));
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
async function viewProfile(main) {
  const me = await api('/auth/me');
  main.innerHTML = pageHeader('Profile', esc(me.email)) + `<div class="grid md:grid-cols-2 gap-4 max-w-4xl">
    <form id="pf" class="card p-5 space-y-4"><h3 class="font-semibold">Details</h3>
      ${field({ name: 'name', label: 'Name', value: me.name, required: true })}${field({ name: 'company_name', label: 'Company', value: me.company_name })}
      ${field({ name: 'phone', label: 'Phone', value: me.phone })}<button class="btn btn-primary">Save</button></form>
    <form id="cp" class="card p-5 space-y-4"><h3 class="font-semibold">Change password</h3>
      ${field({ name: 'current_password', label: 'Current password', type: 'password', required: true })}
      <div>${field({ name: 'new_password', label: 'New password', type: 'password', required: true })}<p class="text-xs mt-1" id="pwh"></p></div>
      <button class="btn btn-primary">Change password</button></form></div>`;
  pwHint($('[name=new_password]'), $('#pwh'));
  $('#pf').addEventListener('submit', async e => {
    e.preventDefault();
    const u = await run(() => api('/auth/me', { method: 'PATCH', body: Object.fromEntries(new FormData(e.target)) }), 'Profile saved');
    S.user = u; localStorage.setItem('bl_user', JSON.stringify(u)); refresh();
  });
  $('#cp').addEventListener('submit', async e => {
    e.preventDefault();
    await run(() => api('/auth/change-password', { method: 'POST', body: Object.fromEntries(new FormData(e.target)) }), 'Password changed');
    e.target.reset();
  });
}

render();
