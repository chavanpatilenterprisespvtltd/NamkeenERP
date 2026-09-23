from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.identity import create_user
from app.auth import make_access_token, UserRecord
from sqlalchemy import text
from uuid import uuid4
from pathlib import Path
import json

def env():
    uid=str(uuid4()); uname='gl_'+uid[:8]; create_user(engine,uid,uname,'pw','GL','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); ent=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GL','legal_entity',1)"),{'e':ent,'c':'GL'+ent[:8]})
        db.execute(text("INSERT INTO erp_security_entity_organization(entity_id,organization_id,mapped_by) VALUES(:e,:o,:u)"),{'e':ent,'o':org,'u':uid})
        db.execute(text("INSERT INTO erp_organization_user_access(user_id,organization_id,active,granted_by) VALUES(:u,:o,1,:u)"),{'u':uid,'o':org})
    return c,org,ent

def test_gl_release_and_artifacts():
    r=json.loads(Path('config/release_manifest.json').read_text())
    assert r['version'].startswith('v90.') and r['schema_target']>=266
    assert Path('app/v90gl_working_capital.py').exists() and Path('migrations/263_v90gl_working_capital.sql').exists()

def test_working_capital_snapshot_and_listing():
    c,o,e=env()
    payload={'organization_id':o,'entity_id':e,'period_key':'2099-02','cash_available':50000,'receivables':80000,'overdue_receivables':20000,'payables':45000,'overdue_payables':10000,'inventory_value':60000,'customer_credit_limit':100000,'customer_credit_used':75000,'collection_target':50000,'collections_received':40000,'payment_commitments':30000,'dso_days':24,'dpo_days':15,'inventory_days':30}
    r=c.post('/v90gl/working-capital/snapshot',json=payload)
    assert r.status_code==200,r.text
    j=r.json(); assert j['net_working_capital']==95000 and j['credit_utilization_pct']==75 and j['collection_realization_pct']==80 and j['cash_conversion_cycle_days']==39
    r=c.get('/v90gl/working-capital',params={'organization_id':o,'entity_id':e,'period_key':'2099-02'})
    assert r.status_code==200 and r.json()['snapshot']['net_working_capital']==95000
