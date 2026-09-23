from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def perm(e, r, p):
    u = authenticate(r); ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403, 'permission denied')
    return u

def valid(pk):
    try:
        y,m = map(int, pk.split('-'))
        if y < 2000 or not 1 <= m <= 12: raise ValueError
    except Exception: raise HTTPException(400, 'period_key must be YYYY-MM')

def score(control, effectiveness, target, adoption):
    return d(Decimal(str(control or 0))*Decimal('.35') + Decimal(str(effectiveness or 0))*Decimal('.25') + Decimal(str(target or 0))*Decimal('.20') + Decimal(str(adoption or 0))*Decimal('.20'))

def assessment(s, gap):
    if s >= 80: return 'BEST_PRACTICE'
    if s >= 65: return 'STRONG'
    if s >= 50: return 'WATCH'
    return 'BENCHMARK_EXCEPTION' if gap >= 15 else 'NEEDS_IMPROVEMENT'

def register_v90fb_routes(app: FastAPI, e):
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_benchmark_snapshot(
            benchmark_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, scope_name TEXT, control_score NUMERIC NOT NULL DEFAULT 0,
            effectiveness_score NUMERIC NOT NULL DEFAULT 0, target_met_pct NUMERIC NOT NULL DEFAULT 0, adoption_pct NUMERIC NOT NULL DEFAULT 0,
            failed_change_count INTEGER NOT NULL DEFAULT 0, repeat_failure_count INTEGER NOT NULL DEFAULT 0, benchmark_score NUMERIC NOT NULL DEFAULT 0,
            benchmark_rank INTEGER NOT NULL DEFAULT 0, peer_count INTEGER NOT NULL DEFAULT 0, benchmark_gap NUMERIC NOT NULL DEFAULT 0,
            assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', recommendation TEXT, status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,scope_type,scope_id))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_reliability_benchmark_scope ON maintenance_reliability_benchmark_snapshot(organization_id,period_key,scope_type,benchmark_rank,assessment)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_benchmark_exception(
            exception_id TEXT PRIMARY KEY, benchmark_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'MEDIUM',
            reason TEXT NOT NULL, recommended_action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', resolved_by TEXT,
            resolved_at TIMESTAMP, resolution_note TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_reliability_benchmark_exception_scope ON maintenance_reliability_benchmark_exception(organization_id,period_key,status,severity,scope_type)'))
        for p,n in [('maintenance_reliability_benchmark.view','View Enterprise Reliability Benchmarks'),('maintenance_reliability_benchmark.manage','Manage Enterprise Reliability Benchmarks'),('maintenance_reliability_benchmark.close','Close Enterprise Reliability Benchmark Period')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p':p,'n':n})

    @app.post('/v90fb/maintenance/reliability-benchmark/snapshot')
    def snapshot(body: dict, request: Request):
        u=perm(e,request,'maintenance_reliability_benchmark.manage')
        o,pk=body.get('organization_id'),body.get('period_key'); entity_filter=body.get('entity_id')
        if not o or not pk: raise HTTPException(400,'organization_id and period_key are required')
        valid(pk)
        with e.begin() as c:
            q='SELECT * FROM maintenance_reliability_executive_control_snapshot WHERE organization_id=:o AND period_key=:p'
            params={'o':o,'p':pk}
            if entity_filter: q += ' AND entity_id=:e'; params['e']=entity_filter
            entities=c.execute(text(q),params).mappings().all()
            if not entities: raise HTTPException(404,'executive reliability control snapshot not found')
            out=[]
            for x in entities:
                adoption=c.execute(text('''SELECT AVG(adoption_pct) FROM maintenance_reliability_standard_deployment WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='ACTIVE' '''),{'o':o,'e':x['entity_id'],'p':pk}).scalar() or 0
                out.append({'organization_id':o,'entity_id':x['entity_id'],'scope_type':'ENTITY','scope_id':x['entity_id'],'scope_name':x['entity_id'],'control_score':d(x['control_score']),'effectiveness_score':d(x['effectiveness_score']),'target_met_pct':d(x['target_met_pct']),'adoption_pct':d(adoption),'failed_change_count':int(x['failed_change_count'] or 0),'repeat_failure_count':int(x['repeat_failure_count'] or 0)})
            # Work-center benchmarks use effectiveness observations, while entity benchmarks use executive controls.
            wq='''SELECT organization_id,entity_id,period_key,work_center_id,AVG(actual_effectiveness_score) effectiveness_score,
                    AVG(target_met) target_met_pct,SUM(failure_flag) failed_change_count,SUM(repeat_failure_count) repeat_failure_count
                    FROM maintenance_reliability_change_effectiveness_snapshot WHERE organization_id=:o AND period_key=:p AND work_center_id IS NOT NULL'''
            wp={'o':o,'p':pk}
            if entity_filter: wq += ' AND entity_id=:e'; wp['e']=entity_filter
            wq += ' GROUP BY organization_id,entity_id,period_key,work_center_id'
            for x in c.execute(text(wq),wp).mappings().all():
                adoption=c.execute(text('''SELECT AVG(adoption_pct) FROM maintenance_reliability_standard_deployment WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND work_center_id=:w AND status='ACTIVE' '''),{'o':o,'e':x['entity_id'],'p':pk,'w':x['work_center_id']}).scalar()
                adoption=0 if adoption is None else adoption
                # Work-center control is not independently stored; use effectiveness as the available normalized control proxy.
                out.append({'organization_id':o,'entity_id':x['entity_id'],'scope_type':'WORK_CENTER','scope_id':x['work_center_id'],'scope_name':x['work_center_id'],'control_score':d(x['effectiveness_score']),'effectiveness_score':d(x['effectiveness_score']),'target_met_pct':d(float(x['target_met_pct'] or 0)*100),'adoption_pct':d(adoption),'failed_change_count':int(x['failed_change_count'] or 0),'repeat_failure_count':int(x['repeat_failure_count'] or 0)})
            # Rank only against comparable peers in the same organization, period and scope type.
            groups={}
            for x in out: groups.setdefault(x['scope_type'],[]).append(x)
            for typ,items in groups.items():
                for x in items: x['benchmark_score']=score(x['control_score'],x['effectiveness_score'],x['target_met_pct'],x['adoption_pct'])
                items.sort(key=lambda z:(-float(z['benchmark_score']),z['scope_id']))
                top=float(items[0]['benchmark_score']) if items else 0
                for rank,x in enumerate(items,1):
                    x['benchmark_rank']=rank; x['peer_count']=len(items); x['benchmark_gap']=d(Decimal(str(top))-Decimal(str(x['benchmark_score'])))
                    x['assessment']=assessment(Decimal(str(x['benchmark_score'])),Decimal(str(x['benchmark_gap'])))
                    x['recommendation']='Retain as internal best practice and review for controlled replication.' if x['assessment']=='BEST_PRACTICE' else ('Open benchmark exception and identify a validated peer practice for improvement.' if x['assessment']=='BENCHMARK_EXCEPTION' else 'Review gap to top peer and define a controlled improvement action.')
                    bid=str(uuid4())
                    c.execute(text('''INSERT INTO maintenance_reliability_benchmark_snapshot(benchmark_id,organization_id,entity_id,period_key,scope_type,scope_id,scope_name,control_score,effectiveness_score,target_met_pct,adoption_pct,failed_change_count,repeat_failure_count,benchmark_score,benchmark_rank,peer_count,benchmark_gap,assessment,recommendation,status,created_by) VALUES(:id,:o,:e,:p,:t,:sid,:sn,:cs,:es,:tm,:ad,:fc,:rf,:bs,:rank,:pc,:gap,:a,:r,'OPEN',:u) ON CONFLICT(organization_id,entity_id,period_key,scope_type,scope_id) DO UPDATE SET scope_name=:sn,control_score=:cs,effectiveness_score=:es,target_met_pct=:tm,adoption_pct=:ad,failed_change_count=:fc,repeat_failure_count=:rf,benchmark_score=:bs,benchmark_rank=:rank,peer_count=:pc,benchmark_gap=:gap,assessment=:a,recommendation=:r,created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'id':bid,'o':x['organization_id'],'e':x['entity_id'],'p':pk,'t':x['scope_type'],'sid':x['scope_id'],'sn':x['scope_name'],'cs':float(x['control_score']),'es':float(x['effectiveness_score']),'tm':float(x['target_met_pct']),'ad':float(x['adoption_pct']),'fc':x['failed_change_count'],'rf':x['repeat_failure_count'],'bs':float(x['benchmark_score']),'rank':x['benchmark_rank'],'pc':x['peer_count'],'gap':float(x['benchmark_gap']),'a':x['assessment'],'r':x['recommendation'],'u':str(u.user_id)})
                    if x['assessment']=='BENCHMARK_EXCEPTION' and x['benchmark_gap']>=15:
                        sev='HIGH' if x['benchmark_gap']>=25 else 'MEDIUM'
                        c.execute(text('''INSERT INTO maintenance_reliability_benchmark_exception(exception_id,benchmark_id,organization_id,entity_id,period_key,scope_type,scope_id,severity,reason,recommended_action,created_by) VALUES(:id,:b,:o,:e,:p,:t,:sid,:sev,:reason,:act,:u)'''),{'id':str(uuid4()),'b':bid,'o':x['organization_id'],'e':x['entity_id'],'p':pk,'t':x['scope_type'],'sid':x['scope_id'],'sev':sev,'reason':f"Benchmark score {x['benchmark_score']} trails the best peer by {x['benchmark_gap']} points.",'act':'Review validated internal best practice and raise a controlled reliability improvement proposal.','u':str(u.user_id)})
            return {'period_key':pk,'organization_id':o,'benchmark_count':len(out),'entity_benchmark_count':sum(x['scope_type']=='ENTITY' for x in out),'work_center_benchmark_count':sum(x['scope_type']=='WORK_CENTER' for x in out),'causal_attribution':False,'automatic_operational_mutation':False}

    @app.get('/v90fb/maintenance/reliability-benchmark/dashboard')
    def dashboard(request:Request,organization_id:str,period_key:str,scope_type:str|None=None):
        perm(e,request,'maintenance_reliability_benchmark.view'); valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_benchmark_snapshot WHERE organization_id=:o AND period_key=:p'; p={'o':organization_id,'p':period_key}
            if scope_type: q+=' AND scope_type=:t'; p['t']=scope_type.upper()
            rows=c.execute(text(q+' ORDER BY scope_type,benchmark_rank'),p).mappings().all()
            ex=c.execute(text('SELECT * FROM maintenance_reliability_benchmark_exception WHERE organization_id=:o AND period_key=:p AND status=\'OPEN\' ORDER BY severity DESC'),p if not scope_type else {'o':organization_id,'p':period_key}).mappings().all()
        return {'period_key':period_key,'organization_id':organization_id,'benchmark_count':len(rows),'best_score':max([float(x['benchmark_score']) for x in rows],default=0),'open_exception_count':len(ex),'rows':[dict(x) for x in rows],'exceptions':[dict(x) for x in ex],'causal_attribution':False}

    @app.get('/v90fb/maintenance/reliability-benchmark/ranking')
    def ranking(request:Request,organization_id:str,period_key:str,scope_type:str='ENTITY'):
        perm(e,request,'maintenance_reliability_benchmark.view'); valid(period_key)
        with e.connect() as c:
            rows=c.execute(text('SELECT * FROM maintenance_reliability_benchmark_snapshot WHERE organization_id=:o AND period_key=:p AND scope_type=:t ORDER BY benchmark_rank'),{'o':organization_id,'p':period_key,'t':scope_type.upper()}).mappings().all()
        return {'scope_type':scope_type.upper(),'peer_count':len(rows),'ranking':[dict(x) for x in rows],'causal_attribution':False}

    @app.get('/v90fb/maintenance/reliability-benchmark/exceptions')
    def exceptions(request:Request,organization_id:str,period_key:str,status:str='OPEN'):
        perm(e,request,'maintenance_reliability_benchmark.view'); valid(period_key)
        with e.connect() as c:
            rows=c.execute(text('SELECT * FROM maintenance_reliability_benchmark_exception WHERE organization_id=:o AND period_key=:p AND status=:s ORDER BY CASE severity WHEN \'HIGH\' THEN 1 WHEN \'MEDIUM\' THEN 2 ELSE 3 END,created_at'),{'o':organization_id,'p':period_key,'s':status.upper()}).mappings().all()
        return {'count':len(rows),'exceptions':[dict(x) for x in rows]}

    @app.post('/v90fb/maintenance/reliability-benchmark/exceptions/{exception_id}/resolve')
    def resolve(exception_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_benchmark.manage'); note=str(body.get('resolution_note') or '').strip()
        if not note: raise HTTPException(400,'resolution_note is required')
        with e.begin() as c:
            x=c.execute(text('SELECT exception_id FROM maintenance_reliability_benchmark_exception WHERE exception_id=:i'),{'i':exception_id}).first()
            if not x: raise HTTPException(404,'benchmark exception not found')
            c.execute(text("UPDATE maintenance_reliability_benchmark_exception SET status='RESOLVED',resolved_by=:u,resolved_at=CURRENT_TIMESTAMP,resolution_note=:n WHERE exception_id=:i"),{'u':str(u.user_id),'n':note,'i':exception_id})
        return {'exception_id':exception_id,'status':'RESOLVED'}

    @app.post('/v90fb/maintenance/reliability-benchmark/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_benchmark.close'); valid(period_key); o=body.get('organization_id')
        if not o: raise HTTPException(400,'organization_id is required')
        with e.begin() as c:
            open_count=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_benchmark_exception WHERE organization_id=:o AND period_key=:p AND status='OPEN'"),{'o':o,'p':period_key}).scalar() or 0
            if open_count and not body.get('force'): raise HTTPException(409,f'{open_count} open benchmark exceptions remain; resolve them or use force=true')
            c.execute(text("UPDATE maintenance_reliability_benchmark_snapshot SET status='CLOSED' WHERE organization_id=:o AND period_key=:p"),{'o':o,'p':period_key})
        return {'organization_id':o,'period_key':period_key,'status':'CLOSED','open_exception_count':int(open_count),'forced':bool(body.get('force'))}

    @app.get('/ui/maintenance-reliability-benchmark')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-benchmark.html')
