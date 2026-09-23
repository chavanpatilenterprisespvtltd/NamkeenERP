from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
    r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup(c,h):
    oid,eid,lid,pid,mid,wh,orm,bid = [str(uuid4()) for _ in range(8)]
    for path,payload in [('/admin/entities',{'entity_id':eid,'entity_code':'ET'+eid[:5],'entity_name':'Entity T'}),('/admin/locations',{'location_id':lid,'entity_id':eid,'location_code':'LT'+lid[:5],'location_name':'Plant T'}),('/admin/warehouses',{'warehouse_id':wh,'entity_id':eid,'location_id':lid,'warehouse_code':'WT'+wh[:5],'warehouse_name':'RM Store'})]:
        assert c.post(path,json=payload,headers=h).status_code==200
    for path,payload in [('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),('/admin/access/location',{'user_id':'erpadmin','location_id':lid}),('/admin/access/warehouse',{'user_id':'erpadmin','warehouse_id':wh})]:
        assert c.post(path,json=payload,headers=h).status_code==200
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:p,:o,:e,'PRODUCT',1,'{}'),(:m,:o,:e,'RAW_MATERIAL',1,'{}')"),{'p':pid,'m':mid,'o':oid,'e':eid})
        conn.execute(text("INSERT INTO production_order(production_order_id,organization_id,entity_id,location_id,plan_id,plan_line_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:o,:org,:e,:l,:p,:pl,'OT'+:x,:m,100,'kg','APPROVED','erpadmin')"),{'o':orm,'org':oid,'e':eid,'l':lid,'p':str(uuid4()),'pl':str(uuid4()),'x':eid[:5],'m':pid})
        conn.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:o,:org,:e,:l,'BT'+:x,:p,100,'kg','RUNNING','erpadmin')"),{'b':bid,'o':orm,'org':oid,'e':eid,'l':lid,'x':eid[:5],'p':pid})
    r=c.post(f'/v90s/batches/{bid}/process-logs',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'batch_id':bid,'production_order_id':orm,'stage':'FRYING','temperature_c':178.5,'frying_time_sec':92},headers=h)
    assert r.status_code==200,r.text
    pid2=r.json()['process_log_id']
    assert c.post(f'/v90s/process-logs/{pid2}/measurements',json={'measurements':[{'parameter_code':'OILTEMP','parameter_name':'Oil Temp','value_num':178.5,'uom':'C'}]},headers=h).status_code==200
    return oid,eid,lid,bid,pid2

def test_control_evaluate_and_qc_decision():
    c=TestClient(app); h=login(c); oid,eid,lid,bid,pid=setup(c,h)
    r=c.post('/v90t/process-controls',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'stage':'FRYING','parameter_code':'OILTEMP','parameter_name':'Oil Temp','uom':'C','target_min':170,'target_max':185,'severity':'CRITICAL','action_on_breach':'HOLD'},headers=h)
    assert r.status_code==200,r.text
    ev=c.post(f'/v90t/process-logs/{pid}/evaluate',headers=h); assert ev.status_code==200; assert ev.json()['decision']=='PASS'
    q=c.post(f'/v90t/process-logs/{pid}/qc-decision',json={'decision':'PASS','reason':'within target'},headers=h); assert q.status_code==200
    st=c.get(f'/v90t/batches/{bid}/qc-status',headers=h); assert st.status_code==200; assert st.json()['latest_decision']['decision']=='PASS'

def test_breach_requires_hold_when_control_says_hold():
    c=TestClient(app); h=login(c); oid,eid,lid,bid,pid=setup(c,h)
    assert c.post('/v90t/process-controls',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'stage':'FRYING','parameter_code':'OILTEMP','parameter_name':'Oil Temp','target_min':180,'target_max':185,'severity':'CRITICAL','action_on_breach':'HOLD'},headers=h).status_code==200
    ev=c.post(f'/v90t/process-logs/{pid}/evaluate',headers=h); assert ev.status_code==200; assert ev.json()['decision']=='HOLD' and ev.json()['hold'] is True

def test_validation_scope_and_migration():
    c=TestClient(app); h=login(c); oid,eid,lid,bid,pid=setup(c,h)
    bad=c.post('/v90t/process-controls',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'stage':'FRYING','parameter_code':'X','parameter_name':'X','target_min':10,'target_max':5},headers=h)
    assert bad.status_code==422
    ms=load_migrations(); assert any(m.version==93 and m.filename=='093_v90t_process_controls_qc.sql' for m in ms)
    assert c.get('/build').json()['process_controls_qc']=='control_limits_evaluation_hold_release'
