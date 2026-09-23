from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_hypercare_requires_closure_and_checkpoint_evidence():
    c=TestClient(app); h=_admin(c); org='gg-'+str(uuid4())[:8]
    r=c.post('/v90gg/hypercare',headers=h,json={'organization_id':org,'period_key':'2026-09','release_version':'v90.gg','environment':'PRODUCTION','hypercare_days':2,'business_owner':'Owner','support_owner':'Ops','note':'hypercare'}); assert r.status_code==200,r.text; hid=r.json()['hypercare_id']
    r=c.post(f'/v90gg/hypercare/{hid}/accept',headers=h,json={'evidence_ref':'ACC','note':'should fail'}); assert r.status_code==409
    for code in ('GO_LIVE_CLOSURE','HEALTH_STABILITY','CRITICAL_ISSUES','HYPERCARE_EVIDENCE','SUPPORT_OWNERSHIP','BUSINESS_KPI_ACCEPTANCE'):
        r=c.post(f'/v90gg/hypercare/{hid}/controls/{code}',headers=h,json={'status':'PASS','evidence_ref':'EV-'+code,'note':'reviewed'}); assert r.status_code==200,r.text
    for d in ('2026-09-10','2026-09-11'):
        r=c.post(f'/v90gg/hypercare/{hid}/checkpoints',headers=h,json={'checkpoint_date':d,'health_status':'PASS','incident_count':0,'open_critical_count':0,'kpi_status':'PASS','evidence_ref':'CP-'+d,'note':'stable'}); assert r.status_code==200,r.text
    r=c.get(f'/v90gg/hypercare/{hid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_closure'] is False

def test_checkpoint_duplicate_and_close_order():
    c=TestClient(app); h=_admin(c); org='gg2-'+str(uuid4())[:8]
    r=c.post('/v90gg/hypercare',headers=h,json={'organization_id':org,'period_key':'2026-10','release_version':'v90.gg','environment':'PRODUCTION','hypercare_days':1,'business_owner':'Owner','support_owner':'Ops','note':'hypercare'}); hid=r.json()['hypercare_id']
    payload={'checkpoint_date':'2026-10-01','health_status':'PASS','incident_count':0,'open_critical_count':0,'kpi_status':'PASS','evidence_ref':'E1','note':'stable'}
    assert c.post(f'/v90gg/hypercare/{hid}/checkpoints',headers=h,json=payload).status_code==200
    assert c.post(f'/v90gg/hypercare/{hid}/checkpoints',headers=h,json=payload).status_code==409
    assert c.post(f'/v90gg/hypercare/{hid}/close',headers=h,json={'evidence_ref':'C','note':'not accepted'}).status_code==409

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
