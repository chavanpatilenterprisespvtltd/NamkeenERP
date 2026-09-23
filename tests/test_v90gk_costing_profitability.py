from fastapi.testclient import TestClient
from app.__main__ import app,engine
from app.identity import create_user
from app.auth import make_access_token,UserRecord
from sqlalchemy import text
from uuid import uuid4
import json
from pathlib import Path

def env():
 uid=str(uuid4()); uname='gk_'+uid[:8]; create_user(engine,uid,uname,'pw','GK','manager')
 c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))}); org=str(uuid4()); ent=str(uuid4())
 with engine.begin() as db:
  db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GK','legal_entity',1)"),{'e':ent,'c':'GK'+ent[:8]})
  db.execute(text("INSERT INTO erp_security_entity_organization(entity_id,organization_id,mapped_by) VALUES(:e,:o,:u)"),{'e':ent,'o':org,'u':uid})
  db.execute(text("INSERT INTO erp_organization_user_access(user_id,organization_id,active,granted_by) VALUES(:u,:o,1,:u)"),{'u':uid,'o':org})
 return c,org,ent

def test_gk_release_and_artifacts():
 r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
 assert Path('app/v90gk_costing_profitability.py').exists() and Path('migrations/262_v90gk_costing_profitability.sql').exists()

def test_profitability_snapshot_and_listing():
 c,o,e=env(); h=c.headers
 r=c.post('/v90gk/costing/profitability/snapshot',json={'organization_id':o,'entity_id':e,'product_id':'P1','period_key':'2099-01','units_sold':100,'net_sales':15000,'material_cost':5000,'packaging_cost':1000,'labour_cost':1500,'overhead_cost':1000,'return_cost':500,'standard_cost':85}); assert r.status_code==200,r.text
 assert r.json()['gross_margin']==6000 and r.json()['gross_margin_pct']==40
 r=c.get('/v90gk/costing/profitability',params={'organization_id':o,'entity_id':e,'period_key':'2099-01'}); assert r.status_code==200 and r.json()['count']==1 and r.json()['gross_margin_pct']==40
