from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from decimal import Decimal, ROUND_HALF_UP
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

MONEY = Decimal('0.01')

def _money(v) -> float:
    return float(Decimal(str(v or 0)).quantize(MONEY, rounding=ROUND_HALF_UP))

def ensure_v90aq_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS product_cost_rate (
            cost_rate_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            item_master_id TEXT NOT NULL, uom TEXT NOT NULL, unit_cost NUMERIC NOT NULL,
            source_type TEXT NOT NULL, source_reference_id TEXT NULL, effective_from TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,item_master_id,uom,effective_from)
        )""",
        """CREATE TABLE IF NOT EXISTS production_batch_cost (
            batch_cost_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, batch_id TEXT NOT NULL, production_order_id TEXT NOT NULL,
            product_master_id TEXT NOT NULL, planned_qty NUMERIC NOT NULL, actual_good_qty NUMERIC NOT NULL,
            material_cost NUMERIC NOT NULL, packaging_cost NUMERIC NOT NULL, conversion_cost NUMERIC NOT NULL DEFAULT 0,
            wastage_cost NUMERIC NOT NULL DEFAULT 0, total_cost NUMERIC NOT NULL, unit_cost NUMERIC NOT NULL,
            cost_status TEXT NOT NULL DEFAULT 'CALCULATED', calculated_by TEXT NOT NULL, calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(batch_id)
        )""",
        """CREATE TABLE IF NOT EXISTS production_cost_component (
            component_id TEXT PRIMARY KEY, batch_cost_id TEXT NOT NULL, component_type TEXT NOT NULL,
            item_master_id TEXT NULL, reference_id TEXT NULL, quantity NUMERIC NOT NULL, uom TEXT NOT NULL,
            unit_rate NUMERIC NOT NULL, amount NUMERIC NOT NULL, variance_pct NUMERIC NULL,
            notes TEXT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(batch_cost_id) REFERENCES production_batch_cost(batch_cost_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_prod_batch_cost_entity ON production_batch_cost(entity_id,location_id,calculated_at)",
        "CREATE INDEX IF NOT EXISTS ix_prod_cost_comp_batch ON production_cost_component(batch_cost_id,component_type)",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('costing.view','View product and production costs') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('costing.edit','Calculate and snapshot production costs') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('costing.rate','Maintain product cost rates') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
        for role in ('manager','super_admin','accounts','costing','production'):
            for perm in ('costing.view',):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':perm})
        for role in ('manager','super_admin','costing','production'):
            for perm in ('costing.edit',):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':perm})
        for role in ('manager','super_admin','accounts','costing'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'costing.rate') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})

class CostRateIn(BaseModel):
    organization_id: UUID; entity_id: UUID; item_master_id: UUID
    uom: str = Field(min_length=1,max_length=20); unit_cost: float = Field(gt=0)
    effective_from: str | None = None; source_type: str = Field(min_length=2,max_length=40)
    source_reference_id: str | None = None

class BatchCostIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID; batch_id: UUID
    conversion_cost: float = Field(default=0, ge=0); notes: str | None = None

def _require(engine, request: Request, entity_id: str, location_id: str|None, perm: str):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try: assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    return user

def _latest_rate(conn, org, entity, item, uom):
    row = conn.execute(text("""SELECT unit_cost FROM product_cost_rate
        WHERE organization_id=:o AND entity_id=:e AND item_master_id=:i AND uom=:u AND active=1
        ORDER BY effective_from DESC, created_at DESC LIMIT 1"""), {'o':org,'e':entity,'i':item,'u':uom}).scalar()
    return float(row or 0)

