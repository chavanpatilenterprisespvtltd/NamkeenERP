from __future__ import annotations
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

def _ensure(e):
    with e.begin() as c:
        for p,n in [('proc_commercial.view','View Procurement Commercial Controls'),('proc_commercial.manage','Manage Procurement Commercial Controls'),('proc_commercial.approve','Approve Procurement Commercial Settlements')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_ppv_analysis(ppv_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,supplier_id TEXT NOT NULL,item_master_id TEXT NOT NULL,po_id TEXT,qty NUMERIC NOT NULL,baseline_rate NUMERIC NOT NULL,actual_rate NUMERIC NOT NULL,variance_per_unit NUMERIC NOT NULL,variance_value NUMERIC NOT NULL,variance_pct NUMERIC NOT NULL,landed_baseline NUMERIC NOT NULL DEFAULT 0,landed_actual NUMERIC NOT NULL DEFAULT 0,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS supplier_scorecard(pp_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,supplier_id TEXT NOT NULL,period_key TEXT NOT NULL,on_time_pct NUMERIC NOT NULL DEFAULT 0,quality_accept_pct NUMERIC NOT NULL DEFAULT 0,price_score NUMERIC NOT NULL DEFAULT 0,service_score NUMERIC NOT NULL DEFAULT 0,overall_score NUMERIC NOT NULL DEFAULT 0,rank_no INTEGER,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,supplier_id,period_key))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_rebate_settlement(settlement_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,supplier_id TEXT NOT NULL,item_master_id TEXT,period_key TEXT NOT NULL,eligible_qty NUMERIC NOT NULL DEFAULT 0,rebate_pct NUMERIC NOT NULL DEFAULT 0,rebate_value NUMERIC NOT NULL DEFAULT 0,credit_note_ref TEXT,status TEXT NOT NULL DEFAULT 'PENDING',approved_by TEXT,approved_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_budget_control(control_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,budget_value NUMERIC NOT NULL DEFAULT 0,committed_value NUMERIC NOT NULL DEFAULT 0,actual_value NUMERIC NOT NULL DEFAULT 0,available_value NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'OPEN',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))

def register_v90cu_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90cu/procurement/ppv')
    def ppv(body:dict,request:Request):
        u=_perm(e,request,'proc_commercial.manage')
        req=('organization_id','entity_id','supplier_id','item_master_id','qty','baseline_rate','actual_rate')
        if any(not str(body.get(k) or '').strip() for k in req): raise HTTPException(400,'required fields missing')
        qty=_d(body['qty']); base=_d(body['baseline_rate']); actual=_d(body['actual_rate']); variance=(actual-base); value=(variance*qty); pct=((variance/base)*Decimal(100)) if base else Decimal(0)
        pid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO procurement_ppv_analysis(ppv_id,organization_id,entity_id,supplier_id,item_master_id,po_id,qty,baseline_rate,actual_rate,variance_per_unit,variance_value,variance_pct,landed_baseline,landed_actual,period_key,status,created_by) VALUES(:i,:o,:e,:s,:m,:p,:q,:b,:a,:v,:vv,:vp,:lb,:la,:pk,:st,:by)'''),{'i':pid,'o':body['organization_id'],'e':body['entity_id'],'s':body['supplier_id'],'m':body['item_master_id'],'p':body.get('po_id'),'q':float(qty),'b':float(base),'a':float(actual),'v':float(variance),'vv':float(value),'vp':float(pct),'lb':float(_d(body.get('landed_baseline',body['baseline_rate']))),'la':float(_d(body.get('landed_actual',body['actual_rate']))),'pk':body.get('period_key',date.today().strftime('%Y-%m')),'st':'OPEN','by':str(u.user_id)})
        return {'ppv_id':pid,'variance_value':float(value),'variance_pct':float(pct),'status':'OPEN'}
    @app.post('/v90cu/procurement/supplier-scorecard')
    def scorecard(body:dict,request:Request):
        _perm(e,request,'proc_commercial.manage')
        for k in ('organization_id','entity_id','supplier_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        on=_d(body.get('on_time_pct')); quality=_d(body.get('quality_accept_pct')); price=_d(body.get('price_score')); service=_d(body.get('service_score',body.get('on_time_pct',0)))
        overall=((on+quality+price+service)/Decimal(4)).quantize(Decimal('0.01'))
        sid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO supplier_scorecard(pp_id,organization_id,entity_id,supplier_id,period_key,on_time_pct,quality_accept_pct,price_score,service_score,overall_score) VALUES(:i,:o,:e,:s,:p,:on,:q,:pr,:sv,:ov) ON CONFLICT(organization_id,entity_id,supplier_id,period_key) DO UPDATE SET on_time_pct=:on,quality_accept_pct=:q,price_score=:pr,service_score=:sv,overall_score=:ov'''),{'i':sid,'o':body['organization_id'],'e':body['entity_id'],'s':body['supplier_id'],'p':body['period_key'],'on':float(on),'q':float(quality),'pr':float(price),'sv':float(service),'ov':float(overall)})
            rows=c.execute(text('SELECT pp_id FROM supplier_scorecard WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY overall_score DESC, supplier_id'),{'o':body['organization_id'],'e':body['entity_id'],'p':body['period_key']}).all()
            for i,row in enumerate(rows,1): c.execute(text('UPDATE supplier_scorecard SET rank_no=:r WHERE pp_id=:i'),{'r':i,'i':row[0]})
        return {'supplier_id':body['supplier_id'],'overall_score':float(overall),'status':'RECORDED'}
    @app.post('/v90cu/procurement/rebate-settlement')
    def rebate(body:dict,request:Request):
        u=_perm(e,request,'proc_commercial.manage')
        for k in ('organization_id','entity_id','supplier_id','period_key','eligible_qty','rebate_pct'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        qty=_d(body['eligible_qty']); pct=_d(body['rebate_pct']); basis=_d(body.get('eligible_value',0)); value=(basis*pct/Decimal(100)).quantize(Decimal('0.0001'))
        rid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO procurement_rebate_settlement(settlement_id,organization_id,entity_id,supplier_id,item_master_id,period_key,eligible_qty,rebate_pct,rebate_value,credit_note_ref,status,created_by) VALUES(:i,:o,:e,:s,:m,:p,:q,:r,:v,:cr,'PENDING',:by)'''),{'i':rid,'o':body['organization_id'],'e':body['entity_id'],'s':body['supplier_id'],'m':body.get('item_master_id'),'p':body['period_key'],'q':float(qty),'r':float(pct),'v':float(value),'cr':body.get('credit_note_ref'),'by':str(u.user_id)})
        return {'settlement_id':rid,'rebate_value':float(value),'status':'PENDING'}
    @app.post('/v90cu/procurement/rebate-settlement/{settlement_id}/approve')
    def approve_rebate(settlement_id:str,request:Request):
        u=_perm(e,request,'proc_commercial.approve')
        with e.begin() as c:
            r=c.execute(text("UPDATE procurement_rebate_settlement SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE settlement_id=:i AND status='PENDING' RETURNING settlement_id"),{'i':settlement_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'pending rebate settlement not found')
        return {'settlement_id':settlement_id,'status':'APPROVED'}
    @app.post('/v90cu/procurement/budget-control')
    def budget(body:dict,request:Request):
        _perm(e,request,'proc_commercial.manage')
        for k in ('organization_id','entity_id','period_key','budget_value'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        b=_d(body['budget_value']); committed=_d(body.get('committed_value')); actual=_d(body.get('actual_value')); avail=b-committed-actual
        status='OVER' if avail<0 else 'OPEN'; cid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO procurement_budget_control(control_id,organization_id,entity_id,period_key,budget_value,committed_value,actual_value,available_value,status) VALUES(:i,:o,:e,:p,:b,:c,:a,:v,:s) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET budget_value=:b,committed_value=:c,actual_value=:a,available_value=:v,status=:s'''),{'i':cid,'o':body['organization_id'],'e':body['entity_id'],'p':body['period_key'],'b':float(b),'c':float(committed),'a':float(actual),'v':float(avail),'s':status})
        return {'control_id':cid,'available_value':float(avail),'status':status}
    @app.get('/v90cu/procurement/supplier-scorecard')
    def list_scorecard(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'proc_commercial.view')
        with e.connect() as c: rows=c.execute(text('SELECT * FROM supplier_scorecard WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY rank_no NULLS LAST,supplier_id'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'scorecards':[dict(x) for x in rows]}
    @app.get('/ui/procurement-commercial')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'procurement-commercial.html')
