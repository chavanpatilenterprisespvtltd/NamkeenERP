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
    if permission not in p and 'admin.users' not in p: raise HTTPException(403, 'permission denied')
    return u

def _q(v): return Decimal(str(v or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)

def _ensure(engine):
    with engine.begin() as c:
        for pid,name in [('statutory.view','View statutory reports'),('statutory.manage','Manage statutory periods')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p':pid,'n':name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS statutory_report_runs(
            run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
            period_key TEXT NOT NULL, report_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'GENERATED',
            generated_by TEXT NOT NULL, generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,report_type))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS statutory_exceptions(
            exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
            period_key TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
            exception_type TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resolved_at TIMESTAMP, resolved_by TEXT,
            UNIQUE(organization_id,period_key,source_type,source_id,exception_type))'''))

def register_v90ce_routes(app, engine):
    _ensure(engine)

    def period_guard(c, org, period):
        r = c.execute(text('SELECT status FROM tax_reporting_periods WHERE organization_id=:o AND period_key=:p'), {'o':org,'p':period}).mappings().first()
        return r['status'] if r else 'OPEN'

    @app.get('/v90ce/statutory/hsn-summary')
    def hsn_summary(request: Request, organization_id: str, period_key: str, entity_id: str|None=None):
        _perm(engine, request, 'statutory.view')
        q='''SELECT COALESCE(hsn_code,'UNSPECIFIED') hsn_code, COUNT(*) lines,
          SUM(taxable_value) taxable_value,SUM(igst_value) igst,SUM(cgst_value) cgst,
          SUM(sgst_value) sgst,SUM(cess_value) cess,SUM(total_tax) total_tax
          FROM tax_transaction_lines WHERE organization_id=:o AND substr(created_at,1,7)=:p'''
        par={'o':organization_id,'p':period_key}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        q+=' GROUP BY COALESCE(hsn_code,\'UNSPECIFIED\') ORDER BY hsn_code'
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(q),par).mappings().all()]
        for r in rows:
            for k in ('taxable_value','igst','cgst','sgst','cess','total_tax'): r[k]=float(r[k] or 0)
        return {'period_key':period_key,'entity_id':entity_id,'items':rows}

    @app.get('/v90ce/statutory/gst-summary')
    def gst_summary(request: Request, organization_id: str, period_key: str, entity_id: str|None=None):
        _perm(engine, request, 'statutory.view')
        q='''SELECT supply_type, COUNT(*) lines, SUM(taxable_value) taxable_value,
          SUM(igst_value) igst,SUM(cgst_value) cgst,SUM(sgst_value) sgst,SUM(cess_value) cess,SUM(total_tax) total_tax
          FROM tax_transaction_lines WHERE organization_id=:o AND substr(created_at,1,7)=:p'''
        par={'o':organization_id,'p':period_key}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        q+=' GROUP BY supply_type ORDER BY supply_type'
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(q),par).mappings().all()]
        for r in rows:
            r['taxable_value']=float(r['taxable_value'] or 0)
            for k in ('igst','cgst','sgst','cess','total_tax'): r[k]=float(r[k] or 0)
        totals={k:sum(r[k] for r in rows) for k in ('taxable_value','igst','cgst','sgst','cess','total_tax')}
        return {'period_key':period_key,'entity_id':entity_id,'by_supply_type':rows,'totals':totals}

    @app.get('/v90ce/statutory/exceptions')
    def exceptions(request: Request, organization_id: str, period_key: str, entity_id: str|None=None, status: str='OPEN'):
        _perm(engine, request, 'statutory.view')
        q='SELECT * FROM statutory_exceptions WHERE organization_id=:o AND period_key=:p AND status=:s'; par={'o':organization_id,'p':period_key,'s':status}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        q+=' ORDER BY created_at DESC'
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(q),par).mappings().all()]
        return {'items':rows,'count':len(rows)}

    @app.post('/v90ce/statutory/validate')
    def validate(request: Request, body: dict):
        u=_perm(engine, request, 'statutory.manage'); org=body['organization_id']; period=body['period_key']; entity=body.get('entity_id')
        found=[]
        with engine.begin() as c:
            q='SELECT tax_line_id,source_type,source_id,hsn_code,taxable_value,total_tax FROM tax_transaction_lines WHERE organization_id=:o AND substr(created_at,1,7)=:p'; par={'o':org,'p':period}
            if entity: q+=' AND entity_id=:e'; par['e']=entity
            for r in c.execute(text(q),par).mappings().all():
                msg=None; typ=None
                if not r['hsn_code']: typ='MISSING_HSN'; msg='HSN/SAC code is missing'
                elif _q(r['taxable_value']) < 0: typ='NEGATIVE_TAXABLE'; msg='Taxable value is negative'
                elif _q(r['total_tax']) < 0: typ='NEGATIVE_TAX'; msg='Tax amount is negative'
                if typ:
                    eid=str(uuid4())
                    c.execute(text('''INSERT INTO statutory_exceptions(exception_id,organization_id,entity_id,period_key,source_type,source_id,exception_type,message) VALUES(:i,:o,:e,:p,:st,:sid,:t,:m) ON CONFLICT(organization_id,period_key,source_type,source_id,exception_type) DO UPDATE SET message=:m,status='OPEN',resolved_at=NULL,resolved_by=NULL'''), {'i':eid,'o':org,'e':entity,'p':period,'st':r['source_type'],'sid':r['source_id'],'t':typ,'m':msg})
                    found.append({'source_id':r['source_id'],'exception_type':typ,'message':msg})
            c.execute(text('''INSERT INTO statutory_report_runs(run_id,organization_id,entity_id,period_key,report_type,status,generated_by) VALUES(:i,:o,:e,:p,'VALIDATION','GENERATED',:u) ON CONFLICT(organization_id,entity_id,period_key,report_type) DO UPDATE SET status='GENERATED',generated_by=:u,generated_at=CURRENT_TIMESTAMP'''), {'i':str(uuid4()),'o':org,'e':entity,'p':period,'u':str(u.user_id)})
        return {'period_key':period,'exceptions_found':len(found),'exceptions':found}

    @app.post('/v90ce/statutory/periods/{period_key}/close')
    def close_period(period_key: str, body: dict, request: Request):
        u=_perm(engine, request, 'statutory.manage'); org=body['organization_id']
        with engine.begin() as c:
            r=c.execute(text('SELECT status FROM tax_reporting_periods WHERE organization_id=:o AND period_key=:p'),{'o':org,'p':period_key}).mappings().first()
            if not r:
                c.execute(text('INSERT INTO tax_reporting_periods(period_id,organization_id,period_key,start_date,end_date,status) VALUES(:i,:o,:p,:s,:e,\'OPEN\')'),{'i':str(uuid4()),'o':org,'p':period_key,'s':period_key+'-01','e':period_key+'-31'})
            open_count=c.execute(text("SELECT COUNT(*) n FROM statutory_exceptions WHERE organization_id=:o AND period_key=:p AND status='OPEN'"),{'o':org,'p':period_key}).scalar()
            if open_count: raise HTTPException(400,f'{open_count} open statutory exceptions must be resolved before closing')
            c.execute(text("UPDATE tax_reporting_periods SET status='CLOSED' WHERE organization_id=:o AND period_key=:p"),{'o':org,'p':period_key})
        return {'organization_id':org,'period_key':period_key,'status':'CLOSED','closed_by':str(u.user_id)}

    @app.get('/ui/statutory')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'statutory.html')
