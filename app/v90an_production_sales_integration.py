from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text

from .auth import authenticate
from .master_scope import assert_entity_location_allowed
from .identity import permissions_for_user


def ensure_v90an_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS e2e_integration_validation (
            validation_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            sales_order_id TEXT,
            production_batch_id TEXT,
            fg_lot_id TEXT,
            packing_run_id TEXT,
            packed_fg_lot_id TEXT,
            validation_status TEXT NOT NULL,
            production_status TEXT,
            production_qc_status TEXT,
            fg_status TEXT,
            packing_status TEXT,
            packing_qc_status TEXT,
            sales_status TEXT,
            allocation_status TEXT,
            pick_status TEXT,
            dispatch_status TEXT,
            invoice_status TEXT,
            failure_count INTEGER NOT NULL DEFAULT 0,
            validated_by TEXT NOT NULL,
            validated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS ix_e2e_validation_scope ON e2e_integration_validation(entity_id, location_id, validation_status, validated_at)",
        "CREATE INDEX IF NOT EXISTS ix_e2e_validation_order ON e2e_integration_validation(sales_order_id, validated_at)",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('integration.view','View end-to-end integration status') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('integration.validate','Validate end-to-end production/sales flow') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def _require(engine, request: Request, entity_id: str, location_id: str, write: bool = False):
    user = authenticate(request)
    permissions = permissions_for_user(engine, user.user_id)
    needed = 'integration.validate' if write else 'integration.view'
    if needed not in permissions:
        # Management/operational roles already have the underlying permissions; do not create a new blocker.
        if not (('production.edit' in permissions or 'sales.edit' in permissions or 'dispatch.view' in permissions) if not write else ('production.edit' in permissions and 'sales.edit' in permissions)):
            raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _first(conn, sql: str, **params):
    return conn.execute(text(sql), params).mappings().first()


def _one(conn, sql: str, **params):
    return conn.execute(text(sql), params).scalar()


def register_v90an_routes(app: FastAPI, engine) -> None:
    ensure_v90an_schema(engine)

    @app.get('/v90an/integration/sales-orders/{sales_order_id}/trace')
    def integration_trace(sales_order_id: UUID, request: Request):
        with engine.connect() as conn:
            order = _first(conn, 'SELECT * FROM sales_orders WHERE sales_order_id=:id', id=str(sales_order_id))
            if not order:
                raise HTTPException(404, 'sales order not found')
            _require(engine, request, str(order['entity_id']), str(order['location_id']), False)

            allocations = conn.execute(text('SELECT * FROM sales_order_allocations WHERE sales_order_id=:id ORDER BY created_at'), {'id': str(sales_order_id)}).mappings().all()
            picks = conn.execute(text('SELECT * FROM dispatch_pick_lists WHERE sales_order_id=:id ORDER BY created_at DESC'), {'id': str(sales_order_id)}).mappings().all()
            dispatch = _first(conn, 'SELECT * FROM dispatches WHERE sales_order_id=:id ORDER BY posted_at DESC', id=str(sales_order_id))
            invoice = _first(conn, 'SELECT * FROM sales_invoices WHERE sales_order_id=:id ORDER BY created_at DESC', id=str(sales_order_id))

            packed = []
            production_batches = []
            for allocation in allocations:
                lot = _first(conn, 'SELECT * FROM packed_fg_lot WHERE packed_fg_lot_id=:id', id=str(allocation['packed_fg_lot_id']))
                if lot:
                    packed.append(dict(lot))
                    run = _first(conn, 'SELECT * FROM packing_run WHERE packing_run_id=:id', id=str(lot['packing_run_id']))
                    if run:
                        fg = _first(conn, 'SELECT * FROM finished_goods_lot WHERE fg_lot_id=:id', id=str(run['source_fg_lot_id']))
                        if fg:
                            batch = _first(conn, 'SELECT * FROM production_batch WHERE batch_id=:id', id=str(fg['batch_id']))
                            if batch:
                                production_batches.append(dict(batch))

            return {
                'sales_order': dict(order),
                'production_batches': production_batches,
                'packed_fg_lots': packed,
                'allocations': [dict(x) for x in allocations],
                'pick_lists': [dict(x) for x in picks],
                'dispatch': dict(dispatch) if dispatch else None,
                'invoice': dict(invoice) if invoice else None,
            }

    @app.post('/v90an/integration/sales-orders/{sales_order_id}/validate')
    def validate_sales_order_flow(sales_order_id: UUID, request: Request):
        with engine.connect() as conn:
            order = _first(conn, 'SELECT * FROM sales_orders WHERE sales_order_id=:id', id=str(sales_order_id))
            if not order:
                raise HTTPException(404, 'sales order not found')
            user = _require(engine, request, str(order['entity_id']), str(order['location_id']), True)

            allocation = _first(conn, "SELECT * FROM sales_order_allocations WHERE sales_order_id=:id AND status IN ('ALLOCATED','DISPATCHED') ORDER BY created_at", id=str(sales_order_id))
            pick = _first(conn, "SELECT * FROM dispatch_pick_lists WHERE sales_order_id=:id AND status='PICKED' ORDER BY created_at DESC", id=str(sales_order_id))
            dispatch = _first(conn, "SELECT * FROM dispatches WHERE sales_order_id=:id AND status='POSTED' ORDER BY posted_at DESC", id=str(sales_order_id))
            invoice = _first(conn, "SELECT * FROM sales_invoices WHERE sales_order_id=:id AND status='POSTED' ORDER BY created_at DESC", id=str(sales_order_id))

            packed_lot = None
            packing_run = None
            fg_lot = None
            batch = None
            production_qc = None
            if allocation:
                packed_lot = _first(conn, 'SELECT * FROM packed_fg_lot WHERE packed_fg_lot_id=:id', id=str(allocation['packed_fg_lot_id']))
            if packed_lot:
                packing_run = _first(conn, 'SELECT * FROM packing_run WHERE packing_run_id=:id', id=str(packed_lot['packing_run_id']))
            if packing_run:
                fg_lot = _first(conn, 'SELECT * FROM finished_goods_lot WHERE fg_lot_id=:id', id=str(packing_run['source_fg_lot_id']))
            if fg_lot:
                batch = _first(conn, 'SELECT * FROM production_batch WHERE batch_id=:id', id=str(fg_lot['batch_id']))
                production_qc = _first(conn, "SELECT * FROM production_process_qc_decision WHERE batch_id=:id ORDER BY decided_at DESC", id=str(fg_lot['batch_id']))

        checks = []
        def check(name, condition, detail):
            checks.append({'check': name, 'passed': bool(condition), 'detail': detail})

        check('sales_order_approved_or_dispatched', str(order['status']) in {'APPROVED','DISPATCHED'}, str(order['status']))
        check('production_batch_exists', batch is not None, 'production batch linked through FG lot')
        check('production_batch_completed', batch is not None and str(batch.get('status')) == 'COMPLETED', str(batch.get('status')) if batch else 'missing')
        check('production_qc_released', production_qc is not None and str(production_qc.get('decision')) == 'RELEASE', str(production_qc.get('decision')) if production_qc else 'missing')
        check('fg_released', fg_lot is not None and str(fg_lot.get('qc_status')) == 'RELEASED' and str(fg_lot.get('status')) in {'AVAILABLE','ALLOCATED','DISPATCHED'}, str(fg_lot.get('status')) if fg_lot else 'missing')
        check('packing_completed', packing_run is not None and str(packing_run.get('status')) == 'COMPLETED', str(packing_run.get('status')) if packing_run else 'missing')
        check('packing_qc_released', packed_lot is not None and str(packed_lot.get('qc_status')) == 'RELEASED', str(packed_lot.get('qc_status')) if packed_lot else 'missing')
        check('stock_allocated', allocation is not None, str(allocation.get('status')) if allocation else 'missing')
        check('pick_confirmed', pick is not None, 'PICKED' if pick else 'missing')
        check('dispatch_posted', dispatch is not None, 'POSTED' if dispatch else 'missing')
        check('invoice_posted', invoice is not None, 'POSTED' if invoice else 'missing')

        failures = [c for c in checks if not c['passed']]
        status = 'PASS' if not failures else 'FAIL'
        validation_id = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO e2e_integration_validation(
                validation_id,organization_id,entity_id,location_id,sales_order_id,
                production_batch_id,fg_lot_id,packing_run_id,packed_fg_lot_id,
                validation_status,production_status,production_qc_status,fg_status,
                packing_status,packing_qc_status,sales_status,allocation_status,
                pick_status,dispatch_status,invoice_status,failure_count,validated_by,notes
            ) VALUES (:vid,:org,:ent,:loc,:so,:batch,:fg,:pr,:pfg,:status,:prod,:prodqc,:fgst,:pack,:packqc,:sales,:alloc,:pick,:disp,:inv,:fc,:by,:notes)"""), {
                'vid': validation_id,
                'org': str(order['organization_id']), 'ent': str(order['entity_id']), 'loc': str(order['location_id']),
                'so': str(sales_order_id), 'batch': str(batch['batch_id']) if batch else None, 'fg': str(fg_lot['fg_lot_id']) if fg_lot else None,
                'pr': str(packing_run['packing_run_id']) if packing_run else None, 'pfg': str(packed_lot['packed_fg_lot_id']) if packed_lot else None,
                'status': status, 'prod': str(batch['status']) if batch else None,
                'prodqc': str(production_qc['decision']) if production_qc else None, 'fgst': str(fg_lot['status']) if fg_lot else None,
                'pack': str(packing_run['status']) if packing_run else None, 'packqc': str(packed_lot['qc_status']) if packed_lot else None,
                'sales': str(order['status']), 'alloc': str(allocation['status']) if allocation else None, 'pick': str(pick['status']) if pick else None,
                'disp': str(dispatch['status']) if dispatch else None, 'inv': str(invoice['status']) if invoice else None,
                'fc': len(failures), 'by': user.user_id,
                'notes': '; '.join(f"{x['check']}: {x['detail']}" for x in failures) or 'All integration checks passed'
            })

        return {'validation_id': validation_id, 'status': status, 'failure_count': len(failures), 'checks': checks, 'validated_at': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}
