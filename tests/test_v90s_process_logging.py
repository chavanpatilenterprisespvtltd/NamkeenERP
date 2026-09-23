from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations


def login(c, username='erpadmin', password='change-me'):
    r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def setup(c,h):
    oid,eid,lid,pid,mid,wh,lot,orm,bid=[str(uuid4()) for _ in range(9)]
    assert c.post('/admin/entities',json={'entity_id':eid,'entity_code':'ES'+eid[:5],'entity_name':'Entity S'},headers=h).status_code==200
    assert c.post('/admin/locations',json={'location_id':lid,'entity_id':eid,'location_code':'LS'+lid[:5],'location_name':'Plant S'},headers=h).status_code==200
    assert c.post('/admin/warehouses',json={'warehouse_id':wh,'entity_id':eid,'location_id':lid,'warehouse_code':'WS'+wh[:5],'warehouse_name':'RM Store'},headers=h).status_code==200
    assert c.post('/admin/access/entity',json={'user_id':'erpadmin','entity_id':eid},headers=h).status_code==200
    assert c.post('/admin/access/location',json={'user_id':'erpadmin','location_id':lid},headers=h).status_code==200
    assert c.post('/admin/access/warehouse',json={'user_id':'erpadmin','warehouse_id':wh},headers=h).status_code==200
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:p,:o,:e,'PRODUCT',1,'{}'),(:m,:o,:e,'RAW_MATERIAL',1,'{}')"),{'p':pid,'m':mid,'o':oid,'e':eid})
        conn.execute(text("INSERT INTO production_plan(plan_id,organization_id,entity_id,location_id,plan_no,period_start,period_end,status,created_by) VALUES(:p,:o,:e,:l,'PS'+:x,'2026-09-11','2026-09-11','APPROVED','erpadmin')"),{'p':str(uuid4()),'o':oid,'e':eid,'l':lid,'x':eid[:5]})
        plan=conn.execute(text("SELECT plan_id FROM production_plan WHERE entity_id=:e ORDER BY rowid DESC LIMIT 1"),{'e':eid}).scalar_one()
        conn.execute(text("INSERT INTO production_plan_line(plan_line_id,plan_id,line_no,item_master_id,uom,planned_qty) VALUES(:pl,:p,1,:m,'kg',100)"),{'pl':str(uuid4()),'p':plan,'m':pid})
        pl=conn.execute(text("SELECT plan_line_id FROM production_plan_line WHERE plan_id=:p"),{'p':plan}).scalar_one()
        conn.execute(text("INSERT INTO production_order(production_order_id,organization_id,entity_id,location_id,plan_id,plan_line_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:o,:org,:e,:l,:p,:pl,'ORS'+:x,:m,100,'kg','APPROVED','erpadmin')"),{'o':orm,'org':oid,'e':eid,'l':lid,'p':plan,'pl':pl,'x':eid[:5],'m':pid})
        conn.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:o,:org,:e,:l,'BS'+:x,:p,100,'kg','RUNNING','erpadmin')"),{'b':bid,'o':orm,'org':oid,'e':eid,'l':lid,'x':eid[:5],'p':pid})
    return oid,eid,lid,bid,orm


def test_process_log_and_measurements():
    c=TestClient(app); h=login(c); oid,eid,lid,bid,orm=setup(c,h)
    r=c.post(f'/v90s/batches/{bid}/process-logs',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'batch_id':bid,'production_order_id':orm,'stage':'FRYING','temperature_c':178.5,'frying_time_sec':92,'machine_id':'FRY-01'},headers=h)
    assert r.status_code==200,r.text; pid=r.json()['process_log_id']
    m=c.post(f'/v90s/process-logs/{pid}/measurements',json={'measurements':[{'parameter_code':'OILTEMP','parameter_name':'Oil Temp','value_num':178.5,'uom':'C','target_min':170,'target_max':185,'pass_flag':True},{'parameter_code':'TIME','parameter_name':'Fry Time','value_num':92,'uom':'sec'}]},headers=h)
    assert m.status_code==200,m.text
    g=c.get(f'/v90s/process-logs/{pid}',headers=h); assert g.status_code==200; assert len(g.json()['measurements'])==2


def test_deviation_flag_and_batch_scope():
    c=TestClient(app); h=login(c); oid,eid,lid,bid,orm=setup(c,h)
    r=c.post(f'/v90s/batches/{bid}/process-logs',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'batch_id':bid,'production_order_id':orm,'stage':'FRYING','temperature_c':192,'deviation_reason':'Above target'},headers=h)
    assert r.status_code==200 and r.json()['deviation_flag'] is True
    bad=c.post(f'/v90s/batches/{bid}/process-logs',json={'organization_id':oid,'entity_id':str(uuid4()),'location_id':lid,'batch_id':bid,'production_order_id':orm,'stage':'FRYING'},headers=h)
    assert bad.status_code in (403,422)


def test_duplicate_reads_and_migration():
    c=TestClient(app); h=login(c); oid,eid,lid,bid,orm=setup(c,h)
    r=c.post(f'/v90s/batches/{bid}/process-logs',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'batch_id':bid,'production_order_id':orm,'stage':'COOLING','started_at':'2026-09-11T10:00:00+00:00','ended_at':'2026-09-11T10:05:00+00:00','process_value':30,'process_uom':'C'},headers=h)
    assert r.status_code==200; pid=r.json()['process_log_id']
    assert c.get(f'/v90s/batches/{bid}/process-logs',headers=h).status_code==200
    assert c.get(f'/v90s/process-logs/{pid}',headers=h).status_code==200
    ms=load_migrations(); assert any(m.version==92 and m.filename=='092_v90s_production_process_logging.sql' for m in ms)
    assert c.get('/build').json()['production_process_logging']=='stage_operator_machine_measurements_deviations'
