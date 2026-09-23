from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from datetime import date, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def register_v90df_routes(app: FastAPI, e):
    with e.begin() as c:
        for p,n in [('traceability.view','View Food Traceability'),('traceability.manage','Manage Food Traceability'),('traceability.release','Release Traceability'),('traceability.recall','Manage Recall Impact')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS product_shelf_life(policy_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,product_id TEXT NOT NULL,shelf_days INTEGER NOT NULL,fefo_required BOOLEAN NOT NULL DEFAULT TRUE,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS batch_shelf_life(batch_life_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,product_id TEXT NOT NULL,manufactured_on DATE NOT NULL,expiry_on DATE NOT NULL,status TEXT NOT NULL DEFAULT 'VALID',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS quality_coa(coa_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,inspection_id TEXT,coa_no TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'DRAFT',issued_at TIMESTAMP,issued_by TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS product_nutrition(product_nutrition_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,product_id TEXT NOT NULL,serving_size TEXT,energy_kcal NUMERIC,protein_g NUMERIC,carbohydrate_g NUMERIC,fat_g NUMERIC,sodium_mg NUMERIC,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS batch_allergen(batch_allergen_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,allergen_code TEXT NOT NULL,source TEXT NOT NULL DEFAULT 'BOM',contains BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS recall_impact(impact_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',affected_qty NUMERIC NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS capa_effectiveness(effectiveness_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,capa_id TEXT NOT NULL,evidence TEXT NOT NULL,effective BOOLEAN NOT NULL,verified_by TEXT NOT NULL,verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE INDEX IF NOT EXISTS ix_batch_life_expiry ON batch_shelf_life(organization_id,entity_id,product_id,expiry_on,status)'''))

    @app.post('/v90df/traceability/shelf-life')
    def shelf_life(b:dict,request:Request):
        u=_perm(e,request,'traceability.manage')
        for k in ('organization_id','entity_id','product_id','shelf_days'):
            if b.get(k) in (None,''): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO product_shelf_life(policy_id,organization_id,entity_id,product_id,shelf_days,fefo_required,active,created_by) VALUES(:i,:o,:e,:p,:d,:f,:a,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'p':b['product_id'],'d':int(b['shelf_days']),'f':bool(b.get('fefo_required',True)),'a':bool(b.get('active',True)),'u':str(u.user_id)})
        return {'policy_id':i,'status':'ACTIVE'}

    @app.post('/v90df/traceability/batches/{batch_id}/shelf-life')
    def batch_life(batch_id:str,b:dict,request:Request):
        u=_perm(e,request,'traceability.manage')
        for k in ('organization_id','entity_id','product_id','manufactured_on'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        with e.begin() as c:
            policy=c.execute(text('SELECT shelf_days FROM product_shelf_life WHERE organization_id=:o AND entity_id=:e AND product_id=:p AND active=TRUE ORDER BY created_at DESC LIMIT 1'),{'o':b['organization_id'],'e':b['entity_id'],'p':b['product_id']}).scalar()
            if policy is None: raise HTTPException(409,'active shelf-life policy not found')
            i=str(uuid4())
            manufactured=date.fromisoformat(str(b['manufactured_on']))
            expiry=manufactured + timedelta(days=int(policy))
            c.execute(text('''INSERT INTO batch_shelf_life(batch_life_id,organization_id,entity_id,batch_id,product_id,manufactured_on,expiry_on,created_by) VALUES(:i,:o,:e,:b,:p,:m,:x,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'b':batch_id,'p':b['product_id'],'m':manufactured.isoformat(),'x':expiry.isoformat(),'u':str(u.user_id)})
        return {'batch_life_id':i,'batch_id':batch_id,'shelf_days':int(policy),'status':'VALID'}

    @app.post('/v90df/traceability/coas')
    def coa(b:dict,request:Request):
        u=_perm(e,request,'traceability.manage')
        for k in ('organization_id','entity_id','batch_id','coa_no'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO quality_coa(coa_id,organization_id,entity_id,batch_id,inspection_id,coa_no,created_by) VALUES(:i,:o,:e,:b,:x,:n,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'b':b['batch_id'],'x':b.get('inspection_id'),'n':b['coa_no'],'u':str(u.user_id)})
        return {'coa_id':i,'status':'DRAFT'}

    @app.post('/v90df/traceability/coas/{coa_id}/issue')
    def issue_coa(coa_id:str,request:Request):
        u=_perm(e,request,'traceability.release')
        with e.begin() as c:
            row=c.execute(text('SELECT batch_id FROM quality_coa WHERE coa_id=:i'),{'i':coa_id}).first()
            if not row: raise HTTPException(404,'COA not found')
            c.execute(text("UPDATE quality_coa SET status='ISSUED',issued_at=CURRENT_TIMESTAMP,issued_by=:u WHERE coa_id=:i"),{'u':str(u.user_id),'i':coa_id})
        return {'coa_id':coa_id,'status':'ISSUED'}

    @app.post('/v90df/traceability/nutrition')
    def nutrition(b:dict,request:Request):
        u=_perm(e,request,'traceability.manage')
        for k in ('organization_id','entity_id','product_id'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO product_nutrition(product_nutrition_id,organization_id,entity_id,product_id,serving_size,energy_kcal,protein_g,carbohydrate_g,fat_g,sodium_mg,created_by) VALUES(:i,:o,:e,:p,:s,:k,:pr,:c,:f,:n,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'p':b['product_id'],'s':b.get('serving_size'),'k':b.get('energy_kcal'),'pr':b.get('protein_g'),'c':b.get('carbohydrate_g'),'f':b.get('fat_g'),'n':b.get('sodium_mg'),'u':str(u.user_id)})
        return {'product_nutrition_id':i,'status':'ACTIVE'}

    @app.post('/v90df/traceability/batches/{batch_id}/allergens/propagate')
    def allergens(batch_id:str,b:dict,request:Request):
        u=_perm(e,request,'traceability.manage')
        codes=b.get('allergen_codes') or []
        if not isinstance(codes,list): raise HTTPException(400,'allergen_codes must be a list')
        with e.begin() as c:
            for code in codes:
                c.execute(text('''INSERT INTO batch_allergen(batch_allergen_id,organization_id,entity_id,batch_id,allergen_code,source,contains,created_by) VALUES(:i,:o,:e,:b,:a,'BOM',TRUE,:u)'''),{'i':str(uuid4()),'o':b['organization_id'],'e':b['entity_id'],'b':batch_id,'a':str(code),'u':str(u.user_id)})
        return {'batch_id':batch_id,'propagated':len(codes)}

    @app.post('/v90df/traceability/recall-impact')
    def recall(b:dict,request:Request):
        u=_perm(e,request,'traceability.recall')
        for k in ('organization_id','entity_id','batch_id','reason'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO recall_impact(impact_id,organization_id,entity_id,batch_id,reason,affected_qty,created_by) VALUES(:i,:o,:e,:b,:r,:q,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'b':b['batch_id'],'r':b['reason'],'q':float(b.get('affected_qty') or 0),'u':str(u.user_id)})
        return {'impact_id':i,'status':'OPEN'}

    @app.post('/v90df/traceability/capa-effectiveness')
    def effectiveness(b:dict,request:Request):
        u=_perm(e,request,'traceability.manage')
        for k in ('organization_id','entity_id','capa_id','evidence'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO capa_effectiveness(effectiveness_id,organization_id,entity_id,capa_id,evidence,effective,verified_by) VALUES(:i,:o,:e,:c,:x,:ok,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'c':b['capa_id'],'x':b['evidence'],'ok':bool(b.get('effective',False)),'u':str(u.user_id)})
        return {'effectiveness_id':i,'status':'VERIFIED'}

    @app.get('/v90df/traceability/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'traceability.view')
        with e.connect() as c:
            exp=c.execute(text("SELECT COUNT(*) FROM batch_shelf_life WHERE organization_id=:o AND entity_id=:e AND expiry_on < CURRENT_DATE AND status='VALID'"),{'o':organization_id,'e':entity_id}).scalar_one()
            coa=c.execute(text("SELECT COUNT(*) FROM quality_coa WHERE organization_id=:o AND entity_id=:e AND status='DRAFT'"),{'o':organization_id,'e':entity_id}).scalar_one()
            recalls=c.execute(text("SELECT COUNT(*) FROM recall_impact WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),{'o':organization_id,'e':entity_id}).scalar_one()
            ineffective=c.execute(text("SELECT COUNT(*) FROM capa_effectiveness WHERE organization_id=:o AND entity_id=:e AND effective=FALSE"),{'o':organization_id,'e':entity_id}).scalar_one()
        return {'expired_batches':int(exp),'draft_coas':int(coa),'open_recall_impacts':int(recalls),'ineffective_capa_verifications':int(ineffective)}

    @app.get('/ui/food-traceability')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'food-traceability.html')
