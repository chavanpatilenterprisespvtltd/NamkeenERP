import json, uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]

def auth():
    from app.auth import make_access_token, UserRecord
    return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}

def test_release_and_ui():
    d=json.loads((ROOT/'config/release_manifest.json').read_text())
    assert str(d['release']).startswith('v90.') and int(d['schema_target']) >= 210
    assert TestClient(app).get('/ui/maintenance-production-cost').status_code==200

def test_maintenance_to_production_cost_flow():
    c,h=TestClient(app),auth(); o,e=map(str,[uuid.uuid4(),uuid.uuid4()])
    w=c.post('/v90cz/manufacturing/work-centers',json={'organization_id':o,'entity_id':e,'code':'WC-1','name':'Fryer','capacity_per_shift':100,'shifts_per_day':1},headers=h).json()['work_center_id']
    oid=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'description':'repair'},headers=h).json()['order_id']
    r=c.post('/v90ei/maintenance/labour-rates',json={'organization_id':o,'entity_id':e,'work_center_id':w,'labour_category':'TECH','regular_rate':100,'overtime_rate':150},headers=h); assert r.status_code==200
    ch=c.post('/v90ei/maintenance/labour-charges',json={'organization_id':o,'entity_id':e,'maintenance_order_id':oid,'work_center_id':w,'labour_category':'TECH','charge_date':'2026-09-08','regular_hours':4,'overtime_hours':2},headers=h); assert ch.status_code==200
    batch=str(uuid.uuid4()); prod=str(uuid.uuid4())
    c.post('/v90cz/manufacturing/schedule',json={'organization_id':o,'entity_id':e,'production_order_id':str(uuid.uuid4()),'product_id':prod,'work_center_id':w,'schedule_date':'2026-09-08','shift_code':'A','planned_qty':100,'required_hours':8},headers=h)
    mc=c.post('/v90cw/manufacturing/batch-cost',json={'organization_id':o,'entity_id':e,'batch_id':batch,'product_id':prod,'period_key':'2026-09','planned_qty':100,'good_qty':90,'material_cost':900,'labor_cost':200,'overhead_cost':100},headers=h); assert mc.status_code==200
    rr=c.post('/v90ej/maintenance/production-cost/allocate',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','work_center_id':w,'allocation_basis':'PRODUCTION_QTY'},headers=h); assert rr.status_code==200
    assert rr.json()['maintenance_labour_cost']==700
    dash=c.get('/v90ej/maintenance/production-cost/dashboard',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert dash.status_code==200
    assert dash.json()['allocated_cost']==700
    lines=c.get('/v90ej/maintenance/production-cost/lines',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json()['lines']; assert lines
    assert lines[0]['allocated_maintenance_cost']==700
    closed=c.post('/v90ej/maintenance/production-cost/2026-09/close',json={'organization_id':o,'entity_id':e},headers=h); assert closed.status_code==200
    again=c.post('/v90ej/maintenance/production-cost/allocate',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','work_center_id':w},headers=h); assert again.status_code==409
