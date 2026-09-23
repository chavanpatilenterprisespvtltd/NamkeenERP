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
        perms=[('year_end.view','View year-end close'),('year_end.manage','Manage year-end close'),('year_end.reopen','Reopen year-end close')]
        for p,n in perms: c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS year_end_closes(close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, financial_year TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', net_profit_loss NUMERIC NOT NULL DEFAULT 0, retained_earnings_ledger TEXT, prepared_by TEXT, prepared_at TIMESTAMP, closed_by TEXT, closed_at TIMESTAMP, reopened_by TEXT, reopened_at TIMESTAMP, reopen_reason TEXT, UNIQUE(organization_id,entity_id,financial_year))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS year_end_carryforwards(carryforward_id TEXT PRIMARY KEY, close_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, next_period_key TEXT NOT NULL, ledger_code TEXT NOT NULL, debit NUMERIC NOT NULL DEFAULT 0, credit NUMERIC NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(close_id,ledger_code))'''))

def _balances(c, org, ent, start, end):
    rows=c.execute(text('''SELECT a.ledger_code,a.account_type,COALESCE((SELECT SUM(o.debit-o.credit) FROM accounting_opening_balances o WHERE o.organization_id=a.organization_id AND o.entity_id=:e AND o.ledger_code=a.ledger_code),0)+COALESCE(SUM(l.debit-l.credit),0) bal
      FROM chart_of_accounts a LEFT JOIN journal_vouchers j ON j.organization_id=a.organization_id AND j.entity_id=:e AND j.status='POSTED' AND j.journal_date>=:s AND j.journal_date<=:d LEFT JOIN journal_voucher_lines l ON l.journal_id=j.journal_id AND l.ledger_code=a.ledger_code
      WHERE a.organization_id=:o GROUP BY a.ledger_code,a.account_type ORDER BY a.ledger_code'''),{'o':org,'e':ent,'s':start,'d':end}).mappings().all()
    return rows

