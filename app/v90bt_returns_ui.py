from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

WEB_ROOT = Path(__file__).resolve().parents[1] / 'web'

def _safe_table(engine, name: str) -> bool:
    try:
        from sqlalchemy import inspect
        return inspect(engine).has_table(name)
    except Exception:
        return False

def _require(engine, request: Request, entity_id: str, location_id: str, write: bool = False):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'returns_ui.manage' if write else 'returns_ui.view'
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user

def ensure_v90bt_schema(engine) -> None:
    ddl = '''CREATE TABLE IF NOT EXISTS ui_returns_preferences (
        preference_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        screen_key TEXT NOT NULL,
        filters TEXT NOT NULL DEFAULT '{}',
        columns TEXT NOT NULL DEFAULT '[]',
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, screen_key)
    )'''
    with engine.begin() as conn:
        conn.execute(text(ddl))
        perms = {
            'returns_ui.view': 'View returns UI screens',
            'returns_ui.manage': 'Manage returns UI preferences',
        }
        for pid, name in perms.items():
            conn.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p':pid,'n':name})
        for role in ('manager','super_admin','mis','salesperson','warehouse','quality','accounts'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'returns_ui.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})
        for role in ('manager','super_admin','mis','quality','accounts'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'returns_ui.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_returns_ui_scope ON sales_returns(entity_id,location_id,status,requested_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_return_disposition_ui_scope ON return_disposition_history(sales_return_id,disposition,created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_return_credit_ui_scope ON return_credit_notes(entity_id,location_id,status,created_at)"))

def register_v90bt_routes(app: FastAPI, engine) -> None:
    ensure_v90bt_schema(engine)

    @app.get('/v90bt/returns/summary')
    def returns_summary(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, str(entity_id), str(location_id))
        p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        counts={'returns':0,'requested':0,'received_qc_hold':0,'dispositioned':0,'credit_notes':0,'credited_value':0.0}
        if _safe_table(engine,'sales_returns'):
            with engine.connect() as c:
                row=c.execute(text("""SELECT COUNT(*) returns,
                    COALESCE(SUM(CASE WHEN status='REQUESTED' THEN 1 ELSE 0 END),0) requested,
                    COALESCE(SUM(CASE WHEN status='RECEIVED_QC_HOLD' THEN 1 ELSE 0 END),0) received_qc_hold,
                    COALESCE(SUM(CASE WHEN status='DISPOSITIONED' THEN 1 ELSE 0 END),0) dispositioned
                    FROM sales_returns WHERE organization_id=:o AND entity_id=:e AND location_id=:l"""),p).mappings().one()
                counts.update({k:int(row[k] or 0) for k in ('returns','requested','received_qc_hold','dispositioned')})
        if _safe_table(engine,'return_credit_notes'):
            with engine.connect() as c:
                r=c.execute(text("SELECT COUNT(*) credit_notes, COALESCE(SUM(grand_total),0) credited_value FROM return_credit_notes WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND status='POSTED'"),p).mappings().one()
                counts['credit_notes']=int(r['credit_notes'] or 0); counts['credited_value']=round(float(r['credited_value'] or 0),2)
        return {'counts':counts}

    @app.get('/v90bt/returns')
    def return_queue(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str|None=None, limit: int=100):
        _require(engine,request,str(entity_id),str(location_id))
        if not _safe_table(engine,'sales_returns'): return {'items':[],'count':0}
        q="SELECT sales_return_id,return_no,sales_order_id,customer_id,warehouse_id,status,reason,requested_at,received_at FROM sales_returns WHERE organization_id=:o AND entity_id=:e AND location_id=:l"
        p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if status: q += ' AND status=:s'; p['s']=status.upper()
        q += ' ORDER BY requested_at DESC LIMIT :lim'; p['lim']=max(1,min(limit,200))
        with engine.connect() as c: rows=[dict(x) for x in c.execute(text(q),p).mappings().all()]
        return {'items':rows,'count':len(rows)}

    @app.get('/v90bt/returns/{sales_return_id}/details')
    def return_details(sales_return_id: UUID, request: Request):
        with engine.connect() as c:
            ret=c.execute(text('SELECT * FROM sales_returns WHERE sales_return_id=:r'),{'r':str(sales_return_id)}).mappings().first()
            if not ret: raise HTTPException(404,'sales return not found')
            lines=c.execute(text('SELECT * FROM sales_return_lines WHERE sales_return_id=:r ORDER BY created_at,sales_return_line_id'),{'r':str(sales_return_id)}).mappings().all()
            disps=c.execute(text('SELECT * FROM return_disposition_history WHERE sales_return_id=:r ORDER BY created_at,disposition_id'),{'r':str(sales_return_id)}).mappings().all() if _safe_table(engine,'return_disposition_history') else []
            cn=c.execute(text('SELECT * FROM return_credit_notes WHERE sales_return_id=:r'),{'r':str(sales_return_id)}).mappings().first() if _safe_table(engine,'return_credit_notes') else None
        _require(engine,request,str(ret['entity_id']),str(ret['location_id']))
        accounting={}
        if _safe_table(engine,'return_credit_notes') and _safe_table(engine,'customer_credit_adjustments') and _safe_table(engine,'incentive_reversals'):
            with engine.connect() as c:
                accounting['customer_credit_adjustments']=[dict(x) for x in c.execute(text('SELECT * FROM customer_credit_adjustments WHERE sales_return_id=:r ORDER BY created_at'),{'r':str(sales_return_id)}).mappings().all()]
                accounting['incentive_reversals']=[dict(x) for x in c.execute(text('SELECT * FROM incentive_reversals WHERE sales_return_id=:r ORDER BY created_at'),{'r':str(sales_return_id)}).mappings().all()]
        return {'return':dict(ret),'lines':[dict(x) for x in lines],'dispositions':[dict(x) for x in disps],'credit_note':dict(cn) if cn else None,'accounting':accounting}

    @app.get('/v90bt/dispositions')
    def disposition_queue(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, disposition: str|None=None, limit: int=100):
        _require(engine,request,str(entity_id),str(location_id))
        if not _safe_table(engine,'return_disposition_history'): return {'items':[],'count':0}
        q="""SELECT d.disposition_id,d.sales_return_id,d.sales_return_line_id,d.disposition,d.quantity,d.reason,d.approved_by,d.created_at,
            r.return_no,r.customer_id,r.status AS return_status
            FROM return_disposition_history d JOIN sales_returns r ON r.sales_return_id=d.sales_return_id
            WHERE r.organization_id=:o AND r.entity_id=:e AND r.location_id=:l"""
        p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if disposition: q+=' AND d.disposition=:d'; p['d']=disposition.upper()
        q+=' ORDER BY d.created_at DESC LIMIT :lim'; p['lim']=max(1,min(limit,200))
        with engine.connect() as c: rows=[dict(x) for x in c.execute(text(q),p).mappings().all()]
        return {'items':rows,'count':len(rows)}

    @app.get('/v90bt/accounting')
    def accounting_queue(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, limit: int=100):
        _require(engine,request,str(entity_id),str(location_id))
        if not _safe_table(engine,'return_credit_notes'): return {'items':[],'count':0}
        q="""SELECT rcn.credit_note_id,rcn.credit_note_no,rcn.sales_return_id,rcn.customer_id,rcn.status,rcn.taxable_value,rcn.gst_total,rcn.grand_total,rcn.created_at,
            sr.return_no,sr.reason FROM return_credit_notes rcn JOIN sales_returns sr ON sr.sales_return_id=rcn.sales_return_id
            WHERE rcn.organization_id=:o AND rcn.entity_id=:e AND rcn.location_id=:l ORDER BY rcn.created_at DESC LIMIT :lim"""
        with engine.connect() as c: rows=[dict(x) for x in c.execute(text(q),{'o':str(organization_id),'e':str(entity_id),'l':str(location_id),'lim':max(1,min(limit,200))}).mappings().all()]
        return {'items':rows,'count':len(rows)}

    @app.get('/v90bt/preferences/{screen_key}')
    def get_preferences(screen_key: str, request: Request):
        user=authenticate(request)
        with engine.connect() as c: row=c.execute(text('SELECT filters,columns FROM ui_returns_preferences WHERE user_id=:u AND screen_key=:s'),{'u':str(user.user_id),'s':screen_key}).mappings().first()
        return {'screen_key':screen_key,'filters':json.loads(row['filters'] or '{}') if row else {},'columns':json.loads(row['columns'] or '[]') if row else []}

    @app.put('/v90bt/preferences/{screen_key}')
    def put_preferences(screen_key: str, payload: dict, request: Request):
        user=authenticate(request)
        if 'returns_ui.manage' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        filters,columns=payload.get('filters',{}),payload.get('columns',[])
        if not isinstance(filters,dict) or not isinstance(columns,list) or len(columns)>60: raise HTTPException(400,'invalid preference payload')
        with engine.begin() as c:
            c.execute(text("""INSERT INTO ui_returns_preferences(preference_id,user_id,screen_key,filters,columns) VALUES(:i,:u,:s,:f,:c)
                ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=excluded.filters,columns=excluded.columns,updated_at=CURRENT_TIMESTAMP"""),{'i':str(uuid4()),'u':str(user.user_id),'s':screen_key,'f':json.dumps(filters),'c':json.dumps(columns)})
        return {'screen_key':screen_key,'filters':filters,'columns':columns}

    @app.get('/ui/returns')
    def returns_page(): return FileResponse(WEB_ROOT/'returns.html')

    @app.get('/ui/returns/accounting')
    def returns_accounting_page(): return FileResponse(WEB_ROOT/'returns_accounting.html')
