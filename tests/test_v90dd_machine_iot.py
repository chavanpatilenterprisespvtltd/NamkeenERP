import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=181
 assert TestClient(app).get('/ui/machine-iot').status_code==200
def test_iot_flow():
 c=TestClient(app); h=auth(); o,e,w,d=[str(uuid.uuid4()) for _ in range(4)]
 r=c.post('/v90dd/iot/devices',json={'organization_id':o,'entity_id':e,'work_center_id':w,'device_code':'M1','device_type':'PLC','protocol':'MQTT'},headers=h); assert r.status_code==200
 r=c.post('/v90dd/iot/thresholds',json={'organization_id':o,'entity_id':e,'device_id':d,'parameter_code':'TEMP','max_value':80},headers=h); assert r.status_code==200
 r=c.post('/v90dd/iot/telemetry',json={'organization_id':o,'entity_id':e,'work_center_id':w,'device_id':d,'parameter_code':'TEMP','value':95,'unit':'C'},headers=h); assert r.status_code==200 and r.json()['alert_id']
 r=c.post('/v90dd/iot/states',json={'organization_id':o,'entity_id':e,'work_center_id':w,'device_id':d,'state_code':'RUN'},headers=h); assert r.status_code==200
 x=c.get('/v90dd/iot/dashboard',params={'organization_id':o,'entity_id':e},headers=h); assert x.status_code==200 and x.json()['open_alerts']==1
