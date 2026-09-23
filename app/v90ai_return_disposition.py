from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_v90ai_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS return_disposition_history (
            disposition_id TEXT PRIMARY KEY,
            sales_return_id TEXT NOT NULL,
            sales_return_line_id TEXT NOT NULL,
            return_hold_id TEXT NOT NULL,
            disposition TEXT NOT NULL,
            quantity NUMERIC NOT NULL,
            reason TEXT NULL,
            approved_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_return_disposition_line ON return_disposition_history(sales_return_line_id,created_at)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
        conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('returns.approve','Approve return disposition') ON CONFLICT(permission_id) DO NOTHING"))
        for role in ('manager', 'super_admin'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'returns.approve') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})


class DispositionIn(BaseModel):
    disposition: str = Field(min_length=3, max_length=30)
    quantity: float = Field(gt=0)
    reason: str | None = Field(default=None, max_length=500)


_ALLOWED = {'SALEABLE', 'REPACK', 'REWORK', 'DAMAGE', 'EXPIRED', 'DISPOSE'}


def _require(engine, request: Request, entity_id: str, location_id: str, approval: bool = False):
    user = authenticate(request)
    needed = 'returns.approve' if approval else 'returns.edit'
    if needed not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def register_v90ai_routes(app: FastAPI, engine) -> None:
    ensure_v90ai_schema(engine)

    @app.post('/v90ai/returns/{sales_return_id}/lines/{sales_return_line_id}/disposition')
    def set_disposition(sales_return_id: UUID, sales_return_line_id: UUID, body: DispositionIn, request: Request):
        disposition = body.disposition.strip().upper()
        if disposition not in _ALLOWED:
            raise HTTPException(422, f'disposition must be one of {sorted(_ALLOWED)}')
        with engine.connect() as conn:
            row = conn.execute(text("""SELECT r.*, l.*, h.return_hold_id, h.status AS hold_status, h.quantity AS hold_qty
                                      FROM sales_returns r
                                      JOIN sales_return_lines l ON l.sales_return_id=r.sales_return_id
                                      JOIN return_hold_lots h ON h.sales_return_line_id=l.sales_return_line_id
                                      WHERE r.sales_return_id=:r AND l.sales_return_line_id=:l
                                      ORDER BY h.created_at DESC LIMIT 1"""), {'r': str(sales_return_id), 'l': str(sales_return_line_id)}).mappings().first()
            if not row:
                raise HTTPException(404, 'return line/hold not found')
        user = _require(engine, request, str(row['entity_id']), str(row['location_id']), approval=True)
        if str(row['status']) != 'RECEIVED_QC_HOLD':
            raise HTTPException(409, f'return is not awaiting disposition: {row["status"]}')
        if str(row['hold_status']) != 'QC_HOLD':
            raise HTTPException(409, f'return hold is not open: {row["hold_status"]}')
        if float(body.quantity) > float(row['hold_qty']) + 1e-9:
            raise HTTPException(409, 'disposition quantity exceeds held return quantity')
        # An open hold may be split across multiple dispositions, but total disposed cannot exceed hold quantity.
        with engine.connect() as conn:
            prior = float(conn.execute(text("SELECT COALESCE(SUM(quantity),0) FROM return_disposition_history WHERE return_hold_id=:h"), {'h': str(row['return_hold_id'])}).scalar() or 0)
        remaining = float(row['hold_qty']) - prior
        if body.quantity > remaining + 1e-9:
            raise HTTPException(409, 'disposition quantity exceeds remaining held quantity')

        disp_id = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO return_disposition_history(disposition_id,sales_return_id,sales_return_line_id,return_hold_id,disposition,quantity,reason,approved_by,created_at)
                                VALUES(:id,:r,:l,:h,:d,:q,:reason,:u,:at)"""), {'id': disp_id, 'r': str(sales_return_id), 'l': str(sales_return_line_id), 'h': str(row['return_hold_id']), 'd': disposition, 'q': body.quantity, 'reason': body.reason, 'u': str(user.user_id), 'at': _now()})
            if disposition == 'SALEABLE':
                conn.execute(text("""INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty,updated_at)
                    VALUES(:o,:e,:l,:w,:i,'kg',:q,CURRENT_TIMESTAMP)
                    ON CONFLICT(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom)
                    DO UPDATE SET available_qty=inventory_stock_balance.available_qty+excluded.available_qty, updated_at=CURRENT_TIMESTAMP"""), {'o': row['organization_id'], 'e': row['entity_id'], 'l': row['location_id'], 'w': row['warehouse_id'], 'i': row['sku_id'], 'q': body.quantity})
                conn.execute(text("""INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by)
                    VALUES(:id,:o,:e,:l,:w,:i,:lot,'RETURN_IN',:q,'kg','SALES_RETURN',:r,'POSTED',:u)"""), {'id': str(uuid4()), 'o': row['organization_id'], 'e': row['entity_id'], 'l': row['location_id'], 'w': row['warehouse_id'], 'i': row['sku_id'], 'lot': row['packed_fg_lot_id'], 'q': body.quantity, 'r': str(sales_return_id), 'u': str(user.user_id)})
                conn.execute(text("UPDATE packed_fg_lot SET available_qty=available_qty+:q, status='AVAILABLE', qc_status='RELEASED' WHERE packed_fg_lot_id=:lot"), {'q': body.quantity, 'lot': row['packed_fg_lot_id']})
            elif disposition in {'REPACK', 'REWORK'}:
                # Remains outside saleable stock; downstream rework/repack modules can consume these held quantities.
                pass
            else:
                # Damage/expired/dispose are explicitly non-saleable. Record only the disposition history now.
                pass
            consumed = prior + float(body.quantity)
            if consumed >= float(row['hold_qty']) - 1e-9:
                conn.execute(text("UPDATE return_hold_lots SET status='DISPOSED' WHERE return_hold_id=:h"), {'h': str(row['return_hold_id'])})
                conn.execute(text("UPDATE sales_return_lines SET disposition_status=:d WHERE sales_return_line_id=:l"), {'d': disposition, 'l': str(sales_return_line_id)})
            else:
                conn.execute(text("UPDATE sales_return_lines SET disposition_status='PARTIALLY_DISPOSED' WHERE sales_return_line_id=:l"), {'l': str(sales_return_line_id)})

            unresolved = conn.execute(text("SELECT COUNT(*) FROM sales_return_lines WHERE sales_return_id=:r AND disposition_status IN ('QC_HOLD','PARTIALLY_DISPOSED')"), {'r': str(sales_return_id)}).scalar_one()
            if int(unresolved) == 0:
                conn.execute(text("UPDATE sales_returns SET status='DISPOSITIONED' WHERE sales_return_id=:r"), {'r': str(sales_return_id)})

        return {'disposition_id': disp_id, 'sales_return_id': str(sales_return_id), 'sales_return_line_id': str(sales_return_line_id), 'disposition': disposition, 'quantity': body.quantity}

    @app.get('/v90ai/returns/{sales_return_id}/dispositions')
    def list_dispositions(sales_return_id: UUID, request: Request):
        with engine.connect() as conn:
            ret = conn.execute(text('SELECT entity_id,location_id FROM sales_returns WHERE sales_return_id=:r'), {'r': str(sales_return_id)}).mappings().first()
            if not ret:
                raise HTTPException(404, 'sales return not found')
        _require(engine, request, str(ret['entity_id']), str(ret['location_id']), approval=False)
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM return_disposition_history WHERE sales_return_id=:r ORDER BY created_at, disposition_id"), {'r': str(sales_return_id)}).mappings().all()
        return {'items': [dict(x) for x in rows]}
