// FILE PATH: web/assets/erp-forms.js
// ─── ERP Form Helpers v1.0 (Session CS2 — shared helpers for the V90.gx entry screens) ─
// [Session CS2] FEATURE — the new entry screens (company profile, intercompany X→Y, plant registers)
// share: token handling, JSON API calls with readable errors, form → object, select filling from
// /v90gx/lookups/scope and /v90gx/lookups/items, and a status line. No framework, no external CDN.
(function (w) {
  'use strict';
  function token() { try { return localStorage.getItem('erp_token') || sessionStorage.getItem('erp_token') || ''; } catch (e) { return ''; } }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  async function api(method, path, body) {
    var r = await fetch(path, { method: method, headers: { Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    var d = null; try { d = await r.json(); } catch (e) { d = null; }
    if (!r.ok) {
      var det = d && d.detail;
      if (Array.isArray(det)) det = det.map(function (x) { return (x.loc || []).slice(1).join('.') + ': ' + x.msg; }).join('; ');
      else if (det && typeof det === 'object') det = det.message ? det.message + ' ' + JSON.stringify(Object.assign({}, det, { message: undefined })) : JSON.stringify(det);
      if (r.status === 401) det = 'Please sign in on the ERP home page first.';
      throw new Error(det || ('HTTP ' + r.status));
    }
    return d;
  }
  function formData(form) {
    var o = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.disabled) return;
      if (el.type === 'checkbox') { o[el.name] = el.checked; return; }
      var v = el.value.trim();
      if (v === '') return;
      o[el.name] = el.type === 'number' ? Number(v) : v;
    });
    return o;
  }
  function fillSelect(sel, rows, valueKey, label, blank) {
    sel.innerHTML = (blank ? '<option value="">' + esc(blank) + '</option>' : '') + rows.map(function (r) { return '<option value="' + esc(r[valueKey]) + '">' + esc(label(r)) + '</option>'; }).join('');
  }
  function status(el, msg, ok) { el.textContent = msg; el.className = ok ? 'ok' : 'error'; }
  var scopeCache = null;
  async function scope() { if (!scopeCache) scopeCache = await api('GET', '/v90gx/lookups/scope'); return scopeCache; }
  w.ERP = { token: token, esc: esc, api: api, formData: formData, fillSelect: fillSelect, status: status, scope: scope };
}(window));
