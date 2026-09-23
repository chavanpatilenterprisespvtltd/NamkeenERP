from app.__main__ import app
from fastapi.testclient import TestClient
client=TestClient(app)
def login():
 r=client.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text; return {'Authorization':f"Bearer {r.json()['access_token']}"}
def test_completion_audit_gate_and_close():
 h=login(); r=client.post('/v90gw/completion-audits',headers=h,json={'period_key':'2026-09','release_version':'v90.gw'}); assert r.status_code==200,r.text; aid=r.json()['audit_id']
 controls=['SECURITY','AUDIT','BACKUP_DR','PERFORMANCE','DEPLOYMENT','UAT','OPERATIONS','MOBILE','DATA_INTEGRITY','BUSINESS_SIGNOFF']
 assert client.post(f'/v90gw/completion-audits/{aid}/controls/SECURITY',headers=h,json={'control_code':'SECURITY','result':'PASS','evidence_ref':'UT-GW-SEC','notes':'verified'}).status_code==200
 assert client.post(f'/v90gw/completion-audits/{aid}/controls/AUDIT',headers=h,json={'control_code':'AUDIT','result':'PASS','evidence_ref':'UT-GW-AUD','notes':'verified'}).status_code==200
 assert client.post(f'/v90gw/completion-audits/{aid}/close',headers=h,json={'note':'not ready','evidence_ref':'UT-GW-CLOSE'}).status_code==409
 for c in controls[2:]: assert client.post(f'/v90gw/completion-audits/{aid}/controls/{c}',headers=h,json={'control_code':c,'result':'WAIVED','evidence_ref':'UT-GW-'+c,'notes':'controlled waiver for unit test'}).status_code==200
 assert client.post(f'/v90gw/completion-audits/{aid}/close',headers=h,json={'note':'all controls evidenced','evidence_ref':'UT-GW-FINAL'}).status_code==200
def test_completion_audit_requires_evidence_and_rbac():
 h=login(); r=client.post('/v90gw/completion-audits',headers=h,json={'period_key':'2026-10'}); aid=r.json()['audit_id']
 assert client.post(f'/v90gw/completion-audits/{aid}/controls/SECURITY',headers=h,json={'control_code':'SECURITY','result':'PASS','notes':'missing evidence'}).status_code==422
