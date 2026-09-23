from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_backup_restore_drill_and_readiness():
    c=TestClient(app); h=_admin(c)
    bid=c.post('/v90fw/backups',headers=h,json={'environment':'STAGING','backup_type':'FULL','artifact_ref':'backup://test','status':'SUCCESS','notes':'verified backup'}).json()['backup_id']
    assert c.post('/v90fw/restores',headers=h,json={'backup_id':bid,'environment':'DR','result':'PASS','restored_schema':248,'validation_evidence_ref':'restore-evidence','notes':'schema and application validation'}).status_code==200
    assert c.post('/v90fw/dr-drills',headers=h,json={'scenario':'isolated restore and application recovery','result':'PASS','rpo_minutes':30,'rto_minutes':60,'evidence_ref':'dr-evidence','notes':'recovery drill'}).status_code==200
    s=c.get('/v90fw/recovery-readiness',headers=h).json(); assert s['ready_for_dr'] is True

def test_restore_requires_validation_evidence():
    c=TestClient(app); h=_admin(c)
    bid=c.post('/v90fw/backups',headers=h,json={'environment':'STAGING','backup_type':'FULL','artifact_ref':'backup://test2','status':'SUCCESS','notes':'x'}).json()['backup_id']
    assert c.post('/v90fw/restores',headers=h,json={'backup_id':bid,'environment':'DR','result':'PASS','notes':'missing evidence'}).status_code==422

def test_dr_close_blocked_without_readiness():
    c=TestClient(app); h=_admin(c)
    org='no-readiness-'+str(uuid4())
    assert c.post('/v90fw/2026-09/close?organization_id='+org,headers=h,json={'signoff_note':'x','evidence_ref':'x'}).status_code==409

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
