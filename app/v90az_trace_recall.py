from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now(): return datetime.now(timezone.utc).isoformat()


def _require(engine, request: Request, entity_id: str, location_id: str, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90az_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS recall_cases (
            recall_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, recall_no TEXT NOT NULL, title TEXT NOT NULL, reason TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'MEDIUM', status TEXT NOT NULL DEFAULT 'OPEN',
            source_type TEXT NOT NULL, source_id TEXT NOT NULL, initiated_by TEXT NOT NULL,
            initiated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, closed_at TEXT NULL,
            UNIQUE(organization_id,entity_id,recall_no))""",
        """CREATE TABLE IF NOT EXISTS recall_affected_lots (
            recall_lot_id TEXT PRIMARY KEY, recall_id TEXT NOT NULL, lot_type TEXT NOT NULL,
            lot_id TEXT NOT NULL, lot_code TEXT NULL, item_id TEXT NULL, original_qty NUMERIC NOT NULL DEFAULT 0,
            identified_qty NUMERIC NOT NULL DEFAULT 0, withdrawn_qty NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'IDENTIFIED', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(recall_id,lot_type,lot_id))""",
        """CREATE TABLE IF NOT EXISTS recall_withdrawals (
            withdrawal_id TEXT PRIMARY KEY, recall_id TEXT NOT NULL, lot_type TEXT NOT NULL,
            lot_id TEXT NOT NULL, quantity NUMERIC NOT NULL, reason TEXT NOT NULL, warehouse_id TEXT NULL,
            performed_by TEXT NOT NULL, performed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS recall_trace_events (
            trace_event_id TEXT PRIMARY KEY, recall_id TEXT NOT NULL, event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, reference_id TEXT NULL,
            quantity NUMERIC NULL, customer_id TEXT NULL, event_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE INDEX IF NOT EXISTS ix_recall_cases_scope ON recall_cases(entity_id,location_id,status,initiated_at)",
        "CREATE INDEX IF NOT EXISTS ix_recall_affected_lot ON recall_affected_lots(lot_type,lot_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_recall_trace ON recall_trace_events(recall_id,event_type)",
    ]
    with engine.begin() as conn:
        for stmt in stmts: conn.execute(text(stmt))
        perms = {
            'recall.view':'View batch traceability and recall records',
            'recall.edit':'Create recalls and identify affected lots',
            'recall.withdraw':'Perform recall withdrawal actions',
        }
        for p,n in perms.items():
            conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p':p,'n':n})
        for role in ('manager','super_admin','mis','quality','production','dispatch','accounts','salesperson'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'recall.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})
        for role in ('manager','super_admin','quality','production'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'recall.edit') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})
        for role in ('manager','super_admin','quality','warehouse','dispatch'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'recall.withdraw') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})


class RecallIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    recall_no: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=160)
    reason: str = Field(min_length=2, max_length=500)
    severity: str = Field(default='MEDIUM', max_length=20)
    source_type: str = Field(default='PACKED_FG_LOT', max_length=30)
    source_id: UUID


class WithdrawalIn(BaseModel):
    lot_type: str = Field(min_length=2, max_length=30)
    lot_id: UUID
    quantity: float = Field(gt=0)
    reason: str = Field(min_length=2, max_length=300)
    warehouse_id: UUID | None = None


