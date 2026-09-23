import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and int(d['schema_target'])>=230
 assert TestClient(app).get('/ui/maintenance-outcome-optimization').status_code==200

def test_outcome_optimization_and_action_approval():
 c,h=TestClient(app),auth(); o,e,w=[str(uuid.uuid4()) for _ in range(3)]
 for typ,day in [('PREVENTIVE','2026-09-05'),('BREAKDOWN','2026-09-06')]:
  x=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':typ,'scheduled_date':day},headers=h); assert x.status_code==200,x.text
  oid=x.json()['order_id']
  et='PM_COMPLETED' if typ=='PREVENTIVE' else 'BREAKDOWN'
  x=c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':et,'event_at':day+' 08:00:00','duration_minutes':60,'maintenance_order_id':oid},headers=h); assert x.status_code==200,x.text
 c.post('/v90dc/maintenance/spares',json={'organization_id':o,'entity_id':e,'work_center_id':w,'maintenance_order_id':oid,'material_id':'SP-1','quantity':2,'unit_cost':10},headers=h)
 x=c.post('/v90es/maintenance/outcome-optimization/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert x.status_code==200,x.text
 j=x.json(); assert j['count']==1 and j['rows'][0]['pm_orders']==1 and j['rows'][0]['corrective_orders']==1
 a=c.get('/v90es/maintenance/outcome-optimization/actions',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json(); assert a['count']==2
 aid=a['actions'][0]['action_id']; x=c.post(f'/v90es/maintenance/outcome-optimization/actions/{aid}/approve',json={'decision_note':'approved for management review'},headers=h); assert x.status_code==200,x.text
 x=c.post('/v90es/maintenance/outcome-optimization/2026-09/close',json={'organization_id':o,'entity_id':e},headers=h); assert x.status_code==200,x.text
 x=c.post('/v90es/maintenance/outcome-optimization/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert x.status_code==409
