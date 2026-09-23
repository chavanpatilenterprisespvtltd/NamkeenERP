from fastapi.testclient import TestClient
from app.__main__ import app
from app.v90gj_advanced_mis_dashboard import ensure_v90gj_schema
from app.__main__ import engine
from uuid import uuid4
import json
from pathlib import Path

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_gj_manifest_and_artifacts():
    r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
    assert Path('app/v90gj_advanced_mis_dashboard.py').exists()
    assert Path('migrations/262_v90gk_costing_profitability.sql').exists()
    assert Path('web/mis-dashboard.html').exists()

def _env():
    c=TestClient(app); h=_admin(c); org=str(uuid4()); entity=str(uuid4())
    with engine.begin() as db:
        db.execute(__import__('sqlalchemy').text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GJ','legal_entity',1)"),{'e':entity,'c':'GJ'+entity[:8]})
        db.execute(__import__('sqlalchemy').text("INSERT INTO erp_security_entity_organization(entity_id,organization_id,mapped_by) VALUES(:e,:o,'erpadmin')"),{'e':entity,'o':org})
    return c,h,org,entity

def test_dashboard_snapshot_zero_source_and_readback():
    ensure_v90gj_schema(engine)
    c,h,org,entity=_env()
    r=c.post('/v90gj/mis/dashboard/snapshot',headers=h,json={'organization_id':org,'entity_id':entity,'period_key':'2099-01','evidence_ref':'MIS-EVID'}); assert r.status_code==200,r.text
    body=r.json(); assert body['assessment']=='REVIEW_REQUIRED' and body['executive_health_score']==0.0
    r=c.get('/v90gj/mis/dashboard',headers=h,params={'organization_id':org,'entity_id':entity,'period_key':'2099-01'}); assert r.status_code==200
    assert len(r.json()['kpis'])==17

def test_dashboard_compare():
    c,h,org,entity=_env()
    for p in ('2099-02','2099-03'):
        r=c.post('/v90gj/mis/dashboard/snapshot',headers=h,json={'organization_id':org,'entity_id':entity,'period_key':p}); assert r.status_code==200,r.text
    r=c.get('/v90gj/mis/dashboard/compare',headers=h,params={'organization_id':org,'entity_id':entity,'from_period':'2099-02','to_period':'2099-03'}); assert r.status_code==200 and r.json()['count']==2
