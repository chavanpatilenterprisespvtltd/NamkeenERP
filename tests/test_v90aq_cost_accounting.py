from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def setup_env():
    uid=str(uuid4()); uname='aq_'+uid[:8]
    create_user(engine,uid,uname,'pw','AQ Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); ids={k:str(uuid4()) for k in ['e','l','w','mat','prod','ord','plan','plan_line','batch','out','fg','run','sku','pack']}
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'AQ','legal_entity',1)"),{'e':ids['e'],'c':'AQ'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'AQ','site',1)"),{'l':ids['l'],'e':ids['e'],'c':'AQL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:c,'AQ','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'c':'AQW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO production_plan(plan_id,organization_id,entity_id,location_id,plan_no,period_start,period_end,status,created_by) VALUES(:pl,:org,:e,:l,'AQP','2026-09-01','2026-09-07','APPROVED',:u)"),{'pl':ids['plan'],'org':org,'e':ids['e'],'l':ids['l'],'u':uid})
        db.execute(text("INSERT INTO production_plan_line(plan_line_id,plan_id,line_no,item_master_id,uom,planned_qty,priority,status) VALUES(:pli,:pl,1,:p,'kg',100,1,'PLANNED')"),{'pli':ids['plan_line'],'pl':ids['plan'],'p':ids['prod']})
        db.execute(text("INSERT INTO production_order(production_order_id,plan_id,plan_line_id,organization_id,entity_id,location_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:o,:pl,:plan_line_id,:org,:e,:l,:on,:p,100,'kg','APPROVED',:u)"),{'o':ids['ord'],'pl':ids['plan'],'plan_line_id':ids['plan_line'],'org':org,'on':'AQO-'+ids['ord'][:6],'e':ids['e'],'l':ids['l'],'p':ids['prod'],'u':uid})
        db.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:o,:org,:e,:l,'AQB1',:p,100,'kg','COMPLETED',:u)"),{'b':ids['batch'],'o':ids['ord'],'org':org,'e':ids['e'],'l':ids['l'],'p':ids['prod'],'u':uid})
        db.execute(text("INSERT INTO production_batch_output(output_id,batch_id,organization_id,entity_id,location_id,good_qty,rework_qty,wastage_qty,uom,yield_pct,wastage_pct,recorded_by) VALUES(:id,:b,:org,:e,:l,90,0,10,'kg',90,10,:u)"),{'id':ids['out'],'b':ids['batch'],'org':org,'e':ids['e'],'l':ids['l'],'u':uid})
        db.execute(text("INSERT INTO production_material_issue(issue_id,production_order_id,organization_id,entity_id,location_id,warehouse_id,material_master_id,lot_id,issued_qty,uom,status,issued_by) VALUES(:id,:o,:org,:e,:l,:w,:m,:lot,100,'kg','POSTED',:u)"),{'id':str(uuid4()),'o':ids['ord'],'org':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'m':ids['mat'],'lot':str(uuid4()),'u':uid})
    return c,ids,org

def test_rate_and_batch_cost():
    c,ids,org=setup_env()
    r=c.post('/v90aq/cost-rates',json={'organization_id':org,'entity_id':ids['e'],'item_master_id':ids['mat'],'uom':'kg','unit_cost':10,'source_type':'GRN'})
    assert r.status_code==200,r.text
    r=c.post(f'/v90aq/batches/{ids["batch"]}/cost',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'batch_id':ids['batch'],'conversion_cost':100})
    assert r.status_code==200,r.text
    j=r.json(); assert j['material_cost']==1000; assert j['total_cost']==1200; assert j['unit_cost']==13.33

def test_duplicate_batch_cost_is_blocked():
    c,ids,org=setup_env()
    c.post('/v90aq/cost-rates',json={'organization_id':org,'entity_id':ids['e'],'item_master_id':ids['mat'],'uom':'kg','unit_cost':10,'source_type':'GRN'})
    first=c.post(f'/v90aq/batches/{ids["batch"]}/cost',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'batch_id':ids['batch']})
    assert first.status_code==200
    second=c.post(f'/v90aq/batches/{ids["batch"]}/cost',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'batch_id':ids['batch']})
    assert second.status_code==409

def test_product_cost_history():
    c,ids,org=setup_env()
    c.post('/v90aq/cost-rates',json={'organization_id':org,'entity_id':ids['e'],'item_master_id':ids['mat'],'uom':'kg','unit_cost':10,'source_type':'GRN','effective_from':'2026-09-01T00:00:00+00:00'})
    c.post('/v90aq/cost-rates',json={'organization_id':org,'entity_id':ids['e'],'item_master_id':ids['mat'],'uom':'kg','unit_cost':12,'source_type':'GRN','effective_from':'2026-09-05T00:00:00+00:00'})
    r=c.get(f'/v90aq/products/{ids["mat"]}/cost',params={'organization_id':org,'entity_id':ids['e'],'uom':'kg'})
    assert r.status_code==200 and r.json()['current_unit_cost']==12 and len(r.json()['history'])==2
