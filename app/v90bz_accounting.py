from __future__ import annotations
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(engine, request, permission):
    u=authenticate(request); p=permissions_for_user(engine,u.user_id)
    if permission not in p and 'admin.users' not in p: raise HTTPException(403,'permission denied')
    return u

def _ensure_schema(engine):
    with engine.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS accounting_ledger_map (mapping_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT, source_key TEXT NOT NULL, ledger_code TEXT NOT NULL, ledger_name TEXT, active INTEGER NOT NULL DEFAULT 1, UNIQUE(organization_id, entity_id, source_key))"))
        c.execute(text("CREATE TABLE IF NOT EXISTS accounting_export_batches (batch_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT, export_format TEXT NOT NULL DEFAULT 'TALLY_XML', status TEXT NOT NULL DEFAULT 'DRAFT', period_key TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, exported_at TIMESTAMP)"))
        c.execute(text("CREATE TABLE IF NOT EXISTS accounting_export_lines (export_line_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL, voucher_type TEXT NOT NULL, voucher_no TEXT NOT NULL, debit_ledger TEXT NOT NULL, credit_ledger TEXT NOT NULL, amount NUMERIC NOT NULL DEFAULT 0, tax_ledger TEXT, narration TEXT, UNIQUE(batch_id, source_type, source_id))"))

def register_v90bz_routes(app, engine):
    _ensure_schema(engine)
    @app.get('/v90bz/accounting/summary')
    def summary(request:Request, organization_id:str, entity_id:str|None=None, period_key:str|None=None):
        _perm(engine,request,'accounting.export')
        q='SELECT COUNT(*) n, COALESCE(SUM(amount),0) amount FROM accounting_export_lines l JOIN accounting_export_batches b ON b.batch_id=l.batch_id WHERE b.organization_id=:o'; p={'o':organization_id}
        if entity_id:q+=' AND b.entity_id=:e';p['e']=entity_id
        if period_key:q+=' AND b.period_key=:pk';p['pk']=period_key
        with engine.connect() as c:r=c.execute(text(q),p).mappings().one()
        return {'lines':int(r['n'] or 0),'amount':float(r['amount'] or 0),'period_key':period_key}
    @app.get('/v90bz/accounting/maps')
    def maps(request:Request, organization_id:str, entity_id:str|None=None):
        _perm(engine,request,'accounting.view')
        q='SELECT * FROM accounting_ledger_map WHERE organization_id=:o AND active=1';p={'o':organization_id}
        if entity_id:q+=' AND (entity_id=:e OR entity_id IS NULL)';p['e']=entity_id
        with engine.connect() as c: return {'items':[dict(x) for x in c.execute(text(q+' ORDER BY source_key'),p).mappings().all()]}
    @app.post('/v90bz/accounting/maps')
    def create_map(body:dict, request:Request):
        _perm(engine,request,'accounting.manage')
        for k in ('organization_id','source_key','ledger_code'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with engine.begin() as c:c.execute(text('INSERT INTO accounting_ledger_map(mapping_id,organization_id,entity_id,source_key,ledger_code,ledger_name,active) VALUES(:i,:o,:e,:s,:l,:n,1)'),{'i':i,'o':body['organization_id'],'e':body.get('entity_id'),'s':body['source_key'],'l':body['ledger_code'],'n':body.get('ledger_name')})
        return {'mapping_id':i}
    @app.post('/v90bz/accounting/batches')
    def create_batch(body:dict,request:Request):
        u=_perm(engine,request,'accounting.export'); i=str(uuid4())
        if not body.get('organization_id'):raise HTTPException(400,'organization_id is required')
        with engine.begin() as c:c.execute(text('INSERT INTO accounting_export_batches(batch_id,organization_id,entity_id,export_format,status,period_key,created_by) VALUES(:i,:o,:e,:f,\'DRAFT\',:p,:u)'),{'i':i,'o':body['organization_id'],'e':body.get('entity_id'),'f':body.get('export_format','TALLY_XML'),'p':body.get('period_key'),'u':str(u.user_id)})
        return {'batch_id':i,'status':'DRAFT'}
    @app.post('/v90bz/accounting/batches/{batch_id}/generate')
    def generate(batch_id:str,request:Request):
        _perm(engine,request,'accounting.export')
        with engine.begin() as c:
            b=c.execute(text('SELECT * FROM accounting_export_batches WHERE batch_id=:b'),{'b':batch_id}).mappings().first()
            if not b:raise HTTPException(404,'batch not found')
            if b['status']!='DRAFT':raise HTTPException(409,'batch is not draft')
            rows=c.execute(text('SELECT * FROM tax_transaction_lines WHERE organization_id=:o AND (:e IS NULL OR entity_id=:e) AND (:p IS NULL OR substr(created_at,1,7)=:p) ORDER BY created_at'),{'o':b['organization_id'],'e':b['entity_id'],'p':b['period_key']}).mappings().all()
            for r in rows:
                exists=c.execute(text('SELECT 1 FROM accounting_export_lines WHERE batch_id=:b AND source_type=:s AND source_id=:i'),{'b':batch_id,'s':r['source_type'],'i':r['source_id']}).first()
                if exists:continue
                tax=float(r['total_tax'] or 0); taxable=float(r['taxable_value'] or 0)
                c.execute(text('INSERT INTO accounting_export_lines(export_line_id,batch_id,source_type,source_id,voucher_type,voucher_no,debit_ledger,credit_ledger,amount,tax_ledger,narration) VALUES(:i,:b,:s,:sid,\'SALES\',:vn,\'CUSTOMER\',\'SALES\',:a,:t,:n)'),{'i':str(uuid4()),'b':batch_id,'s':r['source_type'],'sid':r['source_id'],'vn':r['source_id'],'a':taxable+tax,'t':'GST','n':f"GST source {r['source_id']}"})
            c.execute(text("UPDATE accounting_export_batches SET status='GENERATED' WHERE batch_id=:b"),{'b':batch_id})
        return {'batch_id':batch_id,'status':'GENERATED','generated_lines':len(rows)}
    @app.post('/v90bz/accounting/batches/{batch_id}/export')
    def export(batch_id:str,request:Request):
        _perm(engine,request,'accounting.export')
        with engine.begin() as c:
            b=c.execute(text('SELECT * FROM accounting_export_batches WHERE batch_id=:b'),{'b':batch_id}).mappings().first()
            if not b:raise HTTPException(404,'batch not found')
            if b['status']!='GENERATED':raise HTTPException(409,'generate batch before export')
            lines=c.execute(text('SELECT * FROM accounting_export_lines WHERE batch_id=:b ORDER BY voucher_no'),{'b':batch_id}).mappings().all()
            c.execute(text("UPDATE accounting_export_batches SET status='EXPORTED', exported_at=CURRENT_TIMESTAMP WHERE batch_id=:b"),{'b':batch_id})
        return {'batch_id':batch_id,'format':b['export_format'],'status':'EXPORTED','vouchers':[dict(x) for x in lines]}
    @app.get('/ui/accounting')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'accounting.html')
