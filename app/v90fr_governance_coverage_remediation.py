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
from .v90fq_governance_certification import CRITICAL_ACTIONS

PERM_VIEW='governance.remediation.view'; PERM_MANAGE='governance.remediation.manage'

class ResolveIn(BaseModel):
    resolution_note:str=Field(min_length=1,max_length=2000)
    evidence_ref:str=Field(min_length=1,max_length=500)

def _u(e:Engine,r:Request,p:str):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def ensure_v90fr_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_governance_coverage_gap(gap_id TEXT PRIMARY KEY,organization_id TEXT NULL,module_name TEXT NOT NULL,action_code TEXT NOT NULL,gap_type TEXT NOT NULL,first_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,last_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,status TEXT NOT NULL DEFAULT 'OPEN',resolution_note TEXT NULL,evidence_ref TEXT NULL,resolved_by TEXT NULL,resolved_at TIMESTAMP NULL,UNIQUE(organization_id,module_name,action_code,gap_type))''',
    '''CREATE TABLE IF NOT EXISTS erp_governance_coverage_scan(scan_id TEXT PRIMARY KEY,organization_id TEXT NULL,total_actions INTEGER NOT NULL,covered_actions INTEGER NOT NULL,approval_required INTEGER NOT NULL,approval_missing INTEGER NOT NULL,evidence_missing INTEGER NOT NULL,certification_exceptions INTEGER NOT NULL,open_gaps INTEGER NOT NULL,coverage_percent NUMERIC NOT NULL,scanned_by TEXT NOT NULL,scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    'CREATE INDEX IF NOT EXISTS ix_governance_gap_scope ON erp_governance_coverage_gap(organization_id,status,module_name,action_code)',
    'CREATE INDEX IF NOT EXISTS ix_governance_scan_scope ON erp_governance_coverage_scan(organization_id,scanned_at)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View ERP governance coverage remediation'),(PERM_MANAGE,'Manage ERP governance coverage remediation')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90fr_routes(app:FastAPI,e:Engine):
    ensure_v90fr_schema(e)
    @app.post('/v90fr/governance/coverage/scan')
    def scan(r:Request,organization_id:str|None=None):
        u=_u(e,r,PERM_MANAGE)
        try: assert_security_scope(e,u.user_id,organization_id=organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        gaps=[]; covered=0; approval_missing=0; evidence_missing=0; cert_exceptions=0
        with e.begin() as c:
            for m,a in CRITICAL_ACTIONS:
                cert=c.execute(text('''SELECT * FROM erp_governance_critical_action_certification WHERE organization_id IS NOT DISTINCT FROM :o AND module_name=:m AND action_code=:a AND active=TRUE'''),{'o':organization_id,'m':m,'a':a}).mappings().first()
                pol=c.execute(text('''SELECT * FROM erp_governed_action_policy WHERE (organization_id=:o OR organization_id IS NULL) AND module_name=:m AND action_code=:a AND active=TRUE ORDER BY organization_id NULLS LAST LIMIT 1'''),{'o':organization_id,'m':m,'a':a}).mappings().first()
                if cert and cert['certification_status']=='CERTIFIED' and pol and pol['approval_required']:
                    covered+=1
                else:
                    if not pol or not pol['approval_required']: approval_missing+=1
                    if not pol or not pol['evidence_required']: evidence_missing+=1
                    if cert and cert['certification_status']=='EXCEPTION': cert_exceptions+=1
                    gap_type='MISSING_POLICY' if not pol else ('APPROVAL_NOT_REQUIRED' if not pol['approval_required'] else 'UNCERTIFIED')
                    gaps.append((m,a,gap_type))
                    existing=c.execute(text('''SELECT gap_id FROM erp_governance_coverage_gap WHERE organization_id IS NOT DISTINCT FROM :o AND module_name=:m AND action_code=:a AND gap_type=:g AND status='OPEN' '''),{'o':organization_id,'m':m,'a':a,'g':gap_type}).first()
                    if not existing:
                        c.execute(text('''INSERT INTO erp_governance_coverage_gap(gap_id,organization_id,module_name,action_code,gap_type) VALUES(:id,:o,:m,:a,:g)'''),{'id':str(uuid4()),'o':organization_id,'m':m,'a':a,'g':gap_type})
                    else:
                        c.execute(text('UPDATE erp_governance_coverage_gap SET last_detected_at=CURRENT_TIMESTAMP WHERE gap_id=:id'),{'id':existing[0]})
            open_gaps=c.execute(text("SELECT COUNT(*) FROM erp_governance_coverage_gap WHERE organization_id IS NOT DISTINCT FROM :o AND status='OPEN'"),{'o':organization_id}).scalar() or 0
            sid=str(uuid4()); total=len(CRITICAL_ACTIONS); pct=round(covered*100/total,2)
            c.execute(text('''INSERT INTO erp_governance_coverage_scan(scan_id,organization_id,total_actions,covered_actions,approval_required,approval_missing,evidence_missing,certification_exceptions,open_gaps,coverage_percent,scanned_by) VALUES(:id,:o,:t,:c,:ar,:am,:em,:ce,:og,:p,:u)'''),{'id':sid,'o':organization_id,'t':total,'c':covered,'ar':total-approval_missing,'am':approval_missing,'em':evidence_missing,'ce':cert_exceptions,'og':open_gaps,'p':pct,'u':u.user_id})
        return {'scan_id':sid,'total_actions':len(CRITICAL_ACTIONS),'covered_actions':covered,'coverage_percent':pct,'open_gaps':open_gaps,'gaps':[{'module_name':m,'action_code':a,'gap_type':g} for m,a,g in gaps]}
    @app.get('/v90fr/governance/coverage/dashboard')
    def dashboard(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            q='SELECT * FROM erp_governance_coverage_scan WHERE organization_id IS NOT DISTINCT FROM :o ORDER BY scanned_at DESC LIMIT 1'; row=c.execute(text(q),{'o':organization_id}).mappings().first()
            gaps=[dict(x) for x in c.execute(text("SELECT * FROM erp_governance_coverage_gap WHERE organization_id IS NOT DISTINCT FROM :o AND status='OPEN' ORDER BY module_name,action_code"),{'o':organization_id}).mappings().all()]
        return {'latest_scan':dict(row) if row else None,'open_gaps':gaps}
    @app.get('/v90fr/governance/coverage/gaps')
    def gaps(r:Request,organization_id:str|None=None,status:str='OPEN'):
        _u(e,r,PERM_VIEW)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text('SELECT * FROM erp_governance_coverage_gap WHERE organization_id IS NOT DISTINCT FROM :o AND status=:s ORDER BY last_detected_at DESC'),{'o':organization_id,'s':status.upper()}).mappings().all()]
        return {'gaps':rows}
    @app.post('/v90fr/governance/coverage/gaps/{gap_id}/resolve')
    def resolve(gap_id:str,b:ResolveIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text("SELECT * FROM erp_governance_coverage_gap WHERE gap_id=:id AND status='OPEN'"),{'id':gap_id}).mappings().first()
            if not row: raise HTTPException(404,'open governance coverage gap not found')
            try: assert_security_scope(e,u.user_id,organization_id=str(row['organization_id']) if row['organization_id'] else None)
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            c.execute(text("UPDATE erp_governance_coverage_gap SET status='RESOLVED',resolution_note=:n,evidence_ref=:r,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE gap_id=:id"),{'id':gap_id,'n':b.resolution_note,'r':b.evidence_ref,'u':u.user_id})
        return {'gap_id':gap_id,'status':'RESOLVED'}
    @app.get('/ui/governance-coverage-remediation')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'governance_coverage_remediation.html')
