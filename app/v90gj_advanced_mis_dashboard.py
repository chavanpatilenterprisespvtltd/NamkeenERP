from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .v90fn_security_rbac_scope_hardening import assert_security_scope

PERM_VIEW='mis.executive.view'
PERM_MANAGE='mis.executive.manage'

def _d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _u(e:Engine,r:Request,p:str):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,o,ei):
    try: assert_security_scope(e,u.user_id,organization_id=o,entity_id=ei)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def _one(c,sql,**p): return c.execute(text(sql),p).scalar() or 0

def _row(c,sql,**p): return c.execute(text(sql),p).mappings().first()

def ensure_v90gj_schema(e:Engine):
    with e.begin() as c:
        stmts=[
        '''CREATE TABLE IF NOT EXISTS erp_mis_dashboard_snapshot(
            snapshot_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,
            gross_sales NUMERIC NOT NULL DEFAULT 0,net_sales NUMERIC NOT NULL DEFAULT 0,collections NUMERIC NOT NULL DEFAULT 0,
            outstanding NUMERIC NOT NULL DEFAULT 0,inventory_value NUMERIC NOT NULL DEFAULT 0,slow_moving_value NUMERIC NOT NULL DEFAULT 0,
            dead_stock_value NUMERIC NOT NULL DEFAULT 0,production_cost NUMERIC NOT NULL DEFAULT 0,production_yield_pct NUMERIC NOT NULL DEFAULT 0,
            cost_variance NUMERIC NOT NULL DEFAULT 0,procurement_spend NUMERIC NOT NULL DEFAULT 0,procurement_savings NUMERIC NOT NULL DEFAULT 0,
            supplier_score NUMERIC NOT NULL DEFAULT 0,labour_cost NUMERIC NOT NULL DEFAULT 0,labour_cost_per_hour NUMERIC NOT NULL DEFAULT 0,
            maintenance_health_score NUMERIC NOT NULL DEFAULT 0,open_alerts INTEGER NOT NULL DEFAULT 0,open_incidents INTEGER NOT NULL DEFAULT 0,
            open_problems INTEGER NOT NULL DEFAULT 0,open_escalations INTEGER NOT NULL DEFAULT 0,critical_risks INTEGER NOT NULL DEFAULT 0,
            executive_health_score NUMERIC NOT NULL DEFAULT 0,assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',status TEXT NOT NULL DEFAULT 'OPEN',
            evidence_ref TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        '''CREATE TABLE IF NOT EXISTS erp_mis_dashboard_kpi(
            kpi_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,
            kpi_code TEXT NOT NULL,kpi_name TEXT NOT NULL,value NUMERIC NOT NULL DEFAULT 0,target NUMERIC NULL,unit TEXT NOT NULL DEFAULT 'NUMBER',
            direction TEXT NOT NULL DEFAULT 'HIGHER',status TEXT NOT NULL DEFAULT 'INFO',source_module TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,kpi_code))''',
        'CREATE INDEX IF NOT EXISTS ix_mis_dashboard_scope ON erp_mis_dashboard_snapshot(organization_id,entity_id,period_key,status)',
        'CREATE INDEX IF NOT EXISTS ix_mis_dashboard_kpi_scope ON erp_mis_dashboard_kpi(organization_id,entity_id,period_key,kpi_code)',
        ]
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View executive MIS dashboard and KPI cards'),(PERM_MANAGE,'Create and refresh executive MIS dashboard snapshots')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})
        for role in ('manager','accounts','costing','production','mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':PERM_VIEW})
        for role in ('manager','accounts','costing','mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':PERM_MANAGE})

def _source_data(e:Engine,o:str,ei:str,pk:str):
    with e.connect() as c:
        sales=_row(c,'''SELECT gross_sales,net_sales,collections,outstanding FROM sales_mis_snapshot
            WHERE organization_id=:o AND entity_id=:e ORDER BY CASE WHEN to_date LIKE :pref THEN 0 ELSE 1 END,to_date DESC,calculated_at DESC LIMIT 1''',o=o,e=ei,pref=f'{pk}%')
        inv=_row(c,'''SELECT total_value,slow_moving_value,dead_stock_value FROM inventory_valuation_snapshot
            WHERE organization_id=:o AND entity_id=:e ORDER BY created_at DESC LIMIT 1''',o=o,e=ei)
        prod=_row(c,'''SELECT COALESCE(SUM(total_cost),0) total_cost,COALESCE(AVG(yield_pct),0) yield_pct,COALESCE(SUM(variance_value),0) variance_value
            FROM manufacturing_batch_cost WHERE organization_id=:o AND entity_id=:e AND period_key=:p''',o=o,e=ei,p=pk)
        proc=_row(c,'''SELECT COALESCE(SUM(spend_value),0) spend,COALESCE(SUM(savings_value),0) savings,COALESCE(AVG(score),0) score
            FROM procurement_supplier_analytics WHERE organization_id=:o AND entity_id=:e AND period_key=:p''',o=o,e=ei,p=pk)
        lab=_row(c,'''SELECT COALESCE(SUM(production_labour),0) labour,COALESCE(AVG(avg_labour_cost_per_hour),0) cph
            FROM hr_payroll_mis_snapshot WHERE organization_id=:o AND entity_id=:e AND period_id=:p''',o=o,e=ei,p=pk)
        maint=_one(c,'''SELECT COALESCE(AVG(executive_health_score),0) FROM maintenance_reliability_executive_command_snapshot
            WHERE organization_id=:o AND entity_id=:e AND period_key=:p''',o=o,e=ei,p=pk)
        alerts=int(_one(c,"SELECT COUNT(*) FROM erp_ops_alert WHERE organization_id=:o AND status='OPEN'",o=o))
        crit_alerts=int(_one(c,"SELECT COUNT(*) FROM erp_ops_alert WHERE organization_id=:o AND status='OPEN' AND severity='CRITICAL'",o=o))
        incidents=int(_one(c,"SELECT COUNT(*) FROM erp_ops_incident WHERE organization_id=:o AND status NOT IN ('CLOSED','RESOLVED')",o=o))
        problems=int(_one(c,"SELECT COUNT(*) FROM erp_ops_problem WHERE organization_id=:o AND status NOT IN ('CLOSED','ACCEPTED_EXCEPTION')",o=o))
        escalations=int(_one(c,"SELECT COUNT(*) FROM erp_ops_escalation WHERE organization_id=:o AND status NOT IN ('CLOSED','WAIVED')",o=o))
        return {
            '_source_flags': {
                'sales': bool(sales and any(_d(sales[k]) for k in ('gross_sales','net_sales','collections','outstanding'))),
                'inventory': bool(inv and any(_d(inv[k]) for k in ('total_value','slow_moving_value','dead_stock_value'))),
                'production': bool(prod and any(_d(prod[k]) for k in ('total_cost','yield_pct','variance_value'))),
                'procurement': bool(proc and any(_d(proc[k]) for k in ('spend','savings','score'))),
                'workforce': bool(lab and any(_d(lab[k]) for k in ('labour','cph'))),
                'maintenance': bool(maint),
            },
            'gross_sales':_d(sales['gross_sales'] if sales else 0),'net_sales':_d(sales['net_sales'] if sales else 0),'collections':_d(sales['collections'] if sales else 0),'outstanding':_d(sales['outstanding'] if sales else 0),
            'inventory_value':_d(inv['total_value'] if inv else 0),'slow_moving_value':_d(inv['slow_moving_value'] if inv else 0),'dead_stock_value':_d(inv['dead_stock_value'] if inv else 0),
            'production_cost':_d(prod['total_cost'] if prod else 0),'production_yield_pct':_d(prod['yield_pct'] if prod else 0),'cost_variance':_d(prod['variance_value'] if prod else 0),
            'procurement_spend':_d(proc['spend'] if proc else 0),'procurement_savings':_d(proc['savings'] if proc else 0),'supplier_score':_d(proc['score'] if proc else 0),
            'labour_cost':_d(lab['labour'] if lab else 0),'labour_cost_per_hour':_d(lab['cph'] if lab else 0),'maintenance_health_score':_d(maint),
            'open_alerts':alerts,'open_incidents':incidents,'open_problems':problems,'open_escalations':escalations,'critical_risks':crit_alerts
        }

def _health(d):
    flags=d.get('_source_flags',{})
    available=[]
    if flags.get('procurement') and d['supplier_score']:
        available.append(max(Decimal(0),min(Decimal(100),d['supplier_score'])))
    if flags.get('maintenance'):
        available.append(max(Decimal(0),min(Decimal(100),d['maintenance_health_score'])))
    if flags.get('production'):
        available.append(max(Decimal(0),min(Decimal(100),d['production_yield_pct'])))
    if flags.get('sales'):
        collection_rate=(d['collections']/d['net_sales']*Decimal(100)) if d['net_sales'] else Decimal(0)
        available.append(max(Decimal(0),min(Decimal(100),collection_rate)))
    if flags.get('inventory'):
        dead_ratio=(d['dead_stock_value']/d['inventory_value']*Decimal(100)) if d['inventory_value'] else Decimal(0)
        available.append(max(Decimal(0),Decimal(100)-dead_ratio))
    if flags.get('workforce'):
        available.append(Decimal(100) if d['labour_cost'] >= 0 else Decimal(0))
    if d['critical_risks'] or d['open_escalations'] or d['open_incidents'] or d['open_problems']:
        available.append(max(Decimal(0),Decimal(100)-Decimal(min(d['critical_risks'],20))*5-Decimal(min(d['open_escalations'],20))*3-Decimal(min(d['open_incidents']+d['open_problems'],20))*2))
    if not available:
        return Decimal('0.00'),'REVIEW_REQUIRED'
    base=sum(available,Decimal(0))/Decimal(len(available))
    score=base
    assessment='HEALTHY' if score>=90 and not d['critical_risks'] and not d['open_escalations'] else ('WATCH' if score>=75 else 'AT_RISK')
    return score.quantize(Decimal('0.01')),assessment

def register_v90gj_routes(app:FastAPI,e:Engine):
    ensure_v90gj_schema(e)
    @app.post('/v90gj/mis/dashboard/snapshot')
    def snapshot(body:dict,request:Request):
        u=_u(e,request,PERM_MANAGE)
        o=str(body.get('organization_id') or '').strip(); ei=str(body.get('entity_id') or '').strip(); pk=str(body.get('period_key') or '').strip()
        if not o or not ei or not pk: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        _scope(e,u,o,ei)
        d=_source_data(e,o,ei,pk); health,assessment=_health(d); sid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO erp_mis_dashboard_snapshot(snapshot_id,organization_id,entity_id,period_key,gross_sales,net_sales,collections,outstanding,inventory_value,slow_moving_value,dead_stock_value,production_cost,production_yield_pct,cost_variance,procurement_spend,procurement_savings,supplier_score,labour_cost,labour_cost_per_hour,maintenance_health_score,open_alerts,open_incidents,open_problems,open_escalations,critical_risks,executive_health_score,assessment,evidence_ref,created_by)
            VALUES(:i,:o,:e,:p,:gs,:ns,:co,:out,:iv,:sm,:ds,:pc,:yp,:cv,:ps,:pv,:ss,:lc,:lh,:mh,:oa,:oi,:op,:oe,:cr,:hs,:a,:ev,:u)
            ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET gross_sales=:gs,net_sales=:ns,collections=:co,outstanding=:out,inventory_value=:iv,slow_moving_value=:sm,dead_stock_value=:ds,production_cost=:pc,production_yield_pct=:yp,cost_variance=:cv,procurement_spend=:ps,procurement_savings=:pv,supplier_score=:ss,labour_cost=:lc,labour_cost_per_hour=:lh,maintenance_health_score=:mh,open_alerts=:oa,open_incidents=:oi,open_problems=:op,open_escalations=:oe,critical_risks=:cr,executive_health_score=:hs,assessment=:a,evidence_ref=:ev,created_by=:u,created_at=CURRENT_TIMESTAMP,status='OPEN' '''),{
                'i':sid,'o':o,'e':ei,'p':pk,'gs':float(d['gross_sales']),'ns':float(d['net_sales']),'co':float(d['collections']),'out':float(d['outstanding']),
                'iv':float(d['inventory_value']),'sm':float(d['slow_moving_value']),'ds':float(d['dead_stock_value']),'pc':float(d['production_cost']),'yp':float(d['production_yield_pct']),'cv':float(d['cost_variance']),
                'ps':float(d['procurement_spend']),'pv':float(d['procurement_savings']),'ss':float(d['supplier_score']),'lc':float(d['labour_cost']),'lh':float(d['labour_cost_per_hour']),'mh':float(d['maintenance_health_score']),
                'oa':int(d['open_alerts']),'oi':int(d['open_incidents']),'op':int(d['open_problems']),'oe':int(d['open_escalations']),'cr':int(d['critical_risks']),
                'hs':float(health),'a':assessment,'ev':body.get('evidence_ref'),'u':str(u.user_id)})
            c.execute(text('DELETE FROM erp_mis_dashboard_kpi WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk})
            kpis=[
                ('NET_SALES','Net Sales',d['net_sales'],'CURRENCY','sales'),('COLLECTIONS','Collections',d['collections'],'CURRENCY','sales'),('OUTSTANDING','Outstanding',d['outstanding'],'CURRENCY','sales'),
                ('INVENTORY_VALUE','Inventory Value',d['inventory_value'],'CURRENCY','inventory'),('DEAD_STOCK_VALUE','Dead Stock Value',d['dead_stock_value'],'CURRENCY','inventory'),
                ('PRODUCTION_COST','Production Cost',d['production_cost'],'CURRENCY','production'),('PRODUCTION_YIELD','Production Yield',d['production_yield_pct'],'PERCENT','production'),('COST_VARIANCE','Cost Variance',d['cost_variance'],'CURRENCY','production'),
                ('PROCUREMENT_SPEND','Procurement Spend',d['procurement_spend'],'CURRENCY','procurement'),('PROCUREMENT_SAVINGS','Procurement Savings',d['procurement_savings'],'CURRENCY','procurement'),('SUPPLIER_SCORE','Supplier Score',d['supplier_score'],'PERCENT','procurement'),
                ('LABOUR_COST','Production Labour Cost',d['labour_cost'],'CURRENCY','workforce'),('LABOUR_COST_PER_HOUR','Labour Cost / Hour',d['labour_cost_per_hour'],'CURRENCY','workforce'),('MAINTENANCE_HEALTH','Maintenance Health',d['maintenance_health_score'],'PERCENT','maintenance'),
                ('CRITICAL_RISKS','Critical Risks',d['critical_risks'],'NUMBER','operations'),('OPEN_ESCALATIONS','Open Escalations',d['open_escalations'],'NUMBER','operations'),('EXECUTIVE_HEALTH','Executive Health Score',health,'PERCENT','mis')]
            for code,name,val,unit,src in kpis:
                c.execute(text('INSERT INTO erp_mis_dashboard_kpi(kpi_id,organization_id,entity_id,period_key,kpi_code,kpi_name,value,unit,source_module) VALUES(:i,:o,:e,:p,:c,:n,:v,:u,:s)'),{'i':str(uuid4()),'o':o,'e':ei,'p':pk,'c':code,'n':name,'v':float(val),'u':unit,'s':src})
        return {'snapshot_id':sid,'organization_id':o,'entity_id':ei,'period_key':pk,'executive_health_score':float(health),'assessment':assessment,'data':{k:float(v) if isinstance(v,Decimal) else v for k,v in d.items() if not k.startswith('_')}}

    @app.get('/v90gj/mis/dashboard')
    def dashboard(organization_id:str,entity_id:str,period_key:str,request:Request):
        _u(e,request,PERM_VIEW); u=authenticate(request); _scope(e,u,organization_id,entity_id)
        with e.connect() as c:
            s=_row(c,'SELECT * FROM erp_mis_dashboard_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p',o=organization_id,e=entity_id,p=period_key)
            k=c.execute(text('SELECT * FROM erp_mis_dashboard_kpi WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY kpi_code'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        if not s: raise HTTPException(404,'MIS dashboard snapshot not found; create a snapshot first')
        return {'snapshot':dict(s),'kpis':[dict(x) for x in k],'decision_flags':{'critical_risks':s['critical_risks'],'open_escalations':s['open_escalations'],'open_incidents':s['open_incidents'],'open_problems':s['open_problems']}}

    @app.get('/v90gj/mis/dashboard/compare')
    def compare(organization_id:str,entity_id:str,from_period:str,to_period:str,request:Request):
        u=_u(e,request,PERM_VIEW); _scope(e,u,organization_id,entity_id)
        with e.connect() as c:
            rows=c.execute(text('''SELECT * FROM erp_mis_dashboard_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key>=:f AND period_key<=:t ORDER BY period_key'''),{'o':organization_id,'e':entity_id,'f':from_period,'t':to_period}).mappings().all()
        return {'organization_id':organization_id,'entity_id':entity_id,'from_period':from_period,'to_period':to_period,'count':len(rows),'periods':[dict(x) for x in rows]}

    @app.get('/ui/mis-dashboard')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'mis-dashboard.html')
    return {'allowed':True}
