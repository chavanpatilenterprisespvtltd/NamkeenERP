from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
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

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _ensure(engine):
    with engine.begin() as c:
        for pid,name in [("asset.view","View fixed assets"),("asset.manage","Manage fixed assets"),("loan.view","View loans"),("loan.manage","Manage loans")]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p":pid,"n":name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS fixed_assets(asset_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,asset_code TEXT NOT NULL,asset_name TEXT NOT NULL,category TEXT,location_id TEXT,acquisition_date TEXT NOT NULL,acquisition_cost NUMERIC NOT NULL,capitalized_cost NUMERIC NOT NULL DEFAULT 0,useful_life_months INTEGER NOT NULL, depreciation_method TEXT NOT NULL DEFAULT 'STRAIGHT_LINE',residual_value NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'ACTIVE',disposed_date TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,asset_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS asset_depreciation(asset_depreciation_id TEXT PRIMARY KEY,asset_id TEXT NOT NULL,period_key TEXT NOT NULL,depreciation_amount NUMERIC NOT NULL,accumulated_depreciation NUMERIC NOT NULL,net_book_value NUMERIC NOT NULL,posted INTEGER NOT NULL DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(asset_id,period_key))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS asset_disposals(disposal_id TEXT PRIMARY KEY,asset_id TEXT NOT NULL,disposal_date TEXT NOT NULL,proceeds NUMERIC NOT NULL DEFAULT 0,book_value NUMERIC NOT NULL,gain_loss NUMERIC NOT NULL,reason TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS loans(loan_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,loan_code TEXT NOT NULL,lender_name TEXT NOT NULL,principal NUMERIC NOT NULL,interest_rate NUMERIC NOT NULL DEFAULT 0,tenure_months INTEGER NOT NULL,start_date TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ACTIVE',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,loan_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS loan_schedule(schedule_id TEXT PRIMARY KEY,loan_id TEXT NOT NULL,installment_no INTEGER NOT NULL,due_date TEXT NOT NULL,principal_due NUMERIC NOT NULL,interest_due NUMERIC NOT NULL,total_due NUMERIC NOT NULL,paid_amount NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'DUE',UNIQUE(loan_id,installment_no))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS loan_payments(payment_id TEXT PRIMARY KEY,loan_id TEXT NOT NULL,installment_no INTEGER NOT NULL,payment_date TEXT NOT NULL,amount NUMERIC NOT NULL,reference TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

