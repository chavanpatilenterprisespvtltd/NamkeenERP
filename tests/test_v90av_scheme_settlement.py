from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from app.__main__ import app
from app.migrations import load_migrations
from tests.test_v90ab_incentives import login, setup

def test_scheme_create_and_discount_settlement():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); now=datetime.now(timezone.utc)
    r=c.post('/v90av/schemes',json={'organization_id':org,'entity_id':eid,'scheme_name':'Quarterly 5%','scheme_type':'PERCENT_DISCOUNT','discount_pct':5,'effective_from':now.isoformat()},headers=h)
    assert r.status_code==200
    sid=r.json()['scheme_id']; invoice=str(uuid4())
    r=c.post('/v90av/discount-settlements',json={'organization_id':org,'entity_id':eid,'location_id':lid,'sales_invoice_id':invoice,'scheme_id':sid,'eligible_base':10000,'requested_discount':600,'settlement_reference':'SCH-001'},headers=h)
    assert r.status_code==200 and r.json()['approved_discount']==500.0

def test_fixed_scheme_caps_discount():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); now=datetime.now(timezone.utc)
    sid=c.post('/v90av/schemes',json={'organization_id':org,'entity_id':eid,'scheme_name':'Fixed Cap','scheme_type':'FIXED_DISCOUNT','fixed_amount':250,'max_settlement':200,'effective_from':now.isoformat()},headers=h).json()['scheme_id']
    r=c.post('/v90av/discount-settlements',json={'organization_id':org,'entity_id':eid,'location_id':lid,'sales_invoice_id':str(uuid4()),'scheme_id':sid,'eligible_base':10000,'requested_discount':500,'settlement_reference':'SCH-002'},headers=h)
    assert r.status_code==200 and r.json()['approved_discount']==200.0

def test_incentive_settlement_sums_accruals_and_migrations():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); now=datetime.now(timezone.utc)
    c.post('/v90ab/incentive-rules',json={'organization_id':org,'entity_id':eid,'rule_name':'2pct','rule_type':'PERCENT_OF_NET_SALES','rate':2,'effective_from':now.isoformat()},headers=h)
    for ref,qty in [('I1',100),('I2',50)]:
        r=c.post('/v90ab/incentives/accrue',json={'organization_id':org,'entity_id':eid,'location_id':lid,'salesperson_user_id':'erpadmin','sku_id':sku,'quantity':qty,'unit_cost':100,'approved_net_unit_price':200,'gst_rate':12},headers=h); assert r.status_code==200
    r=c.post('/v90av/incentive-settlements',json={'organization_id':org,'entity_id':eid,'location_id':lid,'salesperson_user_id':'erpadmin','period_from':now.date().isoformat(),'period_to':now.date().isoformat(),'settlement_reference':'PAY-001'},headers=h)
    assert r.status_code==200 and r.json()['payable_amount']==600.0
    assert any(m.version==121 and m.filename=='121_v90av_scheme_incentive_settlement.sql' for m in load_migrations())
