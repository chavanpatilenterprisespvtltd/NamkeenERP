from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now(): return datetime.now(timezone.utc).isoformat()

def ensure_v90w_schema(engine):
    stmts=[
    """CREATE TABLE IF NOT EXISTS packing_run (
      packing_run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
      location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, source_fg_lot_id TEXT NOT NULL,
      sku_id TEXT NOT NULL, run_no TEXT NOT NULL, source_qty NUMERIC NOT NULL,
      packed_qty NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'DRAFT',
      started_at TEXT NULL, completed_at TEXT NULL, created_by TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, notes TEXT NULL)""",
    """CREATE TABLE IF NOT EXISTS packing_material_consumption (
      consumption_id TEXT PRIMARY KEY, packing_run_id TEXT NOT NULL, material_master_id TEXT NOT NULL,
      lot_id TEXT NULL, quantity NUMERIC NOT NULL, uom TEXT NOT NULL,
      created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(packing_run_id) REFERENCES packing_run(packing_run_id))""",
    """CREATE TABLE IF NOT EXISTS packed_fg_lot (
      packed_fg_lot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
      location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, packing_run_id TEXT NOT NULL,
      source_fg_lot_id TEXT NOT NULL, sku_id TEXT NOT NULL, lot_code TEXT NOT NULL,
      pack_count NUMERIC NOT NULL, net_qty NUMERIC NOT NULL, available_qty NUMERIC NOT NULL,
      uom TEXT NOT NULL, mfg_date TEXT NOT NULL, expiry_date TEXT NULL,
      status TEXT NOT NULL DEFAULT 'AVAILABLE', qc_status TEXT NOT NULL DEFAULT 'RELEASED',
      created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_packing_run_no ON packing_run(organization_id,entity_id,run_no)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_packed_fg_lot_code ON packed_fg_lot(organization_id,entity_id,lot_code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_packed_fg_run ON packed_fg_lot(packing_run_id)",
    "CREATE INDEX IF NOT EXISTS ix_packing_run_scope ON packing_run(entity_id,location_id,warehouse_id,status)",
    ]
    with engine.begin() as c:
        for s in stmts: c.execute(text(s))

class MaterialLine(BaseModel):
    material_master_id: UUID
    lot_id: UUID | None = None
    quantity: float = Field(gt=0)
    uom: str = Field(min_length=1,max_length=20)

class PackingRunCreate(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID; warehouse_id: UUID
    source_fg_lot_id: UUID; sku_id: UUID; run_no: str = Field(min_length=1,max_length=80)
    source_qty: float = Field(gt=0); notes: str|None=None; materials: list[MaterialLine]=Field(default_factory=list)

class PackingComplete(BaseModel):
    lot_code: str = Field(min_length=1,max_length=80)
    pack_count: float = Field(gt=0)
    net_qty: float = Field(gt=0)
    mfg_date: str|None=None; expiry_date: str|None=None
    materials: list[MaterialLine] = Field(default_factory=list)


def _require(engine, request: Request, entity_id: UUID, location_id: UUID, write=True):
    u=authenticate(request); p=permissions_for_user(engine,u.user_id)
    if (('inventory.edit' if write else 'inventory.view') not in p and 'production.edit' not in p): raise HTTPException(403,'permission denied')
    try: assert_entity_location_allowed(engine,u.user_id,str(entity_id),str(location_id))
    except PermissionError as e: raise HTTPException(403,str(e))
    return u

def _warehouse_ok(engine,w,e,l):
    with engine.connect() as c:
        if not c.execute(text("SELECT 1 FROM erp_warehouses WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1"),{'w':str(w),'e':str(e),'l':str(l)}).first():
            raise HTTPException(422,'warehouse not found in entity/location scope')

def _stock(engine,org,e,l,w,item,lot=None):
    with engine.connect() as c:
        if lot:
            r=c.execute(text("SELECT available_qty FROM inventory_lot WHERE lot_id=:lot AND organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND qc_status='RELEASED' AND status='AVAILABLE'"),{'lot':str(lot),'o':str(org),'e':str(e),'l':str(l),'w':str(w),'i':str(item)}).scalar()
        else:
            r=c.execute(text("SELECT available_qty FROM inventory_stock_balance WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i"),{'o':str(org),'e':str(e),'l':str(l),'w':str(w),'i':str(item)}).scalar()
    return float(r or 0)

def _consume_inventory(engine, org,e,l,w,item,qty,uom,run_id,lot_id=None,user=''):
    if lot_id:
        with engine.begin() as c:
            r=c.execute(text("SELECT available_qty FROM inventory_lot WHERE lot_id=:lot AND organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND qc_status='RELEASED' AND status='AVAILABLE'"),{'lot':str(lot_id),'o':str(org),'e':str(e),'l':str(l),'w':str(w),'i':str(item)}).mappings().first()
            if not r or float(r['available_qty'])<qty: raise HTTPException(409,'insufficient packaging lot stock')
            c.execute(text("UPDATE inventory_lot SET available_qty=available_qty-:q WHERE lot_id=:lot"),{'q':qty,'lot':str(lot_id)})
    else:
        with engine.begin() as c:
            r=c.execute(text("SELECT available_qty FROM inventory_stock_balance WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND uom=:u"),{'o':str(org),'e':str(e),'l':str(l),'w':str(w),'i':str(item),'u':uom}).mappings().first()
            if not r or float(r['available_qty'])<qty: raise HTTPException(409,'insufficient packaging stock')
            c.execute(text("UPDATE inventory_stock_balance SET available_qty=available_qty-:q, updated_at=CURRENT_TIMESTAMP WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND uom=:u"),{'q':qty,'o':str(org),'e':str(e),'l':str(l),'w':str(w),'i':str(item),'u':uom})
    with engine.begin() as c:
        c.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:id,:o,:e,:l,:w,:i,:lot,'PACKAGING_CONSUMPTION',:q,:u,'PACKING_RUN',:r,'POSTED',:by)"),{'id':str(uuid4()),'o':str(org),'e':str(e),'l':str(l),'w':str(w),'i':str(item),'lot':str(lot_id) if lot_id else None,'q':-qty,'u':uom,'r':str(run_id),'by':user})

def register_v90w_routes(app: FastAPI, engine):
    ensure_v90w_schema(engine)
    @app.post('/v90w/packing-runs')
    def create_run(body:PackingRunCreate, request:Request):
        u=_require(engine,request,body.entity_id,body.location_id,True); _warehouse_ok(engine,body.warehouse_id,body.entity_id,body.location_id)
        with engine.connect() as c:
            ex=c.execute(text('SELECT 1 FROM packing_run WHERE organization_id=:o AND entity_id=:e AND run_no=:n'),{'o':str(body.organization_id),'e':str(body.entity_id),'n':body.run_no}).first()
            fg=c.execute(text("SELECT available_qty,status,product_master_id,expiry_date,mfg_date FROM finished_goods_lot WHERE fg_lot_id=:f AND organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w"),{'f':str(body.source_fg_lot_id),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id)}).mappings().first()
        if ex: raise HTTPException(409,'packing run number already exists')
        if not fg or fg['status']!='AVAILABLE' or float(fg['available_qty'])<body.source_qty: raise HTTPException(409,'source FG lot has insufficient available quantity')
        # validate SKU exists
        with engine.connect() as c:
            sku=c.execute(text("SELECT 1 FROM master_record WHERE master_id=:s AND organization_id=:o AND master_type='SKU' AND active=1"),{'s':str(body.sku_id),'o':str(body.organization_id)}).first()
        if not sku: raise HTTPException(422,'SKU not found in product master')
        run=uuid4()
        with engine.begin() as c:
            c.execute(text("INSERT INTO packing_run(packing_run_id,organization_id,entity_id,location_id,warehouse_id,source_fg_lot_id,sku_id,run_no,source_qty,status,created_by,notes) VALUES(:id,:o,:e,:l,:w,:f,:s,:n,:q,'DRAFT',:u,:notes)"),{'id':str(run),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id),'f':str(body.source_fg_lot_id),'s':str(body.sku_id),'n':body.run_no,'q':body.source_qty,'u':str(u.user_id),'notes':body.notes})
            for m in body.materials:
                c.execute(text("INSERT INTO packing_material_consumption(consumption_id,packing_run_id,material_master_id,lot_id,quantity,uom,created_by) VALUES(:id,:r,:m,:lot,:q,:u,:by)"),{'id':str(uuid4()),'r':str(run),'m':str(m.material_master_id),'lot':str(m.lot_id) if m.lot_id else None,'q':m.quantity,'u':m.uom,'by':str(u.user_id)})
        return {'packing_run_id':str(run),'status':'DRAFT','source_qty':body.source_qty,'materials':len(body.materials)}

    @app.post('/v90w/packing-runs/{packing_run_id}/start')
    def start_run(packing_run_id:UUID,request:Request):
        u=authenticate(request)
        if 'production.edit' not in permissions_for_user(engine,u.user_id) and 'inventory.edit' not in permissions_for_user(engine,u.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as c:
            r=c.execute(text('SELECT status,created_by FROM packing_run WHERE packing_run_id=:id'),{'id':str(packing_run_id)}).mappings().first()
            if not r: raise HTTPException(404,'packing run not found')
            if r['status']!='DRAFT': raise HTTPException(409,'only draft packing run can start')
            c.execute(text("UPDATE packing_run SET status='RUNNING',started_at=CURRENT_TIMESTAMP WHERE packing_run_id=:id"),{'id':str(packing_run_id)})
        return {'packing_run_id':str(packing_run_id),'status':'RUNNING'}

    @app.post('/v90w/packing-runs/{packing_run_id}/complete')
    def complete_run(packing_run_id:UUID,body:PackingComplete,request:Request):
        u=authenticate(request)
        if 'inventory.edit' not in permissions_for_user(engine,u.user_id) and 'production.edit' not in permissions_for_user(engine,u.user_id): raise HTTPException(403,'permission denied')
        with engine.connect() as c:
            r=c.execute(text('SELECT * FROM packing_run WHERE packing_run_id=:id'),{'id':str(packing_run_id)}).mappings().first()
        if not r: raise HTTPException(404,'packing run not found')
        if r['status']!='RUNNING': raise HTTPException(409,'packing run must be RUNNING')
        if body.net_qty>float(r['source_qty']): raise HTTPException(422,'packed quantity exceeds source quantity')
        with engine.connect() as c:
            exists=c.execute(text('SELECT 1 FROM packed_fg_lot WHERE organization_id=:o AND entity_id=:e AND lot_code=:c'),{'o':r['organization_id'],'e':r['entity_id'],'c':body.lot_code}).first()
            fg=c.execute(text('SELECT available_qty,mfg_date,expiry_date FROM finished_goods_lot WHERE fg_lot_id=:f'),{'f':r['source_fg_lot_id']}).mappings().first()
        if exists: raise HTTPException(409,'packed FG lot code already exists')
        if not fg or float(fg['available_qty'])<body.net_qty: raise HTTPException(409,'source FG lot insufficient stock')
        materials=list(body.materials)
        if not materials:
            with engine.connect() as c:
                materials=[type('M',(),dict(material_master_id=UUID(x['material_master_id']),lot_id=UUID(x['lot_id']) if x.get('lot_id') else None,quantity=float(x['quantity']),uom=x['uom'])) for x in c.execute(text('SELECT material_master_id,lot_id,quantity,uom FROM packing_material_consumption WHERE packing_run_id=:r'),{'r':str(packing_run_id)}).mappings().all()]
        if not materials:
            raise HTTPException(409,'at least one packaging material consumption line is required')
        # Validate packaging availability before touching FG stock.
        for m in materials:
            if _stock(engine,UUID(str(r['organization_id'])),UUID(str(r['entity_id'])),UUID(str(r['location_id'])),UUID(str(r['warehouse_id'])),m.material_master_id,m.lot_id)<m.quantity: raise HTTPException(409,'insufficient packaging stock for completion')
        packed_id=uuid4()
        with engine.begin() as c:
            c.execute(text("UPDATE finished_goods_lot SET available_qty=available_qty-:q, status=CASE WHEN available_qty-:q<=0 THEN 'CONSUMED' ELSE status END WHERE fg_lot_id=:f"),{'q':body.net_qty,'f':str(r['source_fg_lot_id'])})
            c.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) SELECT :id,organization_id,entity_id,location_id,warehouse_id,product_master_id,fg_lot_id,'FG_BULK_CONSUMED',:q,uom,'PACKING_RUN',:run,'POSTED',:by FROM finished_goods_lot WHERE fg_lot_id=:f"),{'id':str(uuid4()),'q':-body.net_qty,'run':str(packing_run_id),'by':str(u.user_id),'f':str(r['source_fg_lot_id'])})
        for m in materials: _consume_inventory(engine,UUID(str(r['organization_id'])),UUID(str(r['entity_id'])),UUID(str(r['location_id'])),UUID(str(r['warehouse_id'])),m.material_master_id,m.quantity,m.uom,packing_run_id,m.lot_id,str(u.user_id))
        with engine.begin() as c:
            c.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by) VALUES(:id,:o,:e,:l,:w,:r,:f,:s,:c,:pc,:q,:q,:u,:mfg,:exp,'AVAILABLE','RELEASED',:by)"),{'id':str(packed_id),'o':r['organization_id'],'e':r['entity_id'],'l':r['location_id'],'w':r['warehouse_id'],'r':str(packing_run_id),'f':r['source_fg_lot_id'],'s':r['sku_id'],'c':body.lot_code,'pc':body.pack_count,'q':body.net_qty,'u':'kg','mfg':body.mfg_date or fg['mfg_date'] or _now(),'exp':body.expiry_date or fg['expiry_date'],'by':str(u.user_id)})
            c.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:id,:o,:e,:l,:w,:i,:lot,'PACKED_FG_RECEIPT',:q,'kg','PACKING_RUN',:r,'POSTED',:by)"),{'id':str(uuid4()),'o':r['organization_id'],'e':r['entity_id'],'l':r['location_id'],'w':r['warehouse_id'],'i':r['sku_id'],'lot':str(packed_id),'q':body.net_qty,'r':str(packing_run_id),'by':str(u.user_id)})
            c.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty,updated_at) VALUES(:o,:e,:l,:w,:i,'kg',:q,CURRENT_TIMESTAMP) ON CONFLICT(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom) DO UPDATE SET available_qty=inventory_stock_balance.available_qty+excluded.available_qty,updated_at=CURRENT_TIMESTAMP"),{'o':r['organization_id'],'e':r['entity_id'],'l':r['location_id'],'w':r['warehouse_id'],'i':r['sku_id'],'q':body.net_qty})
            c.execute(text("UPDATE packing_run SET packed_qty=:q,status='COMPLETED',completed_at=CURRENT_TIMESTAMP WHERE packing_run_id=:id"),{'q':body.net_qty,'id':str(packing_run_id)})
        return {'packing_run_id':str(packing_run_id),'status':'COMPLETED','packed_fg_lot_id':str(packed_id),'lot_code':body.lot_code,'pack_count':body.pack_count,'net_qty':body.net_qty,'uom':'kg'}

    @app.get('/v90w/packing-runs/{packing_run_id}')
    def get_run(packing_run_id:UUID,request:Request):
        u=authenticate(request)
        if 'inventory.view' not in permissions_for_user(engine,u.user_id) and 'production.view' not in permissions_for_user(engine,u.user_id): raise HTTPException(403,'permission denied')
        with engine.connect() as c:
            r=c.execute(text('SELECT * FROM packing_run WHERE packing_run_id=:id'),{'id':str(packing_run_id)}).mappings().first()
            if not r: raise HTTPException(404,'packing run not found')
            m=c.execute(text('SELECT * FROM packing_material_consumption WHERE packing_run_id=:id ORDER BY created_at'),{'id':str(packing_run_id)}).mappings().all()
        try: assert_entity_location_allowed(engine,u.user_id,str(r['entity_id']),str(r['location_id']))
        except PermissionError as e: raise HTTPException(403,str(e))
        return {'packing_run':dict(r),'materials':[dict(x) for x in m]}
