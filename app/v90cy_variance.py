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
        perms=[('mfg_var.view','View Production Variance'),('mfg_var.manage','Manage Production Variance'),('mfg_var.approve','Approve Production Variance')]
        for p,n in perms: c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_variance_detail(
            variance_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, batch_id TEXT NOT NULL,
            product_id TEXT NOT NULL, period_key TEXT NOT NULL, variance_type TEXT NOT NULL, standard_value NUMERIC NOT NULL DEFAULT 0,
            actual_value NUMERIC NOT NULL DEFAULT 0, variance_value NUMERIC NOT NULL DEFAULT 0, variance_pct NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN', reason TEXT, created_by TEXT NOT NULL, approved_by TEXT, approved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_variance_corrective_action(
            action_id TEXT PRIMARY KEY, variance_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            action_text TEXT NOT NULL, owner_user_id TEXT, due_date DATE, status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT NOT NULL, completed_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_shift_performance(
            performance_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            shift_code TEXT NOT NULL, operator_ref TEXT, machine_ref TEXT, batch_count INTEGER NOT NULL DEFAULT 0,
            good_qty NUMERIC NOT NULL DEFAULT 0, wastage_qty NUMERIC NOT NULL DEFAULT 0, avg_yield_pct NUMERIC NOT NULL DEFAULT 0,
            total_variance_value NUMERIC NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,shift_code,operator_ref,machine_ref))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_mfg_var_scope ON manufacturing_variance_detail(organization_id,entity_id,period_key,product_id,variance_type)'))

