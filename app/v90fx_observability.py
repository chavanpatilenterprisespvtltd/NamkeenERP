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

PERM_VIEW='ops.observability.view'; PERM_MANAGE='ops.observability.manage'
RESULTS=('PASS','FAIL','BLOCKED','WAIVED')
INCIDENT_STATUSES=('OPEN','ACKNOWLEDGED','RESOLVED','CLOSED')
SEVERITIES=('LOW','MEDIUM','HIGH','CRITICAL')
CHECKS=(
 ('APP_HEALTH','Application','Application health/readiness endpoint is healthy'),
 ('DATABASE_HEALTH','Database','Database connectivity and migration state are healthy'),
 ('BACKGROUND_JOBS','Platform','Background jobs/checks are running within SLA'),
 ('ALERTING','Platform','Alert generation and notification route are tested'),
 ('ESCALATION','Operations','Escalation path and ownership are tested'),
 ('PERFORMANCE','Platform','Latency/error-rate smoke remains within threshold'),
 ('BACKUP_DR','Resilience','Backup and DR readiness remains healthy'),
 ('SECURITY','Security','Authentication, authorization and scope controls remain healthy'),
)

class CheckIn(BaseModel):
    check_code:str=Field(min_length=2,max_length=80); result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); metric_value:float|None=None; threshold_value:float|None=None; evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class AlertIn(BaseModel):
    organization_id:str|None=None; severity:str=Field(pattern='^(LOW|MEDIUM|HIGH|CRITICAL)$'); alert_code:str=Field(min_length=2,max_length=100); message:str=Field(min_length=1,max_length=3000); metric_value:float|None=None; threshold_value:float|None=None; evidence_ref:str|None=None
class IncidentIn(BaseModel):
    organization_id:str|None=None; severity:str=Field(pattern='^(LOW|MEDIUM|HIGH|CRITICAL)$'); title:str=Field(min_length=2,max_length=300); description:str=Field(min_length=1,max_length=3000); alert_id:str|None=None; owner_user_id:str|None=None
class IncidentUpdate(BaseModel):
    status:str=Field(pattern='^(OPEN|ACKNOWLEDGED|RESOLVED|CLOSED)$'); resolution_note:str|None=None; evidence_ref:str|None=None
