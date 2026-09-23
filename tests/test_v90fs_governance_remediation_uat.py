from fastapi.testclient import TestClient
from app.__main__ import app, engine
from sqlalchemy import text
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def _gap(c,h,org):
    r=c.post('/v90fr/governance/coverage/scan',headers=h,params={'organization_id':org}); assert r.status_code==200,r.text
    return c.get('/v90fr/governance/coverage/gaps',headers=h,params={'organization_id':org}).json()['gaps'][0]['gap_id']

def test_remediation_lifecycle_and_uat():
    c=TestClient(app); h=_admin(c); org='fs-'+str(uuid4())[:8]; gap=_gap(c,h,org)
    r=c.post('/v90fs/governance/remediation',headers=h,json={'gap_id':gap,'owner_user_id':'erpadmin','remediation_plan':'restore policy and certification','due_date':'2026-09-20'}); assert r.status_code==200,r.text
    rid=r.json()['remediation_id']; action=r.json().get('action_code') or c.get('/v90fs/governance/remediation',headers=h,params={'organization_id':org}).json()['remediation'][0]['action_code']; assert c.post(f'/v90fs/governance/remediation/{rid}/start',headers=h).status_code==200
    assert c.post(f'/v90fs/governance/remediation/{rid}/uat',headers=h,json={'critical_action_code':action,'test_case':'policy approval is enforced','result':'PASS','reviewer_note':'verified','evidence_ref':'UT-FS-1'}).status_code==200
    assert c.post(f'/v90fs/governance/remediation/{rid}/complete',headers=h,json={'evidence_ref':'REM-FS-1','note':'implemented and tested'}).status_code==200

def test_uat_requires_evidence_and_readiness():
    c=TestClient(app); h=_admin(c); org='fsr-'+str(uuid4()); gap=_gap(c,h,org)
    rr=c.post('/v90fs/governance/remediation',headers=h,json={'gap_id':gap,'owner_user_id':'erpadmin','remediation_plan':'fix control'}); rid=rr.json()['remediation_id']; action=c.get('/v90fs/governance/remediation',headers=h,params={'organization_id':org}).json()['remediation'][0]['action_code']
    c.post(f'/v90fs/governance/remediation/{rid}/start',headers=h)
    assert c.post(f'/v90fs/governance/remediation/{rid}/uat',headers=h,json={'critical_action_code':action,'test_case':'approval','result':'PASS','reviewer_note':'missing evidence'}).status_code==422
    rd=c.get('/v90fs/governance/certification-readiness',headers=h,params={'organization_id':org}); assert rd.status_code==200 and rd.json()['ready'] is False

def test_close_blocks_unready_and_ui():
    c=TestClient(app); h=_admin(c); org='fsc-'+str(uuid4());
    r=c.post('/v90fs/governance/2026-09/close',headers=h,params={'organization_id':org,'note':'normal close'}); assert r.status_code==409
    assert c.get('/ui/governance-remediation-uat').status_code==200

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
