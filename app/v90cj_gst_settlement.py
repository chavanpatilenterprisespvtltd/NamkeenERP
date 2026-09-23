from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(engine, request, permission):
    u=authenticate(request); p=permissions_for_user(engine,u.user_id)
    if permission not in p and 'admin.users' not in p: raise HTTPException(403,'permission denied')
    return u

def _q(v): return Decimal(str(v or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)

def _ensure(engine):
    with engine.begin() as c:
        for pid,name in [('gst_settlement.view','View GST settlement'),('gst_settlement.manage','Manage GST settlement'),('gst_settlement.signoff','Sign off GST settlement')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':pid,'n':name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_settlement_runs(
          settlement_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT,
          liability NUMERIC NOT NULL DEFAULT 0, challan_amount NUMERIC NOT NULL DEFAULT 0, ledger_amount NUMERIC NOT NULL DEFAULT 0,
          bank_amount NUMERIC NOT NULL DEFAULT 0, difference NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'DRAFT',
          exception_reason TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(filing_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_settlement_matches(
          match_id TEXT PRIMARY KEY, settlement_id TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
          amount NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'MATCHED', notes TEXT, created_by TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(settlement_id,source_type,source_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_settlement_signoffs(
          signoff_id TEXT PRIMARY KEY, settlement_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
          signed_by TEXT, signed_at TIMESTAMP, remarks TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(settlement_id))'''))

def register_v90cj_routes(app, engine):
    _ensure(engine)
    @app.post('/v90cj/gst/settlement/{filing_id}/run')
    def run(filing_id:str, request:Request):
        u=_perm(engine,request,'gst_settlement.manage')
        with engine.begin() as c:
            f=c.execute(text('SELECT * FROM gst_filing_periods WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not f: raise HTTPException(404,'filing not found')
            # Return-operation payments are the primary statutory payment source.
            challan=_q(c.execute(text('SELECT COALESCE(SUM(amount+interest+penalty),0) FROM gst_tax_payments WHERE filing_id=:f AND status<>\'VOID\''),{'f':filing_id}).scalar() or 0)
            liability=_q(f['net_tax'])
            ledger=_q(c.execute(text('''SELECT COALESCE(SUM(CASE WHEN l.tax_component IS NOT NULL THEN l.credit-l.debit ELSE 0 END),0)
              FROM accounting_posting_lines l JOIN accounting_postings p ON p.posting_id=l.posting_id
              WHERE p.organization_id=:o AND (:e IS NULL OR p.entity_id=:e) AND substr(COALESCE(p.posting_date,''),1,7)=:period'''),{'o':f['organization_id'],'e':f['entity_id'],'period':f['period_key']}).scalar() or 0)
            bank=_q(c.execute(text('''SELECT COALESCE(SUM(amount),0) FROM bank_reconciliation_lines
              WHERE entity_id=:e AND status IN ('MATCHED','RECONCILED') AND substr(CAST(statement_date AS TEXT),1,7)=:period'''),{'e':f['entity_id'],'period':f['period_key']}).scalar() or 0) if f['entity_id'] else Decimal('0')
            difference=_q(challan-liability)
            status='MATCHED' if difference==0 else 'EXCEPTION'
            sid=str(uuid4()); old=c.execute(text('SELECT settlement_id FROM gst_settlement_runs WHERE filing_id=:f'),{'f':filing_id}).scalar()
            sid=old or sid
            c.execute(text('''INSERT INTO gst_settlement_runs(settlement_id,filing_id,organization_id,entity_id,liability,challan_amount,ledger_amount,bank_amount,difference,status,exception_reason,created_by)
              VALUES(:s,:f,:o,:e,:l,:c,:g,:b,:d,:st,:r,:u)
              ON CONFLICT(filing_id) DO UPDATE SET liability=:l,challan_amount=:c,ledger_amount=:g,bank_amount=:b,difference=:d,status=:st,exception_reason=:r,created_by=:u,created_at=CURRENT_TIMESTAMP'''),
              {'s':sid,'f':filing_id,'o':f['organization_id'],'e':f['entity_id'],'l':float(liability),'c':float(challan),'g':float(ledger),'b':float(bank),'d':float(difference),'st':status,'r':None if status=='MATCHED' else 'GST liability and challan/payment amount differ','u':str(u.user_id)})
        return {'settlement_id':sid,'filing_id':filing_id,'status':status,'liability':float(liability),'challan_amount':float(challan),'ledger_amount':float(ledger),'bank_amount':float(bank),'difference':float(difference)}

    @app.get('/v90cj/gst/settlement/{filing_id}')
    def summary(filing_id:str,request:Request):
        _perm(engine,request,'gst_settlement.view')
        with engine.connect() as c:
            s=c.execute(text('SELECT * FROM gst_settlement_runs WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not s: raise HTTPException(404,'settlement not generated')
            m=[dict(x) for x in c.execute(text('SELECT * FROM gst_settlement_matches WHERE settlement_id=:s ORDER BY created_at'),{'s':s['settlement_id']}).mappings().all()]
            so=c.execute(text('SELECT * FROM gst_settlement_signoffs WHERE settlement_id=:s'),{'s':s['settlement_id']}).mappings().first()
        return {'settlement':dict(s),'matches':m,'signoff':dict(so) if so else None}

    @app.post('/v90cj/gst/settlement/{settlement_id}/match')
    def match(settlement_id:str,request:Request,body:dict):
        u=_perm(engine,request,'gst_settlement.manage'); amount=_q(body.get('amount'))
        if amount<=0: raise HTTPException(400,'amount must be positive')
        st=str(body.get('source_type','CHALLAN')).upper(); src=str(body.get('source_id') or '').strip()
        if not src: raise HTTPException(400,'source_id is required')
        with engine.begin() as c:
            if not c.execute(text('SELECT 1 FROM gst_settlement_runs WHERE settlement_id=:s'),{'s':settlement_id}).first(): raise HTTPException(404,'settlement not found')
            c.execute(text('''INSERT INTO gst_settlement_matches(match_id,settlement_id,source_type,source_id,amount,status,notes,created_by)
              VALUES(:i,:s,:t,:x,:a,'MATCHED',:n,:u) ON CONFLICT(settlement_id,source_type,source_id) DO UPDATE SET amount=:a,notes=:n,created_by=:u'''),{'i':str(uuid4()),'s':settlement_id,'t':st,'x':src,'a':float(amount),'n':body.get('notes'),'u':str(u.user_id)})
        return {'settlement_id':settlement_id,'source_type':st,'source_id':src,'amount':float(amount),'status':'MATCHED'}

    @app.post('/v90cj/gst/settlement/{settlement_id}/signoff')
    def signoff(settlement_id:str,request:Request,body:dict):
        u=_perm(engine,request,'gst_settlement.signoff'); status=body.get('status','SIGNED')
        if status not in {'SIGNED','REJECTED'}: raise HTTPException(400,'status must be SIGNED or REJECTED')
        with engine.begin() as c:
            s=c.execute(text('SELECT status FROM gst_settlement_runs WHERE settlement_id=:s'),{'s':settlement_id}).first()
            if not s: raise HTTPException(404,'settlement not found')
            if status=='SIGNED' and s[0]!='MATCHED': raise HTTPException(409,'settlement has unresolved exception')
            c.execute(text('''INSERT INTO gst_settlement_signoffs(signoff_id,settlement_id,status,signed_by,signed_at,remarks)
              VALUES(:i,:s,:st,:u,CURRENT_TIMESTAMP,:r) ON CONFLICT(settlement_id) DO UPDATE SET status=:st,signed_by=:u,signed_at=CURRENT_TIMESTAMP,remarks=:r'''),{'i':str(uuid4()),'s':settlement_id,'st':status,'u':str(u.user_id),'r':body.get('remarks')})
        return {'settlement_id':settlement_id,'status':status,'signed_by':str(u.user_id)}

    @app.get('/v90cj/gst/settlement/{filing_id}/export')
    def export(filing_id:str,request:Request):
        _perm(engine,request,'gst_settlement.view')
        with engine.connect() as c:
            s=c.execute(text('SELECT * FROM gst_settlement_runs WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not s: raise HTTPException(404,'settlement not generated')
            m=[dict(x) for x in c.execute(text('SELECT source_type,source_id,amount,status,notes FROM gst_settlement_matches WHERE settlement_id=:s ORDER BY created_at'),{'s':s['settlement_id']}).mappings().all()]
            so=c.execute(text('SELECT status,signed_by,signed_at,remarks FROM gst_settlement_signoffs WHERE settlement_id=:s'),{'s':s['settlement_id']}).mappings().first()
        return {'format':'GST_SETTLEMENT_PACK_V1','settlement':dict(s),'matches':m,'signoff':dict(so) if so else None}

    @app.get('/ui/gst-settlement')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'gst-settlement.html')
