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


def _require(engine, request: Request, entity_id: str, location_id: str, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90ax_schema(engine):
    # Runtime-safe for SQLite test harnesses; production migration is PostgreSQL-only.
    with engine.begin() as conn:
        for stmt in (
            "CREATE TABLE IF NOT EXISTS transporters (transporter_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, transporter_code TEXT NOT NULL, transporter_name TEXT NOT NULL, phone TEXT NULL, gstin TEXT NULL, active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,transporter_code))",
            "CREATE TABLE IF NOT EXISTS dispatch_delivery_assignments (assignment_id TEXT PRIMARY KEY, dispatch_id TEXT NOT NULL, transporter_id TEXT NULL, transporter_name TEXT NULL, vehicle_no TEXT NULL, driver_name TEXT NULL, driver_phone TEXT NULL, eway_bill_no TEXT NULL, assigned_by TEXT NOT NULL, assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL DEFAULT 'ASSIGNED', UNIQUE(dispatch_id))",
            "CREATE TABLE IF NOT EXISTS dispatch_reconciliation (reconciliation_id TEXT PRIMARY KEY, sales_order_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL, ordered_qty NUMERIC NOT NULL DEFAULT 0, dispatched_qty NUMERIC NOT NULL DEFAULT 0, backorder_qty NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL, reconciled_by TEXT NOT NULL, reconciled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(sales_order_id))",
            "CREATE TABLE IF NOT EXISTS dispatch_pod (pod_id TEXT PRIMARY KEY, dispatch_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL, received_by TEXT NULL, received_at TEXT NULL, pod_reference TEXT NULL, attachment_ref TEXT NULL, notes TEXT NULL, status TEXT NOT NULL DEFAULT 'PENDING', captured_by TEXT NOT NULL, captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS sales_order_backorders (backorder_id TEXT PRIMARY KEY, sales_order_id TEXT NOT NULL, sales_order_line_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL, sku_id TEXT NOT NULL, ordered_qty NUMERIC NOT NULL, dispatched_qty NUMERIC NOT NULL, backorder_qty NUMERIC NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', reason TEXT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, closed_at TEXT NULL, UNIQUE(sales_order_id,sales_order_line_id))",
        ):
            conn.execute(text(stmt))
        perms = {
            'dispatch_mis.view':'View dispatch reconciliation and delivery MIS',
            'dispatch_mis.edit':'Edit transporter, delivery assignment and backorder records',
            'pod.edit':'Capture delivery proof/POD',
        }
        for pid, name in perms.items():
            conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p':pid,'n':name})
        for role in ('manager','super_admin','salesperson','accounts','mis'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'dispatch_mis.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})
        for role in ('manager','super_admin','salesperson'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'dispatch_mis.edit') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})
        for role in ('manager','super_admin','salesperson','dispatch'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'pod.edit') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})


class TransporterIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    transporter_code: str = Field(min_length=2, max_length=50)
    transporter_name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    gstin: str | None = Field(default=None, max_length=30)


class AssignmentIn(BaseModel):
    transporter_id: UUID | None = None
    transporter_name: str | None = Field(default=None, max_length=120)
    vehicle_no: str | None = Field(default=None, max_length=40)
    driver_name: str | None = Field(default=None, max_length=120)
    driver_phone: str | None = Field(default=None, max_length=30)
    eway_bill_no: str | None = Field(default=None, max_length=80)


class PodIn(BaseModel):
    received_by: str | None = Field(default=None, max_length=120)
    received_at: str | None = None
    pod_reference: str | None = Field(default=None, max_length=120)
    attachment_ref: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


