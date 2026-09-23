from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .v90fn_security_rbac_scope_hardening import assert_security_scope

PERM_VIEW='uat.production_readiness.view'; PERM_MANAGE='uat.production_readiness.manage'
SCENARIOS=(
 ('PROCURE_RECEIVE_QC','Procurement','Supplier purchase through receiving and QC'),
 ('INVENTORY_TRACEABILITY','Inventory','Lot/batch traceability and stock movement'),
 ('PRODUCTION_EXECUTION','Production','Material issue, production execution and output'),
 ('PROCESS_QC_PACKING','Quality','Process QC through batch packing'),
 ('FG_DISPATCH_FEFO','Dispatch','Finished-goods FEFO dispatch and POD'),
 ('SALES_TO_AR','Sales','Sales order through receivable posting'),
 ('RETURNS_DISPOSITION','Returns','Customer return through disposition'),
 ('INTERCOMPANY_X_TO_Y','Intercompany','Manufacturing X to marketing/sales Y execution and elimination evidence'),
 ('ACCOUNTING_GST','Finance','Accounting, GST evidence and reconciliation readiness'),
 ('MAINTENANCE_WORKFORCE','Operations','Maintenance execution and workforce/labour-cost evidence'),
 ('TRACEABILITY_RECALL','Compliance','Forward/backward traceability and recall readiness'),
 ('BACKUP_RESTORE','Platform','Backup and restore evidence'),
)
CHECKS=(
 ('GOVERNANCE_CERTIFICATION','Governance','Governance certification and coverage remediation are closed'),
 ('SECURITY_SCOPE','Security','Organization/entity/location/warehouse access is scoped and tested'),
 ('AUDIT_EVIDENCE','Governance','Audit, approval and evidence controls are reviewable'),
 ('INTERCOMPANY_CONTROL','Finance','X/Y intercompany controls and elimination evidence are reconciled'),
 ('GST_ACCOUNTING','Finance','Accounting/GST configuration and reconciliation evidence is reviewed'),
 ('BACKUP_RESTORE','Platform','Backup and restore procedure is executed and evidenced'),
 ('MONITORING_ALERTS','Platform','Monitoring, notifications and escalation paths are tested'),
 ('PERFORMANCE','Platform','Production-scale performance smoke evidence is reviewed'),
 ('DEPLOYMENT_CONFIG','Platform','Production configuration, secrets and migration process are verified'),
 ('BUSINESS_OWNER_SIGNOFF','Business','Business owners approve UAT outcomes and residual risks'),
)

class PlanIn(BaseModel):
    organization_id:str|None=None; period_key:str=Field(min_length=1,max_length=80); name:str=Field(min_length=2,max_length=200)
class ExecuteIn(BaseModel):
    scenario_code:str=Field(min_length=2,max_length=80); result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=Field(default=None,max_length=500); notes:str=Field(min_length=1,max_length=3000)
class CheckIn(BaseModel):
    check_code:str=Field(min_length=2,max_length=80); status:str=Field(pattern='^(PASS|FAIL|WAIVED)$'); evidence_ref:str|None=Field(default=None,max_length=500); notes:str=Field(min_length=1,max_length=2000); owner_user_id:str|None=None
class CertifyIn(BaseModel):
    signoff_note:str=Field(min_length=1,max_length=3000); evidence_ref:str=Field(min_length=1,max_length=500)

