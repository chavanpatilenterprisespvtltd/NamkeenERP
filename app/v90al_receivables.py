from __future__ import annotations
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

BUCKETS = ('CURRENT', '1_30', '31_60', '61_90', '91_180', '181_PLUS')

class FollowUpIn(BaseModel):
    customer_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    follow_up_date: date
    mode: str = Field(min_length=2, max_length=40)
    note: str = Field(min_length=2, max_length=500)
    assigned_to_user_id: UUID | None = None


def ensure_v90al_schema(engine) -> None:
    with engine.begin() as conn:
        # Make due date explicit on invoices while retaining backward compatibility.
        cols = conn.execute(text("SELECT name FROM pragma_table_info('sales_invoices')")) if engine.dialect.name == 'sqlite' else conn.execute(text("SELECT column_name AS name FROM information_schema.columns WHERE table_name='sales_invoices'"))
        names = {str(r[0]) for r in cols.fetchall()}
        if 'due_date' not in names:
            conn.execute(text("ALTER TABLE sales_invoices ADD COLUMN due_date DATE"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_invoices_due_date ON sales_invoices(entity_id,due_date,status)"))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS receivable_followups (
            followup_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT, customer_id TEXT NOT NULL, follow_up_date DATE NOT NULL,
            mode TEXT NOT NULL, note TEXT NOT NULL, assigned_to_user_id TEXT, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_receivable_followups_customer ON receivable_followups(entity_id,customer_id,follow_up_date)"))
        perms = [
            ('receivables.view','View receivables and aging'),
            ('receivables.followup','Record receivables follow-up'),
        ]
        for pid,pname in perms:
            conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p':pid,'n':pname})
        for role in ('manager','super_admin','accounts'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'receivables.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})
        for role in ('manager','super_admin','accounts','salesperson'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'receivables.followup') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})


def _require(engine, request: Request, perm: str, entity_id: str, location_id: str | None):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _d(s) -> date:
    if isinstance(s, date): return s
    return datetime.fromisoformat(str(s).replace('Z','+00:00')).date()


def _policy_days(conn, entity_id: str, customer_id: str) -> int:
    x = conn.execute(text("SELECT credit_days FROM customer_credit_policies WHERE entity_id=:e AND customer_id=:c AND active=1 ORDER BY created_at DESC LIMIT 1"), {'e':entity_id,'c':customer_id}).scalar()
    return int(x or 0)


def _invoice_rows(engine, entity_id: str, customer_id: str, as_of: date):
    with engine.connect() as conn:
        invs = conn.execute(text("""SELECT si.invoice_id,si.invoice_no,si.organization_id,si.entity_id,si.location_id,si.grand_total,si.status,si.created_at,si.due_date
            FROM sales_invoices si JOIN sales_orders so ON so.sales_order_id=si.sales_order_id
            WHERE si.entity_id=:e AND so.customer_id=:c AND si.status='POSTED' ORDER BY si.created_at,si.invoice_id"""), {'e':entity_id,'c':customer_id}).mappings().all()
        days = _policy_days(conn, entity_id, customer_id)
        result=[]
        for inv in invs:
            created = _d(inv['created_at'])
            due = _d(inv['due_date']) if inv['due_date'] else created + timedelta(days=days)
            allocated = float(conn.execute(text("SELECT COALESCE(SUM(amount),0) FROM payment_allocations WHERE invoice_id=:i AND status='POSTED'"), {'i':str(inv['invoice_id'])}).scalar() or 0)
            credit = float(conn.execute(text("SELECT COALESCE(SUM(rcl.line_total),0) FROM return_credit_note_lines rcl JOIN return_credit_notes rcn ON rcn.credit_note_id=rcl.credit_note_id WHERE rcl.invoice_line_id IN (SELECT invoice_line_id FROM sales_invoice_lines WHERE invoice_id=:i) AND rcn.status='POSTED'"), {'i':str(inv['invoice_id'])}).scalar() or 0)
            total = float(inv['grand_total'] or 0)
            outstanding = max(0.0, total - allocated - credit)
            if outstanding <= 1e-9: continue
            days_overdue = max(0, (as_of - due).days)
            if as_of < due: bucket='CURRENT'
            elif days_overdue <= 30: bucket='1_30'
            elif days_overdue <= 60: bucket='31_60'
            elif days_overdue <= 90: bucket='61_90'
            elif days_overdue <= 180: bucket='91_180'
            else: bucket='181_PLUS'
            result.append({'invoice_id':str(inv['invoice_id']),'invoice_no':inv['invoice_no'],'invoice_date':created.isoformat(),'due_date':due.isoformat(),'days_overdue':days_overdue,'bucket':bucket,'invoice_total':round(total,2),'allocated_amount':round(allocated,2),'credit_note_amount':round(credit,2),'outstanding':round(outstanding,2)})
        return result


def register_v90al_routes(app: FastAPI, engine) -> None:
    ensure_v90al_schema(engine)

    @app.get('/v90al/customers/{customer_id}/aging')
    def customer_aging(customer_id: UUID, request: Request, entity_id: UUID, as_of_date: date | None = None):
        user = _require(engine, request, 'receivables.view', str(entity_id), None)
        as_of = as_of_date or date.today()
        rows = _invoice_rows(engine, str(entity_id), str(customer_id), as_of)
        buckets={b:0.0 for b in BUCKETS}
        for r in rows: buckets[r['bucket']] += r['outstanding']
        overdue=sum(v for b,v in buckets.items() if b!='CURRENT')
        total=sum(buckets.values())
        with engine.connect() as conn:
            fu = conn.execute(text("SELECT * FROM receivable_followups WHERE entity_id=:e AND customer_id=:c ORDER BY follow_up_date DESC,created_at DESC"), {'e':str(entity_id),'c':str(customer_id)}).mappings().all()
        return {'customer_id':str(customer_id),'entity_id':str(entity_id),'as_of_date':as_of.isoformat(),'invoices':rows,'buckets':{k:round(v,2) for k,v in buckets.items()},'summary':{'total_outstanding':round(total,2),'overdue_amount':round(overdue,2),'current_amount':round(buckets['CURRENT'],2),'invoice_count':len(rows)},'followups':[dict(x) for x in fu]}

    @app.get('/v90al/customers/{customer_id}/credit-utilization')
    def credit_utilization(customer_id: UUID, request: Request, entity_id: UUID, as_of_date: date | None = None):
        _require(engine, request, 'receivables.view', str(entity_id), None)
        as_of = as_of_date or date.today()
        rows = _invoice_rows(engine, str(entity_id), str(customer_id), as_of)
        outstanding=round(sum(r['outstanding'] for r in rows),2)
        with engine.connect() as conn:
            policy=conn.execute(text("SELECT credit_limit,credit_days FROM customer_credit_policies WHERE entity_id=:e AND customer_id=:c AND active=1 ORDER BY created_at DESC LIMIT 1"), {'e':str(entity_id),'c':str(customer_id)}).mappings().first()
        limit=float(policy['credit_limit']) if policy else 0.0
        utilization=(outstanding/limit*100) if limit>0 else (100.0 if outstanding>0 else 0.0)
        available=max(0.0,limit-outstanding)
        return {'customer_id':str(customer_id),'entity_id':str(entity_id),'credit_limit':round(limit,2),'outstanding':outstanding,'available_credit':round(available,2),'utilization_pct':round(utilization,2),'credit_days':int(policy['credit_days']) if policy else 0}

    @app.get('/v90al/overdue')
    def overdue(request: Request, entity_id: UUID, location_id: UUID | None = None, min_days_overdue: int = 1, as_of_date: date | None = None):
        _require(engine, request, 'receivables.view', str(entity_id), str(location_id) if location_id else None)
        as_of=as_of_date or date.today()
        with engine.connect() as conn:
            customers=conn.execute(text("SELECT DISTINCT so.customer_id FROM sales_orders so JOIN sales_invoices si ON si.sales_order_id=so.sales_order_id WHERE so.entity_id=:e AND si.status='POSTED'"), {'e':str(entity_id)}).scalars().all()
        items=[]
        for c in customers:
            for row in _invoice_rows(engine,str(entity_id),str(c),as_of):
                if row['days_overdue']>=min_days_overdue and row['bucket']!='CURRENT': items.append(row | {'customer_id':str(c)})
        items.sort(key=lambda x:(-x['days_overdue'],-x['outstanding']))
        return {'entity_id':str(entity_id),'as_of_date':as_of.isoformat(),'count':len(items),'total_overdue':round(sum(x['outstanding'] for x in items),2),'items':items}

    @app.post('/v90al/followups')
    def create_followup(body: FollowUpIn, request: Request):
        user=_require(engine, request, 'receivables.followup', str(body.entity_id), str(body.location_id) if body.location_id else None)
        with engine.begin() as conn:
            row=conn.execute(text("SELECT organization_id FROM sales_orders WHERE entity_id=:e AND customer_id=:c ORDER BY created_at LIMIT 1"), {'e':str(body.entity_id),'c':str(body.customer_id)}).first()
            if not row: raise HTTPException(404,'customer not found in entity')
            fid=str(uuid4())
            conn.execute(text("INSERT INTO receivable_followups(followup_id,organization_id,entity_id,location_id,customer_id,follow_up_date,mode,note,assigned_to_user_id,created_by) VALUES(:i,:o,:e,:l,:c,:d,:m,:n,:a,:u)"), {'i':fid,'o':str(row[0]),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'c':str(body.customer_id),'d':body.follow_up_date.isoformat(),'m':body.mode,'n':body.note,'a':str(body.assigned_to_user_id) if body.assigned_to_user_id else None,'u':str(user.user_id)})
        return {'followup_id':fid,'status':'RECORDED'}

    @app.get('/v90al/collection-dashboard')
    def collection_dashboard(request: Request, entity_id: UUID, as_of_date: date | None = None):
        _require(engine, request, 'receivables.view', str(entity_id), None)
        as_of=as_of_date or date.today()
        with engine.connect() as conn:
            customers=conn.execute(text("SELECT DISTINCT so.customer_id FROM sales_orders so JOIN sales_invoices si ON si.sales_order_id=so.sales_order_id WHERE so.entity_id=:e AND si.status='POSTED'"), {'e':str(entity_id)}).scalars().all()
        rows=[]
        for c in customers:
            aging=customer_aging_data=_invoice_rows(engine,str(entity_id),str(c),as_of)
            total=sum(x['outstanding'] for x in aging)
            overdue=sum(x['outstanding'] for x in aging if x['bucket']!='CURRENT')
            rows.append({'customer_id':str(c),'outstanding':round(total,2),'overdue':round(overdue,2),'oldest_days_overdue':max((x['days_overdue'] for x in aging),default=0)})
        rows.sort(key=lambda x:(-x['overdue'],-x['outstanding']))
        return {'entity_id':str(entity_id),'as_of_date':as_of.isoformat(),'customer_count':len(rows),'total_outstanding':round(sum(x['outstanding'] for x in rows),2),'total_overdue':round(sum(x['overdue'] for x in rows),2),'customers':rows}
