from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_problem_escalation_lifecycle_and_gate():
    c=TestClient(app); h=_admin(c); org='gi-'+str(uuid4())[:8]
    r=c.post('/v90gi/problems',headers=h,json={'organization_id':org,'problem_code':'P-001','title':'Recurring outage','description':'test','severity':'CRITICAL','note':'problem'}); assert r.status_code==200,r.text; pid=r.json()['problem_id']
    assert c.post(f'/v90gi/problems/{pid}/links',headers=h,json={'reference_type':'SLA_BREACH','reference_id':'B-1','note':'linked'}).status_code==200
    assert c.post('/v90gi/escalations',headers=h,json={'problem_id':pid,'level':1,'due_at':'2999-01-01T10:00:00','reason':'critical'}).status_code==200
    d=c.get('/v90gi/dashboard',headers=h,params={'organization_id':org}); assert d.json()['critical_open_problems']==1 and d.json()['governance_gate_pass'] is False
    assert c.post(f'/v90gi/problems/{pid}/status',headers=h,json={'status':'CLOSED','evidence_ref':'C','note':'early'}).status_code==409
    assert c.post(f'/v90gi/problems/{pid}/status',headers=h,json={'status':'RESOLVED','evidence_ref':'R','note':'resolved','root_cause':'root'}).status_code==200
    assert c.post(f'/v90gi/problems/{pid}/status',headers=h,json={'status':'CLOSED','evidence_ref':'C','note':'closed'}).status_code==200

def test_escalation_requires_evidence_to_close():
    c=TestClient(app); h=_admin(c); org='gi2-'+str(uuid4())[:8]
    r=c.post('/v90gi/problems',headers=h,json={'organization_id':org,'problem_code':'P-002','title':'Issue','description':'test','severity':'HIGH','note':'problem'}); pid=r.json()['problem_id']
    r=c.post('/v90gi/escalations',headers=h,json={'problem_id':pid,'level':1,'due_at':'2999-01-01T10:00:00','reason':'test'}); eid=r.json()['escalation_id']
    assert c.post(f'/v90gi/escalations/{eid}/status',headers=h,json={'status':'CLOSED','note':'missing'}).status_code==422
    assert c.post(f'/v90gi/escalations/{eid}/status',headers=h,json={'status':'CLOSED','evidence_ref':'E','note':'closed'}).status_code==200

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
