from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_env():
    uid=str(uuid4()); uname='ba_'+uid[:8]
    create_user(engine,uid,uname,'pw','BA Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4()); w=str(uuid4()); lot=str(uuid4()); sku=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'BA','legal_entity',1)"),{'e':e,'c':'BA'+e[:8]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'BA','site',1)"),{'l':l,'e':e,'c':'BAL'+l[:6]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:c,'BA','general',1)"),{'w':w,'e':e,'l':l,'c':'BAW'+w[:6]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
        db.execute(text("INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,lot_code,received_qty,accepted_qty,available_qty,uom,qc_status,status) VALUES(:lot,:o,:e,:l,:w,:i,:g,:gl,:s,'RAWBA',10,10,10,'kg','RELEASED','AVAILABLE')"),{'lot':lot,'o':org,'e':e,'l':l,'w':w,'i':sku,'g':str(uuid4()),'gl':str(uuid4()),'s':str(uuid4())})
    return c,org,e,l,w

def test_register_resolve_and_scan_batch():
    c,org,e,l,w=setup_env()
    r=c.post('/v90ba/barcodes/register',json={'organization_id':org,'entity_id':e,'location_id':l,'code':'RAW-BA-001','symbology':'CODE128','object_type':'RAW_LOT','object_id':str(uuid4())})
    assert r.status_code==200, r.text
    assert c.post('/v90ba/barcodes/register',json={'organization_id':org,'entity_id':e,'location_id':l,'code':'RAW-BA-001','symbology':'CODE128','object_type':'RAW_LOT','object_id':str(uuid4())}).status_code==409
    q=c.get('/v90ba/barcodes/resolve',params={'organization_id':org,'entity_id':e,'location_id':l,'code':'RAW-BA-001'}); assert q.status_code==200
    s=c.post('/v90ba/scans',json={'organization_id':org,'entity_id':e,'location_id':l,'warehouse_id':w,'code':'RAW-BA-001','purpose':'PICK'}); assert s.status_code==200
    b=c.post('/v90ba/scan-batches',json={'organization_id':org,'entity_id':e,'location_id':l,'purpose':'STOCKTAKE'}); assert b.status_code==200; bid=b.json()['scan_batch_id']
    bs=c.post(f'/v90ba/scan-batches/{bid}/scans',json={'code':'RAW-BA-001','quantity':2,'uom':'kg'}); assert bs.status_code==200
    assert c.post(f'/v90ba/scan-batches/{bid}/close').status_code==200
    assert c.get(f'/v90ba/scan-batches/{bid}').status_code==200

def test_unknown_scan_and_migration():
    c,org,e,l,w=setup_env()
    x=c.post('/v90ba/scans',json={'organization_id':org,'entity_id':e,'location_id':l,'code':'NOPE','purpose':'LOOKUP'})
    assert x.status_code==404
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==126 and m.filename=='126_v90ba_barcode_qr_operational_completion.sql' for m in ms); assert any(m.version==127 and m.filename=='127_v90bb_mobile_offline_sync.sql' for m in ms); assert any(m.version==128 for m in ms)
