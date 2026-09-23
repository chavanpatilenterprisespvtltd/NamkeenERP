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
    assert str(d['release']).startswith('v90.') and int(d['schema_target'])>=230
    assert TestClient(app).get('/ui/maintenance-reliability-cost').status_code==200

def test_reliability_cost_snapshot_flow():
    c,h=TestClient(app),auth(); o,e=map(str,[uuid.uuid4(),uuid.uuid4()])
    w=c.post('/v90cz/manufacturing/work-centers',json={'organization_id':o,'entity_id':e,'code':'WC-R2','name':'Fryer2','capacity_per_shift':100,'shifts_per_day':1},headers=h).json()['work_center_id']
    pre=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'PREVENTIVE','scheduled_date':'2026-09-08','description':'PM'},headers=h).json()['order_id']
    br=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'BREAKDOWN','scheduled_date':'2026-09-08','description':'repair'},headers=h).json()['order_id']
    for oid2,hours in ((pre,2),(br,1)):
        r=c.post('/v90ei/maintenance/labour-charges',json={'organization_id':o,'entity_id':e,'maintenance_order_id':oid2,'work_center_id':w,'labour_category':'TECH','charge_date':'2026-09-08','regular_hours':hours,'overtime_hours':0,'regular_rate':100,'overtime_rate':150},headers=h)
        assert r.status_code==200, r.text
    r=c.post('/v90dc/maintenance/spares',json={'organization_id':o,'entity_id':e,'work_center_id':w,'maintenance_order_id':pre,'material_id':str(uuid.uuid4()),'quantity':2,'unit_cost':50},headers=h); assert r.status_code==200, r.text
    r=c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','event_at':'2026-09-08 10:00:00','duration_minutes':120},headers=h); assert r.status_code==200, r.text
    prod=str(uuid.uuid4())
    r=c.post('/v90cw/manufacturing/batch-cost',json={'organization_id':o,'entity_id':e,'batch_id':str(uuid.uuid4()),'product_id':prod,'period_key':'2026-09','planned_qty':100,'good_qty':90,'material_cost':900,'labor_cost':200,'overhead_cost':100},headers=h); assert r.status_code==200, r.text
    r=c.post('/v90db/machines/runs',json={'organization_id':o,'entity_id':e,'work_center_id':w,'product_id':prod,'planned_qty':100,'good_qty':90,'reject_qty':10,'ideal_cycle_minutes':1,'planned_minutes':100,'actual_run_minutes':90,'downtime_minutes':10},headers=h); assert r.status_code==200, r.text
    r=c.post('/v90db/machines/oee/calculate',json={'organization_id':o,'entity_id':e,'work_center_id':w,'period_start':'2026-09-01','period_end':'2026-09-30'},headers=h); assert r.status_code==200, r.text
    snap=c.post('/v90ek/maintenance/reliability-cost/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','work_center_id':w},headers=h)
    assert snap.status_code==200, snap.text
    j=snap.json(); assert j['maintenance_cost']==400.0 and j['breakdown_hours']==2.0
    dash=c.get('/v90ek/maintenance/reliability-cost/dashboard',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert dash.status_code==200 and dash.json()['count']==1
    comp=c.get('/v90ek/maintenance/reliability-cost/compare',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert comp.status_code==200 and comp.json()['breakdown_cost']==100.0
    assert c.post('/v90ek/maintenance/reliability-cost/2026-09/close',json={'organization_id':o,'entity_id':e},headers=h).status_code==200
    assert c.post('/v90ek/maintenance/reliability-cost/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).status_code==409
