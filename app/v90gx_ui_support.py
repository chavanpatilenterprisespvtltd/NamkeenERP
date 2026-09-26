# FILE PATH: app/v90gx_ui_support.py
# ─── UI Support v1.0 (Session CS2 — scope dropdowns instead of typed IDs on every screen) ─
#
# [Session CS2] FEATURE — USERS HAD TO TYPE RAW ORGANIZATION / ENTITY / LOCATION UUIDs ON EVERY SCREEN.
# Confirmed this session by reading web/*.html and the HTML embedded in app/v90bo…v90br UI modules:
# forms use <input placeholder="Organization ID"> etc., with no lookup. 17 screens are affected.
# THE FIX:
#   - GET /v90gx/lookups/scope → organizations, entities (with legal/trade name and X/Y role), locations
#     and warehouses the signed-in user may access (admins see all).
#   - web/assets/scope-picker.js turns those ID inputs into linked dropdowns (organization → entity →
#     location → warehouse), keeps the same element id so each page's own code is unchanged, and
#     remembers the last choice per browser.
#   - An HTTP middleware adds <script src="/web/assets/scope-picker.js"> before </body> of HTML
#     responses served under /ui/ and /web, so none of the existing 136 page files had to be edited.
# NOT touched: page logic, APIs the pages call, authentication.
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import text
from sqlalchemy.engine import Engine
from pathlib import Path

from .auth import authenticate
from .identity import permissions_for_user

SCRIPT_TAG = b'<script src="/web/assets/scope-picker.js" defer></script>'
WEB = Path(__file__).resolve().parents[1] / 'web'


def register_v90gx_ui_routes(app: FastAPI, e: Engine):
    @app.get('/v90gx/lookups/scope')
    def scope(r: Request):
        u = authenticate(r)
        ps = permissions_for_user(e, u.user_id)
        admin = 'admin.users' in ps or 'security.rbac.manage' in ps
        with e.connect() as c:
            ents = [dict(x) for x in c.execute(text('''SELECT en.entity_id,en.entity_code,en.entity_name,m.organization_id,p.legal_name,p.trade_name,p.business_role
                FROM erp_entities en LEFT JOIN erp_security_entity_organization m ON m.entity_id=en.entity_id LEFT JOIN erp_entity_profile p ON p.entity_id=en.entity_id ORDER BY en.entity_code''')).mappings().all()]
            locs = [dict(x) for x in c.execute(text('SELECT location_id,entity_id,location_code,location_name FROM erp_locations ORDER BY location_code')).mappings().all()]
            whs = [dict(x) for x in c.execute(text('SELECT warehouse_id,entity_id,location_id,warehouse_code,warehouse_name FROM erp_warehouses ORDER BY warehouse_code')).mappings().all()]
            if not admin:
                ae = {str(x[0]) for x in c.execute(text('SELECT entity_id FROM erp_entity_user_access WHERE user_id=:u AND active=TRUE'), {'u': u.user_id}).all()}
                al = {str(x[0]) for x in c.execute(text('SELECT location_id FROM erp_location_user_access WHERE user_id=:u AND active=TRUE'), {'u': u.user_id}).all()}
                ao = {str(x[0]) for x in c.execute(text('SELECT organization_id FROM erp_organization_user_access WHERE user_id=:u AND active=TRUE'), {'u': u.user_id}).all()}
                ents = [x for x in ents if str(x['entity_id']) in ae or (x['organization_id'] and str(x['organization_id']) in ao)]
                keep = {str(x['entity_id']) for x in ents}
                locs = [x for x in locs if str(x['location_id']) in al or str(x['entity_id']) in keep]
                whs = [x for x in whs if str(x['entity_id']) in keep]
        orgs = sorted({str(x['organization_id']) for x in ents if x['organization_id']})
        for x in ents:
            x['label'] = f"{x['entity_code']} — {x['trade_name'] or x['legal_name'] or x['entity_name']}" + (f" ({'Manufacturing' if x['business_role'] == 'MANUFACTURER' else 'Sales & Marketing' if x['business_role'] == 'SALES_MARKETING' else x['business_role']})" if x['business_role'] else '')
        return {'organizations': [{'organization_id': o, 'label': o} for o in orgs], 'entities': ents, 'locations': locs, 'warehouses': whs}

    @app.get('/v90gx/lookups/items')
    def items(organization_id: str, r: Request, master_type: str | None = None):
        """Active product/SKU/material masters for dropdowns (id + code/name from the master JSON)."""
        import json as _json
        authenticate(r)
        q = 'SELECT master_id,master_type,data FROM master_record WHERE organization_id=:o AND active=:a'
        p = {'o': organization_id, 'a': True if e.dialect.name == 'postgresql' else 1}
        if master_type:
            q += ' AND master_type=:t'; p['t'] = master_type.upper()
        with e.connect() as c:
            rows = c.execute(text(q + ' ORDER BY master_type'), p).all()
        out = []
        for mid, mt, data in rows[:2000]:
            d = data if isinstance(data, dict) else (_json.loads(data or '{}') if isinstance(data, str) else {})
            out.append({'id': str(mid), 'type': mt, 'label': f"{d.get('code') or ''} {d.get('name') or d.get('sku_name') or ''}".strip() or str(mid)})
        return {'items': out}

    @app.middleware('http')
    async def inject_scope_picker(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if not (path.startswith('/ui/') or path == '/web' or (path.startswith('/web/') and path.endswith('.html'))):
            return response
        if 'text/html' not in (response.headers.get('content-type') or ''):
            return response
        body = b''.join([chunk async for chunk in response.body_iterator])
        if SCRIPT_TAG not in body and b'</body>' in body:
            body = body.replace(b'</body>', SCRIPT_TAG + b'</body>', 1)
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ('content-length', 'etag')}
        return Response(content=body, status_code=response.status_code, headers=headers, media_type='text/html')

    for route, page in (('/ui/daily-work', 'daily-work.html'),):  # other V90.gx pages are served by their modules
        def _page(p=page):
            return FileResponse(WEB / p)
        app.add_api_route(route, _page, methods=['GET'])
