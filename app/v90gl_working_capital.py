from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .v90fn_security_rbac_scope_hardening import assert_security_scope
PERM_VIEW='working_capital.view'; PERM_MANAGE='working_capital.manage'
def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u
def _scope(e,u,o,ei):
    try: assert_security_scope(e,u.user_id,organization_id=o,entity_id=ei)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
def ensure_v90gl_schema(e: Engine):
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS erp_working_capital_snapshot(snapshot_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,cash_available NUMERIC NOT NULL DEFAULT 0,receivables NUMERIC NOT NULL DEFAULT 0,overdue_receivables NUMERIC NOT NULL DEFAULT 0,payables NUMERIC NOT NULL DEFAULT 0,overdue_payables NUMERIC NOT NULL DEFAULT 0,inventory_value NUMERIC NOT NULL DEFAULT 0,customer_credit_limit NUMERIC NOT NULL DEFAULT 0,customer_credit_used NUMERIC NOT NULL DEFAULT 0,collection_target NUMERIC NOT NULL DEFAULT 0,collections_received NUMERIC NOT NULL DEFAULT 0,payment_commitments NUMERIC NOT NULL DEFAULT 0,net_working_capital NUMERIC NOT NULL DEFAULT 0,credit_utilization_pct NUMERIC NOT NULL DEFAULT 0,collection_realization_pct NUMERIC NOT NULL DEFAULT 0,dso_days NUMERIC NOT NULL DEFAULT 0,dpo_days NUMERIC NOT NULL DEFAULT 0,inventory_days NUMERIC NOT NULL DEFAULT 0,cash_conversion_cycle_days NUMERIC NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_working_capital_scope ON erp_working_capital_snapshot(organization_id,entity_id,period_key)'))
        for p,n in [(PERM_VIEW,'View working capital and credit cockpit'),(PERM_MANAGE,'Create working capital snapshots')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})
        for role in ('manager','accounts','sales','mis'): c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':PERM_VIEW})
        for role in ('manager','accounts','mis'): c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':PERM_MANAGE})
def register_v90gl_routes(app: FastAPI, e: Engine):
    ensure_v90gl_schema(e)
    @app.post('/v90gl/working-capital/snapshot')
    def snapshot(body: dict, request: Request):
        u=_u(e,request,PERM_MANAGE); o=str(body.get('organization_id') or '').strip(); ei=str(body.get('entity_id') or '').strip(); pk=str(body.get('period_key') or '').strip()
        if not all((o,ei,pk)): raise HTTPException(400,'organization_id, entity_id and period_key are required')
        _scope(e,u,o,ei)
        cash=_d(body.get('cash_available')); ar=_d(body.get('receivables')); overdue_ar=_d(body.get('overdue_receivables')); ap=_d(body.get('payables')); overdue_ap=_d(body.get('overdue_payables')); inv=_d(body.get('inventory_value')); limit=_d(body.get('customer_credit_limit')); used=_d(body.get('customer_credit_used')); target=_d(body.get('collection_target')); received=_d(body.get('collections_received')); commitments=_d(body.get('payment_commitments')); dso=_d(body.get('dso_days')); dpo=_d(body.get('dpo_days')); invdays=_d(body.get('inventory_days'))
        nwc=ar+inv-ap; credit_pct=(used/limit*100) if limit else Decimal(0); collection_pct=(received/target*100) if target else Decimal(0); ccc=dso+invdays-dpo; sid=str(uuid4())
        vals={'i':sid,'o':o,'e':ei,'p':pk,'cash':float(cash),'ar':float(ar),'oar':float(overdue_ar),'ap':float(ap),'oap':float(overdue_ap),'inv':float(inv),'lim':float(limit),'used':float(used),'target':float(target),'received':float(received),'commit':float(commitments),'nwc':float(nwc),'cp':float(credit_pct),'cr':float(collection_pct),'dso':float(dso),'dpo':float(dpo),'id':float(invdays),'ccc':float(ccc),'by':str(u.user_id)}
        with e.begin() as c: c.execute(text('''INSERT INTO erp_working_capital_snapshot(snapshot_id,organization_id,entity_id,period_key,cash_available,receivables,overdue_receivables,payables,overdue_payables,inventory_value,customer_credit_limit,customer_credit_used,collection_target,collections_received,payment_commitments,net_working_capital,credit_utilization_pct,collection_realization_pct,dso_days,dpo_days,inventory_days,cash_conversion_cycle_days,created_by) VALUES(:i,:o,:e,:p,:cash,:ar,:oar,:ap,:oap,:inv,:lim,:used,:target,:received,:commit,:nwc,:cp,:cr,:dso,:dpo,:id,:ccc,:by) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET cash_available=:cash,receivables=:ar,overdue_receivables=:oar,payables=:ap,overdue_payables=:oap,inventory_value=:inv,customer_credit_limit=:lim,customer_credit_used=:used,collection_target=:target,collections_received=:received,payment_commitments=:commit,net_working_capital=:nwc,credit_utilization_pct=:cp,collection_realization_pct=:cr,dso_days=:dso,dpo_days=:dpo,inventory_days=:id,cash_conversion_cycle_days=:ccc,created_by=:by,created_at=CURRENT_TIMESTAMP'''),vals)
        return {'snapshot_id':sid,'net_working_capital':float(nwc),'credit_utilization_pct':float(credit_pct),'collection_realization_pct':float(collection_pct),'cash_conversion_cycle_days':float(ccc)}
    @app.get('/v90gl/working-capital')
    def listing(organization_id:str, entity_id:str, period_key:str, request:Request):
        u=_u(e,request,PERM_VIEW); _scope(e,u,organization_id,entity_id)
        with e.connect() as c: r=c.execute(text('SELECT * FROM erp_working_capital_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().first()
        return {'snapshot':dict(r) if r else None}
    @app.get('/ui/working-capital')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'working-capital.html')
    return {'allowed':True}
