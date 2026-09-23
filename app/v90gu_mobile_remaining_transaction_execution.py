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


def _now():
    return datetime.now(timezone.utc).isoformat()


def _user(engine, request, entity_id, location_id):
    u = authenticate(request)
    if 'mobile.txn.write' not in permissions_for_user(engine, u.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, u.user_id, str(entity_id), str(location_id) if location_id else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return u


def ensure_v90gu_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS mobile_stock_count_execution (
            count_execution_id TEXT PRIMARY KEY, integration_id TEXT NOT NULL UNIQUE,
            organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL, item_master_id TEXT NOT NULL, lot_id TEXT NULL,
            system_qty NUMERIC NOT NULL, counted_qty NUMERIC NOT NULL, variance_qty NUMERIC NOT NULL,
            uom TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'RECORDED', notes TEXT NULL,
            counted_by TEXT NOT NULL, counted_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_mobile_count_scope ON mobile_stock_count_execution(entity_id,location_id,warehouse_id,counted_at)",
    ]
    with engine.begin() as c:
        for s in stmts:
            c.execute(text(s))


class ExecuteIn(BaseModel):
    payload: dict = Field(default_factory=dict)


def _require_special(engine, user_id, permission):
    if permission not in permissions_for_user(engine, user_id):
        raise HTTPException(403, f'{permission} permission required')


def register_v90gu_routes(app: FastAPI, engine):
    ensure_v90gu_schema(engine)

    @app.get('/ui/mobile-remaining-transaction-execution')
    def ui():
        return FileResponse('web/mobile-remaining-transaction-execution.html')

    @app.post('/v90gu/mobile/transactions/{integration_id}/execute')
    def execute(integration_id: UUID, body: ExecuteIn, request: Request):
        with engine.connect() as c:
            row = c.execute(text('SELECT * FROM mobile_transaction_integrations WHERE integration_id=:i'), {'i': str(integration_id)}).mappings().first()
        if not row:
            raise HTTPException(404, 'integration not found')
        user = _user(engine, request, row['entity_id'], row['location_id'])
        with engine.connect() as c:
            existing = c.execute(text('SELECT * FROM mobile_execution_records WHERE integration_id=:i'), {'i': str(integration_id)}).mappings().first()
        if existing:
            return {'execution_id': existing['execution_id'], 'integration_id': str(integration_id), 'status': existing['status'], 'idempotent': True, 'result': json.loads(existing['result_json'])}
        if row['status'] != 'READY':
            raise HTTPException(409, f"integration is {row['status']} and cannot be executed")
        t = str(row['transaction_type']).upper()
        rid = str(row['reference_id'] or '')
        p = body.payload or {}
        result = {}

        with engine.begin() as c:
            if t == 'RECEIPT_CONFIRM':
                grn = c.execute(text('SELECT * FROM inventory_grn WHERE grn_id=:g'), {'g': rid}).mappings().first()
                if not grn:
                    raise HTTPException(404, 'GRN not found')
                if str(grn['entity_id']) != str(row['entity_id']) or str(grn['location_id']) != str(row['location_id']):
                    raise HTTPException(409, 'GRN outside mobile scope')
                if grn['status'] not in ('RECEIVED', 'QC_RELEASED'):
                    raise HTTPException(409, f"GRN is {grn['status']}; source receiving workflow must create the receipt before mobile confirmation")
                result = {'grn_id': rid, 'status': grn['status'], 'confirmed': True, 'line_count': int(c.execute(text('SELECT COUNT(*) FROM inventory_grn_line WHERE grn_id=:g'), {'g': rid}).scalar_one() or 0)}

            elif t == 'PRODUCTION_CONFIRM':
                batch = c.execute(text('SELECT * FROM production_batch WHERE batch_id=:b'), {'b': rid}).mappings().first()
                if not batch:
                    raise HTTPException(404, 'production batch not found')
                if str(batch['entity_id']) != str(row['entity_id']) or str(batch['location_id']) != str(row['location_id']):
                    raise HTTPException(409, 'production batch outside mobile scope')
                if batch['status'] not in ('RUNNING', 'COMPLETED'):
                    raise HTTPException(409, f"production batch is {batch['status']}")
                output = c.execute(text('SELECT * FROM production_batch_output WHERE batch_id=:b'), {'b': rid}).mappings().first()
                if not output:
                    if batch['status'] == 'COMPLETED':
                        raise HTTPException(409, 'completed batch has no recorded output')
                    good = float(p.get('good_qty') or 0); rework = float(p.get('rework_qty') or 0); waste = float(p.get('wastage_qty') or 0)
                    if good + rework + waste <= 0:
                        raise HTTPException(422, 'PRODUCTION_CONFIRM requires good_qty, rework_qty or wastage_qty')
                    latest = c.execute(text('SELECT decision FROM production_process_qc_decision WHERE batch_id=:b ORDER BY decided_at DESC, decision_id DESC'), {'b': rid}).scalar()
                    if latest == 'REJECT':
                        raise HTTPException(409, 'batch has a rejected process QC decision')
                    planned = float(batch['planned_qty'] or 0); total = good + rework + waste
                    if planned > 0 and total > planned * 1.25 + 1e-9:
                        raise HTTPException(422, 'total output exceeds 125% of planned quantity')
                    output_id = str(uuid4())
                    yield_pct = (good * 100.0 / total) if total else 0.0
                    wastage_pct = (waste * 100.0 / total) if total else 0.0
                    c.execute(text("""INSERT INTO production_batch_output(output_id,batch_id,organization_id,entity_id,location_id,good_qty,rework_qty,wastage_qty,uom,yield_pct,wastage_pct,notes,recorded_by)
                        VALUES(:id,:b,:o,:e,:l,:g,:r,:w,:u,:yp,:wp,:n,:by)"""), {'id': output_id, 'b': rid, 'o': batch['organization_id'], 'e': batch['entity_id'], 'l': batch['location_id'], 'g': good, 'r': rework, 'w': waste, 'u': p.get('uom') or batch['uom'], 'yp': yield_pct, 'wp': wastage_pct, 'n': p.get('notes'), 'by': str(user.user_id)})
                    c.execute(text("UPDATE production_batch SET status='COMPLETED',end_at=:t WHERE batch_id=:b AND status='RUNNING'"), {'t': _now(), 'b': rid})
                    output = c.execute(text('SELECT * FROM production_batch_output WHERE batch_id=:b'), {'b': rid}).mappings().first()
                result = {'batch_id': rid, 'status': 'COMPLETED', 'output_id': output['output_id'], 'good_qty': float(output['good_qty']), 'rework_qty': float(output['rework_qty']), 'wastage_qty': float(output['wastage_qty'])}

            elif t == 'STOCK_COUNT':
                warehouse_id = str(p.get('warehouse_id') or '')
                item_master_id = str(p.get('item_master_id') or '')
                lot_id = str(p.get('lot_id') or '') or None
                if not warehouse_id or not item_master_id or p.get('counted_qty') is None:
                    raise HTTPException(422, 'STOCK_COUNT requires warehouse_id, item_master_id and counted_qty')
                wh = c.execute(text('SELECT warehouse_id FROM erp_warehouses WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1'), {'w': warehouse_id, 'e': row['entity_id'], 'l': row['location_id']}).first()
                if not wh:
                    raise HTTPException(422, 'warehouse not found in entity/location scope')
                params = {'o': row['organization_id'], 'e': row['entity_id'], 'l': row['location_id'], 'w': warehouse_id, 'm': item_master_id}
                if lot_id:
                    system_qty = c.execute(text("SELECT COALESCE(available_qty,0) FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:m AND lot_id=:lot"), {**params, 'lot': lot_id}).scalar()
                else:
                    system_qty = c.execute(text("SELECT COALESCE(SUM(available_qty),0) FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:m AND status='AVAILABLE'"), params).scalar()
                if system_qty is None:
                    raise HTTPException(404, 'inventory item/lot not found in warehouse')
                counted = float(p['counted_qty']); system = float(system_qty); variance = counted - system
                count_id = str(uuid4())
                c.execute(text("""INSERT INTO mobile_stock_count_execution(count_execution_id,integration_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,system_qty,counted_qty,variance_qty,uom,status,notes,counted_by,counted_at)
                    VALUES(:id,:i,:o,:e,:l,:w,:m,:lot,:s,:q,:v,:u,'RECORDED',:n,:by,:d)"""), {'id': count_id, 'i': str(integration_id), 'o': row['organization_id'], 'e': row['entity_id'], 'l': row['location_id'], 'w': warehouse_id, 'm': item_master_id, 'lot': lot_id, 's': system, 'q': counted, 'v': variance, 'u': p.get('uom') or 'UNIT', 'n': p.get('notes'), 'by': str(user.user_id), 'd': _now()})
                result = {'count_execution_id': count_id, 'status': 'RECORDED', 'system_qty': system, 'counted_qty': counted, 'variance_qty': variance, 'ledger_adjustment': 'NOT_POSTED'}

            elif t == 'QUALITY_CONFIRM':
                _require_special(engine, user.user_id, 'quality.manage')
                inspection_id = str(p.get('inspection_id') or rid)
                ins = c.execute(text('SELECT * FROM quality_inspection WHERE inspection_id=:i'), {'i': inspection_id}).mappings().first()
                if not ins:
                    raise HTTPException(404, 'quality inspection not found')
                if str(ins['entity_id']) != str(row['entity_id']):
                    raise HTTPException(409, 'quality inspection outside mobile entity scope')
                parameter_code = str(p.get('parameter_code') or '').strip()
                if not parameter_code:
                    raise HTTPException(422, 'QUALITY_CONFIRM requires parameter_code')
                result_id = str(uuid4())
                c.execute(text("""INSERT INTO quality_result(result_id,inspection_id,parameter_code,value_text,value_numeric,unit,pass,remarks,created_by)
                    VALUES(:id,:i,:p,:t,:v,:u,:ok,:r,:by)"""), {'id': result_id, 'i': inspection_id, 'p': parameter_code, 't': p.get('value_text'), 'v': p.get('value_numeric'), 'u': p.get('unit'), 'ok': bool(p.get('pass', False)), 'r': p.get('remarks'), 'by': str(user.user_id)})
                release = bool(p.get('release', False))
                released = False
                if release:
                    if not bool(p.get('pass', False)):
                        raise HTTPException(409, 'failed quality result cannot release inspection')
                    bad = c.execute(text('SELECT COUNT(*) FROM quality_result WHERE inspection_id=:i AND pass=FALSE'), {'i': inspection_id}).scalar_one()
                    open_nc = c.execute(text("SELECT COUNT(*) FROM quality_nc WHERE batch_id=:b AND status='OPEN'"), {'b': ins['batch_id']}).scalar_one()
                    if bad or open_nc:
                        raise HTTPException(409, 'inspection has failed results or open non-conformance')
                    c.execute(text("UPDATE quality_inspection SET status='RELEASED',updated_at=CURRENT_TIMESTAMP WHERE inspection_id=:i"), {'i': inspection_id})
                    released = True
                result = {'inspection_id': inspection_id, 'result_id': result_id, 'status': 'RELEASED' if released else 'RECORDED', 'released': released}

            else:
                raise HTTPException(409, f'{t} has no V90.gu adapter')

            eid = str(uuid4()); now = _now()
            c.execute(text("""INSERT INTO mobile_execution_records(execution_id,integration_id,organization_id,entity_id,location_id,transaction_type,reference_type,reference_id,status,result_json,executed_by,executed_at)
                VALUES(:i,:gi,:o,:e,:l,:t,:rt,:ri,'EXECUTED',:r,:u,:d)"""), {'i': eid, 'gi': str(integration_id), 'o': row['organization_id'], 'e': row['entity_id'], 'l': row['location_id'], 't': t, 'rt': row['reference_type'], 'ri': rid, 'r': json.dumps(result, separators=(',', ':')), 'u': str(user.user_id), 'd': now})
            c.execute(text("UPDATE mobile_transaction_integrations SET status='POSTED',processed_at=:d WHERE integration_id=:i AND status='READY'"), {'d': now, 'i': str(integration_id)})
            c.execute(text("INSERT INTO mobile_transaction_audit(audit_id,integration_id,action,from_status,to_status,message,actor_user_id,created_at) VALUES(:a,:i,'EXECUTE','READY','POSTED','V90.gu executed against source ERP transaction system-of-record',:u,:d)"), {'a': str(uuid4()), 'i': str(integration_id), 'u': str(user.user_id), 'd': now})
        return {'execution_id': eid, 'integration_id': str(integration_id), 'status': 'EXECUTED', 'result': result}

    @app.get('/v90gu/mobile/executions')
    def executions(organization_id: UUID, entity_id: UUID, location_id: UUID | None = None, request: Request = None):
        _user(engine, request, entity_id, location_id)
        q = 'SELECT * FROM mobile_execution_records WHERE organization_id=:o AND entity_id=:e AND transaction_type IN (\'RECEIPT_CONFIRM\',\'PRODUCTION_CONFIRM\',\'STOCK_COUNT\',\'QUALITY_CONFIRM\')'
        params = {'o': str(organization_id), 'e': str(entity_id)}
        if location_id:
            q += ' AND (location_id=:l OR location_id IS NULL)'; params['l'] = str(location_id)
        q += ' ORDER BY executed_at DESC'
        with engine.connect() as c:
            rows = c.execute(text(q), params).mappings().all()
        return {'executions': [dict(r, result=json.loads(r['result_json'])) for r in rows]}
