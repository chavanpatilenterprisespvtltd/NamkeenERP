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
        perms=[('gst_return.view','View GST return operations'),('gst_return.manage','Manage GST return operations'),('gst_return.signoff','Sign off GST return')]
        for pid,name in perms:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':pid,'n':name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_return_sections(
          section_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, section_code TEXT NOT NULL, supply_class TEXT NOT NULL,
          taxable_value NUMERIC NOT NULL DEFAULT 0, tax_value NUMERIC NOT NULL DEFAULT 0, amendment_value NUMERIC NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'DRAFT', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(filing_id,section_code,supply_class))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_tax_payments(
          payment_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, payment_date DATE, challan_no TEXT, amount NUMERIC NOT NULL DEFAULT 0,
          interest NUMERIC NOT NULL DEFAULT 0, penalty NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'DRAFT',
          created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(filing_id,challan_no))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_filing_acknowledgements(
          acknowledgement_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, filing_reference TEXT NOT NULL, acknowledgement_no TEXT,
          filed_at TIMESTAMP, status TEXT NOT NULL DEFAULT 'RECEIVED', notes TEXT, created_by TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(filing_id,filing_reference))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_filing_signoffs(
          signoff_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
          signed_by TEXT, signed_at TIMESTAMP, remarks TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(filing_id))'''))

def register_v90ci_routes(app, engine):
    _ensure(engine)
    @app.get('/v90ci/gst/returns/{filing_id}')
    def summary(filing_id:str, request:Request):
        _perm(engine,request,'gst_return.view')
        with engine.connect() as c:
            f=c.execute(text('SELECT * FROM gst_filing_periods WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not f: raise HTTPException(404,'filing not found')
            sections=[dict(x) for x in c.execute(text('SELECT * FROM gst_return_sections WHERE filing_id=:f ORDER BY section_code,supply_class'),{'f':filing_id}).mappings().all()]
            payments=[dict(x) for x in c.execute(text('SELECT * FROM gst_tax_payments WHERE filing_id=:f ORDER BY payment_date,created_at'),{'f':filing_id}).mappings().all()]
            acks=[dict(x) for x in c.execute(text('SELECT * FROM gst_filing_acknowledgements WHERE filing_id=:f ORDER BY created_at'),{'f':filing_id}).mappings().all()]
            sign=c.execute(text('SELECT * FROM gst_filing_signoffs WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
        return {'filing':dict(f),'sections':sections,'payments':payments,'acknowledgements':acks,'signoff':dict(sign) if sign else None}

    @app.post('/v90ci/gst/returns/{filing_id}/section')
    def section(filing_id:str, request:Request, body:dict):
        u=_perm(engine,request,'gst_return.manage')
        code=body.get('section_code'); supply=body.get('supply_class','OUTWARD')
        if not code: raise HTTPException(400,'section_code is required')
        with engine.begin() as c:
            f=c.execute(text('SELECT status FROM gst_filing_periods WHERE filing_id=:f'),{'f':filing_id}).first()
            if not f: raise HTTPException(404,'filing not found')
            if f[0]=='LOCKED': raise HTTPException(409,'filing period is locked')
            sid=str(uuid4()); vals={'s':sid,'f':filing_id,'c':code,'sc':supply,'v':float(_q(body.get('taxable_value'))),'t':float(_q(body.get('tax_value'))),'a':float(_q(body.get('amendment_value'))),'u':str(u.user_id)}
            c.execute(text('''INSERT INTO gst_return_sections(section_id,filing_id,section_code,supply_class,taxable_value,tax_value,amendment_value,status,created_by)
              VALUES(:s,:f,:c,:sc,:v,:t,:a,'DRAFT',:u) ON CONFLICT(filing_id,section_code,supply_class) DO UPDATE SET taxable_value=:v,tax_value=:t,amendment_value=:a,status='DRAFT',created_by=:u,created_at=CURRENT_TIMESTAMP'''),vals)
        return {'filing_id':filing_id,'section_code':code,'supply_class':supply,'status':'DRAFT','taxable_value':vals['v'],'tax_value':vals['t'],'amendment_value':vals['a']}

    @app.post('/v90ci/gst/returns/{filing_id}/payment')
    def payment(filing_id:str, request:Request, body:dict):
        u=_perm(engine,request,'gst_return.manage'); amount=_q(body.get('amount'))
        if amount<=0: raise HTTPException(400,'amount must be positive')
        with engine.begin() as c:
            f=c.execute(text('SELECT status FROM gst_filing_periods WHERE filing_id=:f'),{'f':filing_id}).first()
            if not f: raise HTTPException(404,'filing not found')
            if f[0]=='LOCKED': raise HTTPException(409,'filing period is locked')
            pid=str(uuid4()); challan=body.get('challan_no')
            c.execute(text('''INSERT INTO gst_tax_payments(payment_id,filing_id,payment_date,challan_no,amount,interest,penalty,status,created_by)
              VALUES(:i,:f,:d,:c,:a,:in,:p,'RECORDED',:u) ON CONFLICT(filing_id,challan_no) DO UPDATE SET payment_date=:d,amount=:a,interest=:in,penalty=:p,status='RECORDED',created_by=:u'''),{'i':pid,'f':filing_id,'d':body.get('payment_date'),'c':challan,'a':float(amount),'in':float(_q(body.get('interest'))),'p':float(_q(body.get('penalty'))),'u':str(u.user_id)})
        return {'filing_id':filing_id,'status':'RECORDED','challan_no':challan,'amount':float(amount)}

    @app.post('/v90ci/gst/returns/{filing_id}/acknowledgement')
    def acknowledgement(filing_id:str, request:Request, body:dict):
        u=_perm(engine,request,'gst_return.manage'); ref=body.get('filing_reference')
        if not ref: raise HTTPException(400,'filing_reference is required')
        with engine.begin() as c:
            if not c.execute(text('SELECT 1 FROM gst_filing_periods WHERE filing_id=:f'),{'f':filing_id}).first(): raise HTTPException(404,'filing not found')
            aid=str(uuid4()); c.execute(text('''INSERT INTO gst_filing_acknowledgements(acknowledgement_id,filing_id,filing_reference,acknowledgement_no,filed_at,status,notes,created_by)
              VALUES(:a,:f,:r,:n,:d,'RECEIVED',:no,:u) ON CONFLICT(filing_id,filing_reference) DO UPDATE SET acknowledgement_no=:n,filed_at=:d,status='RECEIVED',notes=:no,created_by=:u'''),{'a':aid,'f':filing_id,'r':ref,'n':body.get('acknowledgement_no'),'d':body.get('filed_at'),'no':body.get('notes'),'u':str(u.user_id)})
        return {'filing_id':filing_id,'filing_reference':ref,'status':'RECEIVED'}

    @app.post('/v90ci/gst/returns/{filing_id}/signoff')
    def signoff(filing_id:str, request:Request, body:dict):
        u=_perm(engine,request,'gst_return.signoff'); status=body.get('status','SIGNED')
        if status not in {'SIGNED','REJECTED'}: raise HTTPException(400,'status must be SIGNED or REJECTED')
        with engine.begin() as c:
            if not c.execute(text('SELECT 1 FROM gst_filing_periods WHERE filing_id=:f'),{'f':filing_id}).first(): raise HTTPException(404,'filing not found')
            sid=str(uuid4()); c.execute(text('''INSERT INTO gst_filing_signoffs(signoff_id,filing_id,status,signed_by,signed_at,remarks)
              VALUES(:s,:f,:st,:u,CURRENT_TIMESTAMP,:r) ON CONFLICT(filing_id) DO UPDATE SET status=:st,signed_by=:u,signed_at=CURRENT_TIMESTAMP,remarks=:r'''),{'s':sid,'f':filing_id,'st':status,'u':str(u.user_id),'r':body.get('remarks')})
        return {'filing_id':filing_id,'status':status,'signed_by':str(u.user_id)}

    @app.get('/v90ci/gst/returns/{filing_id}/export')
    def export(filing_id:str, request:Request):
        _perm(engine,request,'gst_return.view')
        with engine.connect() as c:
            f=c.execute(text('SELECT * FROM gst_filing_periods WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not f: raise HTTPException(404,'filing not found')
            s=[dict(x) for x in c.execute(text('SELECT section_code,supply_class,taxable_value,tax_value,amendment_value,status FROM gst_return_sections WHERE filing_id=:f ORDER BY section_code,supply_class'),{'f':filing_id}).mappings().all()]
            p=[dict(x) for x in c.execute(text('SELECT payment_date,challan_no,amount,interest,penalty,status FROM gst_tax_payments WHERE filing_id=:f ORDER BY created_at'),{'f':filing_id}).mappings().all()]
            a=[dict(x) for x in c.execute(text('SELECT filing_reference,acknowledgement_no,filed_at,status,notes FROM gst_filing_acknowledgements WHERE filing_id=:f ORDER BY created_at'),{'f':filing_id}).mappings().all()]
            so=c.execute(text('SELECT status,signed_by,signed_at,remarks FROM gst_filing_signoffs WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
        return {'format':'GST_RETURN_OPERATIONS_PACK_V1','filing_id':filing_id,'period_key':f['period_key'],'status':f['status'],'sections':s,'payments':p,'acknowledgements':a,'signoff':dict(so) if so else None}
    @app.get('/ui/gst-return-operations')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'gst-return-operations.html')
