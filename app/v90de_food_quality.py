from __future__ import annotations
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

def register_v90de_routes(app: FastAPI, e):
    with e.begin() as c:
        for p,n in [('quality.view','View Quality'),('quality.manage','Manage Quality'),('quality.release','Release Quality'),('quality.capa','Manage CAPA')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS quality_spec(spec_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,material_or_product_id TEXT NOT NULL,stage TEXT NOT NULL,spec_name TEXT NOT NULL,parameter_code TEXT NOT NULL,unit TEXT,min_value NUMERIC,max_value NUMERIC,required BOOLEAN NOT NULL DEFAULT TRUE,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS quality_sampling_plan(plan_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,stage TEXT NOT NULL,plan_name TEXT NOT NULL,sample_qty NUMERIC NOT NULL DEFAULT 1,frequency TEXT NOT NULL DEFAULT 'BATCH',active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS quality_inspection(inspection_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,stage TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'HOLD',sample_qty NUMERIC NOT NULL DEFAULT 1,coa_no TEXT,remarks TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS quality_result(result_id TEXT PRIMARY KEY,inspection_id TEXT NOT NULL,parameter_code TEXT NOT NULL,value_text TEXT,value_numeric NUMERIC,unit TEXT,pass BOOLEAN NOT NULL,remarks TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS quality_nc(nc_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,inspection_id TEXT,category TEXT NOT NULL,severity TEXT NOT NULL DEFAULT 'MAJOR',description TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,closed_at TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS quality_capa(capa_id TEXT PRIMARY KEY,nc_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,root_cause TEXT,corrective_action TEXT,preventive_action TEXT,due_date DATE,status TEXT NOT NULL DEFAULT 'OPEN',owner_user_id TEXT,closed_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS quality_declaration(declaration_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,product_id TEXT NOT NULL,allergen_code TEXT NOT NULL,contains BOOLEAN NOT NULL DEFAULT TRUE,statement TEXT,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE INDEX IF NOT EXISTS ix_quality_batch ON quality_inspection(organization_id,entity_id,batch_id,status)'''))
    @app.post('/v90de/quality/specs')
    def spec(b:dict,request:Request):
        u=_perm(e,request,'quality.manage')
        for k in ('organization_id','entity_id','material_or_product_id','stage','spec_name','parameter_code'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO quality_spec(spec_id,organization_id,entity_id,material_or_product_id,stage,spec_name,parameter_code,unit,min_value,max_value,required,active,created_by) VALUES(:i,:o,:e,:m,:s,:n,:p,:u,:mn,:mx,:r,:a,:c)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'m':b['material_or_product_id'],'s':b['stage'],'n':b['spec_name'],'p':b['parameter_code'],'u':b.get('unit'),'mn':b.get('min_value'),'mx':b.get('max_value'),'r':bool(b.get('required',True)),'a':bool(b.get('active',True)),'c':str(u.user_id)})
        return {'spec_id':i,'status':'CREATED'}
    @app.post('/v90de/quality/sampling-plans')
    def sampling(b:dict,request:Request):
        u=_perm(e,request,'quality.manage')
        for k in ('organization_id','entity_id','stage','plan_name'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO quality_sampling_plan(plan_id,organization_id,entity_id,stage,plan_name,sample_qty,frequency,active,created_by) VALUES(:i,:o,:e,:s,:n,:q,:f,:a,:c)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'s':b['stage'],'n':b['plan_name'],'q':float(b.get('sample_qty') or 1),'f':b.get('frequency','BATCH'),'a':bool(b.get('active',True)),'c':str(u.user_id)})
        return {'plan_id':i,'status':'ACTIVE'}
    @app.post('/v90de/quality/inspections')
    def inspection(b:dict,request:Request):
        u=_perm(e,request,'quality.manage')
        for k in ('organization_id','entity_id','batch_id','stage'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO quality_inspection(inspection_id,organization_id,entity_id,batch_id,stage,status,sample_qty,coa_no,remarks,created_by) VALUES(:i,:o,:e,:b,:s,'HOLD',:q,:coa,:r,:c)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'b':b['batch_id'],'s':b['stage'],'q':float(b.get('sample_qty') or 1),'coa':b.get('coa_no'),'r':b.get('remarks'),'c':str(u.user_id)})
        return {'inspection_id':i,'status':'HOLD'}
    @app.post('/v90de/quality/inspections/{iid}/results')
    def result(iid:str,b:dict,request:Request):
        u=_perm(e,request,'quality.manage')
        if not str(b.get('parameter_code') or '').strip(): raise HTTPException(400,'parameter_code is required')
        i=str(uuid4())
        with e.begin() as c:
            exists=c.execute(text('SELECT 1 FROM quality_inspection WHERE inspection_id=:i'),{'i':iid}).first()
            if not exists: raise HTTPException(404,'inspection not found')
            c.execute(text('''INSERT INTO quality_result(result_id,inspection_id,parameter_code,value_text,value_numeric,unit,pass,remarks,created_by) VALUES(:i,:x,:p,:t,:v,:u,:ok,:r,:c)'''),{'i':i,'x':iid,'p':b['parameter_code'],'t':b.get('value_text'),'v':b.get('value_numeric'),'u':b.get('unit'),'ok':bool(b.get('pass',False)),'r':b.get('remarks'),'c':str(u.user_id)})
        return {'result_id':i,'status':'RECORDED'}
    @app.post('/v90de/quality/inspections/{iid}/release')
    def release(iid:str,request:Request):
        u=_perm(e,request,'quality.release')
        with e.begin() as c:
            ins=c.execute(text('SELECT organization_id,entity_id,batch_id FROM quality_inspection WHERE inspection_id=:i'),{'i':iid}).mappings().first()
            if not ins: raise HTTPException(404,'inspection not found')
            bad=c.execute(text('SELECT COUNT(*) FROM quality_result WHERE inspection_id=:i AND pass=FALSE'),{'i':iid}).scalar_one()
            if bad: raise HTTPException(409,'inspection has failed results')
            open_nc=c.execute(text("SELECT COUNT(*) FROM quality_nc WHERE batch_id=:b AND status='OPEN'"),{'b':ins['batch_id']}).scalar_one()
            if open_nc: raise HTTPException(409,'batch has open non-conformance')
            c.execute(text("UPDATE quality_inspection SET status='RELEASED',updated_at=CURRENT_TIMESTAMP WHERE inspection_id=:i"),{'i':iid})
        return {'inspection_id':iid,'status':'RELEASED','released_by':str(u.user_id)}
    @app.post('/v90de/quality/nc')
    def nc(b:dict,request:Request):
        u=_perm(e,request,'quality.manage')
        for k in ('organization_id','entity_id','batch_id','category','description'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO quality_nc(nc_id,organization_id,entity_id,batch_id,inspection_id,category,severity,description,created_by) VALUES(:i,:o,:e,:b,:x,:k,:s,:d,:c)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'b':b['batch_id'],'x':b.get('inspection_id'),'k':b['category'],'s':b.get('severity','MAJOR'),'d':b['description'],'c':str(u.user_id)})
        return {'nc_id':i,'status':'OPEN'}
    @app.post('/v90de/quality/capa')
    def capa(b:dict,request:Request):
        u=_perm(e,request,'quality.capa')
        if not str(b.get('nc_id') or '').strip(): raise HTTPException(400,'nc_id is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO quality_capa(capa_id,nc_id,organization_id,entity_id,root_cause,corrective_action,preventive_action,due_date,status,owner_user_id,created_by) VALUES(:i,:n,:o,:e,:r,:c,:p,:d,'OPEN',:own,:by)'''),{'i':i,'n':b['nc_id'],'o':b['organization_id'],'e':b['entity_id'],'r':b.get('root_cause'),'c':b.get('corrective_action'),'p':b.get('preventive_action'),'d':b.get('due_date'),'own':b.get('owner_user_id'),'by':str(u.user_id)})
        return {'capa_id':i,'status':'OPEN'}
    @app.post('/v90de/quality/declarations')
    def declaration(b:dict,request:Request):
        u=_perm(e,request,'quality.manage')
        for k in ('organization_id','entity_id','product_id','allergen_code'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO quality_declaration(declaration_id,organization_id,entity_id,product_id,allergen_code,contains,statement,active,created_by) VALUES(:i,:o,:e,:p,:a,:c,:s,:x,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'p':b['product_id'],'a':b['allergen_code'],'c':bool(b.get('contains',True)),'s':b.get('statement'),'x':bool(b.get('active',True)),'u':str(u.user_id)})
        return {'declaration_id':i,'status':'ACTIVE'}
    @app.get('/v90de/quality/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'quality.view')
        with e.connect() as c:
            holds=c.execute(text("SELECT COUNT(*) FROM quality_inspection WHERE organization_id=:o AND entity_id=:e AND status='HOLD'"),{'o':organization_id,'e':entity_id}).scalar_one()
            open_nc=c.execute(text("SELECT COUNT(*) FROM quality_nc WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),{'o':organization_id,'e':entity_id}).scalar_one()
            capa=c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),{'o':organization_id,'e':entity_id}).scalar_one()
            failed=c.execute(text('SELECT COUNT(*) FROM quality_result r JOIN quality_inspection i ON i.inspection_id=r.inspection_id WHERE i.organization_id=:o AND i.entity_id=:e AND r.pass=FALSE'),{'o':organization_id,'e':entity_id}).scalar_one()
        return {'inspections_on_hold':int(holds),'open_nc':int(open_nc),'open_capa':int(capa),'failed_results':int(failed)}
    @app.get('/ui/food-quality')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'food-quality.html')