def register_v90cn_routes(app,engine):
    _ensure(engine)
    @app.post('/v90cn/year-end/prepare')
    def prepare(body:dict,request:Request):
        u=_perm(engine,request,'year_end.manage')
        req=['organization_id','entity_id','financial_year','start_date','end_date','retained_earnings_ledger']
        if any(not str(body.get(k) or '').strip() for k in req): raise HTTPException(400,'organization_id, entity_id, financial_year, start_date, end_date and retained_earnings_ledger are required')
        org,ent,fy=body['organization_id'],body['entity_id'],body['financial_year']
        with engine.begin() as c:
            existing=c.execute(text('SELECT status FROM year_end_closes WHERE organization_id=:o AND entity_id=:e AND financial_year=:f'),{'o':org,'e':ent,'f':fy}).scalar()
            if existing=='CLOSED': raise HTTPException(409,'financial year already closed')
            rows=_balances(c,org,ent,body['start_date'],body['end_date'])
            pnl=sum((_d(r['bal']) for r in rows if str(r['account_type']).upper() in ('INCOME','REVENUE','EXPENSE','COST_OF_GOODS_SOLD','COGS')),Decimal('0'))
            # Income is normally credit-balance; expense is debit-balance. Net P&L = credits - debits.
            pnl=sum((_d(r['bal']) * (Decimal('-1') if str(r['account_type']).upper() in ('INCOME','REVENUE') else Decimal('1')) for r in rows if str(r['account_type']).upper() in ('INCOME','REVENUE','EXPENSE','COST_OF_GOODS_SOLD','COGS')),Decimal('0'))
            cid=str(uuid4())
            c.execute(text('''INSERT INTO year_end_closes(close_id,organization_id,entity_id,financial_year,start_date,end_date,status,net_profit_loss,retained_earnings_ledger,prepared_by,prepared_at) VALUES(:i,:o,:e,:f,:s,:d,'READY',:p,:r,:u,CURRENT_TIMESTAMP) ON CONFLICT(organization_id,entity_id,financial_year) DO UPDATE SET start_date=:s,end_date=:d,status='READY',net_profit_loss=:p,retained_earnings_ledger=:r,prepared_by=:u,prepared_at=CURRENT_TIMESTAMP'''),{'i':cid,'o':org,'e':ent,'f':fy,'s':body['start_date'],'d':body['end_date'],'p':float(pnl),'r':body['retained_earnings_ledger'],'u':str(u.user_id)})
            actual=c.execute(text('SELECT close_id FROM year_end_closes WHERE organization_id=:o AND entity_id=:e AND financial_year=:f'),{'o':org,'e':ent,'f':fy}).scalar()
        return {'close_id':actual,'status':'READY','net_profit_loss':float(pnl),'ledger_count':len(rows)}
    @app.get('/v90cn/year-end')
    def get_close(request:Request,organization_id:str,entity_id:str,financial_year:str):
        _perm(engine,request,'year_end.view')
        with engine.connect() as c:
            r=c.execute(text('SELECT * FROM year_end_closes WHERE organization_id=:o AND entity_id=:e AND financial_year=:f'),{'o':organization_id,'e':entity_id,'f':financial_year}).mappings().first()
            if not r: raise HTTPException(404,'year-end close not found')
            lines=c.execute(text('SELECT * FROM year_end_carryforwards WHERE close_id=:i ORDER BY ledger_code'),{'i':r['close_id']}).mappings().all()
        return {'close':dict(r),'carryforwards':[dict(x) for x in lines]}
    @app.post('/v90cn/year-end/{close_id}/close')
    def close(close_id:str,body:dict,request:Request):
        u=_perm(engine,request,'year_end.manage')
        next_period=str(body.get('next_period_key') or '').strip()
        if not next_period: raise HTTPException(400,'next_period_key is required')
        with engine.begin() as c:
            r=c.execute(text('SELECT * FROM year_end_closes WHERE close_id=:i'),{'i':close_id}).mappings().first()
            if not r: raise HTTPException(404,'year-end close not found')
            if r['status']=='CLOSED': raise HTTPException(409,'year-end already closed')
            rows=_balances(c,r['organization_id'],r['entity_id'],r['start_date'],r['end_date'])
            c.execute(text('DELETE FROM year_end_carryforwards WHERE close_id=:i'),{'i':close_id})
            for x in rows:
                typ=str(x['account_type']).upper(); bal=_d(x['bal'])
                if typ in ('INCOME','REVENUE','EXPENSE','COST_OF_GOODS_SOLD','COGS'): continue
                if bal==0: continue
                c.execute(text('INSERT INTO year_end_carryforwards(carryforward_id,close_id,organization_id,entity_id,next_period_key,ledger_code,debit,credit,created_by) VALUES(:i,:c,:o,:e,:p,:l,:d,:r,:u)'),{'i':str(uuid4()),'c':close_id,'o':r['organization_id'],'e':r['entity_id'],'p':next_period,'l':x['ledger_code'],'d':float(bal if bal>0 else 0),'r':float(-bal if bal<0 else 0),'u':str(u.user_id)})
            # P&L is transferred conceptually to retained earnings; the carry-forward excludes temporary accounts.
            c.execute(text("UPDATE year_end_closes SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP WHERE close_id=:i"),{'u':str(u.user_id),'i':close_id})
        return {'close_id':close_id,'status':'CLOSED','next_period_key':next_period,'net_profit_loss':float(_d(r['net_profit_loss']))}
    @app.post('/v90cn/year-end/{close_id}/reopen')
    def reopen(close_id:str,body:dict,request:Request):
        u=_perm(engine,request,'year_end.reopen'); reason=str(body.get('reason') or '').strip()
        if not reason: raise HTTPException(400,'reason is required')
        with engine.begin() as c:
            r=c.execute(text('SELECT status FROM year_end_closes WHERE close_id=:i'),{'i':close_id}).scalar()
            if r!='CLOSED': raise HTTPException(409,'year-end is not closed')
            c.execute(text("UPDATE year_end_closes SET status='REOPENED',reopened_by=:u,reopened_at=CURRENT_TIMESTAMP,reopen_reason=:r WHERE close_id=:i"),{'u':str(u.user_id),'r':reason,'i':close_id})
        return {'close_id':close_id,'status':'REOPENED','reason':reason}
    @app.get('/ui/year-end-close')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'year-end-close.html')
