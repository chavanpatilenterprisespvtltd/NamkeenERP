from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env():
    u=str(uuid4()); n='GT'+u[:8]; create_user(engine,u,n,'pw','GT Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(u,n,'manager'))}); o=str(uuid4()); e=str(uuid4()); l=str(uuid4()); w=str(uuid4()); so=str(uuid4()); p=str(uuid4()); pl=str(uuid4())
    with engine.begin() as x:
        x.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GT','legal_entity',1)"),{'e':e,'c':'GT'+e[:8]})
        x.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GT','site',1)"),{'l':l,'e':e,'c':'GTL'+l[:6]})
        x.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':u,'e':e}); x.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':u,'l':l})
        x.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,active) VALUES(:w,:e,:l,'GTW','GT',1)"),{'w':w,'e':e,'l':l})
        x.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:so,:o,:e,:l,:w,:c,:on,'APPROVED','ALLOCATED',0,0,0,0,0,:u)"),{'so':so,'o':o,'e':e,'l':l,'w':w,'c':str(uuid4()),'on':'GT-SO-'+so[:8],'u':u})
        x.execute(text("INSERT INTO dispatch_pick_lists(pick_list_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,status,created_by) VALUES(:p,:o,:e,:l,:w,:so,'OPEN',:u)"),{'p':p,'o':o,'e':e,'l':l,'w':w,'so':so,'u':u})
        x.execute(text("INSERT INTO dispatch_pick_lines(pick_line_id,pick_list_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,lot_code,allocated_qty,picked_qty,status) VALUES(:pl,:p,:sl,:a,:s,:lot,'GTLOT',10,0,'OPEN')"),{'pl':pl,'p':p,'sl':str(uuid4()),'a':str(uuid4()),'s':str(uuid4()),'lot':str(uuid4())})
    return c,o,e,l,p

def integrate(c,o,e,l,t,rt,rid,payload=None):
    b={'organization_id':o,'entity_id':e,'location_id':l,'event_id':str(uuid4()),'transaction_type':t,'reference_type':rt,'reference_id':rid,'payload':payload or {}}
    r=c.post('/v90gs/mobile/transactions/integrate',json=b); assert r.status_code==200 and r.json()['status']=='READY'; return r.json()['integration_id']

def test_pick_confirm_executes_source_transaction_idempotently():
    c,o,e,l,p=env(); iid=integrate(c,o,e,l,'PICK_CONFIRM','PICK_LIST',p)
    r=c.post(f'/v90gt/mobile/transactions/{iid}/execute',json={'payload':{}}); assert r.status_code==200 and r.json()['status']=='EXECUTED'
    r2=c.post(f'/v90gt/mobile/transactions/{iid}/execute',json={'payload':{}}); assert r2.json()['idempotent']
    with engine.connect() as x:
        assert x.execute(text("SELECT status FROM dispatch_pick_lists WHERE pick_list_id=:p"),{'p':p}).scalar()=='PICKED'

def test_unsupported_adapter_does_not_mark_integration_posted():
    c,o,e,l,p=env(); iid=integrate(c,o,e,l,'STOCK_COUNT','COUNT',str(uuid4()))
    r=c.post(f'/v90gt/mobile/transactions/{iid}/execute',json={'payload':{}}); assert r.status_code==409
    with engine.connect() as x: assert x.execute(text("SELECT status FROM mobile_transaction_integrations WHERE integration_id=:i"),{'i':iid}).scalar()=='READY'
