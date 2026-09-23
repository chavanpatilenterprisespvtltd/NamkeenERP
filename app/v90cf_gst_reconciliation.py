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
    u = authenticate(request); p = permissions_for_user(engine, u.user_id)
    if permission not in p and 'admin.users' not in p:
        raise HTTPException(403, 'permission denied')
    return u

def _q(v): return Decimal(str(v or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)

def _ensure(engine):
    with engine.begin() as c:
        for pid,name in [('gst_recon.view','View GST reconciliation'),('gst_recon.manage','Manage GST reconciliation'),('gst_recon.export','Export GST statutory pack')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p':pid,'n':name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_reconciliation_runs(
            run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
            period_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'GENERATED',
            outward_tax NUMERIC NOT NULL DEFAULT 0, inward_tax NUMERIC NOT NULL DEFAULT 0,
            ledger_tax NUMERIC NOT NULL DEFAULT 0, variance NUMERIC NOT NULL DEFAULT 0,
            generated_by TEXT NOT NULL, generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_reconciliation_exceptions(
            exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
            period_key TEXT NOT NULL, exception_type TEXT NOT NULL, expected_value NUMERIC NOT NULL DEFAULT 0,
            actual_value NUMERIC NOT NULL DEFAULT 0, variance NUMERIC NOT NULL DEFAULT 0,
            message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resolved_at TIMESTAMP, resolved_by TEXT,
            UNIQUE(organization_id,entity_id,period_key,exception_type))'''))

def register_v90cf_routes(app, engine):
    _ensure(engine)

    def sums(c, org, period, entity):
        par={'o':org,'p':period}; ef=''
        if entity: ef=' AND entity_id=:e'; par['e']=entity
        q=f'''SELECT COALESCE(SUM(igst_value),0) igst,COALESCE(SUM(cgst_value),0) cgst,
            COALESCE(SUM(sgst_value),0) sgst,COALESCE(SUM(cess_value),0) cess,
            COALESCE(SUM(total_tax),0) total_tax,COALESCE(SUM(taxable_value),0) taxable_value
            FROM tax_transaction_lines WHERE organization_id=:o AND substr(created_at,1,7)=:p{ef}'''
        return dict(c.execute(text(q),par).mappings().one())

    @app.get('/v90cf/gst/reconciliation')
    def reconciliation(request: Request, organization_id: str, period_key: str, entity_id: str|None=None):
        _perm(engine, request, 'gst_recon.view')
        with engine.connect() as c:
            outward=sums(c,organization_id,period_key,entity_id)
            par={'o':organization_id,'p':period_key}; ef=''
            if entity_id: ef=' AND entity_id=:e'; par['e']=entity_id
            # Accounting GST ledgers are identified by configurable ledger names/codes; use posted tax entries.
            try:
                ledger=float(c.execute(text(f"SELECT COALESCE(SUM(debit-credit),0) FROM accounting_posting_lines WHERE organization_id=:o AND substr(created_at,1,7)=:p{ef} AND account_code IN ('CGST_OUTPUT','SGST_OUTPUT','IGST_OUTPUT','CESS_OUTPUT','CGST_INPUT','SGST_INPUT','IGST_INPUT','CESS_INPUT')"),par).scalar() or 0)
            except Exception:
                ledger=0.0
            out=float(outward['total_tax'] or 0)
            return {'organization_id':organization_id,'entity_id':entity_id,'period_key':period_key,'tax':{k:float(v or 0) for k,v in outward.items()},'ledger_tax':round(ledger,2),'variance':round(out-ledger,2),'status':'MATCHED' if _q(out-ledger)==0 else 'MISMATCH'}

    @app.post('/v90cf/gst/reconciliation/run')
    def run_reconciliation(request: Request, body: dict):
        u=_perm(engine,request,'gst_recon.manage'); org=body['organization_id']; period=body['period_key']; entity=body.get('entity_id')
        with engine.begin() as c:
            tx=sums(c,org,period,entity); total=_q(tx['total_tax'])
            par={'o':org,'p':period}; ef=''
            if entity: ef=' AND entity_id=:e'; par['e']=entity
            try: ledger=_q(c.execute(text(f"SELECT COALESCE(SUM(debit-credit),0) FROM accounting_posting_lines WHERE organization_id=:o AND substr(created_at,1,7)=:p{ef} AND account_code IN ('CGST_OUTPUT','SGST_OUTPUT','IGST_OUTPUT','CESS_OUTPUT','CGST_INPUT','SGST_INPUT','IGST_INPUT','CESS_INPUT')"),par).scalar())
            except Exception: ledger=Decimal('0.00')
            variance=_q(total-ledger); status='MATCHED' if variance==0 else 'MISMATCH'
            c.execute(text('''INSERT INTO gst_reconciliation_runs(run_id,organization_id,entity_id,period_key,status,outward_tax,ledger_tax,variance,generated_by) VALUES(:i,:o,:e,:p,:s,:t,:l,:v,:u)
              ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status=:s,outward_tax=:t,ledger_tax=:l,variance=:v,generated_by=:u,generated_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':org,'e':entity,'p':period,'s':status,'t':float(total),'l':float(ledger),'v':float(variance),'u':str(u.user_id)})
            if variance != 0:
                c.execute(text('''INSERT INTO gst_reconciliation_exceptions(exception_id,organization_id,entity_id,period_key,exception_type,expected_value,actual_value,variance,message)
                VALUES(:i,:o,:e,:p,'TAX_LEDGER_VARIANCE',:x,:a,:v,:m)
                ON CONFLICT(organization_id,entity_id,period_key,exception_type) DO UPDATE SET expected_value=:x,actual_value=:a,variance=:v,message=:m,status='OPEN',resolved_at=NULL,resolved_by=NULL'''),{'i':str(uuid4()),'o':org,'e':entity,'p':period,'x':float(total),'a':float(ledger),'v':float(variance),'m':f'GST tax versus ledger variance is {variance}'})
        return {'period_key':period,'status':status,'tax_total':float(total),'ledger_tax':float(ledger),'variance':float(variance)}

    @app.get('/v90cf/gst/exceptions')
    def exceptions(request: Request, organization_id: str, period_key: str, entity_id: str|None=None, status: str='OPEN'):
        _perm(engine,request,'gst_recon.view'); par={'o':organization_id,'p':period_key,'s':status}; ef=''
        if entity_id: ef=' AND entity_id=:e'; par['e']=entity_id
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(f'SELECT * FROM gst_reconciliation_exceptions WHERE organization_id=:o AND period_key=:p AND status=:s{ef} ORDER BY created_at DESC'),par).mappings().all()]
        return {'items':rows,'count':len(rows)}

    @app.post('/v90cf/gst/exceptions/{exception_id}/resolve')
    def resolve(exception_id: str, request: Request, body: dict):
        u=_perm(engine,request,'gst_recon.manage')
        with engine.begin() as c:
            r=c.execute(text("UPDATE gst_reconciliation_exceptions SET status='RESOLVED',resolved_at=CURRENT_TIMESTAMP,resolved_by=:u WHERE exception_id=:i AND status='OPEN' RETURNING exception_id"),{'u':str(u.user_id),'i':exception_id}).first()
            if not r: raise HTTPException(404,'open exception not found')
        return {'exception_id':exception_id,'status':'RESOLVED','resolved_by':str(u.user_id)}

    @app.get('/v90cf/gst/export')
    def export_pack(request: Request, organization_id: str, period_key: str, entity_id: str|None=None):
        _perm(engine,request,'gst_recon.export')
        with engine.connect() as c:
            par={'o':organization_id,'p':period_key}; ef=''
            if entity_id: ef=' AND entity_id=:e'; par['e']=entity_id
            rows=[dict(r) for r in c.execute(text(f'''SELECT COALESCE(hsn_code,'UNSPECIFIED') hsn_code,COALESCE(supply_type,'OUTWARD') supply_type,
              SUM(taxable_value) taxable_value,SUM(igst_value) igst,SUM(cgst_value) cgst,SUM(sgst_value) sgst,SUM(cess_value) cess,SUM(total_tax) total_tax
              FROM tax_transaction_lines WHERE organization_id=:o AND substr(created_at,1,7)=:p{ef} GROUP BY COALESCE(hsn_code,'UNSPECIFIED'),COALESCE(supply_type,'OUTWARD') ORDER BY hsn_code,supply_type'''),par).mappings().all()]
        return {'format':'GST_STATUTORY_PACK_V1','organization_id':organization_id,'entity_id':entity_id,'period_key':period_key,'rows':[dict(r) for r in rows]}

    @app.get('/ui/gst-reconciliation')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'gst-reconciliation.html')
