from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def setup_env():
    uid=str(uuid4()); uname='ar_'+uid[:8]
    create_user(engine,uid,uname,'pw','AR Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); ids={k:str(uuid4()) for k in ['e','l','w','mat','pack','prod','ord','plan','plan_line','batch','out','fg','run','prun','sku','recipe','calc1','calc2']}
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'AR','legal_entity',1)"),{'e':ids['e'],'c':'AR'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'AR','site',1)"),{'l':ids['l'],'e':ids['e'],'c':'ARL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:c,'AR','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'c':'ARW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO production_plan(plan_id,organization_id,entity_id,location_id,plan_no,period_start,period_end,status,created_by) VALUES(:p,:o,:e,:l,'ARP','2026-09-01','2026-09-07','APPROVED',:u)"),{'p':ids['plan'],'o':org,'e':ids['e'],'l':ids['l'],'u':uid})
        db.execute(text("INSERT INTO production_plan_line(plan_line_id,plan_id,line_no,item_master_id,uom,planned_qty,priority,status) VALUES(:pl,:p,1,:pm,'kg',100,1,'PLANNED')"),{'pl':ids['plan_line'],'p':ids['plan'],'pm':ids['prod']})
        db.execute(text("INSERT INTO production_order(production_order_id,plan_id,plan_line_id,organization_id,entity_id,location_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:o,:p,:pl,:org,:e,:l,'ARO',:pm,100,'kg','APPROVED',:u)"),{'o':ids['ord'],'p':ids['plan'],'pl':ids['plan_line'],'org':org,'e':ids['e'],'l':ids['l'],'pm':ids['prod'],'u':uid})
        db.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:o,:org,:e,:l,'ARB1',:pm,100,'kg','COMPLETED',:u)"),{'b':ids['batch'],'o':ids['ord'],'org':org,'e':ids['e'],'l':ids['l'],'pm':ids['prod'],'u':uid})
        db.execute(text("INSERT INTO production_batch_output(output_id,batch_id,organization_id,entity_id,location_id,good_qty,rework_qty,wastage_qty,uom,yield_pct,wastage_pct,recorded_by) VALUES(:id,:b,:org,:e,:l,88,0,12,'kg',88,12,:u)"),{'id':ids['out'],'b':ids['batch'],'org':org,'e':ids['e'],'l':ids['l'],'u':uid})
        db.execute(text("INSERT INTO recipe(recipe_id,organization_id,entity_id,product_master_id,recipe_code,recipe_name,version_no,status,yield_qty,yield_uom,expected_loss_pct,created_by) VALUES(:r,:org,:e,:pm,'AR-R1','AR Recipe',1,'APPROVED',100,'kg',5,:u)"),{'r':ids['recipe'],'org':org,'e':ids['e'],'pm':ids['prod'],'u':uid})
        db.execute(text("INSERT INTO material_requirement_calc(calc_id,plan_id,plan_line_id,recipe_id,material_master_id,requirement_type,gross_qty,scrap_qty,required_qty,uom) VALUES(:c,:p,:pl,:r,:m,'RAW_MATERIAL',100,0,100,'kg')"),{'c':ids['calc1'],'p':ids['plan'],'pl':ids['plan_line'],'r':ids['recipe'],'m':ids['mat']})
        db.execute(text("INSERT INTO material_requirement_calc(calc_id,plan_id,plan_line_id,recipe_id,material_master_id,requirement_type,gross_qty,scrap_qty,required_qty,uom) VALUES(:c,:p,:pl,:r,:m,'PACKAGING',10,0,10,'kg')"),{'c':ids['calc2'],'p':ids['plan'],'pl':ids['plan_line'],'r':ids['recipe'],'m':ids['pack']})
        db.execute(text("INSERT INTO production_material_issue(issue_id,production_order_id,organization_id,entity_id,location_id,warehouse_id,material_master_id,lot_id,issued_qty,uom,status,issued_by) VALUES(:id,:o,:org,:e,:l,:w,:m,:lot,105,'kg','POSTED',:u)"),{'id':str(uuid4()),'o':ids['ord'],'org':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'m':ids['mat'],'lot':str(uuid4()),'u':uid})
        db.execute(text("INSERT INTO packing_run(packing_run_id,organization_id,entity_id,location_id,warehouse_id,source_fg_lot_id,sku_id,run_no,source_qty,status,created_by) VALUES(:r,:org,:e,:l,:w,:f,:sku,'ARR1',10,'COMPLETED',:u)"),{'r':ids['run'],'org':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'f':ids['fg'],'sku':ids['sku'],'u':uid})
        # Minimal FG lot/SKU rows for the packing join.
        db.execute(text("INSERT INTO finished_goods_lot(fg_lot_id,organization_id,entity_id,location_id,warehouse_id,batch_id,product_master_id,sku_id,fg_lot_code,mfg_date,expiry_date,quantity,available_qty,uom,qc_status,status,created_by) VALUES(:f,:org,:e,:l,:w,:b,:pm,NULL,'ARFG','2026-09-01','2026-10-01',10,10,'kg','RELEASED','AVAILABLE',:u)"),{'f':ids['fg'],'org':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'b':ids['batch'],'pm':ids['prod'],'u':uid})
        db.execute(text("INSERT INTO packing_material_consumption(consumption_id,packing_run_id,material_master_id,lot_id,quantity,uom,created_by) VALUES(:id,:r,:m,:lot,11,'kg',:u)"),{'id':str(uuid4()),'r':ids['run'],'m':ids['pack'],'lot':str(uuid4()),'u':uid})
    return c,ids,org

def test_calculate_variance():
    c,ids,org=setup_env()
    for item,cost in [(ids['mat'],10),(ids['pack'],2)]:
        r=c.post('/v90aq/cost-rates',json={'organization_id':org,'entity_id':ids['e'],'item_master_id':item,'uom':'kg','unit_cost':cost,'source_type':'GRN'})
        assert r.status_code==200,r.text
    r=c.post(f'/v90ar/batches/{ids["batch"]}/variance',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']})
    assert r.status_code==200,r.text
    j=r.json(); assert round(j['yield_variance_qty'],2)==-7.0; assert round(j['wastage_variance_qty'],2)==7.0; assert round(j['material_variance_cost'],2)==50; assert round(j['packaging_variance_cost'],2)==2; assert round(j['total_variance_cost'],2)==52

def test_duplicate_variance_blocked():
    c,ids,org=setup_env()
    for item,cost in [(ids['mat'],10),(ids['pack'],2)]:
        c.post('/v90aq/cost-rates',json={'organization_id':org,'entity_id':ids['e'],'item_master_id':item,'uom':'kg','unit_cost':cost,'source_type':'GRN'})
    first=c.post(f'/v90ar/batches/{ids["batch"]}/variance',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']})
    second=c.post(f'/v90ar/batches/{ids["batch"]}/variance',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']})
    assert first.status_code==200 and second.status_code==409

def test_summary():
    c,ids,org=setup_env()
    for item,cost in [(ids['mat'],10),(ids['pack'],2)]:
        c.post('/v90aq/cost-rates',json={'organization_id':org,'entity_id':ids['e'],'item_master_id':item,'uom':'kg','unit_cost':cost,'source_type':'GRN'})
    c.post(f'/v90ar/batches/{ids["batch"]}/variance',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']})
    r=c.get('/v90ar/variance-summary',params={'organization_id':org,'entity_id':ids['e']})
    assert r.status_code==200 and r.json()['batches']==1 and round(r.json()['total_variance_cost'],2)==52
