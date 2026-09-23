from __future__ import annotations
from datetime import date
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(engine, request, p):
    u=authenticate(request); ps=permissions_for_user(engine,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception: raise HTTPException(400,'period_key must be YYYY-MM')

def register_v90fc_routes(app: FastAPI, e):
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_capa_link(
            link_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            benchmark_id TEXT, exception_id TEXT, capa_id TEXT NOT NULL, trigger_type TEXT NOT NULL,
            recurring_failure_count INTEGER NOT NULL DEFAULT 0, root_cause_summary TEXT, action_summary TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(capa_id,trigger_type))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_capa_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            open_capa_count INTEGER NOT NULL DEFAULT 0, overdue_capa_count INTEGER NOT NULL DEFAULT 0,
            ineffective_capa_count INTEGER NOT NULL DEFAULT 0, effective_capa_pct NUMERIC NOT NULL DEFAULT 0,
            closure_pct NUMERIC NOT NULL DEFAULT 0, control_score NUMERIC NOT NULL DEFAULT 0,
            assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_reliability_capa_link_period ON maintenance_reliability_capa_link(organization_id,period_key,status)'))
        for p,n in [('maintenance_reliability_capa.view','View Reliability CAPA'),('maintenance_reliability_capa.manage','Manage Reliability CAPA'),('maintenance_reliability_capa.close','Close Reliability CAPA Period')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

    @app.post('/v90fc/maintenance/reliability-capa/generate')
    def generate(body:dict, request:Request):
        u=_perm(e,request,'maintenance_reliability_capa.manage'); o=body.get('organization_id'); pk=body.get('period_key'); entity_filter=body.get('entity_id')
        if not o or not pk: raise HTTPException(400,'organization_id and period_key are required')
        _valid(pk)
        with e.begin() as c:
            q='SELECT * FROM maintenance_reliability_benchmark_snapshot WHERE organization_id=:o AND period_key=:p AND (repeat_failure_count>=2 OR assessment=\'BENCHMARK_EXCEPTION\')'; prm={'o':o,'p':pk}
            if entity_filter: q+=' AND entity_id=:e'; prm['e']=entity_filter
            rows=c.execute(text(q),prm).mappings().all(); created=[]
            for r in rows:
                ex=c.execute(text('SELECT exception_id FROM maintenance_reliability_benchmark_exception WHERE benchmark_id=:b AND status=\'OPEN\' ORDER BY created_at LIMIT 1'),{'b':r['benchmark_id']}).scalar()
                trigger='RECURRING_FAILURE' if int(r['repeat_failure_count'] or 0)>=2 else 'BENCHMARK_EXCEPTION'
                existing=c.execute(text('SELECT capa_id FROM maintenance_reliability_capa_link WHERE benchmark_id=:b AND trigger_type=:t'),{'b':r['benchmark_id'],'t':trigger}).scalar()
                if existing: created.append(existing); continue
                capa=str(uuid4()); nc_id=f'RELIABILITY:{r["benchmark_id"]}'
                root=f'Reliability trigger: {trigger}; repeat failures={int(r["repeat_failure_count"] or 0)}; benchmark gap={r["benchmark_gap"]}.'
                action='Perform documented root-cause analysis, assign corrective/preventive actions, and verify effectiveness before closure.'
                c.execute(text('''INSERT INTO quality_capa(capa_id,nc_id,organization_id,entity_id,root_cause,corrective_action,preventive_action,due_date,status,owner_user_id,created_by)
                    VALUES(:i,:n,:o,:e,:r,:ca,:pa,:d,'OPEN',:own,:by)'''),{'i':capa,'n':nc_id,'o':o,'e':r['entity_id'],'r':root,'ca':action,'pa':'Review and update the controlled reliability standard/maintenance practice after verified CAPA effectiveness.','d':body.get('due_date'),'own':body.get('owner_user_id'),'by':str(u.user_id)})
                c.execute(text('''INSERT INTO maintenance_reliability_capa_link(link_id,organization_id,entity_id,period_key,benchmark_id,exception_id,capa_id,trigger_type,recurring_failure_count,root_cause_summary,action_summary,created_by)
                    VALUES(:i,:o,:e,:p,:b,:x,:c,:t,:r,:rc,:a,:u)'''),{'i':str(uuid4()),'o':o,'e':r['entity_id'],'p':pk,'b':r['benchmark_id'],'x':ex,'c':capa,'t':trigger,'r':int(r['repeat_failure_count'] or 0),'rc':root,'a':action,'u':str(u.user_id)})
                created.append(capa)
        return {'organization_id':o,'period_key':pk,'created_count':len(created),'capa_ids':created,'automatic_operational_mutation':False}

    @app.post('/v90fc/maintenance/reliability-capa/{capa_id}/effectiveness')
    def effectiveness(capa_id:str, body:dict, request:Request):
        u=_perm(e,request,'maintenance_reliability_capa.manage'); evidence=str(body.get('evidence') or '').strip()
        if not evidence: raise HTTPException(400,'evidence is required')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,entity_id,status FROM quality_capa WHERE capa_id=:i'),{'i':capa_id}).mappings().first()
            if not row: raise HTTPException(404,'CAPA not found')
            eid=str(uuid4()); effective=bool(body.get('effective',False))
            c.execute(text('''INSERT INTO capa_effectiveness(effectiveness_id,organization_id,entity_id,capa_id,evidence,effective,verified_by) VALUES(:i,:o,:e,:c,:x,:ok,:u)'''),{'i':eid,'o':row['organization_id'],'e':row['entity_id'],'c':capa_id,'x':evidence,'ok':effective,'u':str(u.user_id)})
            if effective and body.get('close',True): c.execute(text("UPDATE quality_capa SET status='CLOSED',closed_at=CURRENT_TIMESTAMP WHERE capa_id=:i"),{'i':capa_id})
        return {'capa_id':capa_id,'effectiveness_id':eid,'effective':effective,'status':'CLOSED' if effective and body.get('close',True) else 'OPEN'}

    @app.get('/v90fc/maintenance/reliability-capa/dashboard')
    def dashboard(organization_id:str, period_key:str, entity_id:str|None=None, request:Request=None):
        _perm(e,request,'maintenance_reliability_capa.view'); _valid(period_key)
        with e.begin() as c:
            q='SELECT entity_id FROM maintenance_reliability_capa_link WHERE organization_id=:o AND period_key=:p'; prm={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND entity_id=:e'; prm['e']=entity_id
            entities={r[0] for r in c.execute(text(q),prm).all()}
            if entity_id: entities.add(entity_id)
            out=[]
            for eid in sorted(entities):
                open_n=c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),{'o':organization_id,'e':eid}).scalar() or 0
                overdue=c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND entity_id=:e AND status='OPEN' AND due_date IS NOT NULL AND due_date<CURRENT_DATE"),{'o':organization_id,'e':eid}).scalar() or 0
                total=c.execute(text('SELECT COUNT(*) FROM capa_effectiveness WHERE organization_id=:o AND entity_id=:e'),{'o':organization_id,'e':eid}).scalar() or 0
                ineffective=c.execute(text('SELECT COUNT(*) FROM capa_effectiveness WHERE organization_id=:o AND entity_id=:e AND effective=FALSE'),{'o':organization_id,'e':eid}).scalar() or 0
                effective=max(0,total-ineffective); effpct=(effective/total*100) if total else 0
                closure=100 if open_n==0 and total else max(0,(total-effective)/total*100) if total else 0
                score=max(0,min(100,100-open_n*10-overdue*15-ineffective*10+(effpct*.15)))
                assessment='HEALTHY' if score>=80 else ('WATCH' if score>=60 else 'AT_RISK')
                out.append({'entity_id':eid,'open_capa_count':int(open_n),'overdue_capa_count':int(overdue),'ineffective_capa_count':int(ineffective),'effective_capa_pct':round(effpct,2),'control_score':round(score,2),'assessment':assessment})
            return {'organization_id':organization_id,'period_key':period_key,'entities':out,'capa_count':sum(x['open_capa_count'] for x in out),'overdue_count':sum(x['overdue_capa_count'] for x in out)}

    @app.get('/v90fc/maintenance/reliability-capa/overdue')
    def overdue(organization_id:str, request:Request, entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_capa.view')
        with e.begin() as c:
            q="SELECT * FROM quality_capa WHERE organization_id=:o AND status='OPEN' AND due_date IS NOT NULL AND due_date<CURRENT_DATE"; p={'o':organization_id}
            if entity_id: q+=' AND entity_id=:e'; p['e']=entity_id
            rows=c.execute(text(q+' ORDER BY due_date'),p).mappings().all()
        return {'count':len(rows),'overdue':rows}

    @app.post('/v90fc/maintenance/reliability-capa/{period_key}/close')
    def close(period_key:str, body:dict, request:Request):
        u=_perm(e,request,'maintenance_reliability_capa.close'); _valid(period_key); o=body.get('organization_id')
        if not o: raise HTTPException(400,'organization_id is required')
        with e.begin() as c:
            open_n=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_capa_link WHERE organization_id=:o AND period_key=:p AND status='OPEN' AND capa_id IN (SELECT capa_id FROM quality_capa WHERE status='OPEN')"),{'o':o,'p':period_key}).scalar() or 0
            overdue_n=c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND status='OPEN' AND due_date IS NOT NULL AND due_date<CURRENT_DATE"),{'o':o}).scalar() or 0
            if (open_n or overdue_n) and not bool(body.get('force',False)): raise HTTPException(409,f'open reliability CAPA={open_n}, overdue CAPA={overdue_n}; resolve or force close')
            c.execute(text("UPDATE maintenance_reliability_capa_link SET status='CLOSED' WHERE organization_id=:o AND period_key=:p"),{'o':o,'p':period_key})
        return {'organization_id':o,'period_key':period_key,'status':'CLOSED','forced':bool(body.get('force',False)),'closed_by':str(u.user_id)}

    @app.get('/ui/maintenance-reliability-capa')
    def ui():
        return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-capa.html')
