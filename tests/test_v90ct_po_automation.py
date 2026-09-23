import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=171
 assert TestClient(app).get('/ui/procurement-controls').status_code==200
def test_requisition_to_po_and_approve():
 c=TestClient(app); h=auth(); o,e,l,m=[str(uuid.uuid4()) for _ in range(4)]
 rid=str(uuid.uuid4())
 from app.__main__ import engine
 with engine.begin() as db:
  db.execute(__import__('sqlalchemy').text("INSERT INTO procurement_requisition(requisition_id,organization_id,entity_id,location_id,requested_by,status) VALUES(:i,:o,:e,:l,'erpadmin','APPROVED')"),{'i':rid,'o':o,'e':e,'l':l})
  db.execute(__import__('sqlalchemy').text("INSERT INTO procurement_requisition_line(line_id,requisition_id,line_no,item_master_id,qty,uom) VALUES(:i,:r,1,:m,100,'KG')"),{'i':str(uuid.uuid4()),'r':rid,'m':m})
 r=c.post('/v90ct/procurement/po/from-requisition',json={'requisition_id':rid,'supplier_id':str(uuid.uuid4()),'unit_rate':25,'landed_cost':2600},headers=h); assert r.status_code==200
 po=r.json()['po_id']; a=c.post(f'/v90ct/procurement/po/{po}/approve',headers=h); assert a.status_code==200 and a.json()['status']=='APPROVED'
