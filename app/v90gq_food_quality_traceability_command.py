from __future__ import annotations
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _perm(engine, request, permission):
    u=authenticate(request); ps=permissions_for_user(engine,u.user_id)
    if permission not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def register_v90gq_routes(app: FastAPI, engine):
    with engine.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS erp_food_quality_traceability_snapshot (snapshot_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NULL,from_date TEXT NOT NULL,to_date TEXT NOT NULL,batches_reviewed INTEGER NOT NULL DEFAULT 0,inspections_reviewed INTEGER NOT NULL DEFAULT 0,released_batches INTEGER NOT NULL DEFAULT 0,held_batches INTEGER NOT NULL DEFAULT 0,failed_inspections INTEGER NOT NULL DEFAULT 0,open_nc INTEGER NOT NULL DEFAULT 0,open_capa INTEGER NOT NULL DEFAULT 0,traceable_batches INTEGER NOT NULL DEFAULT 0,traceability_pct NUMERIC NOT NULL DEFAULT 0,release_readiness_pct NUMERIC NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,location_id,from_date,to_date))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS erp_food_quality_traceability_actions (action_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NULL,batch_id TEXT NULL,action_type TEXT NOT NULL,priority TEXT NOT NULL DEFAULT 'MEDIUM',reason TEXT NOT NULL,owner_user_id TEXT NULL,due_date TEXT NULL,status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,closed_at TIMESTAMP NULL)'''))
        for p,n in [('quality.traceability.view','View Quality Traceability'),('quality.traceability.manage','Manage Quality Traceability')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        for role,perm in [('manager','quality.view'),('manager','quality.manage'),('mis','quality.view')]:
            c.execute(text('INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING'),{'r':role,'p':perm})
    @app.get('/ui/food-quality-traceability')
    def ui(): return FileResponse('web/food-quality-traceability-command.html')

    @app.get('/v90gq/food-quality-traceability')
    def dashboard(organization_id:str,entity_id:str,location_id:str|None=None,from_date:str|None=None,to_date:str|None=None,request:Request=None):
        _perm(engine,request,'quality.view')
        fd=from_date or '1900-01-01'; td=to_date or '2999-12-31'
        with engine.connect() as c:
            base={'o':organization_id,'e':entity_id,'l':location_id,'fd':fd,'td':td}
            batches=c.execute(text("SELECT COUNT(*) FROM production_batch WHERE organization_id=:o AND entity_id=:e AND DATE(created_at) BETWEEN :fd AND :td"),base).scalar_one()
            inspections=c.execute(text("SELECT COUNT(*) FROM quality_inspection WHERE organization_id=:o AND entity_id=:e AND DATE(created_at) BETWEEN :fd AND :td"),base).scalar_one()
            released=c.execute(text("SELECT COUNT(DISTINCT batch_id) FROM quality_inspection WHERE organization_id=:o AND entity_id=:e AND status='RELEASED' AND DATE(created_at) BETWEEN :fd AND :td"),base).scalar_one()
            held=c.execute(text("SELECT COUNT(DISTINCT batch_id) FROM quality_inspection WHERE organization_id=:o AND entity_id=:e AND status='HOLD' AND DATE(created_at) BETWEEN :fd AND :td"),base).scalar_one()
            failed=c.execute(text("SELECT COUNT(*) FROM quality_result r JOIN quality_inspection i ON i.inspection_id=r.inspection_id WHERE i.organization_id=:o AND i.entity_id=:e AND r.pass=FALSE AND DATE(r.created_at) BETWEEN :fd AND :td"),base).scalar_one()
            nc=c.execute(text("SELECT COUNT(*) FROM quality_nc WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),base).scalar_one()
            capa=c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),base).scalar_one()
            traceable=c.execute(text("SELECT COUNT(DISTINCT f.batch_id) FROM packed_fg_lot p JOIN finished_goods_lot f ON f.fg_lot_id=p.source_fg_lot_id JOIN production_batch b ON b.batch_id=f.batch_id WHERE b.organization_id=:o AND b.entity_id=:e AND (:l IS NULL OR b.location_id=:l) AND DATE(b.created_at) BETWEEN :fd AND :td"),base).scalar_one()
        trace_pct=round((traceable/batches*100) if batches else 100.0,2)
        readiness=round(((released)/(batches)*100) if batches else 100.0,2)
        return {'from_date':fd,'to_date':td,'batches_reviewed':batches,'inspections_reviewed':inspections,'released_batches':released,'held_batches':held,'failed_inspections':failed,'open_nc':nc,'open_capa':capa,'traceable_batches':traceable,'traceability_pct':trace_pct,'release_readiness_pct':readiness}

    @app.post('/v90gq/food-quality-traceability/snapshots')
    def snapshot(body:dict,request:Request):
        u=_perm(engine,request,'quality.manage')
        q=dashboard(body['organization_id'],body['entity_id'],body.get('location_id'),body.get('from_date'),body.get('to_date'),request)
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO erp_food_quality_traceability_snapshot(snapshot_id,organization_id,entity_id,location_id,from_date,to_date,batches_reviewed,inspections_reviewed,released_batches,held_batches,failed_inspections,open_nc,open_capa,traceable_batches,traceability_pct,release_readiness_pct,created_by) VALUES(:i,:o,:e,:l,:fd,:td,:b,:ins,:r,:h,:f,:n,:ca,:tr,:tp,:rp,:u) ON CONFLICT(organization_id,entity_id,location_id,from_date,to_date) DO UPDATE SET batches_reviewed=:b,inspections_reviewed=:ins,released_batches=:r,held_batches=:h,failed_inspections=:f,open_nc=:n,open_capa=:ca,traceable_batches=:tr,traceability_pct=:tp,release_readiness_pct=:rp,created_by=:u'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'l':body.get('location_id'),'fd':q['from_date'],'td':q['to_date'],'b':q['batches_reviewed'],'ins':q['inspections_reviewed'],'r':q['released_batches'],'h':q['held_batches'],'f':q['failed_inspections'],'n':q['open_nc'],'ca':q['open_capa'],'tr':q['traceable_batches'],'tp':q['traceability_pct'],'rp':q['release_readiness_pct'],'u':str(u.user_id)})
        return {'snapshot_id':i,'status':'CREATED',**q}

    @app.post('/v90gq/food-quality-traceability/actions')
    def create_action(body:dict,request:Request):
        u=_perm(engine,request,'quality.manage')
        for k in ('organization_id','entity_id','action_type','reason'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with engine.begin() as c:c.execute(text('''INSERT INTO erp_food_quality_traceability_actions(action_id,organization_id,entity_id,location_id,batch_id,action_type,priority,reason,owner_user_id,due_date,created_by) VALUES(:i,:o,:e,:l,:b,:t,:p,:r,:own,:d,:u)'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'l':body.get('location_id'),'b':body.get('batch_id'),'t':body['action_type'],'p':body.get('priority','MEDIUM'),'r':body['reason'],'own':body.get('owner_user_id'),'d':body.get('due_date'),'u':str(u.user_id)})
        return {'action_id':i,'status':'OPEN'}

    @app.get('/v90gq/food-quality-traceability/actions')
    def list_actions(organization_id:str,entity_id:str,location_id:str|None=None,request:Request=None):
        _perm(engine,request,'quality.view')
        with engine.connect() as c: rows=c.execute(text('SELECT * FROM erp_food_quality_traceability_actions WHERE organization_id=:o AND entity_id=:e ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'l':location_id}).mappings().all()
        return {'actions':[dict(x) for x in rows]}
