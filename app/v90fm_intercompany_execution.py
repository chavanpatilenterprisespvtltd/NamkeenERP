from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .v90fo_audit_approval_evidence import write_audit

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception as exc: raise HTTPException(400,'period_key must be YYYY-MM') from exc

def ensure_v90fm_schema(e):
    with e.begin() as c:
        for s in [
        '''CREATE TABLE IF NOT EXISTS intercompany_transaction(
            transaction_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL,
            from_entity_id TEXT NOT NULL, to_entity_id TEXT NOT NULL, transaction_type TEXT NOT NULL DEFAULT 'STOCK_TRANSFER',
            reference_type TEXT, reference_id TEXT, status TEXT NOT NULL DEFAULT 'DRAFT',
            posting_date DATE, currency TEXT NOT NULL DEFAULT 'INR', taxable_value NUMERIC NOT NULL DEFAULT 0,
            tax_value NUMERIC NOT NULL DEFAULT 0, total_value NUMERIC NOT NULL DEFAULT 0, narration TEXT,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, posted_by TEXT, posted_at TIMESTAMP,
            UNIQUE(organization_id,reference_type,reference_id))''',
        '''CREATE TABLE IF NOT EXISTS intercompany_transaction_line(
            line_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, item_master_id TEXT NOT NULL, lot_id TEXT,
            quantity NUMERIC NOT NULL, uom TEXT NOT NULL, unit_value NUMERIC NOT NULL DEFAULT 0,
            line_value NUMERIC NOT NULL DEFAULT 0, from_location_id TEXT, from_warehouse_id TEXT,
            to_location_id TEXT, to_warehouse_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS intercompany_elimination(
            elimination_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL,
            transaction_id TEXT NOT NULL, from_entity_id TEXT NOT NULL, to_entity_id TEXT NOT NULL,
            amount NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN', evidence_note TEXT,
            resolved_by TEXT, resolved_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(transaction_id))''',
        '''CREATE TABLE IF NOT EXISTS intercompany_period_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL,
            transaction_count INTEGER NOT NULL DEFAULT 0, posted_count INTEGER NOT NULL DEFAULT 0,
            open_elimination_count INTEGER NOT NULL DEFAULT 0, total_value NUMERIC NOT NULL DEFAULT 0,
            closed_by TEXT NOT NULL, closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_intercompany_tx_scope ON intercompany_transaction(organization_id,period_key,status,from_entity_id,to_entity_id)',
        'CREATE INDEX IF NOT EXISTS ix_intercompany_elim_scope ON intercompany_elimination(organization_id,period_key,status)']:
            c.execute(text(s))
        for p,n in [('intercompany.view','View intercompany transactions'),('intercompany.manage','Manage intercompany transactions'),('intercompany.post','Post intercompany stock transactions'),('intercompany.eliminate','Resolve intercompany elimination'),('intercompany.close','Close intercompany period')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

def register_v90fm_routes(app:FastAPI,e):
    ensure_v90fm_schema(e)
    @app.post('/v90fm/intercompany/transactions')
    def create(body:dict,request:Request):
        u=_perm(e,request,'intercompany.manage'); o,p=body.get('organization_id'),body.get('period_key'); fe,te=body.get('from_entity_id'),body.get('to_entity_id')
        if not all([o,p,fe,te]): raise HTTPException(400,'organization_id, period_key, from_entity_id and to_entity_id are required')
        if fe==te: raise HTTPException(400,'from_entity_id and to_entity_id must differ')
        _valid(p); lines=body.get('lines') or []
        if not lines: raise HTTPException(400,'at least one transaction line is required')
        tid=str(uuid4()); taxable=_d(body.get('taxable_value')); tax=_d(body.get('tax_value')); total=_d(taxable+tax)
        ref_type,ref_id=body.get('reference_type'),body.get('reference_id')
        with e.begin() as c:
            if ref_type and ref_id and c.execute(text('SELECT 1 FROM intercompany_transaction WHERE organization_id=:o AND reference_type=:rt AND reference_id=:ri'),{'o':o,'rt':ref_type,'ri':ref_id}).first(): raise HTTPException(409,'reference is already linked to an intercompany transaction')
            c.execute(text('''INSERT INTO intercompany_transaction(transaction_id,organization_id,period_key,from_entity_id,to_entity_id,transaction_type,reference_type,reference_id,posting_date,currency,taxable_value,tax_value,total_value,narration,created_by) VALUES(:id,:o,:p,:f,:t,:tt,:rt,:ri,:pd,:cur,:tx,:tax,:tot,:n,:u)'''),{'id':tid,'o':o,'p':p,'f':fe,'t':te,'tt':str(body.get('transaction_type') or 'STOCK_TRANSFER').upper(),'rt':ref_type,'ri':ref_id,'pd':body.get('posting_date'),'cur':body.get('currency') or 'INR','tx':float(taxable),'tax':float(tax),'tot':float(total),'n':body.get('narration'),'u':str(u.user_id)})
            for line in lines:
                q=_d(line.get('quantity'))
                if q<=0: raise HTTPException(400,'line quantity must be positive')
                uv=_d(line.get('unit_value')); item=line.get('item_master_id'); uom=line.get('uom')
                if not item or not uom or not line.get('from_location_id') or not line.get('from_warehouse_id') or not line.get('to_location_id') or not line.get('to_warehouse_id'): raise HTTPException(400,'each line requires item_master_id, uom and source/destination location and warehouse')
                c.execute(text('''INSERT INTO intercompany_transaction_line(line_id,transaction_id,item_master_id,lot_id,quantity,uom,unit_value,line_value,from_location_id,from_warehouse_id,to_location_id,to_warehouse_id) VALUES(:id,:t,:i,:lot,:q,:u,:uv,:lv,:fl,:fw,:tl,:tw)'''),{'id':str(uuid4()),'t':tid,'i':str(item),'lot':line.get('lot_id'),'q':float(q),'u':uom,'uv':float(uv),'lv':float(_d(q*uv)),'fl':line['from_location_id'],'fw':line['from_warehouse_id'],'tl':line['to_location_id'],'tw':line['to_warehouse_id']})
        write_audit(e, actor_user_id=str(u.user_id), module_name='INTERCOMPANY', action_code='TRANSACTION_CREATE', outcome='SUCCESS', organization_id=o, subject_type='INTERCOMPANY_TRANSACTION', subject_id=tid, details={'status':'DRAFT','total_value':float(total)})
        return {'transaction_id':tid,'status':'DRAFT','total_value':float(total),'automatic_operational_mutation':False,'accounting_posting_automatic':False}
    @app.get('/v90fm/intercompany/transactions')
    def list_tx(organization_id:str,period_key:str,request:Request,entity_id:str|None=None,status:str|None=None):
        _perm(e,request,'intercompany.view'); _valid(period_key); q='SELECT * FROM intercompany_transaction WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
        if entity_id:q+=' AND (from_entity_id=:e OR to_entity_id=:e)';par['e']=entity_id
        if status:q+=' AND status=:s';par['s']=status.upper()
        with e.connect() as c: rows=c.execute(text(q+' ORDER BY created_at DESC'),par).mappings().all()
        return {'transactions':[dict(x) for x in rows]}
    @app.post('/v90fm/intercompany/transactions/{transaction_id}/post')
    def post(transaction_id:str,body:dict,request:Request):
        u=_perm(e,request,'intercompany.post'); ev=str(body.get('evidence_note') or '').strip()
        if not ev: raise HTTPException(400,'evidence_note is required')
        with e.begin() as c:
            tx=c.execute(text("SELECT * FROM intercompany_transaction WHERE transaction_id=:id AND status='DRAFT'"),{'id':transaction_id}).mappings().first()
            if not tx: raise HTTPException(404,'draft intercompany transaction not found')
            lines=c.execute(text('SELECT * FROM intercompany_transaction_line WHERE transaction_id=:t ORDER BY line_id'),{'t':transaction_id}).mappings().all()
            if not lines: raise HTTPException(409,'transaction has no lines')
            for l in lines:
                q=_d(l['quantity'])
                bal=c.execute(text("SELECT COALESCE(SUM(quantity),0) FROM inventory_stock_ledger WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND ((lot_id=:lot) OR (lot_id IS NULL AND :lot IS NULL)) AND status='POSTED'"),{'o':tx['organization_id'],'e':tx['from_entity_id'],'l':l['from_location_id'],'w':l['from_warehouse_id'],'i':l['item_master_id'],'lot':l['lot_id']}).scalar() or 0
                if _d(bal) < q: raise HTTPException(409,f'insufficient source stock for item {l["item_master_id"]}')
                c.execute(text("""INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:a,:o,:fe,:fl,:fw,:i,:lot,'INTERCOMPANY_OUT',:outq,:u,'INTERCOMPANY',:t,'POSTED',:by),(:b,:o,:te,:tl,:tw,:i,:lot,'INTERCOMPANY_IN',:inq,:u,'INTERCOMPANY',:t,'POSTED',:by)"""),{'a':str(uuid4()),'b':str(uuid4()),'o':tx['organization_id'],'fe':tx['from_entity_id'],'te':tx['to_entity_id'],'fl':l['from_location_id'],'fw':l['from_warehouse_id'],'tl':l['to_location_id'],'tw':l['to_warehouse_id'],'i':l['item_master_id'],'lot':l['lot_id'],'outq':float(-q),'inq':float(q),'u':l['uom'],'t':transaction_id,'by':str(u.user_id)})
            c.execute(text("UPDATE intercompany_transaction SET status='POSTED',posted_by=:u,posted_at=CURRENT_TIMESTAMP,narration=COALESCE(narration,'') || ' | Posting evidence: ' || :ev WHERE transaction_id=:id"),{'u':str(u.user_id),'ev':ev,'id':transaction_id})
            c.execute(text('''INSERT INTO intercompany_elimination(elimination_id,organization_id,period_key,transaction_id,from_entity_id,to_entity_id,amount,status,evidence_note,created_by) VALUES(:id,:o,:p,:t,:f,:to,:a,'OPEN',:ev,:u)'''),{'id':str(uuid4()),'o':tx['organization_id'],'p':tx['period_key'],'t':transaction_id,'f':tx['from_entity_id'],'to':tx['to_entity_id'],'a':float(tx['total_value']),'ev':ev,'u':str(u.user_id)})
        write_audit(e, actor_user_id=str(u.user_id), module_name='INTERCOMPANY', action_code='TRANSACTION_POST', outcome='SUCCESS', organization_id=str(tx['organization_id']), subject_type='INTERCOMPANY_TRANSACTION', subject_id=transaction_id, details={'evidence_recorded':True,'elimination_status':'OPEN'})
        return {'transaction_id':transaction_id,'status':'POSTED','elimination_status':'OPEN','accounting_posting_automatic':False}
    @app.get('/v90fm/intercompany/eliminations')
    def eliminations(organization_id:str,period_key:str,request:Request,status:str='OPEN'):
        _perm(e,request,'intercompany.view'); _valid(period_key)
        with e.connect() as c: rows=c.execute(text('SELECT * FROM intercompany_elimination WHERE organization_id=:o AND period_key=:p AND status=:s ORDER BY created_at'),{'o':organization_id,'p':period_key,'s':status.upper()}).mappings().all()
        return {'eliminations':[dict(x) for x in rows]}
    @app.post('/v90fm/intercompany/eliminations/{elimination_id}/resolve')
    def resolve(elimination_id:str,body:dict,request:Request):
        u=_perm(e,request,'intercompany.eliminate'); note=str(body.get('resolution_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not note or not ev: raise HTTPException(400,'resolution_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE intercompany_elimination SET status='RESOLVED',evidence_note=COALESCE(evidence_note,'') || ' | Resolution: ' || :ev,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE elimination_id=:id AND status='OPEN' RETURNING elimination_id"),{'ev':ev,'u':str(u.user_id),'id':elimination_id}).first()
            if not r: raise HTTPException(404,'open elimination not found')
        write_audit(e, actor_user_id=str(u.user_id), module_name='INTERCOMPANY', action_code='ELIMINATION_RESOLVE', outcome='SUCCESS', subject_type='INTERCOMPANY_ELIMINATION', subject_id=elimination_id, details={'evidence_recorded':True})
        return {'elimination_id':elimination_id,'status':'RESOLVED','evidence_recorded':True}
    @app.post('/v90fm/intercompany/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'intercompany.close'); _valid(period_key); o=body.get('organization_id')
        if not o: raise HTTPException(400,'organization_id is required')
        with e.connect() as c:
            n=c.execute(text('SELECT COUNT(*) FROM intercompany_transaction WHERE organization_id=:o AND period_key=:p'),{'o':o,'p':period_key}).scalar() or 0
            posted=c.execute(text("SELECT COUNT(*) FROM intercompany_transaction WHERE organization_id=:o AND period_key=:p AND status='POSTED'"),{'o':o,'p':period_key}).scalar() or 0
            op=c.execute(text("SELECT COUNT(*) FROM intercompany_elimination WHERE organization_id=:o AND period_key=:p AND status='OPEN'"),{'o':o,'p':period_key}).scalar() or 0
            total=c.execute(text('SELECT COALESCE(SUM(total_value),0) FROM intercompany_transaction WHERE organization_id=:o AND period_key=:p AND status=\'POSTED\''),{'o':o,'p':period_key}).scalar() or 0
        if op and not body.get('force'): raise HTTPException(409,f'cannot close: {op} open intercompany elimination(s)')
        with e.begin() as c:
            c.execute(text('''INSERT INTO intercompany_period_close(close_id,organization_id,period_key,transaction_count,posted_count,open_elimination_count,total_value,closed_by,closure_note) VALUES(:id,:o,:p,:n,:po,:op,:v,:u,:note) ON CONFLICT(organization_id,period_key) DO UPDATE SET transaction_count=:n,posted_count=:po,open_elimination_count=:op,total_value=:v,closed_by=:u,closure_note=:note,closed_at=CURRENT_TIMESTAMP'''),{'id':str(uuid4()),'o':o,'p':period_key,'n':int(n),'po':int(posted),'op':int(op),'v':float(_d(total)),'u':str(u.user_id),'note':body.get('closure_note')})
        write_audit(e, actor_user_id=str(u.user_id), module_name='INTERCOMPANY', action_code='PERIOD_CLOSE', outcome='SUCCESS', organization_id=o, subject_type='PERIOD', subject_id=period_key, details={'forced':bool(body.get('force')),'open_elimination_count':int(op)})
        return {'organization_id':o,'period_key':period_key,'status':'CLOSED','transaction_count':int(n),'posted_count':int(posted),'open_elimination_count':int(op),'total_value':float(_d(total)),'forced':bool(body.get('force'))}
    @app.get('/ui/intercompany')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'intercompany.html')