def register_v90cc_routes(app,engine):
    _ensure(engine)
    @app.post('/v90cc/assets')
    def create_asset(body:dict,request:Request):
        u=_perm(engine,request,'asset.manage')
        req=['organization_id','entity_id','asset_code','asset_name','acquisition_date','acquisition_cost','useful_life_months']
        if any(not str(body.get(k) or '').strip() for k in req): raise HTTPException(400,'required asset fields missing')
        aid=str(uuid4()); cost=_d(body['acquisition_cost'])
        with engine.begin() as c:c.execute(text('INSERT INTO fixed_assets(asset_id,organization_id,entity_id,asset_code,asset_name,category,location_id,acquisition_date,acquisition_cost,capitalized_cost,useful_life_months,depreciation_method,residual_value,created_by) VALUES(:i,:o,:e,:c,:n,:cat,:l,:d,:a,:cap,:life,:m,:r,:u)'),{'i':aid,'o':body['organization_id'],'e':body['entity_id'],'c':body['asset_code'],'n':body['asset_name'],'cat':body.get('category'),'l':body.get('location_id'),'d':body['acquisition_date'],'a':float(cost),'cap':float(_d(body.get('capitalized_cost') or cost)),'life':int(body['useful_life_months']),'m':body.get('depreciation_method','STRAIGHT_LINE'),'r':float(_d(body.get('residual_value'))),'u':str(u.user_id)})
        return {'asset_id':aid,'status':'ACTIVE'}
    @app.get('/v90cc/assets')
    def assets(request:Request,organization_id:str,entity_id:str|None=None):
        _perm(engine,request,'asset.view'); q='SELECT * FROM fixed_assets WHERE organization_id=:o';p={'o':organization_id}
        if entity_id:q+=' AND entity_id=:e';p['e']=entity_id
        q+=' ORDER BY asset_code'
        with engine.connect() as c:return {'items':[dict(x) for x in c.execute(text(q),p).mappings().all()]}
    @app.post('/v90cc/assets/{asset_id}/depreciate')
    def depreciate(asset_id:str,body:dict,request:Request):
        u=_perm(engine,request,'asset.manage'); pk=str(body.get('period_key') or '').strip()
        if not pk: raise HTTPException(400,'period_key is required')
        with engine.begin() as c:
            a=c.execute(text('SELECT * FROM fixed_assets WHERE asset_id=:i'),{'i':asset_id}).mappings().first()
            if not a: raise HTTPException(404,'asset not found')
            if a['status']!='ACTIVE': raise HTTPException(409,'asset is not active')
            base=max(_d(a['capitalized_cost'])-_d(a['residual_value']),Decimal('0')); dep=(base/Decimal(a['useful_life_months'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            prev=c.execute(text('SELECT COALESCE(MAX(accumulated_depreciation),0) v FROM asset_depreciation WHERE asset_id=:i'),{'i':asset_id}).scalar() or 0
            accum=min(_d(prev)+dep,base); actual=accum-_d(prev); nbv=_d(a['capitalized_cost'])-accum
            try:c.execute(text('INSERT INTO asset_depreciation(asset_depreciation_id,asset_id,period_key,depreciation_amount,accumulated_depreciation,net_book_value,posted) VALUES(:i,:a,:p,:d,:ac,:n,0)'),{'i':str(uuid4()),'a':asset_id,'p':pk,'d':float(actual),'ac':float(accum),'n':float(nbv)})
            except Exception: raise HTTPException(409,'depreciation already recorded for period')
        return {'asset_id':asset_id,'period_key':pk,'depreciation':float(actual),'accumulated_depreciation':float(accum),'net_book_value':float(nbv),'created_by':str(u.user_id)}
    @app.post('/v90cc/assets/{asset_id}/dispose')
    def dispose(asset_id:str,body:dict,request:Request):
        u=_perm(engine,request,'asset.manage')
        with engine.begin() as c:
            a=c.execute(text('SELECT * FROM fixed_assets WHERE asset_id=:i'),{'i':asset_id}).mappings().first()
            if not a: raise HTTPException(404,'asset not found')
            if a['status']!='ACTIVE': raise HTTPException(409,'asset is not active')
            accum=_d(c.execute(text('SELECT COALESCE(MAX(accumulated_depreciation),0) FROM asset_depreciation WHERE asset_id=:i'),{'i':asset_id}).scalar()); bv=_d(a['capitalized_cost'])-accum; proceeds=_d(body.get('proceeds')); did=str(uuid4())
            c.execute(text('INSERT INTO asset_disposals(disposal_id,asset_id,disposal_date,proceeds,book_value,gain_loss,reason,created_by) VALUES(:i,:a,:d,:p,:b,:g,:r,:u)'),{'i':did,'a':asset_id,'d':body.get('disposal_date'),'p':float(proceeds),'b':float(bv),'g':float(proceeds-bv),'r':body.get('reason'),'u':str(u.user_id)})
            c.execute(text("UPDATE fixed_assets SET status='DISPOSED',disposed_date=:d WHERE asset_id=:i"),{'d':body.get('disposal_date'),'i':asset_id})
        return {'disposal_id':did,'book_value':float(bv),'gain_loss':float(proceeds-bv)}
    @app.post('/v90cc/loans')
    def create_loan(body:dict,request:Request):
        u=_perm(engine,request,'loan.manage'); req=['organization_id','entity_id','loan_code','lender_name','principal','tenure_months','start_date']
        if any(not str(body.get(k) or '').strip() for k in req): raise HTTPException(400,'required loan fields missing')
        lid=str(uuid4()); principal=_d(body['principal']); rate=_d(body.get('interest_rate')); n=int(body['tenure_months']); monthly_rate=rate/Decimal('1200')
        if monthly_rate: payment=(principal*monthly_rate*(1+monthly_rate)**n/((1+monthly_rate)**n-1)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        else: payment=(principal/Decimal(n)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        with engine.begin() as c:
            c.execute(text('INSERT INTO loans(loan_id,organization_id,entity_id,loan_code,lender_name,principal,interest_rate,tenure_months,start_date,created_by) VALUES(:i,:o,:e,:c,:l,:p,:r,:n,:d,:u)'),{'i':lid,'o':body['organization_id'],'e':body['entity_id'],'c':body['loan_code'],'l':body['lender_name'],'p':float(principal),'r':float(rate),'n':n,'d':body['start_date'],'u':str(u.user_id)})
            bal=principal
            from datetime import date
            y,m,*_=map(int,str(body['start_date'])[:10].split('-'))
            for i in range(1,n+1):
                m+=1
                if m>12:y+=1;m=1
                due=f'{y:04d}-{m:02d}-01'; interest=(bal*monthly_rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP); pd=payment-interest
                if i==n: pd=bal; payment_i=pd+interest
                else: payment_i=payment
                bal=max(bal-pd,Decimal('0'))
                c.execute(text('INSERT INTO loan_schedule(schedule_id,loan_id,installment_no,due_date,principal_due,interest_due,total_due) VALUES(:i,:l,:n,:d,:p,:r,:t)'),{'i':str(uuid4()),'l':lid,'n':i,'d':due,'p':float(pd),'r':float(interest),'t':float(payment_i)})
        return {'loan_id':lid,'monthly_payment':float(payment),'installments':n}
    @app.get('/v90cc/loans')
    def loans(request:Request,organization_id:str):
        _perm(engine,request,'loan.view')
        with engine.connect() as c:return {'items':[dict(x) for x in c.execute(text('SELECT * FROM loans WHERE organization_id=:o ORDER BY loan_code'),{'o':organization_id}).mappings().all()]}
    @app.get('/v90cc/loans/{loan_id}/schedule')
    def schedule(loan_id:str,request:Request):
        _perm(engine,request,'loan.view')
        with engine.connect() as c:return {'items':[dict(x) for x in c.execute(text('SELECT * FROM loan_schedule WHERE loan_id=:i ORDER BY installment_no'),{'i':loan_id}).mappings().all()]}
    @app.post('/v90cc/loans/{loan_id}/payments')
    def payment(loan_id:str,body:dict,request:Request):
        u=_perm(engine,request,'loan.manage'); amt=_d(body.get('amount')); inst=int(body.get('installment_no') or 0)
        with engine.begin() as c:
            s=c.execute(text('SELECT * FROM loan_schedule WHERE loan_id=:l AND installment_no=:n'),{'l':loan_id,'n':inst}).mappings().first()
            if not s: raise HTTPException(404,'installment not found')
            outstanding=_d(s['total_due'])-_d(s['paid_amount'])
            if amt<=0 or amt>outstanding: raise HTTPException(400,'invalid payment amount')
            c.execute(text('INSERT INTO loan_payments(payment_id,loan_id,installment_no,payment_date,amount,reference,created_by) VALUES(:i,:l,:n,:d,:a,:r,:u)'),{'i':str(uuid4()),'l':loan_id,'n':inst,'d':body.get('payment_date'),'a':float(amt),'r':body.get('reference'),'u':str(u.user_id)})
            new=_d(s['paid_amount'])+amt; status='PAID' if new>=_d(s['total_due']) else 'PARTIAL'
            c.execute(text('UPDATE loan_schedule SET paid_amount=:a,status=:s WHERE loan_id=:l AND installment_no=:n'),{'a':float(new),'s':status,'l':loan_id,'n':inst})
        return {'loan_id':loan_id,'installment_no':inst,'paid_amount':float(new),'status':status}
    @app.get('/v90cc/summary')
    def summary(request:Request,organization_id:str):
        _perm(engine,request,'asset.view')
        with engine.connect() as c:
            a=c.execute(text("SELECT COUNT(*) count,COALESCE(SUM(capitalized_cost),0) cost FROM fixed_assets WHERE organization_id=:o AND status='ACTIVE'"),{'o':organization_id}).mappings().first(); l=c.execute(text("SELECT COUNT(*) count,COALESCE(SUM(total_due-paid_amount),0) outstanding FROM loan_schedule s JOIN loans l ON l.loan_id=s.loan_id WHERE l.organization_id=:o AND s.status<>'PAID'"),{'o':organization_id}).mappings().first()
        return {'active_assets':int(a['count']),'asset_cost':float(a['cost']),'open_installments':int(l['count']),'loan_outstanding':float(l['outstanding'])}
    @app.get('/ui/assets-loans')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'assets-loans.html')
