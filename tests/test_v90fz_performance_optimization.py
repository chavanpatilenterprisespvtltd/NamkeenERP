from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_optimization_execution_and_certification_gate():
    c=TestClient(app); h=_admin(c); org='fz-'+str(uuid4())[:8]
    r=c.get('/v90fz/performance/certification-readiness',headers=h,params={'organization_id':org}); assert r.status_code==200 and r.json()['ready'] is False
    r=c.post('/v90fz/performance/actions',headers=h,json={'organization_id':org,'finding_ref':'HOT-1','action_type':'DB_INDEX','title':'Add missing index','status':'PROPOSED','notes':'optimize order query'}); assert r.status_code==200; aid=r.json()['action_id']
    r=c.post(f'/v90fz/performance/actions/{aid}/status',headers=h,json={'status':'COMPLETED'}); assert r.status_code==422
    r=c.post(f'/v90fz/performance/actions/{aid}/status',headers=h,json={'status':'COMPLETED','evidence_ref':'EXEC-1','result_note':'index deployed'}); assert r.status_code==200
    r=c.post('/v90fz/performance/capacity-remediations',headers=h,json={'organization_id':org,'finding_ref':'CAP-1','resource_type':'DB_CONNECTIONS','current_value':90,'target_value':120,'unit':'connections','action_ref':aid,'status':'IN_PROGRESS','notes':'increase pool'}); assert r.status_code==200; rid=r.json()['remediation_id']
    r=c.get('/v90fz/performance/certification-readiness',headers=h,params={'organization_id':org}); assert r.json()['gates']['capacity_remediated'] is False
    r=c.post(f'/v90fz/performance/capacity-remediations/{rid}/status',headers=h,json={'organization_id':org,'finding_ref':'CAP-1','resource_type':'DB_CONNECTIONS','current_value':120,'target_value':120,'unit':'connections','action_ref':aid,'status':'COMPLETED','evidence_ref':'CAP-EXEC-1','notes':'pool updated'}); assert r.status_code==200
    r=c.post('/v90fz/performance/optimization-results',headers=h,json={'organization_id':org,'action_ref':aid,'baseline_ref':'BASE-1','post_change_ref':'POST-1','latency_delta_pct':-18.0,'throughput_delta_pct':12.0,'error_rate_delta_pct':-0.2,'result':'PASS','evidence_ref':'POST-1','notes':'measured improvement'}); assert r.status_code==200
    r=c.get('/v90fz/performance/certification-readiness',headers=h,params={'organization_id':org}); assert r.status_code==200 and r.json()['ready'] is True
    r=c.post('/v90fz/performance/2026-09/certify',headers=h,params={'organization_id':org},json={'result':'CERTIFIED','certification_note':'scalability remediation complete','evidence_ref':'CERT-1'}); assert r.status_code==200
    r=c.post('/v90fz/performance/2026-09/close',headers=h,params={'organization_id':org},json={'signoff_note':'closed','evidence_ref':'CLOSE-1'}); assert r.status_code==200

def test_failed_post_change_blocks_and_validation():
    c=TestClient(app); h=_admin(c); org='fz2-'+str(uuid4())
    r=c.post('/v90fz/performance/optimization-results',headers=h,json={'organization_id':org,'action_ref':'AA','baseline_ref':'BB','post_change_ref':'PP','latency_delta_pct':1,'throughput_delta_pct':-5,'error_rate_delta_pct':1,'result':'PASS','notes':'x'}); assert r.status_code==422
    r=c.post('/v90fz/performance/actions',headers=h,json={'organization_id':org,'finding_ref':'XX','action_type':'CACHE','title':'Cache hot query','status':'PROPOSED','notes':'x'}); assert r.status_code==200; aid=r.json()['action_id']
    r=c.post('/v90fz/performance/actions/'+aid+'/status',headers=h,json={'status':'COMPLETED','evidence_ref':'E'}); assert r.status_code==200
    r=c.post('/v90fz/performance/capacity-remediations',headers=h,json={'organization_id':org,'finding_ref':'CC','resource_type':'CPU','current_value':95,'target_value':70,'unit':'pct','action_ref':aid,'status':'COMPLETED','evidence_ref':'C','notes':'x'}); assert r.status_code==200
    r=c.post('/v90fz/performance/optimization-results',headers=h,json={'organization_id':org,'action_ref':aid,'baseline_ref':'BB','post_change_ref':'PP','latency_delta_pct':10,'throughput_delta_pct':-10,'error_rate_delta_pct':0.8,'result':'FAIL','evidence_ref':'FAIL-1','notes':'regression'}); assert r.status_code==200
    r=c.get('/v90fz/performance/certification-readiness',headers=h,params={'organization_id':org}); assert r.status_code==200 and r.json()['ready'] is False and r.json()['gates']['no_failed_post_change'] is False

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
