from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
    r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup(c,h):
    org,eid,lid,wid,cust,sku=[str(uuid4()) for _ in range(6)]
    for path,payload in [
        ('/admin/entities',{'entity_id':eid,'entity_code':'EZ'+eid[:5],'entity_name':'Entity Z'}),
        ('/admin/locations',{'location_id':lid,'entity_id':eid,'location_code':'LZ'+lid[:5],'location_name':'Plant Z'}),
        ('/admin/warehouses',{'warehouse_id':wid,'entity_id':eid,'location_id':lid,'warehouse_code':'WZ'+wid[:5],'warehouse_name':'FG'}),
        ('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),
        ('/admin/access/location',{'user_id':'erpadmin','location_id':lid}),
        ('/admin/access/warehouse',{'user_id':'erpadmin','warehouse_id':wid})]:
        r=c.post(path,json=payload,headers=h); assert r.status_code==200,r.text
    with engine.begin() as x:
        for mid,mt in [(cust,'CUSTOMER'),(sku,'SKU')]:
            x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,:t,1,'{}')"),{'id':mid,'o':org,'e':eid,'t':mt})
    return org,eid,lid,wid,cust,sku

def test_create_submit_approve_and_get_order():
    c=TestClient(app); h=login(c); org,eid,lid,wid,cust,sku=setup(c,h)
    r=c.post('/v90z/sales/orders',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'customer_id':cust,'order_no':'SO-Z-1','lines':[{'sku_id':sku,'quantity':10,'unit_price':125,'discount_pct':2,'gst_rate':12}]},headers=h)
    assert r.status_code==200,r.text; d=r.json(); assert d['status']=='DRAFT'; assert round(d['grand_total'],2)==1372.0
    oid=d['sales_order_id']
    assert c.post(f'/v90z/sales/orders/{oid}/submit',headers=h).json()['status']=='SUBMITTED'
    assert c.post(f'/v90z/sales/orders/{oid}/approve',headers=h).json()['status']=='APPROVED'
    g=c.get(f'/v90z/sales/orders/{oid}',headers=h); assert g.status_code==200; assert g.json()['order']['status']=='APPROVED'; assert len(g.json()['lines'])==1

def test_duplicate_order_and_invalid_sku_blocked():
    c=TestClient(app); h=login(c); org,eid,lid,wid,cust,sku=setup(c,h)
    payload={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'customer_id':cust,'order_no':'SO-Z-2','lines':[{'sku_id':sku,'quantity':1,'unit_price':100}]}
    assert c.post('/v90z/sales/orders',json=payload,headers=h).status_code==200
    assert c.post('/v90z/sales/orders',json=payload,headers=h).status_code==409
    payload['order_no']='SO-Z-3'; payload['lines'][0]['sku_id']=str(uuid4())
    assert c.post('/v90z/sales/orders',json=payload,headers=h).status_code==422

def test_salesperson_can_create_but_cannot_approve():
    c=TestClient(app); h=login(c); org,eid,lid,wid,cust,sku=setup(c,h)
    uid=str(uuid4())
    r=c.post('/admin/users',json={'user_id':uid,'username':'salesz','password':'pw','display_name':'Sales Z','role_id':'salesperson'},headers=h); assert r.status_code==200
    for path,payload in [('/admin/access/entity',{'user_id':uid,'entity_id':eid}),('/admin/access/location',{'user_id':uid,'location_id':lid}),('/admin/access/warehouse',{'user_id':uid,'warehouse_id':wid})]:
        assert c.post(path,json=payload,headers=h).status_code==200
    sh=login(c,'salesz','pw')
    r=c.post('/v90z/sales/orders',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'customer_id':cust,'order_no':'SO-Z-4','lines':[{'sku_id':sku,'quantity':2,'unit_price':130}]},headers=sh); assert r.status_code==200
    oid=r.json()['sales_order_id']; assert c.post(f'/v90z/sales/orders/{oid}/submit',headers=sh).status_code==200
    assert c.post(f'/v90z/sales/orders/{oid}/approve',headers=sh).status_code==403

def test_migration_build_marker():
    ms=load_migrations(); assert any(m.version==100 and m.filename=='100_v90aa_price_margin_negotiation.sql' for m in ms); assert TestClient(app).get('/build').json()['sales_orders']=='customer_order_pricing_stock_approval'
