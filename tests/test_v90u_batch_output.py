from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
    r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup(c,h):
    oid,eid,lid,pid,po,bid = [str(uuid4()) for _ in range(6)]
    for path,payload in [('/admin/entities',{'entity_id':eid,'entity_code':'EU'+eid[:5],'entity_name':'Entity U'}),('/admin/locations',{'location_id':lid,'entity_id':eid,'location_code':'LU'+lid[:5],'location_name':'Plant U'})]:
        assert c.post(path,json=payload,headers=h).status_code==200
    for path,payload in [('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),('/admin/access/location',{'user_id':'erpadmin','location_id':lid})]:
        assert c.post(path,json=payload,headers=h).status_code==200
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:p,:o,:e,'PRODUCT',1,'{}')"),{'p':pid,'o':oid,'e':eid})
        conn.execute(text("INSERT INTO production_order(production_order_id,organization_id,entity_id,location_id,plan_id,plan_line_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:po,:o,:e,:l,:p,:pl,'OU'+:x,:m,100,'kg','APPROVED','erpadmin')"),{'po':po,'o':oid,'e':eid,'l':lid,'p':str(uuid4()),'pl':str(uuid4()),'x':eid[:5],'m':pid})
        conn.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:po,:o,:e,:l,'BU'+:x,:m,100,'kg','RUNNING','erpadmin')"),{'b':bid,'po':po,'o':oid,'e':eid,'l':lid,'x':eid[:5],'m':pid})
    return oid,eid,lid,bid

def test_output_yield_and_readiness():
    c=TestClient(app); h=login(c); oid,eid,lid,bid=setup(c,h)
    r=c.post(f'/v90u/batches/{bid}/output',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'good_qty':90,'rework_qty':5,'wastage_qty':5,'uom':'kg'},headers=h)
    assert r.status_code==200,r.text
    data=r.json(); assert data['yield_pct']==90.0; assert data['wastage_pct']==5.0
    g=c.get(f'/v90u/batches/{bid}/output',headers=h); assert g.status_code==200; assert float(g.json()['output']['good_qty'])==90.0
    cr=c.get(f'/v90u/batches/{bid}/closure-readiness',headers=h); assert cr.status_code==200; assert cr.json()['ready_to_close'] is True

def test_output_requires_positive_total_and_no_duplicate():
    c=TestClient(app); h=login(c); oid,eid,lid,bid=setup(c,h)
    r=c.post(f'/v90u/batches/{bid}/output',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'good_qty':0,'rework_qty':0,'wastage_qty':0,'uom':'kg'},headers=h)
    assert r.status_code==422
    p={'organization_id':oid,'entity_id':eid,'location_id':lid,'good_qty':80,'rework_qty':10,'wastage_qty':10,'uom':'kg'}
    assert c.post(f'/v90u/batches/{bid}/output',json=p,headers=h).status_code==200
    assert c.post(f'/v90u/batches/{bid}/output',json=p,headers=h).status_code==409

def test_rejected_qc_blocks_output_and_migration():
    c=TestClient(app); h=login(c); oid,eid,lid,bid=setup(c,h)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO production_process_qc_decision(decision_id,process_log_id,batch_id,organization_id,entity_id,location_id,decision,decided_by) VALUES(:d,:p,:b,:o,:e,:l,'REJECT','erpadmin')"),{'d':str(uuid4()),'p':str(uuid4()),'b':bid,'o':oid,'e':eid,'l':lid})
    r=c.post(f'/v90u/batches/{bid}/output',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'good_qty':90,'rework_qty':5,'wastage_qty':5,'uom':'kg'},headers=h)
    assert r.status_code==409
    ms=load_migrations(); assert any(m.version==94 and m.filename=='094_v90u_batch_output_yield.sql' for m in ms)
    assert c.get('/build').json()['batch_output']=='good_rework_wastage_yield_qc_gate'
