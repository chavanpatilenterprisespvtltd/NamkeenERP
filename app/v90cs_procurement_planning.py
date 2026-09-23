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
  for p,n in [('proc_plan.view','View Procurement Planning'),('proc_plan.manage','Manage Procurement Planning'),('proc_plan.approve','Approve Procurement Planning')]:
   c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
  c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_source_rules(rule_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,material_master_id TEXT NOT NULL,supplier_id TEXT NOT NULL,priority INTEGER NOT NULL DEFAULT 100,allocation_pct NUMERIC NOT NULL DEFAULT 100,min_order_qty NUMERIC NOT NULL DEFAULT 0,lead_time_days INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,material_master_id,supplier_id))'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS supplier_performance_snapshot(snapshot_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,supplier_id TEXT NOT NULL,period_key TEXT NOT NULL,on_time_pct NUMERIC NOT NULL DEFAULT 0,quality_accept_pct NUMERIC NOT NULL DEFAULT 0,price_score NUMERIC NOT NULL DEFAULT 0,overall_score NUMERIC NOT NULL DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,supplier_id,period_key))'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_rfqs(rfq_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NOT NULL,material_master_id TEXT NOT NULL,required_qty NUMERIC NOT NULL,uom TEXT NOT NULL,required_date TEXT,supplier_ids TEXT,status TEXT NOT NULL DEFAULT 'DRAFT',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_quotes(quote_id TEXT PRIMARY KEY,rfq_id TEXT NOT NULL,supplier_id TEXT NOT NULL,unit_price NUMERIC NOT NULL,landed_cost NUMERIC NOT NULL DEFAULT 0,lead_time_days INTEGER NOT NULL DEFAULT 0,quality_score NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'RECEIVED',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_requisitions(requisition_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NOT NULL,material_master_id TEXT NOT NULL,supplier_id TEXT,qty NUMERIC NOT NULL,uom TEXT NOT NULL,required_date TEXT,source_suggestion_id TEXT,source_rfq_id TEXT,status TEXT NOT NULL DEFAULT 'DRAFT',approved_by TEXT,approved_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

def register_v90cs_routes(app:FastAPI,e):
 _ensure(e)
 @app.post('/v90cs/procurement/source-rules')
 def rule(body:dict,request:Request):
  u=_perm(e,request,'proc_plan.manage')
  req=('organization_id','entity_id','material_master_id','supplier_id')
  if any(not str(body.get(k) or '').strip() for k in req): raise HTTPException(400,'required fields missing')
  rid=str(uuid4())
  with e.begin() as c:
   c.execute(text('''INSERT INTO procurement_source_rules(rule_id,organization_id,entity_id,material_master_id,supplier_id,priority,allocation_pct,min_order_qty,lead_time_days) VALUES(:i,:o,:e,:m,:s,:p,:a,:q,:l) ON CONFLICT(organization_id,entity_id,material_master_id,supplier_id) DO UPDATE SET priority=:p,allocation_pct=:a,min_order_qty=:q,lead_time_days=:l,active=1'''),{'i':rid,'o':body['organization_id'],'e':body['entity_id'],'m':body['material_master_id'],'s':body['supplier_id'],'p':int(body.get('priority',100)),'a':float(body.get('allocation_pct',100)),'q':float(body.get('min_order_qty',0)),'l':int(body.get('lead_time_days',0))})
  return {'rule_id':rid,'status':'ACTIVE'}
 @app.post('/v90cs/procurement/rfq')
 def rfq(body:dict,request:Request):
  u=_perm(e,request,'proc_plan.manage')
  for k in ('organization_id','entity_id','location_id','material_master_id','uom'):
   if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  rid=str(uuid4()); suppliers=body.get('supplier_ids') or []
  with e.begin() as c:
   c.execute(text('''INSERT INTO procurement_rfqs(rfq_id,organization_id,entity_id,location_id,material_master_id,required_qty,uom,required_date,supplier_ids,created_by) VALUES(:i,:o,:e,:l,:m,:q,:u,:d,:s,:by)'''),{'i':rid,'o':body['organization_id'],'e':body['entity_id'],'l':body['location_id'],'m':body['material_master_id'],'q':float(body.get('required_qty',0)),'u':body['uom'],'d':body.get('required_date'),'s':','.join(map(str,suppliers)),'by':str(u.user_id)})
  return {'rfq_id':rid,'status':'DRAFT','supplier_count':len(suppliers)}
 @app.post('/v90cs/procurement/rfq/{rfq_id}/quotes')
 def quote(rfq_id:str,body:dict,request:Request):
  _perm(e,request,'proc_plan.manage')
  if not body.get('supplier_id'): raise HTTPException(400,'supplier_id is required')
  qid=str(uuid4())
  with e.begin() as c:
   if not c.execute(text('SELECT 1 FROM procurement_rfqs WHERE rfq_id=:i'),{'i':rfq_id}).first(): raise HTTPException(404,'RFQ not found')
   c.execute(text('''INSERT INTO procurement_quotes(quote_id,rfq_id,supplier_id,unit_price,landed_cost,lead_time_days,quality_score) VALUES(:i,:r,:s,:p,:lc,:l,:q)'''),{'i':qid,'r':rfq_id,'s':body['supplier_id'],'p':float(body.get('unit_price',0)),'lc':float(body.get('landed_cost',body.get('unit_price',0))),'l':int(body.get('lead_time_days',0)),'q':float(body.get('quality_score',0))})
  return {'quote_id':qid,'status':'RECEIVED'}
 @app.get('/v90cs/procurement/rfq/{rfq_id}/compare')
 def compare(rfq_id:str,request:Request):
  _perm(e,request,'proc_plan.view')
  with e.connect() as c: rows=c.execute(text('SELECT * FROM procurement_quotes WHERE rfq_id=:i ORDER BY landed_cost ASC,lead_time_days ASC'),{'i':rfq_id}).mappings().all()
  return {'rfq_id':rfq_id,'quotes':[dict(x) for x in rows],'recommended_quote':dict(rows[0]) if rows else None}
 @app.post('/v90cs/procurement/requisitions/from-suggestion')
 def from_suggestion(body:dict,request:Request):
  u=_perm(e,request,'proc_plan.manage'); sid=body.get('suggestion_id')
  with e.begin() as c:
   s=c.execute(text('SELECT * FROM replenishment_suggestions WHERE suggestion_id=:i AND status=\'APPROVED\''),{'i':sid}).mappings().first()
   if not s: raise HTTPException(404,'approved replenishment suggestion not found')
   rid=str(uuid4()); c.execute(text('''INSERT INTO procurement_requisitions(requisition_id,organization_id,entity_id,location_id,material_master_id,supplier_id,qty,uom,required_date,source_suggestion_id,created_by) VALUES(:i,:o,:e,:l,:m,:s,:q,:u,:d,:x,:by)'''),{'i':rid,'o':s['organization_id'],'e':s['entity_id'],'l':s['location_id'],'m':s['material_master_id'],'s':s['supplier_id'],'q':float(s['suggested_qty']),'u':s['uom'],'d':s['required_date'],'x':sid,'by':str(u.user_id)})
   c.execute(text("UPDATE replenishment_suggestions SET status='CONVERTED' WHERE suggestion_id=:i"),{'i':sid})
  return {'requisition_id':rid,'status':'DRAFT','source_suggestion_id':sid}
 @app.post('/v90cs/procurement/requisitions/{rid}/approve')
 def approve(rid:str,request:Request):
  u=_perm(e,request,'proc_plan.approve')
  with e.begin() as c:
   r=c.execute(text("UPDATE procurement_requisitions SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE requisition_id=:i AND status='DRAFT' RETURNING requisition_id"),{'i':rid,'u':str(u.user_id)}).first()
   if not r: raise HTTPException(409,'requisition not found or already processed')
  return {'requisition_id':rid,'status':'APPROVED'}
 @app.get('/ui/procurement-planning')
 def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'procurement-planning.html')
