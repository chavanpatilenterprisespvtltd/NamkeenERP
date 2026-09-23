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

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.0001'),rounding=ROUND_HALF_UP)

def _ensure(e):
 with e.begin() as c:
  for p,n in [('mfg_loss.view','View Manufacturing Loss/Yield'),('mfg_loss.manage','Manage Manufacturing Loss/Yield'),('mfg_loss.approve','Approve Manufacturing Variance')]:
   c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
  c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_loss_standard(standard_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,product_id TEXT NOT NULL,ingredient_id TEXT,loss_type TEXT NOT NULL,standard_pct NUMERIC NOT NULL DEFAULT 0,standard_qty NUMERIC NOT NULL DEFAULT 0,effective_from DATE NOT NULL,effective_to DATE,status TEXT NOT NULL DEFAULT 'ACTIVE',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,product_id,ingredient_id,loss_type,effective_from))'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_consumption_variance(variance_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,product_id TEXT NOT NULL,ingredient_id TEXT NOT NULL,standard_qty NUMERIC NOT NULL DEFAULT 0,actual_qty NUMERIC NOT NULL DEFAULT 0,unit_cost NUMERIC NOT NULL DEFAULT 0,variance_qty NUMERIC NOT NULL DEFAULT 0,variance_value NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'OPEN',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_byproduct_accounting(byproduct_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,product_id TEXT NOT NULL,byproduct_item_id TEXT NOT NULL,quantity NUMERIC NOT NULL DEFAULT 0,valuation_rate NUMERIC NOT NULL DEFAULT 0,valuation_value NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'RECORDED',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_yield_benchmark(benchmark_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,product_id TEXT NOT NULL,period_key TEXT NOT NULL,batch_count INTEGER NOT NULL DEFAULT 0,avg_yield_pct NUMERIC NOT NULL DEFAULT 0,best_yield_pct NUMERIC NOT NULL DEFAULT 0,avg_wastage_qty NUMERIC NOT NULL DEFAULT 0,avg_cost_per_kg NUMERIC NOT NULL DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,product_id,period_key))'''))

