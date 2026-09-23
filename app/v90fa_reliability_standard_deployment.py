from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def perm(e, r, p):
    u = authenticate(r); ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403, 'permission denied')
    return u

def register_v90fa_routes(app: FastAPI, e):
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_standard_deployment( deployment_id TEXT PRIMARY KEY, standard_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, work_center_id TEXT, period_key TEXT NOT NULL, version_no INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PROPOSED', deployed_at TIMESTAMP, deployed_by TEXT, acknowledgement_required INTEGER NOT NULL DEFAULT 1, acknowledgement_count INTEGER NOT NULL DEFAULT 0, applicable_count INTEGER NOT NULL DEFAULT 0, adoption_pct NUMERIC NOT NULL DEFAULT 0, exception_count INTEGER NOT NULL DEFAULT 0, evidence_note TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(standard_id,work_center_id,period_key))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_reliability_standard_deployment_scope ON maintenance_reliability_standard_deployment(organization_id,entity_id,status,work_center_id)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_standard_adoption( adoption_id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL, standard_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, work_center_id TEXT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', acknowledged_at TIMESTAMP, acknowledged_by TEXT, exception_reason TEXT, evidence_note TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(deployment_id,subject_type,subject_id))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_reliability_standard_adoption_scope ON maintenance_reliability_standard_adoption(organization_id,entity_id,status,work_center_id)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_standard_exception( exception_id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL, standard_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, work_center_id TEXT, exception_type TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'MEDIUM', reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', resolved_by TEXT, resolved_at TIMESTAMP, resolution_note TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_reliability_standard_exception_scope ON maintenance_reliability_standard_exception(organization_id,entity_id,status,severity,work_center_id)'))
        for p,n in [('maintenance_reliability_standard.view','View Reliability Standards'),('maintenance_reliability_standard.manage','Manage Reliability Standard Deployment'),('maintenance_reliability_standard.approve','Approve Reliability Standard Deployment')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p':p,'n':n})

    @app.post('/v90fa/maintenance/reliability-standards/{standard_id}/deploy')
    def deploy(standard_id: str, body: dict, request: Request):
        u=perm(e,request,'maintenance_reliability_standard.manage'); pk=body.get('period_key'); o=body.get('organization_id'); ei=body.get('entity_id'); wc=body.get('work_center_id')
        if not pk or not o or not ei: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        with e.begin() as c:
            s=c.execute(text('SELECT * FROM maintenance_reliability_standard_recommendation WHERE standard_id=:s AND organization_id=:o AND entity_id=:e'),{'s':standard_id,'o':o,'e':ei}).mappings().first()
            if not s: raise HTTPException(404,'approved standard not found')
            if s['status']!='APPROVED': raise HTTPException(409,'standard must be APPROVED before deployment')
            did=str(uuid4())
            c.execute(text('''INSERT INTO maintenance_reliability_standard_deployment(deployment_id,standard_id,organization_id,entity_id,work_center_id,period_key,version_no,status,created_by) VALUES(:d,:s,:o,:e,:w,:p,:v,'PROPOSED',:u) ON CONFLICT(standard_id,work_center_id,period_key) DO UPDATE SET version_no=:v,status='PROPOSED',created_by=:u'''),{'d':did,'s':standard_id,'o':o,'e':ei,'w':wc,'p':pk,'v':s['version_no'],'u':str(u.user_id)})
            d=c.execute(text('SELECT * FROM maintenance_reliability_standard_deployment WHERE standard_id=:s AND organization_id=:o AND entity_id=:e AND period_key=:p AND ((work_center_id=:w) OR (work_center_id IS NULL AND :w IS NULL))'),{'s':standard_id,'o':o,'e':ei,'p':pk,'w':wc}).mappings().first()
        return {'deployment_id':d['deployment_id'],'status':d['status'],'approval_required':True,'operational_mutation':False}

    @app.post('/v90fa/maintenance/reliability-standards/deployments/{deployment_id}/approve')
    def approve(deployment_id:str, request:Request):
        u=perm(e,request,'maintenance_reliability_standard.approve')
        with e.begin() as c:
            d=c.execute(text('SELECT * FROM maintenance_reliability_standard_deployment WHERE deployment_id=:d'),{'d':deployment_id}).mappings().first()
            if not d: raise HTTPException(404,'deployment not found')
            c.execute(text("UPDATE maintenance_reliability_standard_deployment SET status='APPROVED' WHERE deployment_id=:d"),{'d':deployment_id})
        return {'deployment_id':deployment_id,'status':'APPROVED','operational_mutation':False}

    @app.post('/v90fa/maintenance/reliability-standards/deployments/{deployment_id}/activate')
    def activate(deployment_id:str, body:dict | None = None, request:Request = None):
        u=perm(e,request,'maintenance_reliability_standard.manage')
        with e.begin() as c:
            d=c.execute(text('SELECT * FROM maintenance_reliability_standard_deployment WHERE deployment_id=:d'),{'d':deployment_id}).mappings().first()
            if not d: raise HTTPException(404,'deployment not found')
            if d['status']!='APPROVED': raise HTTPException(409,'deployment must be APPROVED before activation')
            c.execute(text("UPDATE maintenance_reliability_standard_deployment SET status='ACTIVE',deployed_at=CURRENT_TIMESTAMP,deployed_by=:u WHERE deployment_id=:d"),{'u':str(u.user_id),'d':deployment_id})
        return {'deployment_id':deployment_id,'status':'ACTIVE','operational_mutation':False}

    @app.post('/v90fa/maintenance/reliability-standards/deployments/{deployment_id}/adoption')
    def adoption(deployment_id:str, body:dict, request:Request):
        u=perm(e,request,'maintenance_reliability_standard.manage'); sid=body.get('subject_id'); st=body.get('subject_type','USER'); status=body.get('status','ACKNOWLEDGED')
        if not sid: raise HTTPException(400,'subject_id is required')
        if status not in ('PENDING','ACKNOWLEDGED','EXCEPTION'): raise HTTPException(400,'invalid adoption status')
        with e.begin() as c:
            d=c.execute(text('SELECT * FROM maintenance_reliability_standard_deployment WHERE deployment_id=:d'),{'d':deployment_id}).mappings().first()
            if not d: raise HTTPException(404,'deployment not found')
            if d['status']!='ACTIVE': raise HTTPException(409,'deployment must be ACTIVE')
            aid=str(uuid4()); c.execute(text('''INSERT INTO maintenance_reliability_standard_adoption(adoption_id,deployment_id,standard_id,organization_id,entity_id,work_center_id,subject_type,subject_id,status,acknowledged_at,acknowledged_by,exception_reason,evidence_note,created_by) VALUES(:a,:d,:s,:o,:e,:w,:t,:sid,:st,CASE WHEN :st='ACKNOWLEDGED' THEN CURRENT_TIMESTAMP ELSE NULL END,CASE WHEN :st='ACKNOWLEDGED' THEN :u ELSE NULL END,:r,:n,:u) ON CONFLICT(deployment_id,subject_type,subject_id) DO UPDATE SET status=:st,acknowledged_at=CASE WHEN :st='ACKNOWLEDGED' THEN CURRENT_TIMESTAMP ELSE acknowledged_at END,acknowledged_by=CASE WHEN :st='ACKNOWLEDGED' THEN :u ELSE acknowledged_by END,exception_reason=:r,evidence_note=:n'''),{'a':aid,'d':deployment_id,'s':d['standard_id'],'o':d['organization_id'],'e':d['entity_id'],'w':d['work_center_id'],'t':st,'sid':sid,'st':status,'r':body.get('exception_reason'),'n':body.get('evidence_note'),'u':str(u.user_id)})
            if status=='EXCEPTION':
                c.execute(text('''INSERT INTO maintenance_reliability_standard_exception(exception_id,deployment_id,standard_id,organization_id,entity_id,work_center_id,exception_type,severity,reason,created_by) VALUES(:i,:d,:s,:o,:e,:w,'ADOPTION_EXCEPTION',:sev,:r,:u)'''),{'i':str(uuid4()),'d':deployment_id,'s':d['standard_id'],'o':d['organization_id'],'e':d['entity_id'],'w':d['work_center_id'],'sev':body.get('severity','MEDIUM'),'r':body.get('exception_reason') or 'Standard adoption exception','u':str(u.user_id)})
            agg=c.execute(text("SELECT COUNT(*) total, SUM(CASE WHEN status='ACKNOWLEDGED' THEN 1 ELSE 0 END) ack, SUM(CASE WHEN status='EXCEPTION' THEN 1 ELSE 0 END) exc FROM maintenance_reliability_standard_adoption WHERE deployment_id=:d"),{'d':deployment_id}).mappings().first(); total=int(agg['total'] or 0); ack=int(agg['ack'] or 0); exc=int(agg['exc'] or 0); pct=(ack*100/total if total else 0)
            c.execute(text('UPDATE maintenance_reliability_standard_deployment SET applicable_count=:t,acknowledgement_count=:a,adoption_pct=:p,exception_count=:x WHERE deployment_id=:d'),{'t':total,'a':ack,'p':pct,'x':exc,'d':deployment_id})
        return {'deployment_id':deployment_id,'status':status,'adoption_pct':pct,'exception_count':exc}

    @app.post('/v90fa/maintenance/reliability-standards/exceptions/{exception_id}/resolve')
    def resolve(exception_id:str, body:dict, request:Request):
        u=perm(e,request,'maintenance_reliability_standard.manage')
        with e.begin() as c:
            x=c.execute(text('SELECT * FROM maintenance_reliability_standard_exception WHERE exception_id=:i'),{'i':exception_id}).mappings().first()
            if not x: raise HTTPException(404,'exception not found')
            c.execute(text("UPDATE maintenance_reliability_standard_exception SET status='RESOLVED',resolved_by=:u,resolved_at=CURRENT_TIMESTAMP,resolution_note=:n WHERE exception_id=:i"),{'u':str(u.user_id),'n':body.get('resolution_note'),'i':exception_id})
        return {'exception_id':exception_id,'status':'RESOLVED'}

    @app.get('/v90fa/maintenance/reliability-standards/dashboard')
    def dashboard(request:Request, organization_id:str, entity_id:str):
        perm(e,request,'maintenance_reliability_standard.view')
        with e.connect() as c:
            d=c.execute(text('SELECT * FROM maintenance_reliability_standard_deployment WHERE organization_id=:o AND entity_id=:e ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id}).mappings().all()
            x=c.execute(text("SELECT * FROM maintenance_reliability_standard_exception WHERE organization_id=:o AND entity_id=:e AND status='OPEN' ORDER BY created_at DESC"),{'o':organization_id,'e':entity_id}).mappings().all()
        active=[r for r in d if r['status']=='ACTIVE']; avg=sum(float(r['adoption_pct'] or 0) for r in active)/len(active) if active else 0
        return {'deployments':[dict(r) for r in d],'open_exceptions':[dict(r) for r in x],'active_deployment_count':len(active),'average_adoption_pct':avg,'operational_mutation':False}

    @app.get('/ui/maintenance-reliability-standard-deployment')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-standard-deployment.html')
