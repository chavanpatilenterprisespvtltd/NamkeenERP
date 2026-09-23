from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


_ALLOWED_REWORK = {"REPACK", "REWORK"}
_ACTIVE_STATUSES = {"OPEN", "IN_PROGRESS"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(value) -> float:
    return round(float(value or 0), 6)


def ensure_v90aw_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS repack_rework_jobs (
            job_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            sales_return_id TEXT NOT NULL,
            sales_return_line_id TEXT NOT NULL,
            source_disposition TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            source_lot_id TEXT NOT NULL,
            input_qty NUMERIC NOT NULL,
            output_qty NUMERIC NOT NULL DEFAULT 0,
            loss_qty NUMERIC NOT NULL DEFAULT 0,
            input_unit_cost NUMERIC NOT NULL DEFAULT 0,
            processing_cost NUMERIC NOT NULL DEFAULT 0,
            input_cost NUMERIC NOT NULL DEFAULT 0,
            total_cost NUMERIC NOT NULL DEFAULT 0,
            output_unit_cost NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            reference_no TEXT NOT NULL,
            notes TEXT NULL,
            created_by TEXT NOT NULL,
            completed_by TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT NULL,
            UNIQUE(organization_id, entity_id, reference_no)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_repack_rework_scope ON repack_rework_jobs(entity_id,location_id,status,created_at)",
        "CREATE INDEX IF NOT EXISTS ix_repack_rework_return_line ON repack_rework_jobs(sales_return_line_id,status)",
        """CREATE TABLE IF NOT EXISTS return_analytics_snapshot (
            snapshot_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            period_from TEXT NOT NULL,
            period_to TEXT NOT NULL,
            total_return_qty NUMERIC NOT NULL,
            return_value NUMERIC NOT NULL,
            damage_qty NUMERIC NOT NULL,
            damage_value NUMERIC NOT NULL,
            expired_qty NUMERIC NOT NULL,
            expired_value NUMERIC NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,location_id,period_from,period_to)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_return_snapshot_scope ON return_analytics_snapshot(entity_id,location_id,period_from,period_to)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
        perms = {
            "returns_mis.view": "View returns, damage and expiry MIS",
            "returns_mis.edit": "Create return analytics snapshots and repack/rework jobs",
            "rework.edit": "Complete repack/rework accounting jobs",
        }
        for pid, pname in perms.items():
            conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p": pid, "n": pname})
        for role in ("manager", "super_admin", "salesperson", "accounts", "costing", "production"):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'returns_mis.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})
        for role in ("manager", "super_admin", "accounts", "costing", "production"):
            for perm in ("returns_mis.edit", "rework.edit"):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role, "p": perm})


class SnapshotIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    period_from: str
    period_to: str


class ReworkJobIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    warehouse_id: UUID
    sales_return_id: UUID
    sales_return_line_id: UUID
    source_disposition: str = Field(min_length=5, max_length=20)
    input_qty: float = Field(gt=0)
    input_unit_cost: float | None = Field(default=None, ge=0)
    processing_cost: float = Field(default=0, ge=0)
    reference_no: str = Field(min_length=2, max_length=80)
    notes: str | None = Field(default=None, max_length=500)


class ReworkCompleteIn(BaseModel):
    output_qty: float = Field(gt=0)
    processing_cost: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=500)


def _require(engine, request: Request, entity_id: str, location_id: str, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, "permission denied")
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _parse_periods(period_from: str, period_to: str):
    try:
        start = datetime.fromisoformat(period_from)
        end = datetime.fromisoformat(period_to)
    except ValueError as exc:
        raise HTTPException(422, "invalid period date") from exc
    if end < start:
        raise HTTPException(422, "period_to must be on or after period_from")
    return start, end


def _cost_rate(conn, organization_id: str, entity_id: str, sku_id: str) -> float:
    row = conn.execute(text("""SELECT unit_cost FROM product_cost_rate
        WHERE organization_id=:o AND entity_id=:e AND item_master_id=:i AND uom='kg' AND active=1
        ORDER BY effective_from DESC, created_at DESC LIMIT 1"""), {"o": organization_id, "e": entity_id, "i": sku_id}).scalar()
    return float(row or 0)


def _analytics_rows(conn, organization_id: str, entity_id: str, location_id: str, period_from: str, period_to: str):
    rows = conn.execute(text("""SELECT
            r.sales_return_id, r.return_no, r.customer_id, r.warehouse_id,
            l.sales_return_line_id, l.sku_id, l.received_qty, l.disposition_status,
            d.disposition, d.quantity, d.reason, d.created_at
        FROM sales_returns r
        JOIN sales_return_lines l ON l.sales_return_id=r.sales_return_id
        JOIN return_disposition_history d ON d.sales_return_line_id=l.sales_return_line_id
        WHERE r.organization_id=:o AND r.entity_id=:e AND r.location_id=:l
          AND datetime(d.created_at) >= datetime(:f) AND datetime(d.created_at) <= datetime(:t)
        ORDER BY datetime(d.created_at), d.disposition_id"""), {
        "o": organization_id, "e": entity_id, "l": location_id, "f": period_from, "t": period_to
    }).mappings().all()
    return rows


def register_v90aw_routes(app: FastAPI, engine) -> None:
    ensure_v90aw_schema(engine)

    @app.get('/v90aw/returns/analytics')
    def return_analytics(organization_id: UUID, entity_id: UUID, location_id: UUID, period_from: str, period_to: str, request: Request):
        _parse_periods(period_from, period_to)
        _require(engine, request, str(entity_id), str(location_id), 'returns_mis.view')
        with engine.connect() as conn:
            rows = _analytics_rows(conn, str(organization_id), str(entity_id), str(location_id), period_from, period_to)
            credit_total = float(conn.execute(text("""SELECT COALESCE(SUM(grand_total),0) FROM return_credit_notes
                WHERE organization_id=:o AND entity_id=:e AND location_id=:l
                  AND datetime(created_at) >= datetime(:f) AND datetime(created_at) <= datetime(:t)"""), {
                'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id), 'f': period_from, 't': period_to
            }).scalar() or 0)
            rates = {}
            for row in rows:
                rates[row['sku_id']] = _cost_rate(conn, str(organization_id), str(entity_id), str(row['sku_id']))
        total_qty = sum(float(r['quantity']) for r in rows)
        saleable_qty = sum(float(r['quantity']) for r in rows if r['disposition'] == 'SALEABLE')
        repack_qty = sum(float(r['quantity']) for r in rows if r['disposition'] == 'REPACK')
        rework_qty = sum(float(r['quantity']) for r in rows if r['disposition'] == 'REWORK')
        damage_qty = sum(float(r['quantity']) for r in rows if r['disposition'] == 'DAMAGE')
        expired_qty = sum(float(r['quantity']) for r in rows if r['disposition'] == 'EXPIRED')
        dispose_qty = sum(float(r['quantity']) for r in rows if r['disposition'] == 'DISPOSE')
        damage_value = sum(float(r['quantity']) * rates.get(r['sku_id'], 0) for r in rows if r['disposition'] == 'DAMAGE')
        expired_value = sum(float(r['quantity']) * rates.get(r['sku_id'], 0) for r in rows if r['disposition'] == 'EXPIRED')
        by_disposition = {}
        by_sku = {}
        for r in rows:
            disp = r['disposition']; qty = float(r['quantity']); cost = qty * rates.get(r['sku_id'], 0)
            by_disposition.setdefault(disp, {'qty': 0.0, 'estimated_cost': 0.0})
            by_disposition[disp]['qty'] += qty; by_disposition[disp]['estimated_cost'] += cost
            sku = r['sku_id']
            by_sku.setdefault(sku, {'qty': 0.0, 'damage_qty': 0.0, 'expired_qty': 0.0, 'estimated_cost': 0.0})
            by_sku[sku]['qty'] += qty; by_sku[sku]['estimated_cost'] += cost
            if disp == 'DAMAGE': by_sku[sku]['damage_qty'] += qty
            if disp == 'EXPIRED': by_sku[sku]['expired_qty'] += qty
        for v in by_disposition.values(): v['qty'] = _money(v['qty']); v['estimated_cost'] = _money(v['estimated_cost'])
        for v in by_sku.values():
            for k in v: v[k] = _money(v[k])
        return {
            'period_from': period_from, 'period_to': period_to,
            'total_return_qty': _money(total_qty), 'return_credit_value': _money(credit_total),
            'saleable_qty': _money(saleable_qty), 'repack_qty': _money(repack_qty), 'rework_qty': _money(rework_qty),
            'damage_qty': _money(damage_qty), 'damage_estimated_cost': _money(damage_value),
            'expired_qty': _money(expired_qty), 'expired_estimated_cost': _money(expired_value),
            'dispose_qty': _money(dispose_qty), 'by_disposition': by_disposition, 'by_sku': by_sku,
            'rows': [dict(r) for r in rows]
        }

    @app.get('/v90aw/returns/damage-expiry')
    def damage_expiry(organization_id: UUID, entity_id: UUID, location_id: UUID, period_from: str, period_to: str, request: Request):
        data = return_analytics(organization_id, entity_id, location_id, period_from, period_to, request)
        return {
            'period_from': period_from, 'period_to': period_to,
            'damage_qty': data['damage_qty'], 'damage_estimated_cost': data['damage_estimated_cost'],
            'expired_qty': data['expired_qty'], 'expired_estimated_cost': data['expired_estimated_cost'],
            'dispose_qty': data['dispose_qty'],
            'damage_and_expiry_qty': _money(data['damage_qty'] + data['expired_qty']),
            'damage_and_expiry_estimated_cost': _money(data['damage_estimated_cost'] + data['expired_estimated_cost']),
            'by_sku': {k: v for k, v in data['by_sku'].items() if v['damage_qty'] or v['expired_qty']}
        }

    @app.post('/v90aw/returns/analytics/snapshots')
    def create_snapshot(body: SnapshotIn, request: Request):
        _parse_periods(body.period_from, body.period_to)
        user = _require(engine, request, str(body.entity_id), str(body.location_id), 'returns_mis.edit')
        data = return_analytics(body.organization_id, body.entity_id, body.location_id, body.period_from, body.period_to, request)
        sid = str(uuid4())
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT snapshot_id FROM return_analytics_snapshot WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND period_from=:f AND period_to=:t"), {
                'o': str(body.organization_id), 'e': str(body.entity_id), 'l': str(body.location_id), 'f': body.period_from, 't': body.period_to
            }).scalar()
            if existing:
                return {'status': 'EXISTS', 'snapshot_id': existing}
            conn.execute(text("""INSERT INTO return_analytics_snapshot
                (snapshot_id,organization_id,entity_id,location_id,period_from,period_to,total_return_qty,return_value,damage_qty,damage_value,expired_qty,expired_value,created_by)
                VALUES(:id,:o,:e,:l,:f,:t,:q,:rv,:dq,:dv,:eq,:ev,:u)"""), {
                'id': sid, 'o': str(body.organization_id), 'e': str(body.entity_id), 'l': str(body.location_id),
                'f': body.period_from, 't': body.period_to, 'q': data['total_return_qty'], 'rv': data['return_credit_value'],
                'dq': data['damage_qty'], 'dv': data['damage_estimated_cost'], 'eq': data['expired_qty'], 'ev': data['expired_estimated_cost'], 'u': str(user.user_id)
            })
        return {'status': 'SNAPSHOT_CREATED', 'snapshot_id': sid, 'metrics': {k: data[k] for k in ('total_return_qty','return_credit_value','damage_qty','damage_estimated_cost','expired_qty','expired_estimated_cost')}}

    @app.get('/v90aw/returns/analytics/snapshots')
    def list_snapshots(organization_id: UUID, entity_id: UUID, location_id: UUID, request: Request):
        _require(engine, request, str(entity_id), str(location_id), 'returns_mis.view')
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM return_analytics_snapshot WHERE organization_id=:o AND entity_id=:e AND location_id=:l ORDER BY period_from DESC"), {
                'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)
            }).mappings().all()
        return {'items': [dict(x) for x in rows]}

    @app.post('/v90aw/repack-rework/jobs')
    def create_rework_job(body: ReworkJobIn, request: Request):
        disposition = body.source_disposition.strip().upper()
        if disposition not in _ALLOWED_REWORK:
            raise HTTPException(422, 'source_disposition must be REPACK or REWORK')
        user = _require(engine, request, str(body.entity_id), str(body.location_id), 'returns_mis.edit')
        with engine.connect() as conn:
            row = conn.execute(text("""SELECT r.*, l.*, COALESCE(SUM(CASE WHEN d.disposition=:disp THEN d.quantity ELSE 0 END),0) AS disposition_qty
                FROM sales_returns r JOIN sales_return_lines l ON l.sales_return_id=r.sales_return_id
                LEFT JOIN return_disposition_history d ON d.sales_return_line_id=l.sales_return_line_id
                WHERE r.sales_return_id=:r AND l.sales_return_line_id=:l
                GROUP BY l.sales_return_line_id"""), {
                'r': str(body.sales_return_id), 'l': str(body.sales_return_line_id), 'disp': disposition
            }).mappings().first()
            if not row:
                raise HTTPException(404, 'return line not found')
            if str(row['entity_id']) != str(body.entity_id) or str(row['location_id']) != str(body.location_id) or str(row['warehouse_id']) != str(body.warehouse_id):
                raise HTTPException(409, 'return scope does not match job scope')
            used = float(conn.execute(text("""SELECT COALESCE(SUM(input_qty),0) FROM repack_rework_jobs
                WHERE sales_return_line_id=:l AND source_disposition=:d AND status IN ('OPEN','IN_PROGRESS','COMPLETED')"""), {'l': str(body.sales_return_line_id), 'd': disposition}).scalar() or 0)
            available = max(float(row['disposition_qty']) - used, 0.0)
            if body.input_qty > available + 1e-9:
                raise HTTPException(409, f'{disposition} quantity exceeds remaining disposed quantity')
            unit_cost = body.input_unit_cost
            if unit_cost is None:
                unit_cost = _cost_rate(conn, str(body.organization_id), str(body.entity_id), str(row['sku_id']))
        job_id = str(uuid4()); input_cost = float(body.input_qty) * float(unit_cost or 0)
        with engine.begin() as conn:
            dup = conn.execute(text('SELECT job_id FROM repack_rework_jobs WHERE organization_id=:o AND entity_id=:e AND reference_no=:n'), {'o':str(body.organization_id),'e':str(body.entity_id),'n':body.reference_no}).scalar()
            if dup: raise HTTPException(409, 'reference_no already exists')
            conn.execute(text("""INSERT INTO repack_rework_jobs
                (job_id,organization_id,entity_id,location_id,warehouse_id,sales_return_id,sales_return_line_id,source_disposition,sku_id,source_lot_id,input_qty,input_unit_cost,processing_cost,input_cost,total_cost,status,reference_no,notes,created_by)
                VALUES(:id,:o,:e,:l,:w,:r,:rl,:d,:s,:lot,:q,:uc,:pc,:ic,:tc,'OPEN',:ref,:n,:u)"""), {
                'id':job_id,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id),
                'r':str(body.sales_return_id),'rl':str(body.sales_return_line_id),'d':disposition,'s':str(row['sku_id']),'lot':str(row['packed_fg_lot_id']),
                'q':body.input_qty,'uc':unit_cost or 0,'pc':body.processing_cost,'ic':input_cost,'tc':input_cost+body.processing_cost,
                'ref':body.reference_no,'n':body.notes,'u':str(user.user_id)
            })
        return {'status':'OPEN','job_id':job_id,'input_qty':body.input_qty,'input_unit_cost':_money(unit_cost),'input_cost':_money(input_cost),'processing_cost':_money(body.processing_cost),'total_cost':_money(input_cost+body.processing_cost)}

    @app.post('/v90aw/repack-rework/jobs/{job_id}/complete')
    def complete_rework_job(job_id: UUID, body: ReworkCompleteIn, request: Request):
        with engine.connect() as conn:
            job = conn.execute(text('SELECT * FROM repack_rework_jobs WHERE job_id=:j'), {'j':str(job_id)}).mappings().first()
            if not job: raise HTTPException(404, 'repack/rework job not found')
        user = _require(engine, request, str(job['entity_id']), str(job['location_id']), 'rework.edit')
        if str(job['status']) not in _ACTIVE_STATUSES:
            raise HTTPException(409, f'job cannot be completed in status {job["status"]}')
        if body.output_qty > float(job['input_qty']) + 1e-9:
            raise HTTPException(409, 'output quantity cannot exceed input quantity')
        processing = float(job['processing_cost']) if body.processing_cost is None else float(body.processing_cost)
        loss = float(job['input_qty']) - float(body.output_qty)
        total = float(job['input_cost']) + processing
        unit = total / float(body.output_qty)
        with engine.begin() as conn:
            conn.execute(text("""UPDATE repack_rework_jobs SET output_qty=:oq,loss_qty=:loss,processing_cost=:pc,total_cost=:tc,output_unit_cost=:uc,status='COMPLETED',notes=COALESCE(:n,notes),completed_by=:u,completed_at=:at WHERE job_id=:j"""), {
                'oq':body.output_qty,'loss':loss,'pc':processing,'tc':total,'uc':unit,'n':body.notes,'u':str(user.user_id),'at':_now(),'j':str(job_id)
            })
        return {'status':'COMPLETED','job_id':str(job_id),'input_qty':_money(job['input_qty']),'output_qty':_money(body.output_qty),'loss_qty':_money(loss),'total_cost':_money(total),'output_unit_cost':_money(unit)}

    @app.get('/v90aw/repack-rework/jobs')
    def list_rework_jobs(organization_id: UUID, entity_id: UUID, location_id: UUID, request: Request, status: str | None = None):
        _require(engine, request, str(entity_id), str(location_id), 'returns_mis.view')
        params={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        sql='SELECT * FROM repack_rework_jobs WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        if status:
            sql+=' AND status=:s'; params['s']=status.upper()
        sql+=' ORDER BY created_at DESC'
        with engine.connect() as conn: rows=conn.execute(text(sql),params).mappings().all()
        return {'items':[dict(x) for x in rows]}
