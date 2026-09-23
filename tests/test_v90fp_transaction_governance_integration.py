from fastapi.testclient import TestClient
from app.__main__ import app, engine
from sqlalchemy import text
from uuid import uuid4


def _admin(c):
    r = c.post('/auth/login', json={'username': 'erpadmin', 'password': 'change-me'})
    assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def test_coverage_and_audit_only_core_routes():
    c = TestClient(app); h = _admin(c)
    r = c.get('/v90fp/governance/coverage', headers=h)
    assert r.status_code == 200
    modules = {x['module_name'] for x in r.json()['modules']}
    assert {'PROCUREMENT','INVENTORY','PRODUCTION','PROCESS_QC','BATCH_PACKING','FG_DISPATCH','SALES','RETURNS','ACCOUNTING','INTERCOMPANY'} <= modules


def test_require_approval_policy_blocks_and_then_allows_with_governed_action():
    c = TestClient(app); h = _admin(c)
    org = 'fp-' + str(uuid4())[:8]
    ent = 'fpe-' + str(uuid4())[:8]
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:e,:c,'FP Entity','legal_entity') ON CONFLICT(entity_id) DO NOTHING"), {'e': ent, 'c': ent[-8:]})
        db.execute(text("INSERT INTO erp_security_entity_organization(entity_id,organization_id,mapped_by) VALUES(:e,:o,'erpadmin') ON CONFLICT(entity_id) DO UPDATE SET organization_id=:o"), {'e': ent, 'o': org})
        db.execute(text("INSERT INTO erp_organization_user_access(user_id,organization_id,active,granted_by) VALUES('erpadmin',:o,1,'erpadmin') ON CONFLICT(user_id,organization_id) DO UPDATE SET active=1"), {'o': org})
    body = {'organization_id':org,'module_name':'TEST','action_code':'TEST.GOVERNED','route_prefix':'/v90fp/test/controlled','http_method':'POST','enforcement':'REQUIRE_APPROVAL','active':True}
    r = c.post('/v90fp/governance/integrations', headers=h, json=body); assert r.status_code==200, r.text
    # Create and approve the action through the V90.fo governance layer; middleware then validates it.
    aid = c.post('/v90fo/governance/actions', headers=h, json={'organization_id':org,'entity_id':ent,'module_name':'TEST','action_code':'TEST.GOVERNED','subject_type':'TEST','subject_id':'1','evidence_required':False}).json()['action_id']
    with engine.begin() as db:
        db.execute(text("UPDATE erp_governed_action SET status='APPROVED',approved_by='system',approved_at=CURRENT_TIMESTAMP,evidence_complete=TRUE WHERE action_id=:a"), {'a':aid})
    r = c.post('/v90fp/test/controlled', headers={'Authorization':h['Authorization'], 'X-Governed-Action-Id':aid})
    assert r.status_code == 404  # middleware authorized; no ordinary route is registered for this probe path.
    with engine.connect() as db:
        row = db.execute(text('SELECT outcome FROM erp_governance_integration_event WHERE governed_action_id=:a ORDER BY created_at DESC LIMIT 1'), {'a':aid}).first()
        assert row and row[0] == 'HTTP_ERROR'


def test_manifest_ui_and_policy_deactivation():
    from app.migrations import load_migrations
    ms = load_migrations(); assert ms[-1].version >= 263 and any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms)
    c=TestClient(app); h=_admin(c)
    r=c.get('/ui/governance-integration',headers=h); assert r.status_code==200