def _trace_packed(conn, packed_id: str):
    root = conn.execute(text("""SELECT p.packed_fg_lot_id,p.organization_id,p.entity_id,p.location_id,p.warehouse_id,p.sku_id,p.lot_code,p.net_qty,p.available_qty,p.mfg_date,p.expiry_date,p.source_fg_lot_id,
                                      f.product_master_id,f.batch_id
                               FROM packed_fg_lot p JOIN finished_goods_lot f ON f.fg_lot_id=p.source_fg_lot_id
                               WHERE p.packed_fg_lot_id=:id"""), {'id':packed_id}).mappings().first()
    if not root: return None
    out = {'packed_fg_lot':dict(root), 'production_batch':None, 'sales':[], 'returns':[]}
    batch = conn.execute(text('SELECT * FROM production_batch WHERE batch_id=:b'), {'b':str(root['batch_id'])}).mappings().first()
    out['production_batch'] = dict(batch) if batch else None
    rows = conn.execute(text("""SELECT d.dispatch_id,d.dispatch_line_id,d.dispatched_qty,dp.dispatch_no,dp.posted_at,
                                     so.sales_order_id,so.customer_id,so.order_no,si.invoice_id,si.invoice_no
                              FROM dispatch_lines d JOIN dispatches dp ON dp.dispatch_id=d.dispatch_id
                              JOIN sales_orders so ON so.sales_order_id=dp.sales_order_id
                              LEFT JOIN sales_invoices si ON si.dispatch_id=dp.dispatch_id
                              WHERE d.packed_fg_lot_id=:p ORDER BY dp.posted_at"""), {'p':packed_id}).mappings().all()
    out['sales'] = [dict(x) for x in rows]
    rets = conn.execute(text("""SELECT r.sales_return_id,r.return_no,r.customer_id,rl.sales_return_line_id,rl.received_qty,rl.disposition_status
                              FROM sales_return_lines rl JOIN sales_returns r ON r.sales_return_id=rl.sales_return_id
                              WHERE rl.packed_fg_lot_id=:p ORDER BY r.requested_at"""), {'p':packed_id}).mappings().all()
    out['returns'] = [dict(x) for x in rets]
    return out


