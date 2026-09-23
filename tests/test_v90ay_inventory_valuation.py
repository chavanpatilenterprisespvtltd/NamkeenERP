from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_env():
    uid=str(uuid4()); uname='ay_'+uid[:8]
    create_user(engine,uid,uname,'pw','AY Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); ids={k:str(uuid4()) for k in ['e','l','w','item','lot','grn','grnl']}
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'AY','legal_entity',1)"),{'e':ids['e'],'c':'AY'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'AY','site',1)"),{'l':ids['l'],'e':ids['e'],'c':'AYL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:c,'AY','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'c':'AYW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:i,'kg',40)"),{'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'i':ids['item']})
        db.execute(text("INSERT INTO inventory_grn(grn_id,organization_id,entity_id,location_id,warehouse_id,grn_no,supplier_id,received_at,status,created_by) VALUES(:g,:o,:e,:l,:w,'AYGRN',:s,'2026-01-01','APPROVED',:u)"),{'g':ids['grn'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'s':str(uuid4()),'u':uid})
        db.execute(text("INSERT INTO inventory_grn_line(grn_line_id,grn_id,line_no,item_master_id,ordered_qty,received_qty,accepted_qty,rejected_qty,uom,unit_rate,mfg_date,expiry_date,qc_required,qc_status) VALUES(:gl,:g,1,:i,40,40,40,0,'kg',12,'2026-01-01','2026-12-31',0,'PASS')"),{'gl':ids['grnl'],'g':ids['grn'],'i':ids['item']})
        db.execute(text("INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,lot_code,mfg_date,expiry_date,received_qty,accepted_qty,available_qty,uom,qc_status,status) VALUES(:lot,:o,:e,:l,:w,:i,:g,:gl,:s,'AYLOT','2026-01-01','2026-12-31',40,40,40,'kg','PASS','AVAILABLE')"),{'lot':ids['lot'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'i':ids['item'],'g':ids['grn'],'gl':ids['grnl'],'s':str(uuid4())})
    return c,ids,org


def test_valuation_uses_grn_fallback_and_snapshot():
    c,ids,org=setup_env()
    r=c.get('/v90ay/inventory/valuation',params={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']})
    assert r.status_code==200,r.text
    j=r.json(); assert j['total_qty']==40.0 and j['total_value']==480.0
    r=c.post('/v90ay/inventory/valuation-snapshots',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']})
    assert r.status_code==200 and r.json()['status']=='SNAPSHOT_CREATED'
    assert c.get('/v90ay/inventory/valuation-snapshots',params={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']}).json()['items']


def test_ageing_policy_and_slow_moving_bucket():
    c,ids,org=setup_env()
    r=c.put('/v90ay/inventory/ageing-policy',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'slow_moving_days':30,'dead_stock_days':60})
    assert r.status_code==200,r.text
    r=c.get('/v90ay/inventory/stock-ageing',params={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']})
    assert r.status_code==200,r.text
    assert r.json()['policy']['slow_moving_days']==30


def test_dead_threshold_validation():
    c,ids,org=setup_env()
    r=c.put('/v90ay/inventory/ageing-policy',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'slow_moving_days':90,'dead_stock_days':90})
    assert r.status_code==422


def test_v90ay_migration_124():
    from app.migrations import load_migrations
    assert any(m.version==124 and m.filename=='124_v90ay_inventory_valuation_ageing.sql' for m in load_migrations())
