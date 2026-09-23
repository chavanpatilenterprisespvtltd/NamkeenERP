from fastapi.testclient import TestClient
from app.__main__ import app, engine
from sqlalchemy import text
from uuid import uuid4


def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'})
    assert r.status_code==200, r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_governed_action_requires_evidence_and_separation_of_duties():
    c=TestClient(app); h=_admin(c)
    org='fo-'+str(uuid4())[:8]; ent='foe-'+str(uuid4())[:8]
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:e,:c,'FO Entity','legal_entity') ON CONFLICT(entity_id) DO NOTHING"),{'e':ent,'c':ent[-8:]})
        db.execute(text("INSERT INTO erp_security_entity_organization(entity_id,organization_id,mapped_by) VALUES(:e,:o,'erpadmin') ON CONFLICT(entity_id) DO UPDATE SET organization_id=:o"),{'e':ent,'o':org})
        db.execute(text("INSERT INTO erp_organization_user_access(user_id,organization_id,active,granted_by) VALUES('erpadmin',:o,1,'erpadmin') ON CONFLICT(user_id,organization_id) DO UPDATE SET active=1"),{'o':org})
    r=c.post('/v90fo/governance/actions',headers=h,json={'organization_id':org,'entity_id':ent,'module_name':'TEST','action_code':'TEST.CRITICAL','subject_type':'TEST','subject_id':'S1'})
    assert r.status_code==200,r.text; aid=r.json()['action_id']
    r=c.post(f'/v90fo/governance/actions/{aid}/approve',headers=h,json={'decision_note':'approve'})
    assert r.status_code==409,r.text
    r=c.post(f'/v90fo/governance/actions/{aid}/evidence',headers=h,json={'evidence_type':'DOCUMENT','evidence_note':'checked source evidence'})
    assert r.status_code==200,r.text
    # self approval remains forbidden
    r=c.post(f'/v90fo/governance/actions/{aid}/approve',headers=h,json={'decision_note':'approve'})
    assert r.status_code==409,r.text
    rows=c.get('/v90fo/governance/audit',headers=h,params={'organization_id':org}).json()['events']
    assert any(x['action_code']=='EVIDENCE_ADD' for x in rows)


def test_migration_241_manifest_and_ui():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(x.version==241 and x.filename=='241_v90fo_audit_approval_evidence.sql' for x in ms)
    c=TestClient(app); h=_admin(c)
    r=c.get('/ui/governance-control',headers=h); assert r.status_code==200
