from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.__main__ import app
from tests.test_v90z_sales_orders import login, setup

def test_salesperson_summary_customers_and_visits():
    c = TestClient(app)
    h = login(c)
    org, ent, loc, wh, cust, sku = setup(c, h)
    r = c.get('/v90bq/salesperson/summary', params={'organization_id':org,'entity_id':ent,'location_id':loc}, headers=h)
    assert r.status_code == 200, r.text
    r = c.post('/v90bq/salesperson/visits', json={'organization_id':org,'entity_id':ent,'location_id':loc,'customer_id':cust,'visit_at':datetime.now(timezone.utc).isoformat(),'purpose':'Order follow-up','outcome':'Interested','next_action':'Send quote'}, headers=h)
    assert r.status_code == 200, r.text
    r = c.get('/v90bq/salesperson/visits', params={'organization_id':org,'entity_id':ent,'location_id':loc}, headers=h)
    assert r.status_code == 200 and r.json()['items']
