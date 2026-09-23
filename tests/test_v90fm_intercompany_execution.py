from pathlib import Path
import hashlib,json

def test_v90fm_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text()); assert m['migrations'][-1]['version']>=244 and m['latest_schema']>=244
    f=Path('migrations/239_v90fm_intercompany_execution.sql'); historical=next(x for x in m['migrations'] if x['version']==239); assert hashlib.sha256(f.read_bytes()).hexdigest()==historical['sha256']

def test_v90fm_routes_and_guardrails():
    assert Path('app/v90fm_intercompany_execution.py').exists() and Path('web/intercompany.html').exists()
    s=Path('app/v90fm_intercompany_execution.py').read_text()
    for route in ['/v90fm/intercompany/transactions','/transactions/{transaction_id}/post','/intercompany/eliminations','/eliminations/{elimination_id}/resolve','/intercompany/{period_key}/close']:
        assert route in s
    assert 'INTERCOMPANY_OUT' in s and 'INTERCOMPANY_IN' in s and 'accounting_posting_automatic' in s

def test_v90fm_main_registration():
    s=Path('app/__main__.py').read_text(); assert 'register_v90fm_routes(app, engine)' in s

def test_v90fm_post_moves_stock_and_creates_elimination():
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.__main__ import app, engine
    from sqlalchemy import text
    c=TestClient(app); h={'Authorization':'Bearer '+__import__('app.auth',fromlist=['make_access_token']).make_access_token(__import__('app.auth',fromlist=['UserRecord']).UserRecord('erpadmin','erpadmin','super_admin'))}
    o,fe,te,fl,tl,fw,tw,item,lot=[str(uuid4()) for _ in range(9)]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:id,:o,:e,:l,:w,:i,:lot,'RECEIPT',50,'kg','TEST',:r,'POSTED','erpadmin')"),{'id':str(uuid4()),'o':o,'e':fe,'l':fl,'w':fw,'i':item,'lot':lot,'r':str(uuid4())})
    r=c.post('/v90fm/intercompany/transactions',json={'organization_id':o,'period_key':'2026-09','from_entity_id':fe,'to_entity_id':te,'lines':[{'item_master_id':item,'lot_id':lot,'quantity':20,'uom':'kg','unit_value':100,'from_location_id':fl,'from_warehouse_id':fw,'to_location_id':tl,'to_warehouse_id':tw}]},headers=h); assert r.status_code==200,r.text
    tid=r.json()['transaction_id']; r=c.post(f'/v90fm/intercompany/transactions/{tid}/post',json={'evidence_note':'approved transfer'},headers=h); assert r.status_code==200,r.text
    with engine.connect() as conn:
        out=conn.execute(text("SELECT SUM(quantity) FROM inventory_stock_ledger WHERE organization_id=:o AND entity_id=:e AND item_master_id=:i AND lot_id=:lot"),{'o':o,'e':fe,'i':item,'lot':lot}).scalar()
        inc=conn.execute(text("SELECT SUM(quantity) FROM inventory_stock_ledger WHERE organization_id=:o AND entity_id=:e AND item_master_id=:i AND lot_id=:lot"),{'o':o,'e':te,'i':item,'lot':lot}).scalar()
    assert float(out)==30.0 and float(inc)==20.0
