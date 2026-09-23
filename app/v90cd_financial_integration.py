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

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)

def _ensure(engine):
    with engine.begin() as c:
        for pid,name in [('financial_reports.view','View financial reports'),('financial_integration.manage','Manage financial integration')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':pid,'n':name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS financial_integration_postings(
            integration_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            source_type TEXT NOT NULL, source_id TEXT NOT NULL, posting_id TEXT NOT NULL,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,source_type,source_id))'''))

def _map(c,org,entity,key):
    r=c.execute(text("SELECT ledger_code,ledger_name FROM accounting_ledger_map WHERE organization_id=:o AND source_key=:k AND active=1 AND (entity_id=:e OR entity_id IS NULL) ORDER BY CASE WHEN entity_id=:e THEN 0 ELSE 1 END LIMIT 1"),{'o':org,'e':entity,'k':key}).mappings().first()
    return dict(r) if r else {'ledger_code':key,'ledger_name':key}

def _post(c,org,entity,source_type,source_id,date,vtype,lines,user):
    if c.execute(text('SELECT 1 FROM financial_integration_postings WHERE organization_id=:o AND source_type=:s AND source_id=:i'),{'o':org,'s':source_type,'i':source_id}).first():
        return None
    dr=sum(_d(x[2]) for x in lines); cr=sum(_d(x[3]) for x in lines)
    if dr!=cr: raise HTTPException(400,'integration posting is not balanced')
    pid=str(uuid4())
    c.execute(text('''INSERT INTO accounting_postings(posting_id,organization_id,entity_id,source_type,source_id,posting_date,voucher_no,voucher_type,status,debit_total,credit_total,created_by) VALUES(:p,:o,:e,:s,:i,:d,:v,:t,'POSTED',:dr,:cr,:u)'''),{'p':pid,'o':org,'e':entity,'s':source_type,'i':source_id,'d':date,'v':source_id,'t':vtype,'dr':float(dr),'cr':float(cr),'u':str(user)})
    for code,name,d,cx,comp,narr in lines:
        c.execute(text('INSERT INTO accounting_posting_lines(line_id,posting_id,ledger_code,ledger_name,debit,credit,tax_component,narration) VALUES(:i,:p,:c,:n,:d,:cr,:tc,:na)'),{'i':str(uuid4()),'p':pid,'c':code,'n':name,'d':float(d),'cr':float(cx),'tc':comp,'na':narr})
    c.execute(text('INSERT INTO financial_integration_postings(integration_id,organization_id,entity_id,source_type,source_id,posting_id,created_by) VALUES(:i,:o,:e,:s,:sid,:p,:u)'),{'i':str(uuid4()),'o':org,'e':entity,'s':source_type,'sid':source_id,'p':pid,'u':str(user)})
    return pid

def register_v90cd_routes(app,engine):
    _ensure(engine)
    @app.post('/v90cd/accounting/assets/{asset_id}/depreciation-post')
    def dep_post(asset_id:str,body:dict,request:Request):
        u=_perm(engine,request,'financial_integration.manage'); period=str(body.get('period_key') or '')
        with engine.begin() as c:
            a=c.execute(text('SELECT * FROM fixed_assets WHERE asset_id=:i'),{'i':asset_id}).mappings().first()
            d=c.execute(text('SELECT * FROM asset_depreciation WHERE asset_id=:i AND period_key=:p'),{'i':asset_id,'p':period}).mappings().first()
            if not a or not d: raise HTTPException(404,'asset or depreciation record not found')
            dep=_d(d['depreciation_amount']); ex=_map(c,a['organization_id'],a['entity_id'],'DEPRECIATION_EXPENSE'); ac=_map(c,a['organization_id'],a['entity_id'],'ACCUMULATED_DEPRECIATION')
            pid=_post(c,a['organization_id'],a['entity_id'],'ASSET_DEPRECIATION',d['asset_depreciation_id'],period+'-01','JOURNAL',[(ex['ledger_code'],ex['ledger_name'],dep,0,None,'Asset depreciation'),(ac['ledger_code'],ac['ledger_name'],0,dep,None,'Accumulated depreciation')],u.user_id)
            if pid:c.execute(text('UPDATE asset_depreciation SET posted=1 WHERE asset_depreciation_id=:i'),{'i':d['asset_depreciation_id']})
        return {'posting_id':pid,'status':'POSTED' if pid else 'ALREADY_POSTED'}

    @app.post('/v90cd/accounting/loans/{loan_id}/interest-post')
    def loan_interest(loan_id:str,body:dict,request:Request):
        u=_perm(engine,request,'financial_integration.manage'); n=int(body.get('installment_no') or 0)
        with engine.begin() as c:
            l=c.execute(text('SELECT * FROM loans WHERE loan_id=:i'),{'i':loan_id}).mappings().first(); s=c.execute(text('SELECT * FROM loan_schedule WHERE loan_id=:i AND installment_no=:n'),{'i':loan_id,'n':n}).mappings().first()
            if not l or not s: raise HTTPException(404,'loan or installment not found')
            amt=_d(s['interest_due']); ex=_map(c,l['organization_id'],l['entity_id'],'LOAN_INTEREST_EXPENSE'); payable=_map(c,l['organization_id'],l['entity_id'],'LOAN_INTEREST_PAYABLE')
            pid=_post(c,l['organization_id'],l['entity_id'],'LOAN_INTEREST',s['schedule_id'],s['due_date'],'JOURNAL',[(ex['ledger_code'],ex['ledger_name'],amt,0,None,'Loan interest'),(payable['ledger_code'],payable['ledger_name'],0,amt,None,'Loan interest payable')],u.user_id)
        return {'posting_id':pid,'interest':float(amt),'status':'POSTED' if pid else 'ALREADY_POSTED'}

    def report(request,organization_id,entity_id,start_date,end_date):
        _perm(engine,request,'financial_reports.view')
        q='''SELECT l.ledger_code,MAX(l.ledger_name) ledger_name,SUM(l.debit) debit,SUM(l.credit) credit FROM accounting_posting_lines l JOIN accounting_postings p ON p.posting_id=l.posting_id WHERE p.organization_id=:o AND (:e IS NULL OR p.entity_id=:e) AND (:s IS NULL OR p.posting_date>=:s) AND (:d IS NULL OR p.posting_date<=:d) GROUP BY l.ledger_code ORDER BY l.ledger_code'''
        with engine.connect() as c: rows=[dict(x) for x in c.execute(text(q),{'o':organization_id,'e':entity_id,'s':start_date,'d':end_date}).mappings().all()]
        for r in rows:r['debit']=float(r['debit'] or 0);r['credit']=float(r['credit'] or 0);r['balance']=round(r['debit']-r['credit'],2)
        return rows
    @app.get('/v90cd/accounting/profit-loss')
    def pnl(request:Request,organization_id:str,entity_id:str|None=None,start_date:str|None=None,end_date:str|None=None):
        rows=report(request,organization_id,entity_id,start_date,end_date); rev=sum(r['credit']-r['debit'] for r in rows if any(x in r['ledger_code'].upper() for x in ('SALES','REVENUE'))); exp=sum(r['debit']-r['credit'] for r in rows if any(x in r['ledger_code'].upper() for x in ('EXPENSE','PURCHASE','COST','DEPRECIATION','INTEREST'))); return {'revenue':round(rev,2),'expenses':round(exp,2),'net_profit':round(rev-exp,2),'lines':rows}
    @app.get('/v90cd/accounting/balance-sheet')
    def bs(request:Request,organization_id:str,entity_id:str|None=None,start_date:str|None=None,end_date:str|None=None):
        rows=report(request,organization_id,entity_id,start_date,end_date); assets=sum(r['balance'] for r in rows if any(x in r['ledger_code'].upper() for x in ('ASSET','CASH','BANK','RECEIVABLE','INVENTORY'))); liabilities=sum(-r['balance'] for r in rows if any(x in r['ledger_code'].upper() for x in ('LIABILITY','PAYABLE','LOAN'))); equity=sum(-r['balance'] for r in rows if any(x in r['ledger_code'].upper() for x in ('EQUITY','CAPITAL'))); return {'assets':round(assets,2),'liabilities':round(liabilities,2),'equity':round(equity,2),'balance_check':round(assets-liabilities-equity,2),'lines':rows}
    @app.get('/v90cd/accounting/cash-flow')
    def cf(request:Request,organization_id:str,entity_id:str|None=None,start_date:str|None=None,end_date:str|None=None):
        rows=report(request,organization_id,entity_id,start_date,end_date); cash=sum(r['balance'] for r in rows if any(x in r['ledger_code'].upper() for x in ('CASH','BANK'))); return {'net_cash_movement':round(cash,2),'cash_bank_lines':[r for r in rows if any(x in r['ledger_code'].upper() for x in ('CASH','BANK'))]}
    @app.get('/ui/financial-reports')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'financial-reports.html')
