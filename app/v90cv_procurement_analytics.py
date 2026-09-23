from __future__ import annotations
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
        for p,n in [('proc_analytics.view','View Procurement Analytics'),('proc_analytics.manage','Manage Procurement Analytics'),('proc_analytics.recommend','Approve Supplier Recommendations')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_supplier_analytics(
            analytics_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, supplier_id TEXT NOT NULL,
            period_key TEXT NOT NULL, spend_value NUMERIC NOT NULL DEFAULT 0, ppv_value NUMERIC NOT NULL DEFAULT 0,
            purchase_qty NUMERIC NOT NULL DEFAULT 0, contracted_rate NUMERIC NOT NULL DEFAULT 0, actual_rate NUMERIC NOT NULL DEFAULT 0,
            landed_cost NUMERIC NOT NULL DEFAULT 0, otif_pct NUMERIC NOT NULL DEFAULT 0, quality_rejection_pct NUMERIC NOT NULL DEFAULT 0,
            dependency_pct NUMERIC NOT NULL DEFAULT 0, savings_value NUMERIC NOT NULL DEFAULT 0, score NUMERIC NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,supplier_id,period_key))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_supplier_recommendation(
            recommendation_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, item_master_id TEXT NOT NULL,
            supplier_id TEXT NOT NULL, period_key TEXT NOT NULL, score NUMERIC NOT NULL, rationale TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING', approved_by TEXT, approved_at TIMESTAMP, created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_proc_analytics_scope ON procurement_supplier_analytics(organization_id,entity_id,period_key,supplier_id)'))

def register_v90cv_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90cv/procurement/supplier-analytics')
    def analytics(body:dict,request:Request):
        u=_perm(e,request,'proc_analytics.manage')
        for k in ('organization_id','entity_id','supplier_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        spend=_d(body.get('spend_value')); ppv=_d(body.get('ppv_value')); qty=_d(body.get('purchase_qty'))
        contracted=_d(body.get('contracted_rate')); actual=_d(body.get('actual_rate')); landed=_d(body.get('landed_cost'))
        otif=_d(body.get('otif_pct')); quality=_d(body.get('quality_rejection_pct')); dep=_d(body.get('dependency_pct'))
        savings=_d(body.get('savings_value'))
        price_score=_d(max(Decimal(0), min(Decimal(100), (contracted/actual*100) if actual else 0)))
        quality_score=max(Decimal(0),Decimal(100)-quality); overall=(otif+quality_score+price_score+(Decimal(100)-min(dep,Decimal(100))))/Decimal(4)
        aid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO procurement_supplier_analytics(analytics_id,organization_id,entity_id,supplier_id,period_key,spend_value,ppv_value,purchase_qty,contracted_rate,actual_rate,landed_cost,otif_pct,quality_rejection_pct,dependency_pct,savings_value,score) VALUES(:i,:o,:e,:s,:p,:sp,:ppv,:q,:cr,:ar,:lc,:ot,:qr,:dp,:sv,:sc) ON CONFLICT(organization_id,entity_id,supplier_id,period_key) DO UPDATE SET spend_value=:sp,ppv_value=:ppv,purchase_qty=:q,contracted_rate=:cr,actual_rate=:ar,landed_cost=:lc,otif_pct=:ot,quality_rejection_pct=:qr,dependency_pct=:dp,savings_value=:sv,score=:sc'''),{'i':aid,'o':body['organization_id'],'e':body['entity_id'],'s':body['supplier_id'],'p':body['period_key'],'sp':float(spend),'ppv':float(ppv),'q':float(qty),'cr':float(contracted),'ar':float(actual),'lc':float(landed),'ot':float(otif),'qr':float(quality),'dp':float(dep),'sv':float(savings),'sc':float(overall)})
        return {'analytics_id':aid,'score':float(overall),'savings_value':float(savings),'status':'RECORDED'}

    @app.get('/v90cv/procurement/supplier-analytics')
    def list_analytics(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'proc_analytics.view')
        with e.connect() as c: rows=c.execute(text('SELECT * FROM procurement_supplier_analytics WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY score DESC,supplier_id'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'analytics':[dict(x) for x in rows]}

    @app.post('/v90cv/procurement/recommendation')
    def recommendation(body:dict,request:Request):
        u=_perm(e,request,'proc_analytics.manage')
        for k in ('organization_id','entity_id','item_master_id','supplier_id','period_key','score'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        rid=str(uuid4()); rationale=body.get('rationale') or 'Supplier selected from procurement score, price, service, quality and dependency analytics.'
        with e.begin() as c: c.execute(text('''INSERT INTO procurement_supplier_recommendation(recommendation_id,organization_id,entity_id,item_master_id,supplier_id,period_key,score,rationale,created_by) VALUES(:i,:o,:e,:m,:s,:p,:sc,:r,:by)'''),{'i':rid,'o':body['organization_id'],'e':body['entity_id'],'m':body['item_master_id'],'s':body['supplier_id'],'p':body['period_key'],'sc':float(_d(body['score'])),'r':rationale,'by':str(u.user_id)})
        return {'recommendation_id':rid,'status':'PENDING'}

    @app.post('/v90cv/procurement/recommendation/{recommendation_id}/approve')
    def approve(recommendation_id:str,request:Request):
        u=_perm(e,request,'proc_analytics.recommend')
        with e.begin() as c:
            r=c.execute(text("UPDATE procurement_supplier_recommendation SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE recommendation_id=:i AND status='PENDING' RETURNING recommendation_id"),{'i':recommendation_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'pending recommendation not found')
        return {'recommendation_id':recommendation_id,'status':'APPROVED'}

    @app.get('/v90cv/procurement/recommendations')
    def recommendations(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'proc_analytics.view')
        with e.connect() as c: rows=c.execute(text('SELECT * FROM procurement_supplier_recommendation WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY score DESC,created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'recommendations':[dict(x) for x in rows]}

    @app.get('/ui/procurement-analytics')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'procurement-analytics.html')
