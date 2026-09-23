from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _n(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _perm(engine, request, p):
    u = authenticate(request)
    ps = permissions_for_user(engine, u.user_id)
    if p not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _value(body, key, positive=False):
    if body.get(key) in (None, ''):
        raise HTTPException(400, f'{key} is required')
    v = _n(body[key])
    if positive and v <= 0:
        raise HTTPException(400, f'{key} must be positive')
    return v


def register_v90dy_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p, n in [
            ('workforce_kpi.view', 'View Workforce KPI Scorecards'),
            ('workforce_kpi.manage', 'Manage Workforce KPI Targets'),
            ('workforce_kpi.post', 'Post Workforce KPI Scorecards'),
            ('workforce_kpi.benchmark', 'Run Workforce Productivity Benchmarks'),
            ('workforce_kpi.close', 'Close Workforce KPI Period')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})

    @app.post('/v90dy/workforce/kpi-targets')
    def target(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_kpi.manage')
        for k in ('organization_id','entity_id','kpi_code','kpi_name'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        value = _value(body, 'target_value', positive=True)
        direction = str(body.get('direction') or 'HIGHER_IS_BETTER').upper()
        if direction not in {'HIGHER_IS_BETTER','LOWER_IS_BETTER'}:
            raise HTTPException(400, 'direction must be HIGHER_IS_BETTER or LOWER_IS_BETTER')
        tid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_kpi_target(
                kpi_target_id,organization_id,entity_id,department_id,product_id,kpi_code,kpi_name,target_value,target_uom,direction,effective_from,effective_to,active,created_by)
                VALUES(:id,:o,:e,:d,:prod,:code,:name,:v,:u,:dir,:f,:t,:a,:by)
                ON CONFLICT(organization_id,entity_id,department_id,product_id,kpi_code,effective_from) DO UPDATE SET
                  kpi_name=:name,target_value=:v,target_uom=:u,direction=:dir,effective_to=:t,active=:a'''),
                {'id':tid,'o':body['organization_id'],'e':body['entity_id'],'d':body.get('department_id'),'prod':body.get('product_id'),
                 'code':body['kpi_code'],'name':body['kpi_name'],'v':float(value),'u':body.get('target_uom'),'dir':direction,
                 'f':body.get('effective_from'),'t':body.get('effective_to'),'a':bool(body.get('active',True)),'by':str(u.user_id)})
        return {'kpi_target_id':tid,'target_value':float(value),'direction':direction,'status':'SAVED'}

    @app.post('/v90dy/workforce/kpi-scorecards')
    def scorecard(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_kpi.post')
        for k in ('organization_id','entity_id','period_id','kpi_code'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        actual = _value(body, 'actual_value')
        target = _value(body, 'target_value', positive=True)
        direction = str(body.get('direction') or 'HIGHER_IS_BETTER').upper()
        if direction not in {'HIGHER_IS_BETTER','LOWER_IS_BETTER'}:
            raise HTTPException(400, 'direction must be HIGHER_IS_BETTER or LOWER_IS_BETTER')
        achievement = _n(actual / target * 100) if direction == 'HIGHER_IS_BETTER' else _n(target / actual * 100) if actual else Decimal('0')
        score = min(achievement, Decimal('150'))
        variance = _n(actual-target)
        status = 'ON_TARGET' if achievement >= 100 else 'BELOW_TARGET'
        sid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_kpi_scorecard(
                scorecard_id,organization_id,entity_id,period_id,department_id,product_id,employee_id,kpi_code,actual_value,target_value,variance_value,achievement_pct,efficiency_score,status,created_by)
                VALUES(:id,:o,:e,:p,:d,:prod,:emp,:code,:a,:t,:v,:ach,:score,:s,:by)
                ON CONFLICT(organization_id,entity_id,period_id,department_id,product_id,employee_id,kpi_code) DO UPDATE SET
                  actual_value=:a,target_value=:t,variance_value=:v,achievement_pct=:ach,efficiency_score=:score,status=:s'''),
                {'id':sid,'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'],'d':body.get('department_id'),
                 'prod':body.get('product_id'),'emp':body.get('employee_id'),'code':body['kpi_code'],'a':float(actual),'t':float(target),
                 'v':float(variance),'ach':float(achievement),'score':float(score),'s':status,'by':str(u.user_id)})
        return {'scorecard_id':sid,'variance_value':float(variance),'achievement_pct':float(achievement),'efficiency_score':float(score),'status':status}

    @app.post('/v90dy/workforce/productivity-benchmarks')
    def benchmark(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_kpi.benchmark')
        for k in ('organization_id','entity_id','period_id','kpi_code'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        direction = str(body.get('direction') or 'HIGHER_IS_BETTER').upper()
        if direction not in {'HIGHER_IS_BETTER','LOWER_IS_BETTER'}:
            raise HTTPException(400, 'direction must be HIGHER_IS_BETTER or LOWER_IS_BETTER')
        params={'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'],'code':body['kpi_code']}
        where='organization_id=:o AND entity_id=:e AND period_id=:p AND kpi_code=:code'
        for key,col in [('department_id','department_id'),('product_id','product_id')]:
            if body.get(key) is not None:
                where += f' AND {col}=:_{key}'; params[f'_{key}']=body[key]
        with engine.connect() as c:
            rows=c.execute(text(f'SELECT scorecard_id,actual_value FROM hr_workforce_kpi_scorecard WHERE {where}'),params).mappings().all()
        if not rows:
            raise HTTPException(409,'no KPI scorecards available for benchmark')
        vals=[Decimal(str(r['actual_value'] or 0)) for r in rows]
        ordered=sorted(vals, reverse=(direction=='HIGHER_IS_BETTER'))
        actual=_n(_value(body,'actual_value')) if body.get('actual_value') not in (None,'') else _n(vals[0])
        rank=ordered.index(actual)+1 if actual in ordered else sum(1 for x in ordered if (x >= actual if direction=='HIGHER_IS_BETTER' else x <= actual))+1
        best=ordered[0]; worst=ordered[-1]; avg=_n(sum(vals,Decimal('0'))/len(vals))
        percentile=_n((len(vals)-rank+1)/len(vals)*100)
        gap=_n(actual-best)
        bid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_productivity_benchmark(
                benchmark_id,organization_id,entity_id,period_id,department_id,product_id,kpi_code,participant_count,average_value,best_value,worst_value,actual_value,peer_rank,percentile,gap_to_best,status,created_by)
                VALUES(:id,:o,:e,:p,:d,:prod,:code,:n,:avg,:best,:worst,:actual,:rank,:pct,:gap,'READY',:by)
                ON CONFLICT(organization_id,entity_id,period_id,department_id,product_id,kpi_code) DO UPDATE SET
                  participant_count=:n,average_value=:avg,best_value=:best,worst_value=:worst,actual_value=:actual,peer_rank=:rank,percentile=:pct,gap_to_best=:gap,status='READY' '''),
                {'id':bid,'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'],'d':body.get('department_id'),'prod':body.get('product_id'),
                 'code':body['kpi_code'],'n':len(vals),'avg':float(avg),'best':float(best),'worst':float(worst),'actual':float(actual),'rank':rank,
                 'pct':float(percentile),'gap':float(gap),'by':str(u.user_id)})
        return {'benchmark_id':bid,'participant_count':len(vals),'average_value':float(avg),'best_value':float(best),'worst_value':float(worst),
                'actual_value':float(actual),'peer_rank':rank,'percentile':float(percentile),'gap_to_best':float(gap),'status':'READY'}

    @app.get('/v90dy/workforce/kpi-scorecards')
    def scorecards(request: Request, organization_id: str, entity_id: str, period_id: str, kpi_code: str|None=None):
        _perm(engine, request, 'workforce_kpi.view')
        where='organization_id=:o AND entity_id=:e AND period_id=:p'; params={'o':organization_id,'e':entity_id,'p':period_id}
        if kpi_code: where+=' AND kpi_code=:k'; params['k']=kpi_code
        with engine.connect() as c:
            return [dict(r) for r in c.execute(text(f'SELECT * FROM hr_workforce_kpi_scorecard WHERE {where} ORDER BY created_at DESC'),params).mappings().all()]

    @app.get('/v90dy/workforce/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_id: str|None=None):
        _perm(engine, request, 'workforce_kpi.view')
        where='organization_id=:o AND entity_id=:e'; params={'o':organization_id,'e':entity_id}
        if period_id: where+=' AND period_id=:p'; params['p']=period_id
        with engine.connect() as c:
            s=c.execute(text(f'''SELECT COUNT(*) runs,COALESCE(AVG(achievement_pct),0) achievement,COALESCE(AVG(efficiency_score),0) score,
                COALESCE(SUM(CASE WHEN status='ON_TARGET' THEN 1 ELSE 0 END),0) on_target,
                COALESCE(SUM(CASE WHEN status='BELOW_TARGET' THEN 1 ELSE 0 END),0) below_target
                FROM hr_workforce_kpi_scorecard WHERE {where}'''),params).mappings().first()
            b=c.execute(text(f'''SELECT COUNT(*) benchmarks,COALESCE(AVG(percentile),0) percentile,COALESCE(AVG(gap_to_best),0) gap
                FROM hr_workforce_productivity_benchmark WHERE {where}'''),params).mappings().first()
        return {'scorecards':int(s['runs'] or 0),'avg_achievement_pct':float(_n(s['achievement'])),
                'avg_efficiency_score':float(_n(s['score'])),'on_target':int(s['on_target'] or 0),'below_target':int(s['below_target'] or 0),
                'benchmarks':int(b['benchmarks'] or 0),'avg_percentile':float(_n(b['percentile'])),'avg_gap_to_best':float(_n(b['gap']))}

    @app.post('/v90dy/workforce/periods/{period_id}/close')
    def close(period_id: str, body: dict, request: Request):
        u=_perm(engine,request,'workforce_kpi.close')
        for k in ('organization_id','entity_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        with engine.connect() as c:
            count=c.execute(text('SELECT COUNT(*) FROM hr_workforce_kpi_scorecard WHERE organization_id=:o AND entity_id=:e AND period_id=:p'),{'o':body['organization_id'],'e':body['entity_id'],'p':period_id}).scalar()
        if not count: raise HTTPException(409,'no KPI scorecards available for period')
        with engine.begin() as c:
            c.execute(text('''CREATE TABLE IF NOT EXISTS hr_workforce_kpi_period_close(
                close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(organization_id,entity_id,period_id))'''))
            cid=str(uuid4())
            c.execute(text('''INSERT INTO hr_workforce_kpi_period_close(close_id,organization_id,entity_id,period_id,status,closed_by)
                VALUES(:id,:o,:e,:p,'CLOSED',:u)
                ON CONFLICT(organization_id,entity_id,period_id) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),
                {'id':cid,'o':body['organization_id'],'e':body['entity_id'],'p':period_id,'u':str(u.user_id)})
        return {'period_id':period_id,'status':'CLOSED'}

    @app.get('/ui/workforce-productivity-kpi')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1]/'web'/'workforce-productivity-kpi.html')
