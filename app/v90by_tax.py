from __future__ import annotations
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException, Request
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _perm(engine, request: Request, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id) and 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    return user

def _q(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _ensure_tax_schema(engine):
    statements = [
        """CREATE TABLE IF NOT EXISTS hsn_tax_master (hsn_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, hsn_code TEXT NOT NULL, description TEXT, goods_or_service TEXT NOT NULL DEFAULT 'GOODS', effective_from TEXT, effective_to TEXT, active INTEGER NOT NULL DEFAULT 1, UNIQUE(organization_id, hsn_code))""",
        """CREATE TABLE IF NOT EXISTS tax_rate_master (tax_rate_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, hsn_id TEXT, tax_name TEXT NOT NULL DEFAULT 'GST', gst_rate NUMERIC NOT NULL DEFAULT 0, igst_rate NUMERIC NOT NULL DEFAULT 0, cgst_rate NUMERIC NOT NULL DEFAULT 0, sgst_rate NUMERIC NOT NULL DEFAULT 0, cess_rate NUMERIC NOT NULL DEFAULT 0, intra_state INTEGER NOT NULL DEFAULT 1, effective_from TEXT, effective_to TEXT, active INTEGER NOT NULL DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS tax_transaction_lines (tax_line_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL, source_line_id TEXT, hsn_code TEXT, taxable_value NUMERIC NOT NULL DEFAULT 0, gst_rate NUMERIC NOT NULL DEFAULT 0, igst_value NUMERIC NOT NULL DEFAULT 0, cgst_value NUMERIC NOT NULL DEFAULT 0, sgst_value NUMERIC NOT NULL DEFAULT 0, cess_value NUMERIC NOT NULL DEFAULT 0, total_tax NUMERIC NOT NULL DEFAULT 0, place_of_supply TEXT, supply_type TEXT NOT NULL DEFAULT 'OUTWARD', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS tax_reporting_periods (period_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', UNIQUE(organization_id, period_key))"""
    ]
    with engine.begin() as c:
        for stmt in statements: c.execute(text(stmt))

def register_v90by_routes(app, engine):
    _ensure_tax_schema(engine)
    @app.get('/v90by/tax/summary')
    def tax_summary(request: Request, organization_id: str, entity_id: str|None=None, period_key: str|None=None):
        _perm(engine, request, 'tax.view')
        q='''SELECT COUNT(*) lines, COALESCE(SUM(taxable_value),0) taxable_value,
             COALESCE(SUM(igst_value),0) igst, COALESCE(SUM(cgst_value),0) cgst,
             COALESCE(SUM(sgst_value),0) sgst, COALESCE(SUM(cess_value),0) cess,
             COALESCE(SUM(total_tax),0) total_tax
             FROM tax_transaction_lines WHERE organization_id=:o'''
        p={'o':organization_id}
        if entity_id: q+=' AND entity_id=:e'; p['e']=entity_id
        if period_key:
            q+=' AND substr(created_at,1,7)=:pk'; p['pk']=period_key
        try:
            with engine.connect() as c: row=c.execute(text(q),p).mappings().one()
            return {'period_key':period_key,'lines':int(row['lines'] or 0),**{k:float(row[k] or 0) for k in ('taxable_value','igst','cgst','sgst','cess','total_tax')}}
        except Exception:
            return {'period_key':period_key,'lines':0,'taxable_value':0,'igst':0,'cgst':0,'sgst':0,'cess':0,'total_tax':0}

    @app.get('/v90by/hsn')
    def list_hsn(request: Request, organization_id: str, active_only: bool=True):
        _perm(engine, request, 'tax.view')
        q='SELECT * FROM hsn_tax_master WHERE organization_id=:o'; p={'o':organization_id}
        if active_only: q+=' AND active=1'
        q+=' ORDER BY hsn_code'
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(q),p).mappings().all()]
        return {'items':rows}

    @app.post('/v90by/hsn')
    def create_hsn(body: dict, request: Request):
        _perm(engine, request, 'tax.manage')
        required=('organization_id','hsn_code')
        if any(not str(body.get(k) or '').strip() for k in required): raise HTTPException(400,'organization_id and hsn_code are required')
        hid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hsn_tax_master(hsn_id,organization_id,hsn_code,description,goods_or_service,effective_from,effective_to,active)
                VALUES(:i,:o,:h,:d,:g,:f,:t,:a)'''),{'i':hid,'o':body['organization_id'],'h':str(body['hsn_code']).strip(),'d':body.get('description'),'g':body.get('goods_or_service','GOODS'),'f':body.get('effective_from'),'t':body.get('effective_to'),'a':1 if body.get('active',True) else 0})
        return {'hsn_id':hid}

    @app.get('/v90by/tax-rates')
    def list_rates(request: Request, organization_id: str, hsn_id: str|None=None):
        _perm(engine, request, 'tax.view')
        q='SELECT * FROM tax_rate_master WHERE organization_id=:o AND active=1'; p={'o':organization_id}
        if hsn_id: q+=' AND hsn_id=:h'; p['h']=hsn_id
        q+=' ORDER BY effective_from DESC'
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(q),p).mappings().all()]
        return {'items':rows}

    @app.post('/v90by/tax-rates')
    def create_rate(body: dict, request: Request):
        _perm(engine, request, 'tax.manage')
        try: rate=_q(body.get('gst_rate'))
        except Exception: raise HTTPException(400,'invalid gst_rate')
        if rate<0 or rate>100: raise HTTPException(400,'gst_rate must be between 0 and 100')
        rid=str(uuid4()); intra=bool(body.get('intra_state',True))
        if intra:
            ig=Decimal('0'); cg=rate/2; sg=rate/2
        else: ig=rate; cg=Decimal('0'); sg=Decimal('0')
        with engine.begin() as c:
            c.execute(text('''INSERT INTO tax_rate_master(tax_rate_id,organization_id,hsn_id,tax_name,gst_rate,igst_rate,cgst_rate,sgst_rate,cess_rate,intra_state,effective_from,effective_to,active)
                VALUES(:i,:o,:h,:n,:r,:ig,:cg,:sg,:ce,:intra,:f,:t,:a)'''),{'i':rid,'o':body['organization_id'],'h':body.get('hsn_id'),'n':body.get('tax_name','GST'),'r':float(rate),'ig':float(ig),'cg':float(cg),'sg':float(sg),'ce':float(_q(body.get('cess_rate'))),'intra':1 if intra else 0,'f':body.get('effective_from'),'t':body.get('effective_to'),'a':1})
        return {'tax_rate_id':rid,'gst_rate':float(rate),'igst_rate':float(ig),'cgst_rate':float(cg),'sgst_rate':float(sg)}

    @app.post('/v90by/tax/calculate')
    def calculate_tax(body: dict, request: Request):
        _perm(engine, request, 'tax.view')
        taxable=_q(body.get('taxable_value')); rate=_q(body.get('gst_rate')); cess_rate=_q(body.get('cess_rate'))
        intra=bool(body.get('intra_state',True))
        gst=taxable*rate/Decimal('100'); cess=taxable*cess_rate/Decimal('100')
        igst=Decimal('0') if intra else gst; cgst=gst/2 if intra else Decimal('0'); sgst=gst/2 if intra else Decimal('0')
        return {'taxable_value':float(taxable),'gst_rate':float(rate),'igst':float(igst),'cgst':float(cgst),'sgst':float(sgst),'cess':float(cess),'total_tax':float(gst+cess),'invoice_total':float(taxable+gst+cess)}

    @app.post('/v90by/tax/transactions')
    def record_tax(body: dict, request: Request):
        user=_perm(engine, request, 'tax.manage')
        calc=calculate_tax(body, request)
        tid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO tax_transaction_lines(tax_line_id,organization_id,entity_id,source_type,source_id,source_line_id,hsn_code,taxable_value,gst_rate,igst_value,cgst_value,sgst_value,cess_value,total_tax,place_of_supply,supply_type)
                VALUES(:i,:o,:e,:st,:sid,:sl,:hsn,:tv,:gr,:ig,:cg,:sg,:ce,:tt,:pos,:sup)'''),{'i':tid,'o':body['organization_id'],'e':body['entity_id'],'st':body.get('source_type','MANUAL'),'sid':body.get('source_id',tid),'sl':body.get('source_line_id'),'hsn':body.get('hsn_code'),'tv':calc['taxable_value'],'gr':calc['gst_rate'],'ig':calc['igst'],'cg':calc['cgst'],'sg':calc['sgst'],'ce':calc['cess'],'tt':calc['total_tax'],'pos':body.get('place_of_supply'),'sup':body.get('supply_type','OUTWARD')})
        return {'tax_line_id':tid, **calc, 'recorded_by':str(user.user_id)}

    @app.get('/ui/tax')
    def tax_page():
        from fastapi.responses import FileResponse
        from pathlib import Path
        return FileResponse(Path(__file__).resolve().parents[1]/'web'/'tax.html')
