// FILE PATH: web/assets/scope-picker.js
// ─── Scope Picker v1.0 (Session CS2 — dropdowns instead of typed Organization/Entity/Location/Warehouse IDs) ─
// [Session CS2] FEATURE — see app/v90gx_ui_support.py header. Replaces <input placeholder="Organization ID|
// Entity ID|Location ID|Warehouse ID" (or "… UUID")> with linked <select>s that keep the same id/name, so
// each page's own script keeps reading `.value`. Data: GET /v90gx/lookups/scope with the signed-in token.
// Last choice is remembered per browser (localStorage, wrapped in try/catch). If the lookup fails (not
// signed in), the original inputs are left untouched.
(function () {
  'use strict';
  var KINDS = [['organization', /^organi[sz]ation (id|uuid)/i], ['entity', /^entity (id|uuid)/i], ['location', /^location (id|uuid)/i], ['warehouse', /^warehouse (id|uuid)/i]];
  function token() { try { return localStorage.getItem('erp_token') || sessionStorage.getItem('erp_token') || ''; } catch (e) { return ''; } }
  function remember(k, v) { try { localStorage.setItem('erp_scope_' + k, v); } catch (e) { /* storage unavailable */ } }
  function recall(k) { try { return localStorage.getItem('erp_scope_' + k) || ''; } catch (e) { return ''; } }
  function find() {
    var found = {};
    document.querySelectorAll('input').forEach(function (el) {
      var ph = (el.getAttribute('placeholder') || '').trim();
      KINDS.forEach(function (k) { if (!found[k[0]] && k[1].test(ph)) found[k[0]] = el; });
    });
    return found;
  }
  function toSelect(input, kind) {
    var s = document.createElement('select');
    ['id', 'name', 'className', 'required'].forEach(function (a) { if (input[a]) s[a] = input[a]; });
    s.setAttribute('data-scope', kind);
    s.style.cssText = 'font:inherit;padding:10px;border-radius:8px;border:1px solid #d1d5db;background:#fff';
    s.title = input.getAttribute('placeholder');
    input.replaceWith(s);
    return s;
  }
  function fill(sel, rows, valueKey, label, optional) {
    var cur = sel.value || recall(sel.getAttribute('data-scope'));
    sel.innerHTML = '';
    var first = document.createElement('option');
    first.value = ''; first.textContent = optional ? '(any)' : 'Select ' + sel.getAttribute('data-scope') + '…';
    sel.appendChild(first);
    rows.forEach(function (r) {
      var o = document.createElement('option');
      o.value = r[valueKey]; o.textContent = label(r);
      if (String(r[valueKey]) === cur) o.selected = true;
      sel.appendChild(o);
    });
    if (!sel.value && rows.length === 1 && !optional) sel.value = rows[0][valueKey];
  }
  function init() {
    var inputs = find();
    if (!Object.keys(inputs).length) return;
    var t = token();
    if (!t) return;
    fetch('/v90gx/lookups/scope', { headers: { Authorization: 'Bearer ' + t } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (!d) return;
      var sel = {};
      Object.keys(inputs).forEach(function (k) { sel[k] = toSelect(inputs[k], k); });
      function refresh() {
        var org = sel.organization ? sel.organization.value : '';
        var ents = d.entities.filter(function (x) { return !org || String(x.organization_id) === org; });
        if (sel.entity) fill(sel.entity, ents, 'entity_id', function (x) { return x.label; });
        var ent = sel.entity ? sel.entity.value : '';
        var locs = d.locations.filter(function (x) { return !ent || String(x.entity_id) === ent; });
        if (sel.location) fill(sel.location, locs, 'location_id', function (x) { return x.location_code + ' — ' + x.location_name; }, /optional/i.test(sel.location.title));
        var loc = sel.location ? sel.location.value : '';
        var whs = d.warehouses.filter(function (x) { return (!ent || String(x.entity_id) === ent) && (!loc || String(x.location_id) === loc); });
        if (sel.warehouse) fill(sel.warehouse, whs, 'warehouse_id', function (x) { return x.warehouse_code + ' — ' + x.warehouse_name; });
        Object.keys(sel).forEach(function (k) { if (sel[k].value) remember(k, sel[k].value); });
      }
      if (sel.organization) {
        fill(sel.organization, d.organizations, 'organization_id', function (x) {
          var names = d.entities.filter(function (e) { return String(e.organization_id) === x.organization_id; }).map(function (e) { return e.entity_code; });
          return 'Organization ' + x.organization_id.slice(0, 8) + '… (' + names.join(', ') + ')';
        });
      }
      Object.keys(sel).forEach(function (k) { sel[k].addEventListener('change', refresh); });
      refresh();
      document.dispatchEvent(new CustomEvent('erp-scope-ready', { detail: d }));
    }).catch(function () { /* leave inputs as they are */ });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
}());
