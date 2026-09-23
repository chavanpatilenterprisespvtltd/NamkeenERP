from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
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
        perms=[('accounting_master.view','View accounting masters'),('accounting_master.manage','Manage accounting masters'),('journal.view','View journal vouchers'),('journal.manage','Manage journal vouchers'),('financial_close.view','View financial close'),('financial_close.manage','Manage financial close')]
        for p,n in perms: c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS chart_of_accounts(account_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT, ledger_code TEXT NOT NULL, ledger_name TEXT NOT NULL, account_type TEXT NOT NULL, parent_code TEXT, active INTEGER NOT NULL DEFAULT 1, UNIQUE(organization_id,entity_id,ledger_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS journal_vouchers(journal_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, voucher_no TEXT NOT NULL, journal_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', narration TEXT, total_debit NUMERIC NOT NULL DEFAULT 0, total_credit NUMERIC NOT NULL DEFAULT 0, created_by TEXT NOT NULL, posted_by TEXT, posted_at TIMESTAMP, UNIQUE(organization_id,entity_id,voucher_no))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS journal_voucher_lines(line_id TEXT PRIMARY KEY, journal_id TEXT NOT NULL, ledger_code TEXT NOT NULL, debit NUMERIC NOT NULL DEFAULT 0, credit NUMERIC NOT NULL DEFAULT 0, narration TEXT)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS accounting_opening_balances(opening_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, ledger_code TEXT NOT NULL, debit NUMERIC NOT NULL DEFAULT 0, credit NUMERIC NOT NULL DEFAULT 0, created_by TEXT NOT NULL, UNIQUE(organization_id,entity_id,period_key,ledger_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS financial_period_closes(close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', closed_by TEXT, closed_at TIMESTAMP, reopened_by TEXT, reopened_at TIMESTAMP, reason TEXT, UNIQUE(organization_id,entity_id,period_key))'''))

def register_v90cl_routes(app,engine):
    _ensure(engine)
    @app.post('/v90cl/accounts')
    def account(body:dict,request:Request):
        u=_perm(engine,request,'accounting_master.manage'); required=['organization_id','ledger_code','ledger_name','account_type']
        if any(not str(body.get(k) or '').strip() for k in required): raise HTTPException(400,'organization_id, ledger_code, ledger_name and account_type are required')
        aid=str(uuid4())
        with engine.begin() as c:
            try: c.execute(text('INSERT INTO chart_of_accounts(account_id,organization_id,entity_id,ledger_code,ledger_name,account_type,parent_code,active) VALUES(:i,:o,:e,:c,:n,:t,:p,:a)'),{'i':aid,'o':body['organization_id'],'e':body.get('entity_id'),'c':body['ledger_code'],'n':body['ledger_name'],'t':body['account_type'],'p':body.get('parent_code'),'a':1 if body.get('active',True) else 0})
            except Exception: raise HTTPException(409,'ledger code already exists for scope')
        return {'account_id':aid,'status':'ACTIVE' if body.get('active',True) else 'INACTIVE'}
    @app.get('/v90cl/accounts')
    def accounts(request:Request,organization_id:str,entity_id:str|None=None):
        _perm(engine,request,'accounting_master.view')
        with engine.connect() as c:
            rows=c.execute(text('SELECT * FROM chart_of_accounts WHERE organization_id=:o AND (:e IS NULL OR entity_id=:e) ORDER BY ledger_code'),{'o':organization_id,'e':entity_id}).mappings().all()
        return {'items':[dict(x) for x in rows]}
    @app.post('/v90cl/journals')
    def journal(body:dict,request:Request):
        u=_perm(engine,request,'journal.manage'); org,ent,date=body.get('organization_id'),body.get('entity_id'),body.get('journal_date'); lines=body.get('lines') or []
        if not all(str(x or '').strip() for x in (org,ent,date)) or not lines: raise HTTPException(400,'organization_id, entity_id, journal_date and lines are required')
        dr=sum((_d(x.get('debit')) for x in lines),Decimal('0')); cr=sum((_d(x.get('credit')) for x in lines),Decimal('0'))
        if dr<=0 or dr!=cr: raise HTTPException(400,'journal must have positive equal debit and credit totals')
        jid=str(uuid4()); vn=str(body.get('voucher_no') or ('JV-'+jid[:8].upper()))
        with engine.begin() as c:
            c.execute(text('INSERT INTO journal_vouchers(journal_id,organization_id,entity_id,voucher_no,journal_date,status,narration,total_debit,total_credit,created_by) VALUES(:i,:o,:e,:v,:d,\'DRAFT\',:n,:dr,:cr,:u)'),{'i':jid,'o':org,'e':ent,'v':vn,'d':date,'n':body.get('narration'),'dr':float(dr),'cr':float(cr),'u':str(u.user_id)})
            for x in lines: c.execute(text('INSERT INTO journal_voucher_lines(line_id,journal_id,ledger_code,debit,credit,narration) VALUES(:i,:j,:l,:d,:c,:n)'),{'i':str(uuid4()),'j':jid,'l':x.get('ledger_code'),'d':float(_d(x.get('debit'))),'c':float(_d(x.get('credit'))),'n':x.get('narration')})
        return {'journal_id':jid,'voucher_no':vn,'status':'DRAFT'}
    @app.post('/v90cl/journals/{journal_id}/post')
    def post_journal(journal_id:str,request:Request):
        u=_perm(engine,request,'journal.manage')
        with engine.begin() as c:
            j=c.execute(text('SELECT * FROM journal_vouchers WHERE journal_id=:i'),{'i':journal_id}).mappings().first()
            if not j: raise HTTPException(404,'journal not found')
            if j['status']=='POSTED': raise HTTPException(409,'journal already posted')
            if j['total_debit']!=j['total_credit']: raise HTTPException(409,'journal is not balanced')
            c.execute(text("UPDATE journal_vouchers SET status='POSTED',posted_by=:u,posted_at=CURRENT_TIMESTAMP WHERE journal_id=:i"),{'u':str(u.user_id),'i':journal_id})
        return {'journal_id':journal_id,'status':'POSTED'}
    @app.get('/v90cl/gl')
    def gl(request:Request,organization_id:str,entity_id:str,ledger_code:str,start_date:str|None=None,end_date:str|None=None):
        _perm(engine,request,'journal.view')
        with engine.connect() as c:
            q='SELECT j.journal_date,j.voucher_no,j.narration,l.debit,l.credit,l.narration line_narration FROM journal_vouchers j JOIN journal_voucher_lines l ON l.journal_id=j.journal_id WHERE j.organization_id=:o AND j.entity_id=:e AND l.ledger_code=:l AND j.status=\'POSTED\''; p={'o':organization_id,'e':entity_id,'l':ledger_code}
            if start_date: q+=' AND j.journal_date>=:s';p['s']=start_date
            if end_date: q+=' AND j.journal_date<=:z';p['z']=end_date
            rows=[dict(x) for x in c.execute(text(q+' ORDER BY j.journal_date,j.voucher_no'),p).mappings().all()]
        bal=Decimal('0'); out=[]
        for r in rows:
            bal += _d(r['debit'])-_d(r['credit']); r['running_balance']=float(bal); out.append(r)
        return {'ledger_code':ledger_code,'opening_balance':0,'closing_balance':float(bal),'items':out}
    @app.post('/v90cl/opening-balances')
    def opening(body:dict,request:Request):
        u=_perm(engine,request,'accounting_master.manage'); rows=body.get('lines') or []
        if not body.get('organization_id') or not body.get('entity_id') or not body.get('period_key') or not rows: raise HTTPException(400,'organization_id, entity_id, period_key and lines are required')
        with engine.begin() as c:
            for x in rows:
                dr,cr=_d(x.get('debit')), _d(x.get('credit'))
                if dr<0 or cr<0: raise HTTPException(400,'opening balances cannot be negative')
                c.execute(text('INSERT INTO accounting_opening_balances(opening_id,organization_id,entity_id,period_key,ledger_code,debit,credit,created_by) VALUES(:i,:o,:e,:p,:l,:d,:c,:u) ON CONFLICT(organization_id,entity_id,period_key,ledger_code) DO UPDATE SET debit=:d,credit=:c'),{'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'p':body['period_key'],'l':x.get('ledger_code'),'d':float(dr),'c':float(cr),'u':str(u.user_id)})
            total=c.execute(text('SELECT COALESCE(SUM(debit),0),COALESCE(SUM(credit),0) FROM accounting_opening_balances WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':body['organization_id'],'e':body['entity_id'],'p':body['period_key']}).first()
            if _d(total[0])!=_d(total[1]): raise HTTPException(400,'opening balances must be balanced')
        return {'status':'ACCEPTED','debit_total':float(_d(total[0])),'credit_total':float(_d(total[1]))}
    @app.post('/v90cl/financial-close')
    def close(body:dict,request:Request):
        u=_perm(engine,request,'financial_close.manage'); org,ent,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        if not all(str(x or '').strip() for x in (org,ent,p)): raise HTTPException(400,'organization_id, entity_id and period_key are required')
        with engine.begin() as c:
            existing=c.execute(text('SELECT status FROM financial_period_closes WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':org,'e':ent,'p':p}).scalar()
            if existing=='CLOSED': raise HTTPException(409,'financial period already closed')
            c.execute(text('INSERT INTO financial_period_closes(close_id,organization_id,entity_id,period_key,status,closed_by,closed_at) VALUES(:i,:o,:e,:p,\'CLOSED\',:u,CURRENT_TIMESTAMP) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status=\'CLOSED\',closed_by=:u,closed_at=CURRENT_TIMESTAMP'),{'i':str(uuid4()),'o':org,'e':ent,'p':p,'u':str(u.user_id)})
        return {'status':'CLOSED','period_key':p}
    @app.post('/v90cl/financial-close/reopen')
    def reopen(body:dict,request:Request):
        u=_perm(engine,request,'financial_close.manage'); reason=str(body.get('reason') or '').strip()
        if not reason: raise HTTPException(400,'reason is required')
        with engine.begin() as c:
            r=c.execute(text('SELECT status FROM financial_period_closes WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':body.get('organization_id'),'e':body.get('entity_id'),'p':body.get('period_key')}).scalar()
            if r!='CLOSED': raise HTTPException(409,'financial period is not closed')
            c.execute(text("UPDATE financial_period_closes SET status='OPEN',reopened_by=:u,reopened_at=CURRENT_TIMESTAMP,reason=:r WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'u':str(u.user_id),'r':reason,'o':body.get('organization_id'),'e':body.get('entity_id'),'p':body.get('period_key')})
        return {'status':'OPEN','reason':reason}
    @app.get('/ui/accounting-completion')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'accounting-completion.html')
