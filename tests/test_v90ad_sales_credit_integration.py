from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def login(uid='adadmin', username='adadmin', role='manager', password='pw'):
    try: create_user(engine, uid, username, password, 'AD Admin', role)
    except Exception: pass
    return {'Authorization':'Bearer '+make_access_token(UserRecord(uid, username, role))}


def seed():
    ids={k:str(uuid4()) for k in ['e','l','w','cust','sku']}; org=str(uuid4())
    with engine.begin() as c:
        for s in [
            "INSERT OR IGNORE INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,'ADE','AD Entity','legal_entity',1)",
            "INSERT OR IGNORE INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,'ADL','AD Location','site',1)",
            "INSERT OR IGNORE INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,'ADW','AD WH','general',1)"]:
            c.execute(text(s),ids)
        c.execute(text("INSERT OR IGNORE INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:id,:o,'CUSTOMER',:e,1,'{}')"),{'id':ids['cust'],'o':org,'e':ids['e']})
        c.execute(text("INSERT OR IGNORE INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:id,:o,'SKU',:e,1,'{}')"),{'id':ids['sku'],'o':org,'e':ids['e']})
        c.execute(text("INSERT OR IGNORE INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':'adadmin','e':ids['e']})
        c.execute(text("INSERT OR IGNORE INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':'adadmin','l':ids['l']})
        c.execute(text("INSERT OR IGNORE INTO erp_warehouse_user_access(user_id,warehouse_id) VALUES(:u,:w)"),{'u':'adadmin','w':ids['w']})
    return org,ids


def test_control_check_blocks_no_credit_and_approval_hold():
    c=TestClient(app); h=login(); org,ids=seed()
    r=c.post('/v90z/sales/orders',headers=h,json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'warehouse_id':ids['w'],'customer_id':ids['cust'],'order_no':'AD-1','lines':[{'sku_id':ids['sku'],'quantity':1,'unit_price':125}]})
    assert r.status_code==200; oid=r.json()['sales_order_id']
    assert c.post(f'/v90z/sales/orders/{oid}/submit',headers=h).status_code==200
    r=c.post(f'/v90ad/sales/orders/{oid}/control-check',headers=h); assert r.status_code==200; assert r.json()['overall_status']=='HOLD'; assert r.json()['credit_status']=='HOLD'
    r=c.post(f'/v90ad/sales/orders/{oid}/approve-controlled',headers=h); assert r.status_code==409
    g=c.get(f'/v90ad/sales/orders/{oid}/control-history',headers=h); assert g.status_code==200 and len(g.json()['items'])==1


def test_control_check_passes_with_credit_and_ready_stock():
    c=TestClient(app); h=login(); org,ids=seed()
    c.post('/v90ac/credit/policies',headers=h,json={'organization_id':org,'entity_id':ids['e'],'customer_id':ids['cust'],'credit_limit':10000,'credit_days':30})
    r=c.post('/v90z/sales/orders',headers=h,json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'warehouse_id':ids['w'],'customer_id':ids['cust'],'order_no':'AD-2','lines':[{'sku_id':ids['sku'],'quantity':1,'unit_price':125}]}); oid=r.json()['sales_order_id']
    c.post(f'/v90z/sales/orders/{oid}/submit',headers=h)
    with engine.begin() as conn: conn.execute(text("UPDATE sales_orders SET pricing_status='CHECKED', stock_status='READY' WHERE sales_order_id=:id"),{'id':oid})
    r=c.post(f'/v90ad/sales/orders/{oid}/control-check',headers=h); assert r.status_code==200 and r.json()['overall_status']=='PASS'
    r=c.post(f'/v90ad/sales/orders/{oid}/approve-controlled',headers=h); assert r.status_code==200 and r.json()['status']=='APPROVED'
