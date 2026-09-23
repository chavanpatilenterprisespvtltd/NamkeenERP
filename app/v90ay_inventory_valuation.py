from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed
from .access_scope import is_entity_allowed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(engine, request: Request, entity_id: str, location_id: str | None, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90ay_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS inventory_ageing_policy (
            policy_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NULL,
            slow_moving_days INTEGER NOT NULL DEFAULT 90,
            dead_stock_days INTEGER NOT NULL DEFAULT 180,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,location_id)
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_valuation_snapshot (
            snapshot_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NULL,
            valuation_basis TEXT NOT NULL,
            total_qty NUMERIC NOT NULL,
            total_value NUMERIC NOT NULL,
            slow_moving_value NUMERIC NOT NULL DEFAULT 0,
            dead_stock_value NUMERIC NOT NULL DEFAULT 0,
            expired_value NUMERIC NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_inv_val_snapshot_scope ON inventory_valuation_snapshot(entity_id,location_id,created_at)",
        "CREATE INDEX IF NOT EXISTS ix_inv_age_policy_scope ON inventory_ageing_policy(entity_id,location_id)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
        perms = {
            'inventory_valuation.view': 'View inventory valuation and stock ageing MIS',
            'inventory_valuation.edit': 'Create inventory valuation snapshots and ageing policies',
        }
        for pid, name in perms.items():
            conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p': pid, 'n': name})
        for role in ('manager','super_admin','accounts','costing','mis','production'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'inventory_valuation.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})
        for role in ('manager','super_admin','accounts','costing'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'inventory_valuation.edit') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})


class AgeingPolicyIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    slow_moving_days: int = Field(default=90, ge=1, le=3650)
    dead_stock_days: int = Field(default=180, ge=2, le=3650)


class SnapshotIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    warehouse_id: UUID | None = None


def _cost_rate(conn, organization_id: str, entity_id: str, item_id: str, uom: str) -> float:
    row = conn.execute(text("""SELECT unit_cost FROM product_cost_rate
        WHERE organization_id=:o AND entity_id=:e AND item_master_id=:i AND uom=:u AND active=1
        ORDER BY effective_from DESC, created_at DESC LIMIT 1"""),
        {'o': organization_id, 'e': entity_id, 'i': item_id, 'u': uom}).scalar()
    return float(row or 0)


def _raw_fallback_rate(conn, organization_id: str, entity_id: str, location_id: str, item_id: str, uom: str) -> float:
    row = conn.execute(text("""SELECT
        COALESCE(SUM(COALESCE(l.available_qty,0) * COALESCE(gl.unit_rate,0)) / NULLIF(SUM(COALESCE(l.available_qty,0)),0),0)
        FROM inventory_lot l LEFT JOIN inventory_grn_line gl ON gl.grn_line_id=l.source_grn_line_id
        WHERE l.organization_id=:o AND l.entity_id=:e AND l.location_id=:l AND l.item_master_id=:i AND l.uom=:u AND l.available_qty>0
          AND gl.unit_rate IS NOT NULL"""),
        {'o':organization_id,'e':entity_id,'l':location_id,'i':item_id,'u':uom}).scalar()
    return float(row or 0)


def _policy(conn, org: str, entity: str, location: str | None):
    row = conn.execute(text("""SELECT slow_moving_days, dead_stock_days FROM inventory_ageing_policy
        WHERE organization_id=:o AND entity_id=:e AND (location_id=:l OR location_id IS NULL)
        ORDER BY CASE WHEN location_id=:l THEN 0 ELSE 1 END, updated_at DESC LIMIT 1"""),
        {'o': org, 'e': entity, 'l': location}).mappings().first()
    return (int(row['slow_moving_days']), int(row['dead_stock_days'])) if row else (90, 180)


def _valuation_rows(conn, org: str, entity: str, location: str, warehouse: str | None):
    q = """SELECT organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty
           FROM inventory_stock_balance
           WHERE organization_id=:o AND entity_id=:e AND location_id=:l"""
    p = {'o': org, 'e': entity, 'l': location}
    if warehouse:
        q += " AND warehouse_id=:w"; p['w'] = warehouse
    q += " AND available_qty > 0 ORDER BY item_master_id"
    return conn.execute(text(q), p).mappings().all()


def _age_rows(conn, org: str, entity: str, location: str, warehouse: str | None):
    raw_q = """SELECT l.lot_id AS lot_id, l.item_master_id AS item_master_id, l.uom AS uom,
             l.available_qty AS available_qty, l.expiry_date AS expiry_date, l.mfg_date AS mfg_date,
             l.created_at AS source_date, l.warehouse_id AS warehouse_id, 'RAW_LOT' AS stock_type,
             gl.unit_rate AS source_unit_rate
             FROM inventory_lot l LEFT JOIN inventory_grn_line gl ON gl.grn_line_id=l.source_grn_line_id
             WHERE l.organization_id=:o AND l.entity_id=:e AND l.location_id=:l AND l.available_qty>0"""
    fg_q = """SELECT f.fg_lot_id AS lot_id, COALESCE(f.sku_id,f.product_master_id) AS item_master_id,
             f.uom AS uom, f.available_qty AS available_qty, f.expiry_date AS expiry_date,
             f.mfg_date AS mfg_date, f.created_at AS source_date, f.warehouse_id AS warehouse_id,
             'FG_LOT' AS stock_type, NULL AS source_unit_rate
             FROM finished_goods_lot f
             WHERE f.organization_id=:o AND f.entity_id=:e AND f.location_id=:l AND f.available_qty>0
             AND f.status IN ('AVAILABLE','ALLOCATED') AND f.qc_status='RELEASED'"""
    if warehouse:
        raw_q += " AND l.warehouse_id=:w"; fg_q += " AND f.warehouse_id=:w"
    return conn.execute(text(f"{raw_q} UNION ALL {fg_q} ORDER BY source_date, lot_id"), {**{'o':org,'e':entity,'l':location}, **({'w':warehouse} if warehouse else {})}).mappings().all()


def _age_days(row) -> int:
    basis = row.get('mfg_date') or row.get('source_date')
    if not basis:
        return 0
    try:
        dt = datetime.fromisoformat(str(basis).replace('Z','+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - dt).days, 0)
    except ValueError:
        return 0


def _money(v):
    return round(float(v or 0), 2)


def register_v90ay_routes(app: FastAPI, engine) -> None:
    ensure_v90ay_schema(engine)

    @app.put('/v90ay/inventory/ageing-policy')
    def set_ageing_policy(body: AgeingPolicyIn, request: Request):
        if body.dead_stock_days <= body.slow_moving_days:
            raise HTTPException(422, 'dead_stock_days must be greater than slow_moving_days')
        user = _require(engine, request, str(body.entity_id), str(body.location_id) if body.location_id else None, 'inventory_valuation.edit')
        pid = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO inventory_ageing_policy(
                policy_id,organization_id,entity_id,location_id,slow_moving_days,dead_stock_days,updated_by)
                VALUES(:p,:o,:e,:l,:s,:d,:u)
                ON CONFLICT(organization_id,entity_id,location_id) DO UPDATE SET
                slow_moving_days=excluded.slow_moving_days,dead_stock_days=excluded.dead_stock_days,
                updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP"""),
                {'p':pid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'s':body.slow_moving_days,'d':body.dead_stock_days,'u':str(user.user_id)})
        return {'status':'UPDATED','slow_moving_days':body.slow_moving_days,'dead_stock_days':body.dead_stock_days}

    @app.get('/v90ay/inventory/valuation')
    def inventory_valuation(organization_id: UUID, entity_id: UUID, location_id: UUID, request: Request, warehouse_id: UUID | None = None):
        _require(engine, request, str(entity_id), str(location_id), 'inventory_valuation.view')
        with engine.connect() as conn:
            rows = _valuation_rows(conn, str(organization_id), str(entity_id), str(location_id), str(warehouse_id) if warehouse_id else None)
            slow_days, dead_days = _policy(conn, str(organization_id), str(entity_id), str(location_id))
            age_rows = _age_rows(conn, str(organization_id), str(entity_id), str(location_id), str(warehouse_id) if warehouse_id else None)
        items=[]; total_qty=total_value=slow_value=dead_value=expired_value=0.0
        for r in rows:
            qty=float(r['available_qty'])
            items.append(dict(r)); total_qty += qty
        with engine.connect() as conn:
            for item in items:
                item['unit_cost']=_cost_rate(conn, str(organization_id), str(entity_id), str(item['item_master_id']), str(item['uom']))
                if not item['unit_cost']:
                    item['unit_cost']=_raw_fallback_rate(conn, str(organization_id), str(entity_id), str(location_id), str(item['item_master_id']), str(item['uom']))
                item['value']=_money(float(item['available_qty'])*item['unit_cost'])
                total_value += item['value']
            age_items=[]
            for r in age_rows:
                days=_age_days(r); qty=float(r['available_qty'])
                rate=_cost_rate(conn, str(organization_id), str(entity_id), str(r['item_master_id']), str(r['uom']))
                if not rate and r.get('source_unit_rate') is not None:
                    rate=float(r['source_unit_rate'])
                value=qty*rate
                expired=False
                exp=r.get('expiry_date')
                if exp:
                    try: expired=datetime.fromisoformat(str(exp).replace('Z','+00:00')).date() < datetime.now(timezone.utc).date()
                    except ValueError: expired=False
                bucket='CURRENT'
                if expired: bucket='EXPIRED'; expired_value+=value
                elif days>=dead_days: bucket='DEAD'; dead_value+=value
                elif days>=slow_days: bucket='SLOW_MOVING'; slow_value+=value
                age_items.append({'lot_id':str(r['lot_id']),'stock_type':r['stock_type'],'item_master_id':str(r['item_master_id']),'uom':r['uom'],'available_qty':qty,'age_days':days,'expiry_date':r['expiry_date'],'bucket':bucket,'unit_cost':rate,'value':_money(value)})
        return {'valuation_basis':'CURRENT_AVAILABLE_QTY × LATEST_ACTIVE_COST_RATE (GRN unit-rate fallback for raw lots)','total_qty':total_qty,'total_value':_money(total_value),'slow_moving_value':_money(slow_value),'dead_stock_value':_money(dead_value),'expired_value':_money(expired_value),'ageing_policy':{'slow_moving_days':slow_days,'dead_stock_days':dead_days},'items':items,'lot_ageing':age_items}

    @app.get('/v90ay/inventory/stock-ageing')
    def stock_ageing(organization_id: UUID, entity_id: UUID, location_id: UUID, request: Request, warehouse_id: UUID | None = None):
        _require(engine, request, str(entity_id), str(location_id), 'inventory_valuation.view')
        with engine.connect() as conn:
            slow_days, dead_days = _policy(conn, str(organization_id), str(entity_id), str(location_id))
            rows = _age_rows(conn, str(organization_id), str(entity_id), str(location_id), str(warehouse_id) if warehouse_id else None)
            out=[]
            for r in rows:
                days=_age_days(r); qty=float(r['available_qty'])
                rate=_cost_rate(conn,str(organization_id),str(entity_id),str(r['item_master_id']),str(r['uom']))
                if not rate and r.get('source_unit_rate') is not None: rate=float(r['source_unit_rate'])
                bucket='CURRENT' if days<slow_days else ('SLOW_MOVING' if days<dead_days else 'DEAD')
                out.append({'lot_id':str(r['lot_id']),'stock_type':r['stock_type'],'item_master_id':str(r['item_master_id']),'uom':r['uom'],'available_qty':qty,'age_days':days,'expiry_date':r['expiry_date'],'bucket':bucket,'value':_money(qty*rate)})
        return {'policy':{'slow_moving_days':slow_days,'dead_stock_days':dead_days},'items':out}

    @app.post('/v90ay/inventory/valuation-snapshots')
    def create_snapshot(body: SnapshotIn, request: Request):
        user=_require(engine,request,str(body.entity_id),str(body.location_id),'inventory_valuation.edit')
        c=inventory_valuation(body.organization_id,body.entity_id,body.location_id,request,body.warehouse_id)
        sid=str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO inventory_valuation_snapshot(
                snapshot_id,organization_id,entity_id,location_id,warehouse_id,valuation_basis,total_qty,total_value,slow_moving_value,dead_stock_value,expired_value,created_by)
                VALUES(:s,:o,:e,:l,:w,:b,:q,:v,:sv,:dv,:ev,:u)"""), {'s':sid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id) if body.warehouse_id else None,'b':c['valuation_basis'],'q':c['total_qty'],'v':c['total_value'],'sv':c['slow_moving_value'],'dv':c['dead_stock_value'],'ev':c['expired_value'],'u':str(user.user_id)})
        return {'status':'SNAPSHOT_CREATED','snapshot_id':sid,'metrics':{k:c[k] for k in ('total_qty','total_value','slow_moving_value','dead_stock_value','expired_value')}}

    @app.get('/v90ay/inventory/valuation-snapshots')
    def list_snapshots(organization_id: UUID, entity_id: UUID, location_id: UUID, request: Request):
        _require(engine,request,str(entity_id),str(location_id),'inventory_valuation.view')
        with engine.connect() as conn:
            rows=conn.execute(text('SELECT * FROM inventory_valuation_snapshot WHERE organization_id=:o AND entity_id=:e AND location_id=:l ORDER BY created_at DESC'),{'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}).mappings().all()
        return {'items':[dict(r) for r in rows]}