class CloseIn(BaseModel):
    signoff_note:str=Field(min_length=1,max_length=3000); evidence_ref:str=Field(min_length=1,max_length=500)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def ensure_v90fx_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_ops_health_check(check_id TEXT PRIMARY KEY,organization_id TEXT NULL,check_code TEXT NOT NULL,result TEXT NOT NULL,metric_value DOUBLE PRECISION NULL,threshold_value DOUBLE PRECISION NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,checked_by TEXT NOT NULL,checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_ops_alert(alert_id TEXT PRIMARY KEY,organization_id TEXT NULL,severity TEXT NOT NULL,alert_code TEXT NOT NULL,message TEXT NOT NULL,metric_value DOUBLE PRECISION NULL,threshold_value DOUBLE PRECISION NULL,evidence_ref TEXT NULL,status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,acknowledged_at TIMESTAMP NULL,resolved_at TIMESTAMP NULL)''',
    '''CREATE TABLE IF NOT EXISTS erp_ops_incident(incident_id TEXT PRIMARY KEY,organization_id TEXT NULL,severity TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,alert_id TEXT NULL,owner_user_id TEXT NULL,status TEXT NOT NULL DEFAULT 'OPEN',resolution_note TEXT NULL,evidence_ref TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,acknowledged_at TIMESTAMP NULL,resolved_at TIMESTAMP NULL,closed_at TIMESTAMP NULL)''',
    '''CREATE TABLE IF NOT EXISTS erp_ops_period_close(close_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,signoff_note TEXT NOT NULL,evidence_ref TEXT NOT NULL,closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    'CREATE INDEX IF NOT EXISTS ix_ops_health_scope ON erp_ops_health_check(organization_id,check_code,result,checked_at)',
    'CREATE INDEX IF NOT EXISTS ix_ops_alert_scope ON erp_ops_alert(organization_id,status,severity,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_ops_incident_scope ON erp_ops_incident(organization_id,status,severity,created_at)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View observability, alerts and operational SLA controls'),(PERM_MANAGE,'Manage observability, alerts and operational SLA controls')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90fx_routes(app:FastAPI,e:Engine):
    ensure_v90fx_schema(e)
    @app.post('/v90fx/health-checks')
    def health(b:CheckIn,r:Request,organization_id:str|None=None):
        u=_u(e,r,PERM_MANAGE); code=b.check_code.upper()
        if code not in [x[0] for x in CHECKS]: raise HTTPException(422,'unknown operational check')
        if b.result in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        try: assert_security_scope(e,u.user_id,organization_id=organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        cid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_ops_health_check(check_id,organization_id,check_code,result,metric_value,threshold_value,evidence_ref,notes,checked_by) VALUES(:i,:o,:c,:r,:m,:t,:e,:n,:u)'),{'i':cid,'o':organization_id,'c':code,'r':b.result,'m':b.metric_value,'t':b.threshold_value,'e':b.evidence_ref,'n':b.notes,'u':u.user_id})
        return {'check_id':cid,'check_code':code,'result':b.result}
    @app.get('/v90fx/health-checks')
    def health_list(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text('SELECT * FROM erp_ops_health_check WHERE organization_id IS NOT DISTINCT FROM :o ORDER BY checked_at DESC'),{'o':organization_id}).mappings().all()]
        return {'checks':rows,'catalog':CHECKS}
    @app.post('/v90fx/alerts')
    def alert(b:AlertIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        try: assert_security_scope(e,u.user_id,organization_id=b.organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        aid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_ops_alert(alert_id,organization_id,severity,alert_code,message,metric_value,threshold_value,evidence_ref,created_by) VALUES(:i,:o,:s,:c,:m,:v,:t,:e,:u)'),{'i':aid,'o':b.organization_id,'s':b.severity,'c':b.alert_code,'m':b.message,'v':b.metric_value,'t':b.threshold_value,'e':b.evidence_ref,'u':u.user_id})
        return {'alert_id':aid,'status':'OPEN'}
    @app.get('/v90fx/alerts')
    def alerts(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_ops_alert WHERE organization_id IS NOT DISTINCT FROM :o'; p={'o':organization_id}
        if status:q+=' AND status=:s';p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'alerts':rows}
    @app.post('/v90fx/incidents')
    def incident(b:IncidentIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        try: assert_security_scope(e,u.user_id,organization_id=b.organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        iid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_ops_incident(incident_id,organization_id,severity,title,description,alert_id,owner_user_id,created_by) VALUES(:i,:o,:s,:t,:d,:a,:w,:u)'),{'i':iid,'o':b.organization_id,'s':b.severity,'t':b.title,'d':b.description,'a':b.alert_id,'w':b.owner_user_id,'u':u.user_id})
        return {'incident_id':iid,'status':'OPEN'}
    @app.get('/v90fx/incidents')
    def incidents(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_ops_incident WHERE organization_id IS NOT DISTINCT FROM :o';p={'o':organization_id}
        if status:q+=' AND status=:s';p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'incidents':rows}
    @app.post('/v90fx/incidents/{incident_id}/status')
    def incident_status(incident_id:str,b:IncidentUpdate,r:Request):
        u=_u(e,r,PERM_MANAGE)
        if b.status in ('RESOLVED','CLOSED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for RESOLVED or CLOSED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_ops_incident WHERE incident_id=:i'),{'i':incident_id}).mappings().first()
            if not row: raise HTTPException(404,'incident not found')
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            if b.status=='CLOSED' and row['status']!='RESOLVED': raise HTTPException(409,'incident must be RESOLVED before CLOSED')
            sets=['status=:s']; p={'s':b.status,'i':incident_id,'n':b.resolution_note,'e':b.evidence_ref}
            if b.status=='ACKNOWLEDGED': sets.append('acknowledged_at=COALESCE(acknowledged_at,CURRENT_TIMESTAMP)')
            if b.status=='RESOLVED': sets += ['resolved_at=CURRENT_TIMESTAMP','resolution_note=:n','evidence_ref=:e']
            if b.status=='CLOSED': sets += ['closed_at=CURRENT_TIMESTAMP','resolution_note=COALESCE(:n,resolution_note)','evidence_ref=COALESCE(:e,evidence_ref)']
            c.execute(text('UPDATE erp_ops_incident SET '+','.join(sets)+' WHERE incident_id=:i'),p)
        return {'incident_id':incident_id,'status':b.status}
    @app.get('/v90fx/dashboard')
    def dashboard(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            checks=c.execute(text("SELECT check_code,result,COUNT(*) n FROM erp_ops_health_check WHERE organization_id IS NOT DISTINCT FROM :o GROUP BY check_code,result"),{'o':organization_id}).mappings().all()
            open_alerts=c.execute(text("SELECT COUNT(*) FROM erp_ops_alert WHERE organization_id IS NOT DISTINCT FROM :o AND status='OPEN'"),{'o':organization_id}).scalar_one()
            critical=c.execute(text("SELECT COUNT(*) FROM erp_ops_alert WHERE organization_id IS NOT DISTINCT FROM :o AND status='OPEN' AND severity='CRITICAL'"),{'o':organization_id}).scalar_one()
            incidents_open=c.execute(text("SELECT COUNT(*) FROM erp_ops_incident WHERE organization_id IS NOT DISTINCT FROM :o AND status NOT IN ('CLOSED','RESOLVED')"),{'o':organization_id}).scalar_one()
        latest={}
        for x in checks: latest[x['check_code']]=x['result']
        healthy=all(latest.get(x[0]) in ('PASS','WAIVED') for x in CHECKS)
        return {'operationally_healthy':healthy,'health_checks':latest,'open_alerts':int(open_alerts),'critical_open_alerts':int(critical),'open_incidents':int(incidents_open),'sla_dimensions':['availability','latency','error_rate','alert_acknowledgement','incident_resolution']}
    @app.post('/v90fx/{period_key}/close')
    def close(period_key:str,b:CloseIn,r:Request,organization_id:str|None=None):
        u=_u(e,r,PERM_MANAGE); s=dashboard(r,organization_id)
        if not s['operationally_healthy'] or s['critical_open_alerts'] or s['open_incidents']: raise HTTPException(409,{'message':'operational SLA gate failed','summary':s})
        with e.begin() as c:c.execute(text('INSERT INTO erp_ops_period_close(close_id,organization_id,period_key,signoff_note,evidence_ref,closed_by) VALUES(:i,:o,:p,:n,:e,:u)'),{'i':str(uuid4()),'o':organization_id,'p':period_key,'n':b.signoff_note,'e':b.evidence_ref,'u':u.user_id})
        return {'period_key':period_key,'status':'CLOSED','closed_by':u.user_id}
    @app.get('/ui/observability')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'observability.html')
    return {'allowed':True}
