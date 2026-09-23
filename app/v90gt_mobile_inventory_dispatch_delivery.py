from __future__ import annotations
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now(): return datetime.now(timezone.utc).isoformat()

def _user(engine, request, entity_id, location_id):
    u = authenticate(request)
    if 'mobile.txn.write' not in permissions_for_user(engine, u.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, u.user_id, str(entity_id), str(location_id) if location_id else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return u


def ensure_v90gt_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS mobile_execution_records (execution_id TEXT PRIMARY KEY, integration_id TEXT NOT NULL UNIQUE, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL, transaction_type TEXT NOT NULL, reference_type TEXT NOT NULL, reference_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'EXECUTED', result_json TEXT NOT NULL, executed_by TEXT NOT NULL, executed_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_mobile_exec_scope ON mobile_execution_records(entity_id,location_id,status,executed_at)",
        "CREATE INDEX IF NOT EXISTS ix_mobile_exec_ref ON mobile_execution_records(reference_type,reference_id,transaction_type)",
    ]
    with engine.begin() as c:
        for s in stmts: c.execute(text(s))


class ExecuteIn(BaseModel):
    payload: dict = Field(default_factory=dict)


def register_v90gt_routes(app: FastAPI, engine):
    ensure_v90gt_schema(engine)
    @app.get('/ui/mobile-inventory-dispatch-delivery')
    def ui(): return FileResponse('web/mobile-inventory-dispatch-delivery.html')

    @app.post('/v90gt/mobile/transactions/{integration_id}/execute')
    def execute(integration_id: UUID, body: ExecuteIn, request: Request):
        with engine.connect() as c:
            row = c.execute(text('SELECT * FROM mobile_transaction_integrations WHERE integration_id=:i'), {'i':str(integration_id)}).mappings().first()
        if not row: raise HTTPException(404, 'integration not found')
        user = _user(engine, request, row['entity_id'], row['location_id'])
        with engine.connect() as c:
            existing = c.execute(text('SELECT * FROM mobile_execution_records WHERE integration_id=:i'), {'i':str(integration_id)}).mappings().first()
        if existing:
            return {'execution_id': existing['execution_id'], 'integration_id': str(integration_id), 'status': existing['status'], 'idempotent': True, 'result': json.loads(existing['result_json'])}
        if row['status'] != 'READY': raise HTTPException(409, f"integration is {row['status']} and cannot be executed")
        t = str(row['transaction_type']).upper(); rt = str(row['reference_type']); rid = str(row['reference_id']); p = body.payload or {}
        result = {}
        with engine.begin() as c:
            if t == 'PICK_CONFIRM':
                pick = c.execute(text('SELECT * FROM dispatch_pick_lists WHERE pick_list_id=:id'), {'id':rid}).mappings().first()
                if not pick: raise HTTPException(404, 'pick list not found')
                if str(pick['entity_id']) != str(row['entity_id']) or str(pick['location_id']) != str(row['location_id']): raise HTTPException(409,'pick list outside mobile scope')
                if pick['status'] != 'OPEN':
                    if pick['status'] == 'PICKED': result={'pick_list_id':rid,'status':'PICKED','already_confirmed':True}
                    else: raise HTTPException(409, f"pick list is {pick['status']}")
                else:
                    lines = c.execute(text('SELECT * FROM dispatch_pick_lines WHERE pick_list_id=:id'), {'id':rid}).mappings().all()
                    if not lines: raise HTTPException(409,'pick list has no lines')
                    for line in lines:
                        if float(line['allocated_qty']) <= 0: raise HTTPException(409,'invalid allocated quantity')
                        c.execute(text("UPDATE dispatch_pick_lines SET picked_qty=allocated_qty,status='PICKED' WHERE pick_line_id=:id"), {'id':line['pick_line_id']})
                    c.execute(text("UPDATE dispatch_pick_lists SET status='PICKED',picked_at=CURRENT_TIMESTAMP,confirmed_by=:u WHERE pick_list_id=:id"), {'u':user.user_id,'id':rid})
                    c.execute(text("UPDATE sales_orders SET stock_status='PICKED' WHERE sales_order_id=:id"), {'id':pick['sales_order_id']})
                    result={'pick_list_id':rid,'status':'PICKED','sales_order_id':str(pick['sales_order_id']),'line_count':len(lines)}
            elif t == 'DELIVERY_CONFIRM':
                d = c.execute(text('SELECT * FROM dispatches WHERE dispatch_id=:id'), {'id':rid}).mappings().first()
                if not d: raise HTTPException(404,'dispatch not found')
                if str(d['entity_id']) != str(row['entity_id']) or str(d['location_id']) != str(row['location_id']): raise HTTPException(409,'dispatch outside mobile scope')
                if d['status'] != 'POSTED': raise HTTPException(409, f"dispatch is {d['status']}")
                received_by = p.get('received_by'); received_at = p.get('received_at'); pod_reference = p.get('pod_reference'); attachment_ref = p.get('attachment_ref'); notes = p.get('notes')
                status = 'DELIVERED' if any([received_by, received_at, pod_reference, attachment_ref]) else 'PENDING'
                pid=str(uuid4())
                c.execute(text("INSERT INTO dispatch_pod(pod_id,dispatch_id,organization_id,entity_id,location_id,received_by,received_at,pod_reference,attachment_ref,notes,status,captured_by) VALUES(:i,:d,:o,:e,:l,:r,:ra,:pr,:a,:n,:s,:u)"), {'i':pid,'d':rid,'o':d['organization_id'],'e':d['entity_id'],'l':d['location_id'],'r':received_by,'ra':received_at,'pr':pod_reference,'a':attachment_ref,'n':notes,'s':status,'u':user.user_id})
                result={'pod_id':pid,'dispatch_id':rid,'status':status}
            elif t == 'DISPATCH_CONFIRM':
                d=c.execute(text('SELECT dispatch_id,status,sales_order_id,entity_id,location_id FROM dispatches WHERE dispatch_id=:id'),{'id':rid}).mappings().first()
                if not d: raise HTTPException(404,'dispatch not found')
                if str(d['entity_id'])!=str(row['entity_id']) or str(d['location_id'])!=str(row['location_id']): raise HTTPException(409,'dispatch outside mobile scope')
                if d['status']!='POSTED': raise HTTPException(409,'dispatch must be POSTED before mobile dispatch confirmation')
                result={'dispatch_id':rid,'sales_order_id':str(d['sales_order_id']),'status':'POSTED','confirmed':True}
            elif t == 'RETURN_CONFIRM':
                r=c.execute(text('SELECT * FROM sales_returns WHERE sales_return_id=:id'),{'id':rid}).mappings().first()
                if not r: raise HTTPException(404,'sales return not found')
                if str(r['entity_id'])!=str(row['entity_id']) or str(r['location_id'])!=str(row['location_id']): raise HTTPException(409,'return outside mobile scope')
                if r['status']!='REQUESTED':
                    if r['status']=='RECEIVED_QC_HOLD': result={'sales_return_id':rid,'status':r['status'],'already_received':True}
                    else: raise HTTPException(409,f"return is {r['status']}")
                else:
                    lines=c.execute(text('SELECT * FROM sales_return_lines WHERE sales_return_id=:id'),{'id':rid}).mappings().all()
                    if not lines: raise HTTPException(409,'return has no lines')
                    for line in lines:
                        if float(line['requested_qty'])<=0: raise HTTPException(409,'invalid return quantity')
                        lot=c.execute(text('SELECT packed_fg_lot_id,entity_id,location_id,warehouse_id,lot_code FROM packed_fg_lot WHERE packed_fg_lot_id=:id'),{'id':line['packed_fg_lot_id']}).mappings().first()
                        if not lot: raise HTTPException(409,'FG lot not found')
                        if str(lot['entity_id'])!=str(r['entity_id']) or str(lot['location_id'])!=str(r['location_id']) or str(lot['warehouse_id'])!=str(r['warehouse_id']): raise HTTPException(409,'returned FG lot outside return scope')
                        c.execute(text("UPDATE sales_return_lines SET received_qty=requested_qty,disposition_status='QC_HOLD' WHERE sales_return_line_id=:id"),{'id':line['sales_return_line_id']})
                        c.execute(text("INSERT INTO return_hold_lots(return_hold_id,sales_return_id,sales_return_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,status,created_by) VALUES(:id,:r,:rl,:o,:e,:l,:w,:sku,:lot,:code,:q,'QC_HOLD',:by)"),{'id':str(uuid4()),'r':rid,'rl':line['sales_return_line_id'],'o':r['organization_id'],'e':r['entity_id'],'l':r['location_id'],'w':r['warehouse_id'],'sku':line['sku_id'],'lot':line['packed_fg_lot_id'],'code':lot['lot_code'],'q':float(line['requested_qty']),'by':user.user_id})
                    c.execute(text("UPDATE sales_returns SET status='RECEIVED_QC_HOLD',received_at=CURRENT_TIMESTAMP,received_by=:u WHERE sales_return_id=:id"),{'u':user.user_id,'id':rid})
                    c.execute(text("UPDATE sales_orders SET status='PARTIALLY_RETURNED' WHERE sales_order_id=:id AND status='DISPATCHED'"),{'id':r['sales_order_id']})
                    result={'sales_return_id':rid,'status':'RECEIVED_QC_HOLD','received_line_count':len(lines)}
            else:
                raise HTTPException(409, f'{t} has no V90.gt posting adapter; use the source ERP transaction workflow')
            eid=str(uuid4()); now=_now()
            c.execute(text("INSERT INTO mobile_execution_records(execution_id,integration_id,organization_id,entity_id,location_id,transaction_type,reference_type,reference_id,status,result_json,executed_by,executed_at) VALUES(:i,:gi,:o,:e,:l,:t,:rt,:ri,'EXECUTED',:r,:u,:d)"),{'i':eid,'gi':str(integration_id),'o':row['organization_id'],'e':row['entity_id'],'l':row['location_id'],'t':t,'rt':rt,'ri':rid,'r':json.dumps(result,separators=(',',':')),'u':user.user_id,'d':now})
            c.execute(text("UPDATE mobile_transaction_integrations SET status='POSTED',processed_at=:d WHERE integration_id=:i AND status='READY'"),{'d':now,'i':str(integration_id)})
            c.execute(text("INSERT INTO mobile_transaction_audit(audit_id,integration_id,action,from_status,to_status,message,actor_user_id,created_at) VALUES(:a,:i,'EXECUTE','READY','POSTED','V90.gt executed against source ERP transaction system-of-record',:u,:d)"),{'a':str(uuid4()),'i':str(integration_id),'u':user.user_id,'d':now})
        return {'execution_id':eid,'integration_id':str(integration_id),'status':'EXECUTED','result':result}

    @app.get('/v90gt/mobile/executions')
    def executions(organization_id: UUID, entity_id: UUID, location_id: UUID|None=None, request: Request=None):
        _user(engine,request,entity_id,location_id)
        q='SELECT * FROM mobile_execution_records WHERE organization_id=:o AND entity_id=:e'; p={'o':str(organization_id),'e':str(entity_id)}
        if location_id: q+=' AND (location_id=:l OR location_id IS NULL)'; p['l']=str(location_id)
        q+=' ORDER BY executed_at DESC'
        with engine.connect() as c: rows=c.execute(text(q),p).mappings().all()
        return {'executions':[dict(r, result=json.loads(r['result_json'])) for r in rows]}
