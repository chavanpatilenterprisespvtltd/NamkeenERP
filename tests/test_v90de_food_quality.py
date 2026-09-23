import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=182
 assert TestClient(app).get('/ui/food-quality').status_code==200
def test_quality_flow():
 c=TestClient(app); h=auth(); o,e,b=[str(uuid.uuid4()) for _ in range(3)]
 assert c.post('/v90de/quality/specs',json={'organization_id':o,'entity_id':e,'material_or_product_id':'RM1','stage':'INCOMING','spec_name':'Moisture','parameter_code':'MOIST','unit':'%','max_value':2},headers=h).status_code==200
 i=c.post('/v90de/quality/inspections',json={'organization_id':o,'entity_id':e,'batch_id':b,'stage':'INCOMING'},headers=h).json()['inspection_id']
 assert c.post(f'/v90de/quality/inspections/{i}/results',json={'parameter_code':'MOIST','value_numeric':1.2,'unit':'%','pass':True},headers=h).status_code==200
 assert c.post(f'/v90de/quality/inspections/{i}/release',headers=h).status_code==200
 assert c.post('/v90de/quality/nc',json={'organization_id':o,'entity_id':e,'batch_id':b,'category':'PACKAGING','description':'Label defect'},headers=h).status_code==200
 d=c.get('/v90de/quality/dashboard',params={'organization_id':o,'entity_id':e},headers=h)
 assert d.status_code==200 and d.json()['open_nc']==1
