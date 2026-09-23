from __future__ import annotations
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now(): return datetime.now(timezone.utc).isoformat()

def _require(engine, request: Request, entity_id: str, location_id: str | None, write: bool):
    user = authenticate(request)
    needed = 'barcode.scan' if write else 'barcode.view'
    if needed not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90ba_schema(engine):
    stmts=[
        """CREATE TABLE IF NOT EXISTS barcode_registry (
            barcode_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
            code TEXT NOT NULL, symbology TEXT NOT NULL DEFAULT 'CODE128', object_type TEXT NOT NULL, object_id TEXT NOT NULL,
            item_id TEXT NULL, lot_id TEXT NULL, active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,code)
        )""",
        """CREATE TABLE IF NOT EXISTS barcode_scan_events (
            scan_event_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
            warehouse_id TEXT NULL, code TEXT NOT NULL, symbology TEXT NOT NULL, object_type TEXT NULL, object_id TEXT NULL,
            purpose TEXT NOT NULL DEFAULT 'LOOKUP', result_status TEXT NOT NULL, result_json TEXT NULL,
            scanned_by TEXT NOT NULL, scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS barcode_scan_batches (
            scan_batch_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
            purpose TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', opened_by TEXT NOT NULL,
            opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, closed_at TEXT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS barcode_scan_batch_lines (
            scan_batch_line_id TEXT PRIMARY KEY, scan_batch_id TEXT NOT NULL, code TEXT NOT NULL,
            object_type TEXT NULL, object_id TEXT NULL, quantity NUMERIC NULL, uom TEXT NULL,
            status TEXT NOT NULL DEFAULT 'SCANNED', scanned_by TEXT NOT NULL, scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_barcode_registry_scope ON barcode_registry(entity_id,location_id,active,code)",
        "CREATE INDEX IF NOT EXISTS ix_barcode_scan_events_scope ON barcode_scan_events(entity_id,location_id,scanned_at)",
        "CREATE INDEX IF NOT EXISTS ix_barcode_batch_lines_batch ON barcode_scan_batch_lines(scan_batch_id,scanned_at)",
    ]
    with engine.begin() as c:
        for s in stmts: c.execute(text(s))
        perms={'barcode.view':'Resolve barcode/QR identifiers and view scan history','barcode.scan':'Register identifiers and record operational scans'}
        for p,n in perms.items(): c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})
        for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'barcode.view') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})
        for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'barcode.scan') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})

class RegisterCodeIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None
    code: str=Field(min_length=2,max_length=160); symbology: str=Field(default='CODE128',min_length=2,max_length=30)
    object_type: str=Field(min_length=2,max_length=50); object_id: UUID
    item_id: UUID|None=None; lot_id: UUID|None=None

class ScanIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID
    warehouse_id: UUID|None=None; code: str=Field(min_length=1,max_length=500)
    symbology: str=Field(default='AUTO',max_length=30); purpose: str=Field(default='LOOKUP',max_length=40)

class BatchOpenIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID
    purpose: str=Field(min_length=2,max_length=40)

class BatchScanIn(BaseModel):
    code: str=Field(min_length=1,max_length=500); quantity: float|None=Field(default=None,gt=0); uom: str|None=None; symbology: str=Field(default='AUTO',max_length=30)

def _norm_code(raw: str):
    code=raw.strip()
    if code.upper().startswith('NAMKEEN:'):
        parts=code.split(':')
        if len(parts)>=3 and parts[2]: return parts[-1].strip(), 'QR'
    return code, None

def _resolve(conn, org, ent, loc, code):
    c,_=_norm_code(code)
    row=conn.execute(text("SELECT * FROM barcode_registry WHERE organization_id=:o AND code=:c AND active=1"),{'o':org,'c':c}).mappings().first()
    if row and str(row['entity_id'])==str(ent) and (row['location_id'] is None or str(row['location_id'])==str(loc)): return dict(row)
    # Backward-compatible direct SKU barcode lookup from product master JSON.
    try:
        row2=conn.execute(text("SELECT master_id,entity_id,data FROM master_records WHERE organization_id=:o AND master_type='SKU' AND active=1"),{'o':org}).mappings().all()
        for r in row2:
            if r['entity_id'] not in (None, ent): continue
            data=r['data'] if isinstance(r['data'],dict) else None
            if data and str(data.get('barcode') or '').strip()==c:
                return {'barcode_id':None,'organization_id':org,'entity_id':r['entity_id'] or ent,'location_id':loc,'code':c,'symbology':'BARCODE','object_type':'SKU','object_id':str(r['master_id']),'item_id':str(r['master_id']),'lot_id':None,'active':1}
    except Exception: pass
    checks=[
      ('PACKED_FG_LOT',"SELECT packed_fg_lot_id object_id,sku_id item_id,lot_code code,entity_id,location_id FROM packed_fg_lot WHERE organization_id=:o AND lot_code=:c"),
      ('FG_LOT',"SELECT fg_lot_id object_id,product_master_id item_id,fg_lot_code code,entity_id,location_id FROM finished_goods_lot WHERE organization_id=:o AND fg_lot_code=:c"),
      ('RAW_LOT',"SELECT lot_id object_id,item_master_id item_id,lot_code code,entity_id,location_id FROM inventory_lot WHERE organization_id=:o AND lot_code=:c"),
    ]
    for typ,q in checks:
        r=conn.execute(text(q),{'o':org,'c':c}).mappings().first()
        if r and str(r['entity_id'])==str(ent) and str(r['location_id'])==str(loc):
            return {'barcode_id':None,'organization_id':org,'entity_id':ent,'location_id':loc,'code':c,'symbology':'BARCODE','object_type':typ,'object_id':str(r['object_id']),'item_id':str(r['item_id']) if r['item_id'] else None,'lot_id':str(r['object_id']) if typ=='RAW_LOT' else None,'active':1}
    return None

def _record_event(conn, body, user_id, resolved, status, result_json=None):
    import json
    eid=str(uuid4())
    conn.execute(text("INSERT INTO barcode_scan_events(scan_event_id,organization_id,entity_id,location_id,warehouse_id,code,symbology,object_type,object_id,purpose,result_status,result_json,scanned_by) VALUES(:i,:o,:e,:l,:w,:c,:s,:ot,:oi,:p,:rs,:rj,:u)"),{
        'i':eid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id) if body.warehouse_id else None,'c':str(body.code).strip(),'s':body.symbology,'ot':resolved.get('object_type') if resolved else None,'oi':resolved.get('object_id') if resolved else None,'p':body.purpose.upper(),'rs':status,'rj':json.dumps(result_json,default=str) if result_json is not None else None,'u':user_id})
    return eid

def register_v90ba_routes(app:FastAPI,engine):
    ensure_v90ba_schema(engine)
    @app.post('/v90ba/barcodes/register')
    def register_code(body:RegisterCodeIn,request:Request):
        user=_require(engine,request,str(body.entity_id),str(body.location_id),True)
        with engine.begin() as c:
            dup=c.execute(text("SELECT barcode_id FROM barcode_registry WHERE organization_id=:o AND code=:c"),{'o':str(body.organization_id),'c':body.code.strip()}).first()
            if dup: raise HTTPException(409,'barcode already registered')
            bid=str(uuid4()); c.execute(text("INSERT INTO barcode_registry(barcode_id,organization_id,entity_id,location_id,code,symbology,object_type,object_id,item_id,lot_id,created_by) VALUES(:b,:o,:e,:l,:c,:s,:t,:i,:m,:lot,:u)"),{'b':bid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'c':body.code.strip(),'s':body.symbology.upper(),'t':body.object_type.upper(),'i':str(body.object_id),'m':str(body.item_id) if body.item_id else None,'lot':str(body.lot_id) if body.lot_id else None,'u':user.user_id})
        return {'barcode_id':bid,'code':body.code.strip(),'status':'ACTIVE'}
    @app.get('/v90ba/barcodes/resolve')
    def resolve_code(organization_id:UUID,entity_id:UUID,location_id:UUID,code:str,request:Request):
        _require(engine,request,str(entity_id),str(location_id),False)
        with engine.connect() as c: row=_resolve(c,str(organization_id),str(entity_id),str(location_id),code)
        if not row: raise HTTPException(404,'identifier not found')
        return {'resolved':row}
    @app.post('/v90ba/scans')
    def scan(body:ScanIn,request:Request):
        user=_require(engine,request,str(body.entity_id),str(body.location_id),True)
        with engine.begin() as c:
            r=_resolve(c,str(body.organization_id),str(body.entity_id),str(body.location_id),body.code)
            result={'code':body.code.strip(),'resolved':r}
            eid=_record_event(c,body,user.user_id,r,'RESOLVED' if r else 'NOT_FOUND',result)
        if not r: raise HTTPException(404,detail={'message':'identifier not found','scan_event_id':eid})
        return {'scan_event_id':eid,**result}
    @app.post('/v90ba/scan-batches')
    def open_batch(body:BatchOpenIn,request:Request):
        user=_require(engine,request,str(body.entity_id),str(body.location_id),True)
        bid=str(uuid4())
        with engine.begin() as c: c.execute(text("INSERT INTO barcode_scan_batches(scan_batch_id,organization_id,entity_id,location_id,purpose,opened_by) VALUES(:i,:o,:e,:l,:p,:u)"),{'i':bid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'p':body.purpose.upper(),'u':user.user_id})
        return {'scan_batch_id':bid,'status':'OPEN'}
    @app.post('/v90ba/scan-batches/{scan_batch_id}/scans')
    def batch_scan(scan_batch_id:UUID,body:BatchScanIn,request:Request):
        with engine.connect() as c: b=c.execute(text('SELECT * FROM barcode_scan_batches WHERE scan_batch_id=:b'),{'b':str(scan_batch_id)}).mappings().first()
        if not b: raise HTTPException(404,'scan batch not found')
        user=_require(engine,request,str(b['entity_id']),str(b['location_id']),True)
        if b['status']!='OPEN': raise HTTPException(409,'scan batch is not open')
        with engine.begin() as c:
            r=_resolve(c,str(b['organization_id']),str(b['entity_id']),str(b['location_id']),body.code)
            if not r: raise HTTPException(404,'identifier not found')
            lid=str(uuid4()); c.execute(text("INSERT INTO barcode_scan_batch_lines(scan_batch_line_id,scan_batch_id,code,object_type,object_id,quantity,uom,scanned_by) VALUES(:i,:b,:c,:t,:o,:q,:u,:by)"),{'i':lid,'b':str(scan_batch_id),'c':body.code.strip(),'t':r['object_type'],'o':r['object_id'],'q':body.quantity,'u':body.uom,'by':user.user_id})
        return {'scan_batch_line_id':lid,'resolved':r,'quantity':body.quantity,'uom':body.uom}
    @app.post('/v90ba/scan-batches/{scan_batch_id}/close')
    def close_batch(scan_batch_id:UUID,request:Request):
        with engine.connect() as c: b=c.execute(text('SELECT * FROM barcode_scan_batches WHERE scan_batch_id=:b'),{'b':str(scan_batch_id)}).mappings().first()
        if not b: raise HTTPException(404,'scan batch not found')
        user=_require(engine,request,str(b['entity_id']),str(b['location_id']),True)
        with engine.begin() as c: c.execute(text("UPDATE barcode_scan_batches SET status='CLOSED',closed_at=CURRENT_TIMESTAMP WHERE scan_batch_id=:b AND status='OPEN'"),{'b':str(scan_batch_id)})
        return {'scan_batch_id':str(scan_batch_id),'status':'CLOSED'}
    @app.get('/v90ba/scan-batches/{scan_batch_id}')
    def get_batch(scan_batch_id:UUID,request:Request):
        with engine.connect() as c:
            b=c.execute(text('SELECT * FROM barcode_scan_batches WHERE scan_batch_id=:b'),{'b':str(scan_batch_id)}).mappings().first()
            if not b: raise HTTPException(404,'scan batch not found')
            lines=c.execute(text('SELECT * FROM barcode_scan_batch_lines WHERE scan_batch_id=:b ORDER BY scanned_at'),{'b':str(scan_batch_id)}).mappings().all()
        _require(engine,request,str(b['entity_id']),str(b['location_id']),False)
        return {'batch':dict(b),'lines':[dict(x) for x in lines]}
