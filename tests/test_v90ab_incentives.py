from datetime import datetime, timezone, timedelta
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
    r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup(c,h):
    org,eid,lid,wid,sku=[str(uuid4()) for _ in range(5)]
    for path,payload in [
      ('/admin/entities',{'entity_id':eid,'entity_code':'EAB'+eid[:4],'entity_name':'Entity AB'}),
      ('/admin/locations',{'location_id':lid,'entity_id':eid,'location_code':'LAB'+lid[:4],'location_name':'Plant AB'}),
      ('/admin/warehouses',{'warehouse_id':wid,'entity_id':eid,'location_id':lid,'warehouse_code':'WAB'+wid[:4],'warehouse_name':'FG AB'}),
      ('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),
      ('/admin/access/location',{'user_id':'erpadmin','location_id':lid}),
      ('/admin/access/warehouse',{'user_id':'erpadmin','warehouse_id':wid})]:
      r=c.post(path,json=payload,headers=h); assert r.status_code==200,r.text
    with engine.begin() as x:
      x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,'SKU',1,'{}')"),{'id':sku,'o':org,'e':eid})
    return org,eid,lid,wid,sku

def test_incentive_rule_and_calculation():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h)
    now=datetime.now(timezone.utc)
    r=c.post('/v90ab/incentive-rules',json={'organization_id':org,'entity_id':eid,'rule_name':'AB Standard','rule_type':'PERCENT_OF_NET_SALES','rate':2,'min_margin_pct':8,'effective_from':now.isoformat()},headers=h)
    assert r.status_code==200,r.text
    calc=c.post('/v90ab/incentives/calculate',json={'organization_id':org,'entity_id':eid,'location_id':lid,'salesperson_user_id':'erpadmin','sku_id':sku,'quantity':100,'unit_cost':100,'approved_net_unit_price':125,'discount_pct':0,'gst_rate':12},headers=h)
    assert calc.status_code==200,calc.text; d=calc.json(); assert d['eligible'] is True; assert d['incentive_amount']==250.0; assert d['gst_amount']==1500.0

def test_incentive_below_margin_is_not_eligible():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); now=datetime.now(timezone.utc)
    assert c.post('/v90ab/incentive-rules',json={'organization_id':org,'entity_id':eid,'rule_name':'High Gate','rule_type':'PERCENT_OF_NET_SALES','rate':2,'min_margin_pct':20,'effective_from':now.isoformat()},headers=h).status_code==200
    r=c.post('/v90ab/incentives/calculate',json={'organization_id':org,'entity_id':eid,'location_id':lid,'salesperson_user_id':'erpadmin','sku_id':sku,'quantity':1,'unit_cost':100,'approved_net_unit_price':110,'gst_rate':12},headers=h)
    assert r.status_code==200 and r.json()['eligible'] is False and r.json()['reason']=='margin below incentive threshold'

def test_incentive_accrual_and_migration_marker():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); now=datetime.now(timezone.utc)
    c.post('/v90ab/incentive-rules',json={'organization_id':org,'entity_id':eid,'rule_name':'Fixed','rule_type':'FIXED_PER_UNIT','rate':1,'fixed_amount':1.5,'effective_from':now.isoformat()},headers=h)
    r=c.post('/v90ab/incentives/accrue',json={'organization_id':org,'entity_id':eid,'location_id':lid,'salesperson_user_id':'erpadmin','sku_id':sku,'quantity':20,'unit_cost':100,'approved_net_unit_price':130,'gst_rate':12},headers=h)
    assert r.status_code==200 and r.json()['status']=='ACCRUED' and r.json()['calculation']['incentive_amount']==30.0
    ms=load_migrations(); assert any(m.version==104 and m.filename=='104_v90ae_sales_order_allocation.sql' for m in ms); assert TestClient(app).get('/build').json()['incentives']=='approved_incentive_rules_accrual_calculation' and TestClient(app).get('/build').json()['credit_payment']=='customer_credit_outstanding_payment_verification' and TestClient(app).get('/build').json()['sales_credit_control']=='sales_order_pricing_credit_stock_gate'
