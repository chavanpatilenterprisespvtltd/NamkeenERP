from datetime import datetime, timezone, timedelta
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
from app.migrations import load_migrations


def setup_aw():
    uid=str(uuid4()); uname=f'aw_{uid[:8]}'
    create_user(engine,uid,uname,'pw','AW Tester','manager')
    tok=make_access_token(UserRecord(uid,uname,'manager')); c=TestClient(app,headers={'Authorization':f'Bearer {tok}'})
    org,eid,lid,wid,sku,cust,ret,rl,hold=[str(uuid4()) for _ in range(9)]
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AW','legal_entity',1)"),{'e':eid,'ec':'AW'+eid[:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AW','site',1)"),{'l':lid,'e':eid,'lc':'AWL'+lid[:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:wc,'AW','general',1)"),{'w':wid,'e':eid,'l':lid,'wc':'AWW'+wid[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':eid})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':lid})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:s,:o,'SKU',:e,1,'{}'),(:c,:o,'CUSTOMER',:e,1,'{}')"),{'s':sku,'c':cust,'o':org,'e':eid})
        db.execute(text("INSERT INTO product_cost_rate(cost_rate_id,organization_id,entity_id,item_master_id,uom,unit_cost,source_type,effective_from,active,created_by) VALUES(:id,:o,:e,:i,'kg',50,'TEST',:ef,1,:u)"),{'id':str(uuid4()),'o':org,'e':eid,'i':sku,'ef':datetime.now(timezone.utc).isoformat(),'u':uid})
        # one return line, with DAMAGE 2kg and REWORK 3kg dispositions
        so=str(uuid4())
        db.execute(text("INSERT INTO sales_returns(sales_return_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,customer_id,return_no,status,reason,created_by) VALUES(:r,:o,:e,:l,:w,:so,:c,'RET-AW','DISPOSITIONED','AW',:u)"),{'r':ret,'o':org,'e':eid,'l':lid,'w':wid,'so':so,'c':cust,'u':uid})
        db.execute(text("INSERT INTO sales_return_lines(sales_return_line_id,sales_return_id,dispatch_line_id,sales_order_line_id,sku_id,packed_fg_lot_id,lot_code,requested_qty,received_qty,disposition_status) VALUES(:rl,:r,:dl,:sol,:s,:lot,'AW',5,5,'REWORK')"),{'rl':rl,'r':ret,'dl':str(uuid4()),'sol':str(uuid4()),'s':sku,'lot':str(uuid4())})
        db.execute(text("INSERT INTO return_hold_lots(return_hold_id,sales_return_id,sales_return_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,status,created_by) VALUES(:h,:r,:rl,:o,:e,:l,:w,:s,:lot,'AW',5,'DISPOSED',:u)"),{'h':hold,'r':ret,'rl':rl,'o':org,'e':eid,'l':lid,'w':wid,'s':sku,'lot':str(uuid4()),'u':uid})
        now=datetime.now(timezone.utc).isoformat()
        db.execute(text("INSERT INTO return_disposition_history(disposition_id,sales_return_id,sales_return_line_id,return_hold_id,disposition,quantity,reason,approved_by,created_at) VALUES(:id,:r,:rl,:h,'DAMAGE',2,'broken',:u,:at),(:id2,:r,:rl,:h,'REWORK',3,'repair',:u,:at)"),{'id':str(uuid4()),'id2':str(uuid4()),'r':ret,'rl':rl,'h':hold,'u':uid,'at':now})
    return c, {'org':org,'eid':eid,'lid':lid,'wid':wid,'sku':sku,'ret':ret,'rl':rl}


def test_returns_damage_expiry_analytics_and_snapshot():
    c,ids=setup_aw(); day=datetime.now(timezone.utc).date().isoformat();
    q={'organization_id':ids['org'],'entity_id':ids['eid'],'location_id':ids['lid'],'period_from':day+'T00:00:00+00:00','period_to':day+'T23:59:59+00:00'}
    r=c.get('/v90aw/returns/analytics',params=q); assert r.status_code==200,r.text
    d=r.json(); assert d['total_return_qty']==5 and d['damage_qty']==2 and d['damage_estimated_cost']==100 and d['rework_qty']==3
    r=c.get('/v90aw/returns/damage-expiry',params=q); assert r.status_code==200 and r.json()['damage_and_expiry_estimated_cost']==100
    r=c.post('/v90aw/returns/analytics/snapshots',json=q); assert r.status_code==200,r.text
    snap=r.json()['snapshot_id']; again=c.post('/v90aw/returns/analytics/snapshots',json=q); assert again.json()['snapshot_id']==snap


def test_rework_job_limits_quantity_and_calculates_loss_cost():
    c,ids=setup_aw()
    body={'organization_id':ids['org'],'entity_id':ids['eid'],'location_id':ids['lid'],'warehouse_id':ids['wid'],'sales_return_id':ids['ret'],'sales_return_line_id':ids['rl'],'source_disposition':'REWORK','input_qty':3,'processing_cost':20,'reference_no':'RW-'+ids['ret'][:8]}
    r=c.post('/v90aw/repack-rework/jobs',json=body); assert r.status_code==200,r.text
    job=r.json()['job_id']; assert r.json()['input_cost']==150 and r.json()['total_cost']==170
    over=dict(body); over['reference_no']='RW2-'+ids['ret'][:8]; over['input_qty']=1
    assert c.post('/v90aw/repack-rework/jobs',json=over).status_code==409
    r=c.post(f'/v90aw/repack-rework/jobs/{job}/complete',json={'output_qty':2.5}); assert r.status_code==200,r.text
    d=r.json(); assert d['loss_qty']==0.5 and d['total_cost']==170 and d['output_unit_cost']==68
    assert c.post(f'/v90aw/repack-rework/jobs/{job}/complete',json={'output_qty':1}).status_code==409


def test_v90aw_migration_and_permissions():
    assert any(m.version==122 and m.filename=='122_v90aw_returns_analytics_rework.sql' for m in load_migrations())
    with engine.connect() as db:
        assert db.execute(text("SELECT permission_id FROM erp_permissions WHERE permission_id='returns_mis.view'")).scalar()=='returns_mis.view'
        assert db.execute(text("SELECT permission_id FROM erp_permissions WHERE permission_id='rework.edit'")).scalar()=='rework.edit'
