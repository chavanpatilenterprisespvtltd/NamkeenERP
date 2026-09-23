from fastapi.testclient import TestClient
from app.__main__ import app, engine
from sqlalchemy import text
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_bootstrap_and_coverage():
    c=TestClient(app); h=_admin(c)
    r=c.post('/v90fq/governance/certifications/bootstrap',headers=h); assert r.status_code==200,r.text
    r=c.get('/v90fq/governance/coverage',headers=h); assert r.status_code==200
    assert r.json()['total_critical_actions']==12
    assert r.json()['exceptions']>=12

def test_certify_changes_coverage():
    c=TestClient(app); h=_admin(c); org='fq-'+str(uuid4())[:8]
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_organization_user_access(user_id,organization_id,active,granted_by) VALUES('erpadmin',:o,1,'erpadmin') ON CONFLICT(user_id,organization_id) DO UPDATE SET active=1"),{'o':org})
    r=c.post('/v90fq/governance/certifications',headers=h,json={'organization_id':org,'module_name':'SALES','action_code':'SALES.WRITE','certification_status':'CERTIFIED','control_note':'Approval and evidence control verified','evidence_ref':'UT-FQ-1'})
    assert r.status_code==200,r.text
    r=c.get('/v90fq/governance/certifications',headers=h,params={'organization_id':org,'status':'CERTIFIED'}); assert len(r.json()['certifications'])==1

def test_exception_resolve_requires_evidence():
    c=TestClient(app); h=_admin(c); org='fqx-'+str(uuid4())[:8]
    r=c.post('/v90fq/governance/exceptions',headers=h,json={'organization_id':org,'module_name':'ACCOUNTING','action_code':'ACCOUNTING.WRITE','control_note':'Temporary evidence-system exception'})
    assert r.status_code==200; eid=r.json()['exception_id']
    assert c.post(f'/v90fq/governance/exceptions/{eid}/resolve',headers=h,json={'resolution_note':'No evidence'}).status_code==422
    r=c.post(f'/v90fq/governance/exceptions/{eid}/resolve',headers=h,json={'resolution_note':'Control restored','evidence_ref':'EV-42'}); assert r.status_code==200

def test_close_blocks_open_exceptions():
    c=TestClient(app); h=_admin(c)
    r=c.post('/v90fq/governance/exceptions',headers=h,json={'module_name':'INVENTORY','action_code':'INVENTORY.WRITE','control_note':'Open test exception'}); assert r.status_code==200
    assert c.post('/v90fq/governance/2026-09/close',headers=h,params={'note':'test'}).status_code==409
    assert c.post('/v90fq/governance/2026-09/close',headers=h,params={'force':'true','note':'forced test close'}).status_code==200

def test_manifest_ui():
    from app.migrations import load_migrations
    ms=load_migrations(); assert ms[-1].version>=263 and any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms)
    c=TestClient(app); h=_admin(c); assert c.get('/ui/governance-certification',headers=h).status_code==200