def register_v90ax_routes(app: FastAPI, engine):
    ensure_v90ax_schema(engine)

    @app.post('/v90ax/transporters')
    def create_transporter(body: TransporterIn, request: Request):
        user = authenticate(request)
        if 'dispatch_mis.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.begin() as conn:
            dup = conn.execute(text('SELECT transporter_id FROM transporters WHERE organization_id=:o AND entity_id=:e AND transporter_code=:c'), {'o':str(body.organization_id),'e':str(body.entity_id),'c':body.transporter_code}).first()
            if dup: raise HTTPException(409,'transporter code already exists')
            tid = str(uuid4())
            conn.execute(text('INSERT INTO transporters(transporter_id,organization_id,entity_id,transporter_code,transporter_name,phone,gstin,created_by) VALUES(:i,:o,:e,:c,:n,:p,:g,:u)'), {'i':tid,'o':str(body.organization_id),'e':str(body.entity_id),'c':body.transporter_code,'n':body.transporter_name,'p':body.phone,'g':body.gstin,'u':user.user_id})
        return {'transporter_id':tid,'status':'ACTIVE'}

    @app.get('/v90ax/transporters')
    def list_transporters(organization_id: UUID, entity_id: UUID, request: Request):
        user = authenticate(request)
        if 'dispatch_mis.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        if not is_entity_allowed(engine, user.user_id, str(entity_id)) and user.role != 'super_admin':
            raise HTTPException(403, 'entity access denied')
        with engine.connect() as conn:
            rows=conn.execute(text('SELECT * FROM transporters WHERE organization_id=:o AND entity_id=:e AND active=1 ORDER BY transporter_name'), {'o':str(organization_id),'e':str(entity_id)}).mappings().all()
        return {'items':[dict(r) for r in rows]}

    @app.post('/v90ax/dispatches/{dispatch_id}/assignment')
    def assign_dispatch(dispatch_id: UUID, body: AssignmentIn, request: Request):
        with engine.connect() as conn:
            d=conn.execute(text('SELECT * FROM dispatches WHERE dispatch_id=:d'),{'d':str(dispatch_id)}).mappings().first()
            if not d: raise HTTPException(404,'dispatch not found')
        user=_require(engine,request,str(d['entity_id']),str(d['location_id']),'dispatch_mis.edit')
        if body.transporter_id:
            with engine.connect() as conn:
                t=conn.execute(text('SELECT transporter_name FROM transporters WHERE transporter_id=:t AND organization_id=:o AND entity_id=:e AND active=1'),{'t':str(body.transporter_id),'o':str(d['organization_id']),'e':str(d['entity_id'])}).first()
            if not t: raise HTTPException(422,'transporter not found in entity scope')
            tname=t[0]
        else: tname=body.transporter_name
        if not tname and not body.vehicle_no: raise HTTPException(422,'transporter or vehicle is required')
        aid=str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO dispatch_delivery_assignments(assignment_id,dispatch_id,transporter_id,transporter_name,vehicle_no,driver_name,driver_phone,eway_bill_no,assigned_by)
                VALUES(:i,:d,:t,:n,:v,:dn,:dp,:ew,:u)
                ON CONFLICT(dispatch_id) DO UPDATE SET transporter_id=excluded.transporter_id,transporter_name=excluded.transporter_name,vehicle_no=excluded.vehicle_no,driver_name=excluded.driver_name,driver_phone=excluded.driver_phone,eway_bill_no=excluded.eway_bill_no,assigned_by=excluded.assigned_by,assigned_at=CURRENT_TIMESTAMP,status='ASSIGNED'"""), {'i':aid,'d':str(dispatch_id),'t':str(body.transporter_id) if body.transporter_id else None,'n':tname,'v':body.vehicle_no,'dn':body.driver_name,'dp':body.driver_phone,'ew':body.eway_bill_no,'u':user.user_id})
        return {'dispatch_id':str(dispatch_id),'status':'ASSIGNED','transporter_name':tname,'vehicle_no':body.vehicle_no,'eway_bill_no':body.eway_bill_no}

    @app.get('/v90ax/sales/orders/{sales_order_id}/reconciliation')
    def reconcile_order(sales_order_id: UUID, request: Request):
        with engine.connect() as conn:
            order=conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:s'),{'s':str(sales_order_id)}).mappings().first()
            if not order: raise HTTPException(404,'sales order not found')
            lines=conn.execute(text('SELECT sales_order_line_id,sku_id,quantity FROM sales_order_lines WHERE sales_order_id=:s'),{'s':str(sales_order_id)}).mappings().all()
            dispatched=conn.execute(text('SELECT dl.sales_order_line_id,COALESCE(SUM(dl.dispatched_qty),0) qty FROM dispatches d JOIN dispatch_lines dl ON dl.dispatch_id=d.dispatch_id WHERE d.sales_order_id=:s AND d.status=\'POSTED\' GROUP BY dl.sales_order_line_id'),{'s':str(sales_order_id)}).mappings().all()
        _require(engine,request,str(order['entity_id']),str(order['location_id']),'dispatch_mis.view')
        dmap={str(x['sales_order_line_id']):float(x['qty']) for x in dispatched}
        result=[]; total_o=total_d=0.0
        for l in lines:
            o=float(l['quantity']); d=min(dmap.get(str(l['sales_order_line_id']),0.0),o); b=max(o-d,0.0); total_o+=o; total_d+=d
            result.append({'sales_order_line_id':str(l['sales_order_line_id']),'sku_id':str(l['sku_id']),'ordered_qty':o,'dispatched_qty':d,'backorder_qty':b})
        back=max(total_o-total_d,0.0); status='FULLY_DISPATCHED' if back<=0 else ('PARTIALLY_DISPATCHED' if total_d>0 else 'NOT_DISPATCHED')
        user=authenticate(request)
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO dispatch_reconciliation(reconciliation_id,sales_order_id,organization_id,entity_id,location_id,ordered_qty,dispatched_qty,backorder_qty,status,reconciled_by) VALUES(:i,:s,:o,:e,:l,:oq,:dq,:b,:st,:u) ON CONFLICT(sales_order_id) DO UPDATE SET ordered_qty=excluded.ordered_qty,dispatched_qty=excluded.dispatched_qty,backorder_qty=excluded.backorder_qty,status=excluded.status,reconciled_by=excluded.reconciled_by,reconciled_at=CURRENT_TIMESTAMP'), {'i':str(uuid4()),'s':str(sales_order_id),'o':str(order['organization_id']),'e':str(order['entity_id']),'l':str(order['location_id']),'oq':total_o,'dq':total_d,'b':back,'st':status,'u':user.user_id})
            for item in result:
                if item['backorder_qty']>0:
                    conn.execute(text("""INSERT INTO sales_order_backorders(backorder_id,sales_order_id,sales_order_line_id,organization_id,entity_id,location_id,sku_id,ordered_qty,dispatched_qty,backorder_qty,status,reason,created_by)
                        VALUES(:i,:s,:sl,:o,:e,:l,:sku,:oq,:dq,:b,'OPEN',:r,:u)
                        ON CONFLICT(sales_order_id,sales_order_line_id) DO UPDATE SET ordered_qty=excluded.ordered_qty,dispatched_qty=excluded.dispatched_qty,backorder_qty=excluded.backorder_qty,status='OPEN',reason=excluded.reason"""), {'i':str(uuid4()),'s':str(sales_order_id),'sl':item['sales_order_line_id'],'o':str(order['organization_id']),'e':str(order['entity_id']),'l':str(order['location_id']),'sku':item['sku_id'],'oq':item['ordered_qty'],'dq':item['dispatched_qty'],'b':item['backorder_qty'],'r':'dispatch shortfall','u':user.user_id})
                else:
                    conn.execute(text('UPDATE sales_order_backorders SET status=\'CLOSED\',closed_at=CURRENT_TIMESTAMP,backorder_qty=0 WHERE sales_order_id=:s AND sales_order_line_id=:l'), {'s':str(sales_order_id),'l':item['sales_order_line_id']})
        return {'sales_order_id':str(sales_order_id),'status':status,'ordered_qty':total_o,'dispatched_qty':total_d,'backorder_qty':back,'lines':result}

    @app.get('/v90ax/sales/orders/{sales_order_id}/backorders')
    def get_backorders(sales_order_id: UUID, request: Request):
        with engine.connect() as conn:
            order=conn.execute(text('SELECT entity_id,location_id FROM sales_orders WHERE sales_order_id=:s'),{'s':str(sales_order_id)}).mappings().first()
            if not order: raise HTTPException(404,'sales order not found')
            rows=conn.execute(text('SELECT * FROM sales_order_backorders WHERE sales_order_id=:s ORDER BY created_at'),{'s':str(sales_order_id)}).mappings().all()
        _require(engine,request,str(order['entity_id']),str(order['location_id']),'dispatch_mis.view')
        return {'items':[dict(r) for r in rows]}

    @app.post('/v90ax/dispatches/{dispatch_id}/pod')
    def capture_pod(dispatch_id: UUID, body: PodIn, request: Request):
        with engine.connect() as conn:
            d=conn.execute(text('SELECT * FROM dispatches WHERE dispatch_id=:d'),{'d':str(dispatch_id)}).mappings().first()
            if not d: raise HTTPException(404,'dispatch not found')
        user=_require(engine,request,str(d['entity_id']),str(d['location_id']),'pod.edit')
        status='DELIVERED' if body.received_by or body.received_at or body.pod_reference or body.attachment_ref else 'PENDING'
        pid=str(uuid4())
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO dispatch_pod(pod_id,dispatch_id,organization_id,entity_id,location_id,received_by,received_at,pod_reference,attachment_ref,notes,status,captured_by) VALUES(:i,:d,:o,:e,:l,:r,:ra,:pr,:a,:n,:s,:u)'), {'i':pid,'d':str(dispatch_id),'o':str(d['organization_id']),'e':str(d['entity_id']),'l':str(d['location_id']),'r':body.received_by,'ra':body.received_at,'pr':body.pod_reference,'a':body.attachment_ref,'n':body.notes,'s':status,'u':user.user_id})
        return {'pod_id':pid,'dispatch_id':str(dispatch_id),'status':status}

    @app.get('/v90ax/dispatches/{dispatch_id}/pod')
    def get_pod(dispatch_id: UUID, request: Request):
        with engine.connect() as conn:
            d=conn.execute(text('SELECT * FROM dispatches WHERE dispatch_id=:d'),{'d':str(dispatch_id)}).mappings().first()
            if not d: raise HTTPException(404,'dispatch not found')
            rows=conn.execute(text('SELECT * FROM dispatch_pod WHERE dispatch_id=:d ORDER BY captured_at DESC'),{'d':str(dispatch_id)}).mappings().all()
        _require(engine,request,str(d['entity_id']),str(d['location_id']),'dispatch_mis.view')
        return {'items':[dict(r) for r in rows]}
