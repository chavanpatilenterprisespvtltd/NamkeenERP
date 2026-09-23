from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env():
    u=str(uuid4()); n='GU'+u[:8]; create_user(engine,u,n,'pw','GU Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(u,n,'manager'))})
    o=str(uuid4()); e=str(uuid4()); l=str(uuid4()); w=str(uuid4()); m=str(uuid4()); batch=str(uuid4()); po=str(uuid4())
    with engine.begin() as x:
        x.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GU','legal_entity',1)"),{'e':e,'c':'GU'+e[:8]})
        x.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GU','site',1)"),{'l':l,'e':e,'c':'GUL'+l[:6]})
        x.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':u,'e':e}); x.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':u,'l':l})
        x.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,active) VALUES(:w,:e,:l,'GUW','GU',1)"),{'w':w,'e':e,'l':l})
        x.execute(text("INSERT INTO production_order(production_order_id,organization_id,entity_id,location_id,plan_id,plan_line_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:p,:o,:e,:l,:plan,:pline,:on,:m,100,'KG','APPROVED',:u)"),{'p':po,'o':o,'e':e,'l':l,'plan':str(uuid4()),'pline':str(uuid4()),'on':'GU-PO-'+po[:8],'m':m,'u':u})
        x.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:p,:o,:e,:l,'GUBATCH',:m,100,'KG','RUNNING',:u)"),{'b':batch,'p':po,'o':o,'e':e,'l':l,'m':m,'u':u})
    return c,o,e,l,w,m,batch

def integrate(c,o,e,l,t,rt,rid,payload=None):
    b={'organization_id':o,'entity_id':e,'location_id':l,'event_id':str(uuid4()),'transaction_type':t,'reference_type':rt,'reference_id':rid,'payload':payload or {}}
    r=c.post('/v90gs/mobile/transactions/integrate',json=b); assert r.status_code==200 and r.json()['status']=='READY'; return r.json()['integration_id']

def test_production_confirm_creates_output_completes_batch_and_is_idempotent():
    c,o,e,l,w,m,b=env(); iid=integrate(c,o,e,l,'PRODUCTION_CONFIRM','PRODUCTION_BATCH',b)
    r=c.post(f'/v90gu/mobile/transactions/{iid}/execute',json={'payload':{'good_qty':90,'rework_qty':5,'wastage_qty':5,'uom':'KG'}}); assert r.status_code==200 and r.json()['status']=='EXECUTED'
    r2=c.post(f'/v90gu/mobile/transactions/{iid}/execute',json={'payload':{'good_qty':90}}); assert r2.json()['idempotent']
    with engine.connect() as x:
        assert x.execute(text("SELECT status FROM production_batch WHERE batch_id=:b"),{'b':b}).scalar()=='COMPLETED'
        assert float(x.execute(text("SELECT good_qty FROM production_batch_output WHERE batch_id=:b"),{'b':b}).scalar())==90

def test_stock_count_records_variance_without_posting_ledger():
    c,o,e,l,w,m,b=env(); lot=str(uuid4())
    with engine.begin() as x:
        x.execute(text("INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,lot_code,received_qty,accepted_qty,available_qty,rejected_qty,uom,qc_status,status) VALUES(:id,:o,:e,:l,:w,:m,:g,:gl,:s,'GULOT',50,50,50,0,'KG','RELEASED','AVAILABLE')"),{'id':lot,'o':o,'e':e,'l':l,'w':w,'m':m,'g':str(uuid4()),'gl':str(uuid4()),'s':str(uuid4())})
    iid=integrate(c,o,e,l,'STOCK_COUNT','COUNT',str(uuid4()),{'warehouse_id':w,'item_master_id':m,'lot_id':lot,'counted_qty':47,'uom':'KG'})
    r=c.post(f'/v90gu/mobile/transactions/{iid}/execute',json={'payload':{'warehouse_id':w,'item_master_id':m,'lot_id':lot,'counted_qty':47,'uom':'KG'}}); assert r.status_code==200 and r.json()['result']['variance_qty']==-3
    assert r.json()['result']['ledger_adjustment']=='NOT_POSTED'
