from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations


def login(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'})
    assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def setup(c,h):
    org,eid,lid,wid,sku=[str(uuid4()) for _ in range(5)]
    for path,payload in [
        ('/admin/entities',{'entity_id':eid,'entity_code':'EY'+eid[:5],'entity_name':'Entity Y'}),
        ('/admin/locations',{'location_id':lid,'entity_id':eid,'location_code':'LY'+lid[:5],'location_name':'Plant Y'}),
        ('/admin/warehouses',{'warehouse_id':wid,'entity_id':eid,'location_id':lid,'warehouse_code':'WY'+wid[:5],'warehouse_name':'FG'}),
        ('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),
        ('/admin/access/location',{'user_id':'erpadmin','location_id':lid}),
        ('/admin/access/warehouse',{'user_id':'erpadmin','warehouse_id':wid})]:
        r=c.post(path,json=payload,headers=h); assert r.status_code==200,r.text
    with engine.begin() as x:
        x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,'SKU',1,'{}')"),{'id':sku,'o':org,'e':eid})
    return org,eid,lid,wid,sku


def seed_lots(org,eid,lid,wid,sku):
    ids=[]
    with engine.begin() as x:
        for code,exp,qty in [('EARLY','2026-10-01',10),('LATE','2027-01-01',20),('EXPIRED','2025-01-01',50)]:
            pid=str(uuid4()); ids.append(pid)
            x.execute(text("""INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by)
                VALUES(:id,:o,:e,:l,:w,:pr,:sf,:s,:c,10,:q,:q,'kg',:mfg,:exp,'AVAILABLE','RELEASED','erpadmin')"""),
                {'id':pid,'o':org,'e':eid,'l':lid,'w':wid,'pr':str(uuid4()),'sf':str(uuid4()),'s':sku,'c':code,'q':qty,'mfg':'2026-08-01','exp':exp})
    return ids


def test_fefo_preview_excludes_expired_and_orders_earliest_first():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); seed_lots(org,eid,lid,wid,sku)
    r=c.get('/v90y/fg/fefo-preview',params={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'sku_id':sku,'quantity':25},headers=h)
    assert r.status_code==200,r.text
    d=r.json(); assert d['allocated_qty']==25; assert [x['lot_code'] for x in d['fefo']]==['EARLY','LATE']; assert all(x['lot_code']!='EXPIRED' for x in d['fefo'])
    assert d['fefo'][0]['quantity']==10 and d['fefo'][1]['quantity']==15


def test_allocation_creates_open_fefo_allocations_and_release():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); seed_lots(org,eid,lid,wid,sku)
    r=c.post('/v90y/fg/allocations',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'sku_id':sku,'quantity':15,'reference_type':'SALES_ORDER','reference_id':'SO-1'},headers=h)
    assert r.status_code==200,r.text; gid=r.json()['allocation_group_id']; assert r.json()['allocated_qty']==15
    with engine.connect() as x:
        rows=x.execute(text("SELECT lot_code,quantity,status FROM fg_fefo_allocation WHERE allocation_group_id=:id ORDER BY quantity DESC"),{'id':gid}).all()
    assert sum(float(r[1]) for r in rows)==15 and all(r[2]=='OPEN' for r in rows)
    rr=c.post(f'/v90y/fg/allocations/{gid}/release',params={'reason':'cancelled'},headers=h); assert rr.status_code==200,r.text


def test_dispatch_readiness_blocks_expired_qc_or_consumed():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); ids=seed_lots(org,eid,lid,wid,sku)
    r=c.get(f'/v90y/fg/lots/{ids[0]}/dispatch-readiness',headers=h); assert r.status_code==200 and r.json()['dispatch_ready']
    with engine.begin() as x:
        x.execute(text("UPDATE packed_fg_lot SET status='HOLD' WHERE packed_fg_lot_id=:id"),{'id':ids[0]})
    r=c.get(f'/v90y/fg/lots/{ids[0]}/dispatch-readiness',headers=h); assert not r.json()['dispatch_ready'] and 'not_available' in r.json()['reasons']
    r=c.get(f'/v90y/fg/lots/{ids[2]}/dispatch-readiness',headers=h); assert not r.json()['dispatch_ready'] and r.json()['expired']


def test_fefo_allocation_insufficient_and_migration():
    c=TestClient(app); h=login(c); org,eid,lid,wid,sku=setup(c,h); seed_lots(org,eid,lid,wid,sku)
    r=c.post('/v90y/fg/allocations',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'sku_id':sku,'quantity':100},headers=h)
    assert r.status_code==409
    ms=load_migrations(); assert any(m.version==98 and m.filename=='098_v90y_fg_fefo_dispatch.sql' for m in ms)
    assert c.get('/build').json()['fg_fefo_dispatch']=='expiry_fefo_allocation_dispatch_readiness'
