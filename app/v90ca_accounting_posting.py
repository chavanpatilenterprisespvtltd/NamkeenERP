from __future__ import annotations
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _perm(engine, request, permission):
    u = authenticate(request)
    p = permissions_for_user(engine, u.user_id)
    if permission not in p and 'admin.users' not in p:
        raise HTTPException(403, 'permission denied')
    return u

def _d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _ensure(engine):
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS accounting_postings (
            posting_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            source_type TEXT NOT NULL, source_id TEXT NOT NULL, posting_date TEXT,
            voucher_no TEXT NOT NULL, voucher_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'POSTED',
            debit_total NUMERIC NOT NULL DEFAULT 0, credit_total NUMERIC NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id, source_type, source_id))"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS accounting_posting_lines (
            line_id TEXT PRIMARY KEY, posting_id TEXT NOT NULL, ledger_code TEXT NOT NULL,
            ledger_name TEXT, debit NUMERIC NOT NULL DEFAULT 0, credit NUMERIC NOT NULL DEFAULT 0,
            tax_component TEXT, narration TEXT)"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS tally_export_documents (
            export_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
            posting_id TEXT NOT NULL, format TEXT NOT NULL DEFAULT 'TALLY_XML',
            payload TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(posting_id, format))"""))

def _map(c, org, entity, key):
    row = c.execute(text("""SELECT ledger_code, ledger_name FROM accounting_ledger_map
        WHERE organization_id=:o AND source_key=:k AND active=1
        AND (entity_id=:e OR entity_id IS NULL)
        ORDER BY CASE WHEN entity_id=:e THEN 0 ELSE 1 END LIMIT 1"""), {'o':org,'e':entity,'k':key}).mappings().first()
    return dict(row) if row else {'ledger_code': key, 'ledger_name': key}

def _post(c, body, user_id):
    org, entity = body.get('organization_id'), body.get('entity_id')
    source_type, source_id = body.get('source_type'), body.get('source_id')
    if not all(str(x or '').strip() for x in (org, entity, source_type, source_id)):
        raise HTTPException(400, 'organization_id, entity_id, source_type and source_id are required')
    if c.execute(text('SELECT 1 FROM accounting_postings WHERE organization_id=:o AND source_type=:s AND source_id=:i'), {'o':org,'s':source_type,'i':source_id}).first():
        raise HTTPException(409, 'source is already posted')
    taxable, tax = _d(body.get('taxable_value')), _d(body.get('tax_value'))
    total = taxable + tax
    inward = str(body.get('supply_type','OUTWARD')).upper() == 'INWARD'
    customer_or_supplier = _map(c,org,entity,'SUPPLIER' if inward else 'CUSTOMER')
    base = _map(c,org,entity,'PURCHASE' if inward else 'SALES')
    igst = _d(body.get('igst_value')); cgst = _d(body.get('cgst_value')); sgst = _d(body.get('sgst_value')); cess = _d(body.get('cess_value'))
    if not tax: tax = igst + cgst + sgst + cess
    total = taxable + tax
    pid, vn = str(uuid4()), str(body.get('voucher_no') or source_id)
    lines=[]
    if inward:
        lines.append((customer_or_supplier['ledger_code'],customer_or_supplier['ledger_name'],total,Decimal('0'),'GROSS','Purchase payable'))
        lines.append((base['ledger_code'],base['ledger_name'],Decimal('0'),taxable,None,'Purchase'))
    else:
        lines.append((customer_or_supplier['ledger_code'],customer_or_supplier['ledger_name'],total,Decimal('0'),'GROSS','Sales receivable'))
        lines.append((base['ledger_code'],base['ledger_name'],Decimal('0'),taxable,None,'Sales'))
    for key,val,comp in [('GST_OUTPUT_IGST',igst,'IGST'),('GST_OUTPUT_CGST',cgst,'CGST'),('GST_OUTPUT_SGST',sgst,'SGST'),('GST_OUTPUT_CESS',cess,'CESS')] if not inward else [('GST_INPUT_IGST',igst,'IGST'),('GST_INPUT_CGST',cgst,'CGST'),('GST_INPUT_SGST',sgst,'SGST'),('GST_INPUT_CESS',cess,'CESS')]:
        if val:
            m=_map(c,org,entity,key)
            if inward: lines.append((m['ledger_code'],m['ledger_name'],val,Decimal('0'),comp,'Input tax'))
            else: lines.append((m['ledger_code'],m['ledger_name'],Decimal('0'),val,comp,'Output tax'))
    # Normalize direction for inward: supplier credit, purchase debit, tax debit.
    if inward:
        lines=[]
        lines.append((base['ledger_code'],base['ledger_name'],taxable,Decimal('0'),None,'Purchase'))
        for key,val,comp in [('GST_INPUT_IGST',igst,'IGST'),('GST_INPUT_CGST',cgst,'CGST'),('GST_INPUT_SGST',sgst,'SGST'),('GST_INPUT_CESS',cess,'CESS')]:
            if val:
                m=_map(c,org,entity,key); lines.append((m['ledger_code'],m['ledger_name'],val,Decimal('0'),comp,'Input tax'))
        lines.append((customer_or_supplier['ledger_code'],customer_or_supplier['ledger_name'],Decimal('0'),total,'GROSS','Supplier payable'))
    debit=sum(x[2] for x in lines); credit=sum(x[3] for x in lines)
    if debit != credit: raise HTTPException(400, 'posting is not balanced')
    c.execute(text("""INSERT INTO accounting_postings(posting_id,organization_id,entity_id,source_type,source_id,posting_date,voucher_no,voucher_type,status,debit_total,credit_total,created_by)
        VALUES(:p,:o,:e,:s,:i,:d,:v,:t,'POSTED',:dr,:cr,:u)"""), {'p':pid,'o':org,'e':entity,'s':source_type,'i':source_id,'d':body.get('posting_date'),'v':vn,'t':'PURCHASE' if inward else 'SALES','dr':float(debit),'cr':float(credit),'u':str(user_id)})
    for code,name,dr,cr,comp,narr in lines:
        c.execute(text("""INSERT INTO accounting_posting_lines(line_id,posting_id,ledger_code,ledger_name,debit,credit,tax_component,narration) VALUES(:i,:p,:c,:n,:d,:cr,:tc,:na)"""), {'i':str(uuid4()),'p':pid,'c':code,'n':name,'d':float(dr),'cr':float(cr),'tc':comp,'na':narr})
    return pid

def _tally_xml(c, posting_id):
    p=c.execute(text('SELECT * FROM accounting_postings WHERE posting_id=:p'),{'p':posting_id}).mappings().first()
    if not p: raise HTTPException(404,'posting not found')
    ls=c.execute(text('SELECT * FROM accounting_posting_lines WHERE posting_id=:p ORDER BY line_id'),{'p':posting_id}).mappings().all()
    entries=[]
    for l in ls:
        entries.append(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(str(l['ledger_name'] or l['ledger_code']))}</LEDGERNAME><ISDEEMEDPOSITIVE>{'Yes' if float(l['credit'] or 0)>0 else 'No'}</ISDEEMEDPOSITIVE><AMOUNT>{-float(l['credit'] or 0) if float(l['credit'] or 0)>0 else float(l['debit'] or 0):.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>")
    return f"<ENVELOPE><BODY><IMPORTDATA><REQUESTDATA><TALLYMESSAGE><VOUCHER VCHTYPE=\"{escape(p['voucher_type'])}\" ACTION=\"Create\"><DATE>{escape(str(p['posting_date'] or ''))}</DATE><VOUCHERNUMBER>{escape(str(p['voucher_no']))}</VOUCHERNUMBER><NARRATION>{escape(str(p['source_type']))} {escape(str(p['source_id']))}</NARRATION>{''.join(entries)}</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"

def register_v90ca_routes(app, engine):
    _ensure(engine)
    @app.post('/v90ca/accounting/post')
    def post(body:dict, request:Request):
        u=_perm(engine,request,'accounting.manage')
        with engine.begin() as c: pid=_post(c,body,u.user_id)
        return {'posting_id':pid,'status':'POSTED'}
    @app.post('/v90ca/accounting/post/sales-invoice/{invoice_id}')
    def post_sales(invoice_id:str, request:Request):
        u=_perm(engine,request,'accounting.manage')
        with engine.begin() as c:
            r=c.execute(text('SELECT * FROM sales_invoices WHERE invoice_id=:i'),{'i':invoice_id}).mappings().first()
            if not r: raise HTTPException(404,'sales invoice not found')
            pid=_post(c,{'organization_id':r['organization_id'],'entity_id':r['entity_id'],'source_type':'SALES_INVOICE','source_id':invoice_id,'voucher_no':r['invoice_no'],'posting_date':str(r['created_at'] or '')[:10],'taxable_value':r['taxable_value'],'tax_value':r['gst_total']},u.user_id)
        return {'posting_id':pid,'invoice_id':invoice_id,'status':'POSTED'}
    @app.post('/v90ca/accounting/post/tax/{tax_line_id}')
    def post_tax(tax_line_id:str, request:Request):
        u=_perm(engine,request,'accounting.manage')
        with engine.begin() as c:
            r=c.execute(text('SELECT * FROM tax_transaction_lines WHERE tax_line_id=:i'),{'i':tax_line_id}).mappings().first()
            if not r: raise HTTPException(404,'tax transaction not found')
            pid=_post(c,{'organization_id':r['organization_id'],'entity_id':r['entity_id'],'source_type':r['source_type'],'source_id':r['source_id'],'taxable_value':r['taxable_value'],'tax_value':r['total_tax'],'igst_value':r['igst_value'],'cgst_value':r['cgst_value'],'sgst_value':r['sgst_value'],'cess_value':r['cess_value'],'supply_type':r['supply_type']},u.user_id)
        return {'posting_id':pid,'tax_line_id':tax_line_id,'status':'POSTED'}
    @app.get('/v90ca/accounting/postings')
    def postings(request:Request, organization_id:str, entity_id:str|None=None):
        _perm(engine,request,'accounting.view')
        q='SELECT * FROM accounting_postings WHERE organization_id=:o'; p={'o':organization_id}
        if entity_id:q+=' AND entity_id=:e';p['e']=entity_id
        with engine.connect() as c:return {'items':[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]}
    @app.post('/v90ca/tally/{posting_id}/export')
    def tally(posting_id:str, request:Request):
        _perm(engine,request,'accounting.export')
        with engine.begin() as c:
            p=c.execute(text('SELECT * FROM accounting_postings WHERE posting_id=:p'),{'p':posting_id}).mappings().first()
            if not p: raise HTTPException(404,'posting not found')
            old=c.execute(text('SELECT export_id,payload FROM tally_export_documents WHERE posting_id=:p AND format=\'TALLY_XML\''),{'p':posting_id}).mappings().first()
            if old:return {'export_id':old['export_id'],'format':'TALLY_XML','payload':old['payload'],'idempotent':True}
            payload=_tally_xml(c,posting_id); eid=str(uuid4())
            c.execute(text("INSERT INTO tally_export_documents(export_id,organization_id,entity_id,posting_id,format,payload) VALUES(:i,:o,:e,:p,'TALLY_XML',:x)"),{'i':eid,'o':p['organization_id'],'e':p['entity_id'],'p':posting_id,'x':payload})
            return {'export_id':eid,'format':'TALLY_XML','payload':payload,'idempotent':False}
    @app.get('/ui/accounting-posting')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'accounting-posting.html')