def register_v90cx_routes(app:FastAPI,e):
 _ensure(e)
 @app.post('/v90cx/manufacturing/loss-standard')
 def standard(body:dict,request:Request):
  _perm(e,request,'mfg_loss.manage')
  for k in ('organization_id','entity_id','product_id','loss_type','effective_from'):
   if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  sid=str(uuid4())
  with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_loss_standard(standard_id,organization_id,entity_id,product_id,ingredient_id,loss_type,standard_pct,standard_qty,effective_from,effective_to) VALUES(:i,:o,:e,:p,:g,:t,:sp,:sq,:f,:to)'''),{'i':sid,'o':body['organization_id'],'e':body['entity_id'],'p':body['product_id'],'g':body.get('ingredient_id'),'t':body['loss_type'],'sp':float(_d(body.get('standard_pct'))),'sq':float(_d(body.get('standard_qty'))),'f':body['effective_from'],'to':body.get('effective_to')})
  return {'standard_id':sid,'status':'ACTIVE'}
 @app.post('/v90cx/manufacturing/consumption-variance')
 def variance(body:dict,request:Request):
  _perm(e,request,'mfg_loss.manage')
  for k in ('organization_id','entity_id','batch_id','product_id','ingredient_id','standard_qty','actual_qty'):
   if body.get(k) is None: raise HTTPException(400,f'{k} is required')
  std,act,cost=map(_d,[body['standard_qty'],body['actual_qty'],body.get('unit_cost')]); vq=act-std; vv=vq*cost; vid=str(uuid4())
  with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_consumption_variance(variance_id,organization_id,entity_id,batch_id,product_id,ingredient_id,standard_qty,actual_qty,unit_cost,variance_qty,variance_value) VALUES(:i,:o,:e,:b,:p,:g,:s,:a,:c,:q,:v)'''),{'i':vid,'o':body['organization_id'],'e':body['entity_id'],'b':body['batch_id'],'p':body['product_id'],'g':body['ingredient_id'],'s':float(std),'a':float(act),'c':float(cost),'q':float(vq),'v':float(vv)})
  return {'variance_id':vid,'variance_qty':float(vq),'variance_value':float(vv),'status':'OPEN'}
 @app.post('/v90cx/manufacturing/byproduct')
 def byproduct(body:dict,request:Request):
  _perm(e,request,'mfg_loss.manage')
  for k in ('organization_id','entity_id','batch_id','product_id','byproduct_item_id','quantity','valuation_rate'):
   if body.get(k) is None: raise HTTPException(400,f'{k} is required')
  q,r=map(_d,[body['quantity'],body['valuation_rate']]); val=q*r; bid=str(uuid4())
  with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_byproduct_accounting(byproduct_id,organization_id,entity_id,batch_id,product_id,byproduct_item_id,quantity,valuation_rate,valuation_value) VALUES(:i,:o,:e,:b,:p,:g,:q,:r,:v)'''),{'i':bid,'o':body['organization_id'],'e':body['entity_id'],'b':body['batch_id'],'p':body['product_id'],'g':body['byproduct_item_id'],'q':float(q),'r':float(r),'v':float(val)})
  return {'byproduct_id':bid,'valuation_value':float(val),'status':'RECORDED'}
 @app.post('/v90cx/manufacturing/yield-benchmark/rebuild')
 def benchmark(body:dict,request:Request):
  _perm(e,request,'mfg_loss.manage')
  for k in ('organization_id','entity_id','product_id','period_key'):
   if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  with e.begin() as c:
   r=c.execute(text('''SELECT COUNT(*) n,COALESCE(AVG(yield_pct),0) ay,COALESCE(MAX(yield_pct),0) by,COALESCE(AVG(wastage_qty),0) aw,COALESCE(AVG(cost_per_kg),0) ac FROM manufacturing_batch_cost WHERE organization_id=:o AND entity_id=:e AND product_id=:p AND period_key=:k'''),{'o':body['organization_id'],'e':body['entity_id'],'p':body['product_id'],'k':body['period_key']}).mappings().one()
   bid=str(uuid4()); c.execute(text('''INSERT INTO manufacturing_yield_benchmark(benchmark_id,organization_id,entity_id,product_id,period_key,batch_count,avg_yield_pct,best_yield_pct,avg_wastage_qty,avg_cost_per_kg) VALUES(:i,:o,:e,:p,:k,:n,:ay,:by,:aw,:ac) ON CONFLICT(organization_id,entity_id,product_id,period_key) DO UPDATE SET batch_count=:n,avg_yield_pct=:ay,best_yield_pct=:by,avg_wastage_qty=:aw,avg_cost_per_kg=:ac'''),{'i':bid,'o':body['organization_id'],'e':body['entity_id'],'p':body['product_id'],'k':body['period_key'],'n':r['n'],'ay':r['ay'],'by':r['by'],'aw':r['aw'],'ac':r['ac']})
  return {'benchmark_id':bid,'batch_count':r['n'],'avg_yield_pct':float(r['ay']),'best_yield_pct':float(r['by']),'avg_wastage_qty':float(r['aw']),'avg_cost_per_kg':float(r['ac'])}
 @app.get('/v90cx/manufacturing/variance')
 def listing(request:Request,organization_id:str,entity_id:str,batch_id:str):
  _perm(e,request,'mfg_loss.view')
  with e.connect() as c:
   v=c.execute(text('SELECT * FROM manufacturing_consumption_variance WHERE organization_id=:o AND entity_id=:e AND batch_id=:b ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'b':batch_id}).mappings().all()
   bp=c.execute(text('SELECT * FROM manufacturing_byproduct_accounting WHERE organization_id=:o AND entity_id=:e AND batch_id=:b ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'b':batch_id}).mappings().all()
  return {'consumption_variances':[dict(x) for x in v],'byproducts':[dict(x) for x in bp]}
 @app.post('/v90cx/manufacturing/variance/{variance_id}/approve')
 def approve(variance_id:str,request:Request):
  _perm(e,request,'mfg_loss.approve')
  with e.begin() as c:
   r=c.execute(text("UPDATE manufacturing_consumption_variance SET status='APPROVED' WHERE variance_id=:i AND status='OPEN' RETURNING variance_id"),{'i':variance_id}).first()
   if not r: raise HTTPException(404,'open variance not found')
  return {'variance_id':variance_id,'status':'APPROVED'}
 @app.get('/ui/manufacturing-loss-yield')
 def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'manufacturing-loss-yield.html')
