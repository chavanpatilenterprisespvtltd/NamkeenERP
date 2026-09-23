from uuid import uuid4
from fastapi.testclient import TestClient
from app.__main__ import app


def login(client, username='erpadmin', password='change-me'):
    r=client.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200, r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def setup_scope(c,h):
    oid,eid,lid,wh=map(lambda _: str(uuid4()), range(4))
    suffix=eid[:8]
    assert c.post('/admin/entities',json={'entity_id':eid,'entity_code':'EL'+suffix,'entity_name':'Entity L '+suffix},headers=h).status_code==200
    assert c.post('/admin/locations',json={'location_id':lid,'entity_id':eid,'location_code':'L'+suffix,'location_name':'Plant '+suffix},headers=h).status_code==200
    assert c.post('/admin/access/entity',json={'user_id':'erpadmin','entity_id':eid},headers=h).status_code==200
    assert c.post('/admin/access/location',json={'user_id':'erpadmin','location_id':lid},headers=h).status_code==200
    assert c.post('/admin/warehouses',json={'warehouse_id':wh,'entity_id':eid,'location_id':lid,'warehouse_code':'WH'+suffix,'warehouse_name':'RM Store '+suffix},headers=h).status_code==200
    return oid,eid,lid,wh


def checker(c,h,eid,lid,suffix):
    uid=str(uuid4()); uname='mgr_'+suffix
    assert c.post('/admin/users',json={'user_id':uid,'username':uname,'password':'pw','display_name':'Manager L','role_id':'manager'},headers=h).status_code==200
    assert c.post('/admin/access/entity',json={'user_id':uid,'entity_id':eid},headers=h).status_code==200
    assert c.post('/admin/access/location',json={'user_id':uid,'location_id':lid},headers=h).status_code==200
    return login(c,uname,'pw')


def create_master(c,h,checker_h,oid,eid,typ,payload,lid):
    if typ=='SUPPLIER':
        path=f'/v90k/operational-masters/{typ}/changes'; body={'organization_id':oid,'entity_id':eid,'location_id':lid,'action':'CREATE','payload':payload}
    else:
        path='/v90i/master-data/changes'; body={'organization_id':oid,'entity_id':eid,'action':'CREATE','master_type':typ,'payload':payload}
    r=c.post(path,json=body,headers=h); assert r.status_code==200,r.text
    a=c.post(f"/v90i/approval-queue/{r.json()['request_id']}/approve",json={'organization_id':oid,'reason':'approved'},headers=checker_h); assert a.status_code==200,a.text
    return a.json()['master_id']


def test_procurement_end_to_end():
    c=TestClient(app); h=login(c); oid,eid,lid,wh=setup_scope(c,h); suffix=eid[:8]
    mh=checker(c,h,eid,lid,suffix)
    pid=create_master(c,h,mh,oid,eid,'PRODUCT',{'code':'P-L-'+suffix,'name':'Besan','category':'RM'},lid)
    sid=create_master(c,h,mh,oid,eid,'SUPPLIER',{'code':'S-L-'+suffix,'name':'Supplier L','payment_terms_days':7},lid)
    r=c.post('/v90l/procurement/requisitions',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'purpose':'RM purchase','lines':[{'item_master_id':pid,'qty':100,'uom':'kg'}]},headers=h); assert r.status_code==200,r.text
    rid=r.json()['requisition_id']; assert c.post(f'/v90l/procurement/requisitions/{rid}/submit',headers=h).status_code==200
    q=c.post('/v90l/procurement/quotes',json={'organization_id':oid,'entity_id':eid,'supplier_id':sid,'requisition_id':rid,'quote_no':'Q-'+suffix,'lines':[{'item_master_id':pid,'qty':100,'uom':'kg','unit_rate':50}]},headers=h); assert q.status_code==200,q.text
    qid=q.json()['quote_id']
    p=c.post('/v90l/procurement/purchase-orders',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'supplier_id':sid,'requisition_id':rid,'quote_id':qid,'po_no':'PO-'+suffix,'lines':[{'item_master_id':pid,'qty':100,'uom':'kg','unit_rate':50}]},headers=h); assert p.status_code==200,p.text
    poid=p.json()['po_id']
    a=c.post(f'/v90l/procurement/purchase-orders/{poid}/approve',json={'reason':'rate accepted'},headers=mh); assert a.status_code==200,a.text
    g=c.post('/v90l/procurement/grn-preparations',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'warehouse_id':wh,'po_id':poid,'reference_no':'GRNP-'+suffix,'lines':[{'line_no':1,'planned_receive_qty':90}]},headers=mh); assert g.status_code==200,g.text


def test_procurement_guards():
    c=TestClient(app); h=login(c); oid,eid,lid,wh=setup_scope(c,h); suffix=eid[:8]; mh=checker(c,h,eid,lid,suffix)
    pid=create_master(c,h,mh,oid,eid,'PRODUCT',{'code':'P-G-'+suffix,'name':'Oil','category':'RM'},lid)
    sid=create_master(c,h,mh,oid,eid,'SUPPLIER',{'code':'S-G-'+suffix,'name':'Supplier G'},lid)
    p=c.post('/v90l/procurement/purchase-orders',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'supplier_id':sid,'po_no':'PO-G-'+suffix,'lines':[{'item_master_id':pid,'qty':10,'uom':'kg','unit_rate':100}]},headers=h); assert p.status_code==200
    poid=p.json()['po_id']; self_appr=c.post(f'/v90l/procurement/purchase-orders/{poid}/approve',json={'reason':'x'},headers=h); assert self_appr.status_code==409
    bad=c.post('/v90l/procurement/purchase-orders/'+str(uuid4())+'/approve',json={'reason':'x'},headers=mh); assert bad.status_code==404