def _u(e:Engine,r:Request,p:str):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def ensure_v90ft_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_uat_plan(plan_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'DRAFT',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,started_at TIMESTAMP NULL,certified_at TIMESTAMP NULL,certified_by TEXT NULL,signoff_note TEXT NULL,signoff_evidence_ref TEXT NULL)''',
    '''CREATE TABLE IF NOT EXISTS erp_uat_execution(execution_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,scenario_code TEXT NOT NULL,process_area TEXT NOT NULL,test_case TEXT NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,tested_by TEXT NOT NULL,tested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_production_readiness_check(readiness_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,check_code TEXT NOT NULL,category TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,notes TEXT NOT NULL,owner_user_id TEXT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(plan_id,check_code))''',
    'CREATE INDEX IF NOT EXISTS ix_uat_plan_scope ON erp_uat_plan(organization_id,status,period_key)',
    'CREATE INDEX IF NOT EXISTS ix_uat_execution_plan ON erp_uat_execution(plan_id,result,scenario_code)',
    'CREATE INDEX IF NOT EXISTS ix_readiness_plan ON erp_production_readiness_check(plan_id,status,category)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View ERP UAT and production readiness'),(PERM_MANAGE,'Manage ERP UAT and production readiness')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90ft_routes(app:FastAPI,e:Engine):
    ensure_v90ft_schema(e)
    @app.post('/v90ft/uat/plans')
    def create_plan(b:PlanIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        try: assert_security_scope(e,u.user_id,organization_id=b.organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        pid=str(uuid4())
        with e.begin() as c:
            c.execute(text('INSERT INTO erp_uat_plan(plan_id,organization_id,period_key,name,created_by) VALUES(:id,:o,:p,:n,:u)'),{'id':pid,'o':b.organization_id,'p':b.period_key,'n':b.name,'u':u.user_id})
        return {'plan_id':pid,'status':'DRAFT','scenario_catalog':[x[0] for x in SCENARIOS],'readiness_catalog':[x[0] for x in CHECKS]}
    @app.get('/v90ft/uat/plans')
    def list_plans(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_uat_plan WHERE organization_id IS NOT DISTINCT FROM :o'; p={'o':organization_id}
        if status:q+=' AND status=:s';p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'plans':rows}
    @app.post('/v90ft/uat/plans/{plan_id}/start')
    def start(plan_id:str,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT * FROM erp_uat_plan WHERE plan_id=:id'),{'id':plan_id}).mappings().first()
            if not row: raise HTTPException(404,'UAT plan not found')
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            if row['status'] not in ('DRAFT','BLOCKED'): raise HTTPException(409,'plan cannot be started from current status')
            c.execute(text("UPDATE erp_uat_plan SET status='EXECUTING',started_at=COALESCE(started_at,CURRENT_TIMESTAMP) WHERE plan_id=:id"),{'id':plan_id})
        return {'plan_id':plan_id,'status':'EXECUTING'}
    @app.post('/v90ft/uat/plans/{plan_id}/execute')
    def execute(plan_id:str,b:ExecuteIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        scenario=next((x for x in SCENARIOS if x[0]==b.scenario_code.upper()),None)
        if not scenario: raise HTTPException(422,'unknown UAT scenario')
        if b.result in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_uat_plan WHERE plan_id=:id'),{'id':plan_id}).mappings().first()
            if not row: raise HTTPException(404,'UAT plan not found')
            if row['status']!='EXECUTING': raise HTTPException(409,'plan must be EXECUTING')
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            eid=str(uuid4()); c.execute(text('''INSERT INTO erp_uat_execution(execution_id,plan_id,scenario_code,process_area,test_case,result,evidence_ref,notes,tested_by) VALUES(:id,:p,:s,:a,:t,:r,:e,:n,:u)'''),{'id':eid,'p':plan_id,'s':scenario[0],'a':scenario[1],'t':scenario[2],'r':b.result,'e':b.evidence_ref,'n':b.notes,'u':u.user_id})
        return {'execution_id':eid,'scenario_code':scenario[0],'result':b.result}
    @app.get('/v90ft/uat/plans/{plan_id}/executions')
    def executions(plan_id:str,r:Request):
        _u(e,r,PERM_VIEW)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text('SELECT * FROM erp_uat_execution WHERE plan_id=:p ORDER BY tested_at'),{'p':plan_id}).mappings().all()]
        return {'executions':rows}
    @app.post('/v90ft/uat/plans/{plan_id}/readiness')
    def readiness_check(plan_id:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        check=next((x for x in CHECKS if x[0]==b.check_code.upper()),None)
        if not check: raise HTTPException(422,'unknown readiness check')
        if b.status in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id FROM erp_uat_plan WHERE plan_id=:id'),{'id':plan_id}).mappings().first()
            if not row: raise HTTPException(404,'UAT plan not found')
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            rid=str(uuid4()); c.execute(text('''INSERT INTO erp_production_readiness_check(readiness_id,plan_id,check_code,category,status,evidence_ref,notes,owner_user_id,reviewed_by) VALUES(:id,:p,:c,:a,:s,:e,:n,:o,:u) ON CONFLICT(plan_id,check_code) DO UPDATE SET category=:a,status=:s,evidence_ref=:e,notes=:n,owner_user_id=:o,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP'''),{'id':rid,'p':plan_id,'c':check[0],'a':check[1],'s':b.status,'e':b.evidence_ref,'n':b.notes,'o':b.owner_user_id,'u':u.user_id})
        return {'plan_id':plan_id,'check_code':check[0],'status':b.status}
    @app.get('/v90ft/uat/plans/{plan_id}/production-readiness')
    def production_readiness(plan_id:str,r:Request):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            plan=c.execute(text('SELECT * FROM erp_uat_plan WHERE plan_id=:id'),{'id':plan_id}).mappings().first()
            if not plan: raise HTTPException(404,'UAT plan not found')
            ex=c.execute(text('SELECT result,COUNT(*) n FROM erp_uat_execution WHERE plan_id=:p GROUP BY result'),{'p':plan_id}).mappings().all()
            ck=c.execute(text('SELECT status,COUNT(*) n FROM erp_production_readiness_check WHERE plan_id=:p GROUP BY status'),{'p':plan_id}).mappings().all()
            fs=c.execute(text("SELECT COUNT(*) FROM erp_governance_remediation WHERE organization_id IS NOT DISTINCT FROM :o AND status IN ('REQUESTED','IN_PROGRESS','BLOCKED')"),{'o':plan['organization_id']}).scalar() or 0
            gaps=c.execute(text("SELECT COUNT(*) FROM erp_governance_coverage_gap WHERE organization_id IS NOT DISTINCT FROM :o AND status='OPEN'"),{'o':plan['organization_id']}).scalar() or 0
        em={x['result']:int(x['n']) for x in ex}; cm={x['status']:int(x['n']) for x in ck}; total_s=sum(em.values()); total_c=sum(cm.values())
        ready=(plan['status']=='EXECUTING' and total_s==len(SCENARIOS) and em.get('PASS',0)==len(SCENARIOS) and total_c==len(CHECKS) and cm.get('FAIL',0)==0 and cm.get('PASS',0)+cm.get('WAIVED',0)==len(CHECKS) and fs==0 and gaps==0)
        return {'plan':dict(plan),'ready_for_certification':ready,'uat':em,'readiness_checks':cm,'open_governance_gaps':gaps,'active_governance_remediations':fs,'required_scenarios':len(SCENARIOS),'required_readiness_checks':len(CHECKS)}
    @app.post('/v90ft/uat/plans/{plan_id}/certify')
    def certify(plan_id:str,b:CertifyIn,r:Request):
        u=_u(e,r,PERM_MANAGE); summary=production_readiness(plan_id,r)
        if not summary['ready_for_certification']: raise HTTPException(409,{'message':'production readiness gate failed','summary':summary})
        with e.begin() as c:
            c.execute(text("UPDATE erp_uat_plan SET status='CERTIFIED',certified_at=CURRENT_TIMESTAMP,certified_by=:u,signoff_note=:n,signoff_evidence_ref=:e WHERE plan_id=:p"),{'u':u.user_id,'n':b.signoff_note,'e':b.evidence_ref,'p':plan_id})
        return {'plan_id':plan_id,'status':'CERTIFIED','certified_by':u.user_id}
    @app.get('/ui/uat-production-readiness')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'uat_production_readiness.html')
    return {'allowed':True}
