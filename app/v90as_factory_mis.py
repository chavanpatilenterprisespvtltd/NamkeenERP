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

def _num(v):
    return float(Decimal(str(v or 0)).quantize(MONEY, rounding=ROUND_HALF_UP))

def _date(v: str | None):
    if not v:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.fromisoformat(v.replace('Z','+00:00')).date().isoformat()
    except ValueError as exc:
        raise HTTPException(422, 'invalid date; use ISO-8601') from exc

def _require(engine, request: Request, entity_id: str, location_id: str|None):
    user = authenticate(request)
    if 'dashboard.view' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        if location_id:
            assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
        else:
            assert_entity_location_allowed(engine, user.user_id, entity_id, None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user

class FactoryKPIQuery(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    from_date: str | None = Field(default=None)
    to_date: str | None = Field(default=None)


def _fetch_one(conn, sql, params):
    row = conn.execute(text(sql), params).mappings().first()
    return dict(row or {})

def ensure_v90as_schema(engine) -> None:
    # Persistent, refreshable KPI snapshots for management auditability.
    stmts = [
        """CREATE TABLE IF NOT EXISTS factory_kpi_snapshot (
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NULL, from_date TEXT NOT NULL, to_date TEXT NOT NULL,
            planned_qty NUMERIC NOT NULL DEFAULT 0, produced_good_qty NUMERIC NOT NULL DEFAULT 0,
            wastage_qty NUMERIC NOT NULL DEFAULT 0, yield_pct NUMERIC NOT NULL DEFAULT 0,
            batch_count INTEGER NOT NULL DEFAULT 0, qc_release_count INTEGER NOT NULL DEFAULT 0,
            packing_run_count INTEGER NOT NULL DEFAULT 0, packed_qty NUMERIC NOT NULL DEFAULT 0,
            dispatched_qty NUMERIC NOT NULL DEFAULT 0, invoice_value NUMERIC NOT NULL DEFAULT 0,
            production_cost NUMERIC NOT NULL DEFAULT 0, variance_cost NUMERIC NOT NULL DEFAULT 0,
            calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, calculated_by TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_factory_kpi_scope ON factory_kpi_snapshot(entity_id,location_id,from_date,to_date,calculated_at)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def _where(alias: str, org: str, entity: str, location: str|None, date_col: str, fd: str, td: str):
    parts = [f"{alias}.organization_id=:o", f"{alias}.entity_id=:e", f"date({alias}.{date_col}) BETWEEN :fd AND :td"]
    params = {'o':org,'e':entity,'fd':fd,'td':td}
    if location:
        parts.append(f"{alias}.location_id=:l"); params['l']=location
    return ' AND '.join(parts), params


def register_v90as_routes(app: FastAPI, engine) -> None:
    ensure_v90as_schema(engine)

    @app.get('/v90as/factory-kpi')
    def factory_kpi(organization_id: UUID, entity_id: UUID, request: Request,
                    location_id: UUID | None = None, from_date: str | None = None, to_date: str | None = None):
        _require(engine, request, str(entity_id), str(location_id) if location_id else None)
        fd = _date(from_date); td = _date(to_date) if to_date else fd
        if fd > td: raise HTTPException(422, 'from_date cannot be after to_date')
        org, ent, loc = str(organization_id), str(entity_id), str(location_id) if location_id else None
        with engine.connect() as conn:
            q,p = _where('b',org,ent,loc,'created_at',fd,td)
            batches = _fetch_one(conn, f"SELECT COUNT(*) batch_count, COALESCE(SUM(planned_qty),0) planned_qty FROM production_batch b WHERE {q}",p)
            qo,po = _where('bo',org,ent,loc,'recorded_at',fd,td)
            output = _fetch_one(conn, f"SELECT COALESCE(SUM(good_qty),0) produced_good_qty, COALESCE(SUM(wastage_qty),0) wastage_qty FROM production_batch_output bo WHERE {qo}",po)
            qv,pv = _where('v',org,ent,loc,'calculated_at',fd,td)
            variance = _fetch_one(conn, f"SELECT COALESCE(SUM(total_variance_cost),0) variance_cost FROM production_variance_report v WHERE {qv}",pv)
            qc = _fetch_one(conn, f"SELECT COUNT(*) qc_release_count FROM production_process_qc_decision q WHERE q.organization_id=:o AND q.entity_id=:e AND date(q.decided_at) BETWEEN :fd AND :td AND q.decision='RELEASE'" + (" AND q.location_id=:l" if loc else ''), {**{'o':org,'e':ent,'fd':fd,'td':td}, **({'l':loc} if loc else {})})
            pack = _fetch_one(conn, f"SELECT COUNT(*) packing_run_count, COALESCE(SUM(packed_qty),0) packed_qty FROM packing_run pr WHERE { _where('pr',org,ent,loc,'created_at',fd,td)[0] }", _where('pr',org,ent,loc,'created_at',fd,td)[1])
            disp = _fetch_one(conn, f"SELECT COALESCE(SUM(dl.dispatched_qty),0) dispatched_qty FROM dispatch_lines dl JOIN dispatches d ON d.dispatch_id=dl.dispatch_id WHERE d.organization_id=:o AND d.entity_id=:e AND date(COALESCE(d.posted_at,d.created_at)) BETWEEN :fd AND :td" + (" AND d.location_id=:l" if loc else ''), {**{'o':org,'e':ent,'fd':fd,'td':td}, **({'l':loc} if loc else {})})
            inv = _fetch_one(conn, f"SELECT COALESCE(SUM(grand_total),0) invoice_value FROM sales_invoices si WHERE si.organization_id=:o AND si.entity_id=:e AND date(si.created_at) BETWEEN :fd AND :td AND si.status='POSTED'" + (" AND si.location_id=:l" if loc else ''), {**{'o':org,'e':ent,'fd':fd,'td':td}, **({'l':loc} if loc else {})})
            cost = _fetch_one(conn, f"SELECT COALESCE(SUM(total_cost),0) production_cost FROM production_batch_cost pc WHERE pc.organization_id=:o AND pc.entity_id=:e AND date(pc.calculated_at) BETWEEN :fd AND :td" + (" AND pc.location_id=:l" if loc else ''), {**{'o':org,'e':ent,'fd':fd,'td':td}, **({'l':loc} if loc else {})})
        planned=float(batches.get('planned_qty',0)); good=float(output.get('produced_good_qty',0));
        yield_pct=(good*100/planned) if planned else 0
        return {
            'organization_id':org,'entity_id':ent,'location_id':loc,'from_date':fd,'to_date':td,
            'planned_qty':_num(planned),'produced_good_qty':_num(good),'wastage_qty':_num(output.get('wastage_qty',0)),
            'yield_pct':_num(yield_pct),'batch_count':int(batches.get('batch_count',0) or 0),
            'qc_release_count':int(qc.get('qc_release_count',0) or 0),
            'packing_run_count':int(pack.get('packing_run_count',0) or 0),'packed_qty':_num(pack.get('packed_qty',0)),
            'dispatched_qty':_num(disp.get('dispatched_qty',0)),'invoice_value':_num(inv.get('invoice_value',0)),
            'production_cost':_num(cost.get('production_cost',0)),'variance_cost':_num(variance.get('variance_cost',0)),
        }

    @app.post('/v90as/factory-kpi/snapshots')
    def create_snapshot(body: FactoryKPIQuery, request: Request):
        user = _require(engine, request, str(body.entity_id), str(body.location_id) if body.location_id else None)
        data = factory_kpi(body.organization_id, body.entity_id, request, body.location_id, body.from_date, body.to_date)
        sid = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO factory_kpi_snapshot
                (snapshot_id,organization_id,entity_id,location_id,from_date,to_date,planned_qty,produced_good_qty,wastage_qty,yield_pct,batch_count,qc_release_count,packing_run_count,packed_qty,dispatched_qty,invoice_value,production_cost,variance_cost,calculated_by)
                VALUES(:id,:o,:e,:l,:fd,:td,:pl,:good,:w,:yp,:bc,:qc,:pr,:pq,:dq,:iv,:pc,:vc,:by)"""),
                {'id':sid,'o':data['organization_id'],'e':data['entity_id'],'l':data['location_id'],'fd':data['from_date'],'td':data['to_date'],
                 'pl':data['planned_qty'],'good':data['produced_good_qty'],'w':data['wastage_qty'],'yp':data['yield_pct'],'bc':data['batch_count'],
                 'qc':data['qc_release_count'],'pr':data['packing_run_count'],'pq':data['packed_qty'],'dq':data['dispatched_qty'],
                 'iv':data['invoice_value'],'pc':data['production_cost'],'vc':data['variance_cost'],'by':str(user.user_id)})
        return {'status':'created','snapshot_id':sid,'kpi':data}

    @app.get('/v90as/factory-kpi/snapshots')
    def list_snapshots(organization_id: UUID, entity_id: UUID, request: Request, location_id: UUID|None=None, limit: int=20):
        _require(engine, request, str(entity_id), str(location_id) if location_id else None)
        limit=max(1,min(limit,100))
        sql="SELECT * FROM factory_kpi_snapshot WHERE organization_id=:o AND entity_id=:e"; params={'o':str(organization_id),'e':str(entity_id)}
        if location_id: sql += ' AND location_id=:l'; params['l']=str(location_id)
        sql += ' ORDER BY calculated_at DESC LIMIT :lim'; params['lim']=limit
        with engine.connect() as conn: rows=conn.execute(text(sql),params).mappings().all()
        return {'snapshots':[dict(r) for r in rows]}
