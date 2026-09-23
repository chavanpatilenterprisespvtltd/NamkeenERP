from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
import json

def env(role='manager'):
    uid=str(uuid4()); uname='go_'+uid[:8]; create_user(engine,uid,uname,'pw','GO Tester',role)
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'GO Tester',role))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4()); cust=str(uuid4()); beat=str(uuid4()); stop=str(uuid4())
    with engine.begin() as db:
        db.execute(text("CREATE TABLE IF NOT EXISTS field_sales_beat_plans (beat_plan_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, territory_id TEXT, salesperson_user_id TEXT, beat_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PLANNED', notes TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        db.execute(text("CREATE TABLE IF NOT EXISTS field_sales_beat_stops (stop_id TEXT PRIMARY KEY, beat_plan_id TEXT NOT NULL, customer_id TEXT NOT NULL, sequence_no INTEGER NOT NULL DEFAULT 1, planned_at TEXT, completed_at TEXT, status TEXT NOT NULL DEFAULT 'PLANNED', notes TEXT)"))
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GO','legal_entity',1)"),{'e':e,'c':'GO'+e[:5]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GO','site',1)"),{'l':l,'e':e,'c':'GOL'+l[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,data,active,version_no) VALUES(:m,:o,'CUSTOMER',:e,:d,1,1)"),{'m':cust,'o':org,'e':e,'d':json.dumps({'name':'Dealer GO','channel':'DEALER'})})
        db.execute(text("INSERT INTO field_sales_beat_plans(beat_plan_id,organization_id,entity_id,territory_id,salesperson_user_id,beat_date,status,created_by) VALUES(:b,:o,:e,'T-GO',:u,'2026-09-12','PLANNED',:u)"),{'b':beat,'o':org,'e':e,'u':uid})
        db.execute(text("INSERT INTO field_sales_beat_stops(stop_id,beat_plan_id,customer_id,sequence_no,status,completed_at) VALUES(:s,:b,:c,1,'COMPLETED','2026-09-12T10:00:00')"),{'s':stop,'b':beat,'c':cust})
        so=str(uuid4()); db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by,created_at) VALUES(:id,:o,:e,:l,:w,:c,:n,'APPROVED','CHECKED','CHECKED','READY',1000,0,1000,180,1180,:u,'2026-09-12T09:00:00')"),{'id':so,'o':org,'e':e,'l':l,'w':str(uuid4()),'c':cust,'n':'GO-'+str(uuid4())[:6],'u':uid})
    return c,org,e,l,cust

def test_dashboard_and_health():
    c,o,e,l,cust=env(); q={'organization_id':o,'entity_id':e,'location_id':l,'from_date':'2026-09-12','to_date':'2026-09-12'}
    r=c.get('/v90go/customer-execution',params=q); assert r.status_code==200,r.text; d=r.json(); assert d['planned_stops']==1 and d['completed_stops']==1 and d['completion_pct']==100.0
    h=c.get('/v90go/customer-execution/health',params=q); assert h.status_code==200 and h.json()['items'][0]['status']=='ACTIVE'

def test_snapshot_action_and_rbac():
    c,o,e,l,cust=env(); q={'organization_id':o,'entity_id':e,'location_id':l,'from_date':'2026-09-12','to_date':'2026-09-12'}
    r=c.post('/v90go/customer-execution/snapshots',json=q); assert r.status_code==200 and r.json()['snapshot_id']
    b={**q,'customer_id':cust,'action_type':'RETENTION_FOLLOWUP','priority':'HIGH','reason':'Confirm next order'}
    r=c.post('/v90go/customer-execution/actions',json=b); assert r.status_code==200
    r=c.get('/v90go/customer-execution/actions',params=q); assert r.status_code==200 and r.json()['actions']
    s,_,ee,ll,cc=env('salesperson'); r=s.post('/v90go/customer-execution/actions',json={**q,'organization_id':str(uuid4()),'entity_id':ee,'location_id':ll,'customer_id':cc,'action_type':'X','reason':'x'}); assert r.status_code==403

def test_bad_date():
    c,o,e,l,_=env(); r=c.get('/v90go/customer-execution',params={'organization_id':o,'entity_id':e,'location_id':l,'from_date':'2026-09-13','to_date':'2026-09-12'}); assert r.status_code==422
