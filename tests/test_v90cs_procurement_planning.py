import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=170
 assert TestClient(app).get('/ui/procurement-planning').status_code==200
def test_rfq_quotes_compare():
 c=TestClient(app); h=auth(); o,e,l,m,s=[str(uuid.uuid4()) for _ in range(5)]
 r=c.post('/v90cs/procurement/rfq',json={'organization_id':o,'entity_id':e,'location_id':l,'material_master_id':m,'required_qty':100,'uom':'KG','supplier_ids':[s]},headers=h); assert r.status_code==200
 rid=r.json()['rfq_id']; assert c.post(f'/v90cs/procurement/rfq/{rid}/quotes',json={'supplier_id':s,'unit_price':100,'landed_cost':105,'lead_time_days':5,'quality_score':90},headers=h).status_code==200
 x=c.get(f'/v90cs/procurement/rfq/{rid}/compare',headers=h); assert x.status_code==200 and x.json()['recommended_quote']['supplier_id']==s