def register_v90aq_routes(app: FastAPI, engine) -> None:
    ensure_v90aq_schema(engine)

    @app.post('/v90aq/cost-rates')
    def create_cost_rate(body: CostRateIn, request: Request):
        user = _require(engine, request, str(body.entity_id), None, 'costing.rate')
        effective = body.effective_from or datetime.now(timezone.utc).isoformat()
        rid = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO product_cost_rate
                (cost_rate_id,organization_id,entity_id,item_master_id,uom,unit_cost,source_type,source_reference_id,effective_from,active,created_by)
                VALUES(:id,:o,:e,:i,:u,:c,:s,:r,:ef,1,:by)"""), {'id':rid,'o':str(body.organization_id),'e':str(body.entity_id),'i':str(body.item_master_id),'u':body.uom,'c':body.unit_cost,'s':body.source_type,'r':body.source_reference_id,'ef':effective,'by':str(user.user_id)})
        return {'status':'created','cost_rate_id':rid,'unit_cost':_money(body.unit_cost),'effective_from':effective}

    @app.post('/v90aq/batches/{batch_id}/cost')
    def calculate_batch_cost(batch_id: UUID, body: BatchCostIn, request: Request):
        if str(batch_id) != str(body.batch_id): raise HTTPException(422,'path batch_id does not match payload')
        user = _require(engine, request, str(body.entity_id), str(body.location_id), 'costing.edit')
        with engine.connect() as conn:
            batch = conn.execute(text("SELECT * FROM production_batch WHERE batch_id=:b"), {'b':str(batch_id)}).mappings().first()
            if not batch: raise HTTPException(404,'production batch not found')
            if str(batch['entity_id']) != str(body.entity_id) or str(batch['location_id']) != str(body.location_id): raise HTTPException(422,'batch scope mismatch')
            output = conn.execute(text("SELECT * FROM production_batch_output WHERE batch_id=:b"), {'b':str(batch_id)}).mappings().first()
            if not output: raise HTTPException(409,'batch output is required before costing')
            issues = conn.execute(text("SELECT * FROM production_material_issue WHERE production_order_id=:o AND status='POSTED'"), {'o':batch['production_order_id']}).mappings().all()
            pack_runs = conn.execute(text("SELECT * FROM packing_run WHERE source_fg_lot_id=(SELECT fg_lot_id FROM finished_goods_lot WHERE batch_id=:b LIMIT 1) AND status='COMPLETED'"), {'b':str(batch_id)}).mappings().all()
            packaging = []
            for pr in pack_runs:
                packaging.extend(conn.execute(text("SELECT * FROM packing_material_consumption WHERE packing_run_id=:r"), {'r':pr['packing_run_id']}).mappings().all())
            material_components=[]; packaging_components=[]; material_total=0.0; packaging_total=0.0
            for row in issues:
                rate = _latest_rate(conn,str(batch['organization_id']),str(batch['entity_id']),str(row['material_master_id']),str(row['uom']))
                amount = float(row['issued_qty'])*rate
                material_total += amount
                material_components.append((str(row['material_master_id']),str(row['issue_id']),float(row['issued_qty']),str(row['uom']),rate,amount))
            for row in packaging:
                rate = _latest_rate(conn,str(batch['organization_id']),str(batch['entity_id']),str(row['material_master_id']),str(row['uom']))
                amount = float(row['quantity'])*rate
                packaging_total += amount
                packaging_components.append((str(row['material_master_id']),str(row['consumption_id']),float(row['quantity']),str(row['uom']),rate,amount))
            good_qty=float(output['good_qty'])
            waste_qty=float(output['wastage_qty'])
            wastage_rate=(material_total+packaging_total)/max(good_qty+waste_qty,1e-9)
            wastage_cost=waste_qty*wastage_rate
            total=material_total+packaging_total+float(body.conversion_cost)+wastage_cost
            unit=total/max(good_qty,1e-9)
        with engine.begin() as conn:
            existing=conn.execute(text("SELECT batch_cost_id FROM production_batch_cost WHERE batch_id=:b"), {'b':str(batch_id)}).scalar()
            if existing: raise HTTPException(409,'batch cost already calculated')
            cid=str(uuid4())
            conn.execute(text("""INSERT INTO production_batch_cost
                (batch_cost_id,organization_id,entity_id,location_id,batch_id,production_order_id,product_master_id,planned_qty,actual_good_qty,material_cost,packaging_cost,conversion_cost,wastage_cost,total_cost,unit_cost,cost_status,calculated_by)
                VALUES(:id,:o,:e,:l,:b,:po,:pm,:pl,:good,:mc,:pc,:cc,:wc,:tc,:uc,'CALCULATED',:by)"""), {'id':cid,'o':batch['organization_id'],'e':batch['entity_id'],'l':batch['location_id'],'b':str(batch_id),'po':batch['production_order_id'],'pm':batch['product_master_id'],'pl':batch['planned_qty'],'good':good_qty,'mc':material_total,'pc':packaging_total,'cc':body.conversion_cost,'wc':wastage_cost,'tc':total,'uc':unit,'by':str(user.user_id)})
            for ctype, items in (('RAW_MATERIAL',material_components),('PACKAGING',packaging_components)):
                for item, ref, qty, uom, rate, amount in items:
                    conn.execute(text("INSERT INTO production_cost_component(component_id,batch_cost_id,component_type,item_master_id,reference_id,quantity,uom,unit_rate,amount) VALUES(:id,:bc,:t,:i,:r,:q,:u,:rate,:a)"), {'id':str(uuid4()),'bc':cid,'t':ctype,'i':item,'r':ref,'q':qty,'u':uom,'rate':rate,'a':amount})
        return {'status':'CALCULATED','batch_cost_id':cid,'batch_id':str(batch_id),'material_cost':_money(material_total),'packaging_cost':_money(packaging_total),'conversion_cost':_money(body.conversion_cost),'wastage_cost':_money(wastage_cost),'total_cost':_money(total),'unit_cost':_money(unit)}

    @app.get('/v90aq/batches/{batch_id}/cost')
    def get_batch_cost(batch_id: UUID, request: Request):
        with engine.connect() as conn:
            row=conn.execute(text("SELECT * FROM production_batch_cost WHERE batch_id=:b"), {'b':str(batch_id)}).mappings().first()
            if not row: raise HTTPException(404,'batch cost not found')
            _require(engine,request,str(row['entity_id']),str(row['location_id']),'costing.view')
            comps=conn.execute(text("SELECT * FROM production_cost_component WHERE batch_cost_id=:c ORDER BY component_type,created_at"), {'c':row['batch_cost_id']}).mappings().all()
        result=dict(row); result.update({k:_money(result[k]) for k in ('material_cost','packaging_cost','conversion_cost','wastage_cost','total_cost','unit_cost')})
        return {'cost':result,'components':[dict(x) for x in comps]}

    @app.get('/v90aq/products/{item_master_id}/cost')
    def product_cost(item_master_id: UUID, organization_id: UUID, entity_id: UUID, uom: str, request: Request):
        _require(engine,request,str(entity_id),None,'costing.view')
        with engine.connect() as conn:
            rate=_latest_rate(conn,str(organization_id),str(entity_id),str(item_master_id),uom)
            history=conn.execute(text("SELECT effective_from,unit_cost,source_type,source_reference_id FROM product_cost_rate WHERE organization_id=:o AND entity_id=:e AND item_master_id=:i AND uom=:u AND active=1 ORDER BY effective_from DESC LIMIT 20"), {'o':str(organization_id),'e':str(entity_id),'i':str(item_master_id),'u':uom}).mappings().all()
        return {'item_master_id':str(item_master_id),'uom':uom,'current_unit_cost':_money(rate),'history':[dict(x) for x in history]}
