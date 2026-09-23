from __future__ import annotations
import uuid
from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.identity import create_user, find_user, roles_for_user
from app.auth import make_access_token


def auth(uid='ac-test-user'):
    try: create_user(engine, uid, uid+'@test', 'pw', 'AC Test', 'manager')
    except Exception: pass
    u=find_user(engine, uid+'@test')
    from app.auth import UserRecord
    role=(roles_for_user(engine, uid) or ['manager'])[0]
    return {'Authorization':'Bearer '+make_access_token(UserRecord(uid, u['username'], role))}


def seed_scope():
    from sqlalchemy import text
    ids={k:str(uuid.uuid4()) for k in ['entity','loc','wh','cust','sku']}
    with engine.begin() as c:
        c.execute(text("INSERT OR IGNORE INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:i,'AC','AC Entity','legal_entity',1)"), {'i':ids['entity']})
        c.execute(text("INSERT OR IGNORE INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:i,:e,'ACL','AC Location','site',1)"), {'i':ids['loc'],'e':ids['entity']})
        c.execute(text("INSERT OR IGNORE INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:i,:e,:l,'ACW','AC WH','general',1)"), {'i':ids['wh'],'e':ids['entity'],'l':ids['loc']})
        c.execute(text("INSERT OR IGNORE INTO master_record(master_id,master_type,entity_id,active,data) VALUES(:id,'CUSTOMER',:e,1,'{}')"), {'id':ids['cust'],'e':ids['entity'],'l':ids['loc']})
        c.execute(text("INSERT OR IGNORE INTO master_record(master_id,master_type,entity_id,active,data) VALUES(:id,'SKU',:e,1,'{}')"), {'id':ids['sku'],'e':ids['entity'],'l':ids['loc']})
        c.execute(text("INSERT OR IGNORE INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"), {'u':'ac-test-user','e':ids['entity']})
        c.execute(text("INSERT OR IGNORE INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"), {'u':'ac-test-user','l':ids['loc']})
    return ids


def test_credit_payment_flow():
    client=TestClient(app); h=auth(); ids=seed_scope(); org=str(uuid.uuid4())
    r=client.post('/v90ac/credit/policies',headers=h,json={'organization_id':org,'entity_id':ids['entity'],'customer_id':ids['cust'],'credit_limit':1000,'credit_days':30}); assert r.status_code==200
    r=client.post('/v90ac/credit/check',headers=h,json={'organization_id':org,'entity_id':ids['entity'],'location_id':ids['loc'],'customer_id':ids['cust'],'proposed_order_total':500}); assert r.status_code==200; assert r.json()['status']=='PASS'
    r=client.post('/v90ac/payments',headers=h,json={'organization_id':org,'entity_id':ids['entity'],'location_id':ids['loc'],'customer_id':ids['cust'],'amount':100,'mode':'UPI','payment_date':'2026-09-06','reference_no':'UPI1','proof_file_id':'file1'}); assert r.status_code==200
    pid=r.json()['payment_id']
    r=client.post(f'/v90ac/payments/{pid}/verify',headers=h); assert r.status_code==200 and r.json()['status']=='VERIFIED'
    r=client.post('/v90ac/payments',headers=h,json={'organization_id':org,'entity_id':ids['entity'],'location_id':ids['loc'],'customer_id':ids['cust'],'amount':50,'mode':'CHEQUE','payment_date':'2026-09-06'}); assert r.status_code==422