def register_v90cy_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90cy/manufacturing/variance')
    def record(body:dict,request:Request):
        u=_perm(e,request,'mfg_var.manage')
        for k in ('organization_id','entity_id','batch_id','product_id','period_key','variance_type','standard_value','actual_value'):
            if body.get(k) is None or (isinstance(body.get(k),str) and not body[k].strip()): raise HTTPException(400,f'{k} is required')
        std,act=map(_d,[body['standard_value'],body['actual_value']]); vv=act-std; vp=(vv/std*100 if std else Decimal(0)); vid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_variance_detail(variance_id,organization_id,entity_id,batch_id,product_id,period_key,variance_type,standard_value,actual_value,variance_value,variance_pct,reason,created_by) VALUES(:i,:o,:e,:b,:p,:k,:t,:s,:a,:v,:q,:r,:u)'''),{'i':vid,'o':body['organization_id'],'e':body['entity_id'],'b':body['batch_id'],'p':body['product_id'],'k':body['period_key'],'t':body['variance_type'],'s':float(std),'a':float(act),'v':float(vv),'q':float(vp),'r':body.get('reason'),'u':str(u.user_id)})
        return {'variance_id':vid,'variance_value':float(vv),'variance_pct':float(vp),'status':'OPEN'}

    @app.get('/v90cy/manufacturing/variance')
    def listing(request:Request,organization_id:str,entity_id:str,period_key:str,product_id:str|None=None):
        _perm(e,request,'mfg_var.view')
        q='SELECT * FROM manufacturing_variance_detail WHERE organization_id=:o AND entity_id=:e AND period_key=:k'
        p={'o':organization_id,'e':entity_id,'k':period_key}
        if product_id: q+=' AND product_id=:p'; p['p']=product_id
        q+=' ORDER BY created_at DESC'
        with e.connect() as c: rows=c.execute(text(q),p).mappings().all()
        return {'variances':[dict(x) for x in rows]}

    @app.post('/v90cy/manufacturing/variance/{variance_id}/approve')
    def approve(variance_id:str,request:Request):
        u=_perm(e,request,'mfg_var.approve')
        with e.begin() as c:
            r=c.execute(text("UPDATE manufacturing_variance_detail SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE variance_id=:i AND status='OPEN' RETURNING variance_id"),{'i':variance_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'open variance not found')
        return {'variance_id':variance_id,'status':'APPROVED'}

    @app.post('/v90cy/manufacturing/variance/{variance_id}/corrective-action')
    def corrective(variance_id:str,body:dict,request:Request):
        u=_perm(e,request,'mfg_var.manage')
        if not str(body.get('action_text') or '').strip(): raise HTTPException(400,'action_text is required')
        aid=str(uuid4())
        with e.begin() as c: c.execute(text('INSERT INTO manufacturing_variance_corrective_action(action_id,variance_id,organization_id,entity_id,action_text,owner_user_id,due_date,created_by) SELECT :i,variance_id,organization_id,entity_id,:a,:o,:d,:u FROM manufacturing_variance_detail WHERE variance_id=:v'),{'i':aid,'v':variance_id,'a':body['action_text'],'o':body.get('owner_user_id'),'d':body.get('due_date'),'u':str(u.user_id)})
        return {'action_id':aid,'status':'OPEN'}

    @app.post('/v90cy/manufacturing/corrective-action/{action_id}/complete')
    def complete(action_id:str,request:Request):
        _perm(e,request,'mfg_var.manage')
        with e.begin() as c:
            r=c.execute(text("UPDATE manufacturing_variance_corrective_action SET status='COMPLETED',completed_at=CURRENT_TIMESTAMP WHERE action_id=:i AND status='OPEN' RETURNING action_id"),{'i':action_id}).first()
            if not r: raise HTTPException(404,'open corrective action not found')
        return {'action_id':action_id,'status':'COMPLETED'}

    @app.post('/v90cy/manufacturing/shift-performance')
    def shift(body:dict,request:Request):
        _perm(e,request,'mfg_var.manage')
        for k in ('organization_id','entity_id','period_key','shift_code'): 
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        sid=str(uuid4()); good=_d(body.get('good_qty')); waste=_d(body.get('wastage_qty')); batches=int(body.get('batch_count') or 0); y=(good/(good+waste)*100 if good+waste else Decimal(0)); tv=_d(body.get('total_variance_value'))
        with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_shift_performance(performance_id,organization_id,entity_id,period_key,shift_code,operator_ref,machine_ref,batch_count,good_qty,wastage_qty,avg_yield_pct,total_variance_value) VALUES(:i,:o,:e,:k,:s,:op,:m,:b,:g,:w,:y,:v) ON CONFLICT(organization_id,entity_id,period_key,shift_code,operator_ref,machine_ref) DO UPDATE SET batch_count=:b,good_qty=:g,wastage_qty=:w,avg_yield_pct=:y,total_variance_value=:v'''),{'i':sid,'o':body['organization_id'],'e':body['entity_id'],'k':body['period_key'],'s':body['shift_code'],'op':body.get('operator_ref'),'m':body.get('machine_ref'),'b':batches,'g':float(good),'w':float(waste),'y':float(y),'v':float(tv)})
        return {'performance_id':sid,'avg_yield_pct':float(y),'status':'RECORDED'}

    @app.get('/v90cy/manufacturing/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'mfg_var.view')
        with e.connect() as c:
            rows=c.execute(text('''SELECT variance_type,COUNT(*) count,COALESCE(SUM(variance_value),0) variance_value,COALESCE(AVG(variance_pct),0) avg_variance_pct FROM manufacturing_variance_detail WHERE organization_id=:o AND entity_id=:e AND period_key=:k GROUP BY variance_type ORDER BY ABS(COALESCE(SUM(variance_value),0)) DESC'''),{'o':organization_id,'e':entity_id,'k':period_key}).mappings().all()
            shifts=c.execute(text('SELECT * FROM manufacturing_shift_performance WHERE organization_id=:o AND entity_id=:e AND period_key=:k ORDER BY avg_yield_pct DESC'),{'o':organization_id,'e':entity_id,'k':period_key}).mappings().all()
        return {'variance_summary':[dict(x) for x in rows],'shift_performance':[dict(x) for x in shifts]}

    @app.get('/ui/manufacturing-variance')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'manufacturing-variance.html')