def register_v90az_routes(app: FastAPI, engine):
    ensure_v90az_schema(engine)

    @app.post('/v90az/recalls')
    def create_recall(body: RecallIn, request: Request):
        user = _require(engine, request, str(body.entity_id), str(body.location_id), 'recall.edit')
        with engine.begin() as conn:
            if conn.execute(text('SELECT 1 FROM recall_cases WHERE organization_id=:o AND entity_id=:e AND recall_no=:n'), {'o':str(body.organization_id),'e':str(body.entity_id),'n':body.recall_no}).first():
                raise HTTPException(409,'recall number already exists')
            if body.source_type != 'PACKED_FG_LOT':
                raise HTTPException(422,'only PACKED_FG_LOT source_type is currently supported')
            root = conn.execute(text('SELECT packed_fg_lot_id,lot_code,sku_id,net_qty,available_qty,organization_id,entity_id,location_id FROM packed_fg_lot WHERE packed_fg_lot_id=:p AND organization_id=:o AND entity_id=:e AND location_id=:l'), {'p':str(body.source_id),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id)}).mappings().first()
            if not root: raise HTTPException(404,'source packed FG lot not found in scope')
            rid=str(uuid4())
            conn.execute(text("INSERT INTO recall_cases(recall_id,organization_id,entity_id,location_id,recall_no,title,reason,severity,status,source_type,source_id,initiated_by) VALUES(:r,:o,:e,:l,:n,:t,:why,:sev,'OPEN',:st,:sid,:u)"), {'r':rid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'n':body.recall_no,'t':body.title,'why':body.reason,'sev':body.severity.upper(),'st':body.source_type,'sid':str(body.source_id),'u':str(user.user_id)})
            conn.execute(text("INSERT INTO recall_affected_lots(recall_lot_id,recall_id,lot_type,lot_id,lot_code,item_id,original_qty,identified_qty) VALUES(:i,:r,'PACKED_FG_LOT',:l,:c,:s,:q,:q)"), {'i':str(uuid4()),'r':rid,'l':str(root['packed_fg_lot_id']),'c':root['lot_code'],'s':root['sku_id'],'q':float(root['net_qty'] or 0)})
            conn.execute(text("INSERT INTO recall_trace_events(trace_event_id,recall_id,event_type,entity_type,entity_id,reference_id,quantity) VALUES(:i,:r,'SOURCE_IDENTIFIED','PACKED_FG_LOT',:e,:ref,:q)"), {'i':str(uuid4()),'r':rid,'e':str(body.source_id),'ref':str(body.source_id),'q':float(root['net_qty'] or 0)})
        return {'recall_id':rid,'status':'OPEN','source_id':str(body.source_id)}

    @app.get('/v90az/recalls')
    def list_recalls(organization_id: UUID, entity_id: UUID, location_id: UUID, request: Request):
        _require(engine, request, str(entity_id), str(location_id), 'recall.view')
        with engine.connect() as conn:
            rows=conn.execute(text('SELECT * FROM recall_cases WHERE organization_id=:o AND entity_id=:e AND location_id=:l ORDER BY initiated_at DESC'), {'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}).mappings().all()
        return {'items':[dict(x) for x in rows]}

    @app.get('/v90az/recalls/{recall_id}/trace-forward')
    def trace_forward(recall_id: UUID, request: Request):
        with engine.connect() as conn:
            rec=conn.execute(text('SELECT * FROM recall_cases WHERE recall_id=:r'), {'r':str(recall_id)}).mappings().first()
            if not rec: raise HTTPException(404,'recall not found')
        _require(engine, request, str(rec['entity_id']), str(rec['location_id']), 'recall.view')
        with engine.connect() as conn:
            data=_trace_packed(conn,str(rec['source_id'])) if rec['source_type']=='PACKED_FG_LOT' else None
            if data is None: raise HTTPException(404,'source trace not found')
            events=[]
            root=data['packed_fg_lot']; events.append({'stage':'PACKED_FG_LOT','id':root['packed_fg_lot_id'],'lot_code':root['lot_code'],'quantity':root['net_qty']})
            f=data['production_batch'];
            if f: events.append({'stage':'PRODUCTION_BATCH','id':f['batch_id'],'batch_no':f['batch_no'],'quantity':f['planned_qty']})
            for row in data['sales']:
                events.append({'stage':'DISPATCH','id':row['dispatch_id'],'reference':row['dispatch_no'],'quantity':row['dispatched_qty'],'customer_id':row['customer_id'],'sales_order_id':row['sales_order_id'],'invoice_id':row['invoice_id']})
            for row in data['returns']:
                events.append({'stage':'RETURN','id':row['sales_return_id'],'reference':row['return_no'],'quantity':row['received_qty'],'customer_id':row['customer_id'],'disposition':row['disposition_status']})
            return {'recall':dict(rec),'trace':events}

    @app.post('/v90az/recalls/{recall_id}/withdraw')
    def withdraw(recall_id: UUID, body: WithdrawalIn, request: Request):
        with engine.connect() as conn:
            rec=conn.execute(text('SELECT * FROM recall_cases WHERE recall_id=:r'), {'r':str(recall_id)}).mappings().first()
            if not rec: raise HTTPException(404,'recall not found')
        user=_require(engine,request,str(rec['entity_id']),str(rec['location_id']),'recall.withdraw')
        with engine.begin() as conn:
            aff=conn.execute(text('SELECT * FROM recall_affected_lots WHERE recall_id=:r AND lot_type=:t AND lot_id=:l'), {'r':str(recall_id),'t':body.lot_type,'l':str(body.lot_id)}).mappings().first()
            if not aff: raise HTTPException(404,'affected lot not identified for recall')
            remaining=float(aff['identified_qty'] or 0)-float(aff['withdrawn_qty'] or 0)
            if body.quantity > remaining + 1e-9: raise HTTPException(422,'withdrawal exceeds unwithdrawn identified quantity')
            wid=str(uuid4())
            conn.execute(text('INSERT INTO recall_withdrawals(withdrawal_id,recall_id,lot_type,lot_id,quantity,reason,warehouse_id,performed_by) VALUES(:i,:r,:t,:l,:q,:why,:w,:u)'), {'i':wid,'r':str(recall_id),'t':body.lot_type,'l':str(body.lot_id),'q':body.quantity,'why':body.reason,'w':str(body.warehouse_id) if body.warehouse_id else None,'u':str(user.user_id)})
            neww=float(aff['withdrawn_qty'] or 0)+body.quantity
            status='WITHDRAWN' if neww >= float(aff['identified_qty'] or 0)-1e-9 else 'PARTIALLY_WITHDRAWN'
            conn.execute(text("UPDATE recall_affected_lots SET withdrawn_qty=:q,status=:s WHERE recall_lot_id=:id"), {'q':neww,'s':status,'id':aff['recall_lot_id']})
            conn.execute(text("INSERT INTO recall_trace_events(trace_event_id,recall_id,event_type,entity_type,entity_id,reference_id,quantity) VALUES(:i,:r,'WITHDRAWAL','LOT',:e,:ref,:q)"), {'i':str(uuid4()),'r':str(recall_id),'e':str(body.lot_id),'ref':wid,'q':body.quantity})
        return {'withdrawal_id':wid,'status':status,'withdrawn_qty':neww}
