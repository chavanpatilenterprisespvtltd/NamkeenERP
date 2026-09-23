from __future__ import annotations
from datetime import date
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


def _nonneg(body, keys):
    out = {}
    for k in keys:
        out[k] = _n(body.get(k))
        if out[k] < 0:
            raise HTTPException(400, f'{k} must be non-negative')
    return out


def register_v90dw_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p, n in [
            ('workforce_compliance.view', 'View Workforce Training and Certification Compliance'),
            ('workforce_compliance.manage', 'Manage Workforce Training Effectiveness'),
            ('workforce_compliance.post', 'Post Workforce Training Effectiveness'),
            ('workforce_compliance.check', 'Run Workforce Certification Compliance Check')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})

    @app.post('/v90dw/workforce/training-effectiveness')
    def effectiveness(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_compliance.post')
        for k in ('organization_id', 'entity_id', 'training_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        v = _nonneg(body, ['baseline_output_per_hour','post_output_per_hour',
                           'baseline_labour_cost_per_unit','post_labour_cost_per_unit',
                           'baseline_efficiency_pct','post_efficiency_pct'])
        out_imp = _n((v['post_output_per_hour'] - v['baseline_output_per_hour']) / v['baseline_output_per_hour'] * 100) if v['baseline_output_per_hour'] else Decimal('0')
        cost_imp = _n((v['baseline_labour_cost_per_unit'] - v['post_labour_cost_per_unit']) / v['baseline_labour_cost_per_unit'] * 100) if v['baseline_labour_cost_per_unit'] else Decimal('0')
        score = _n((max(Decimal('0'), out_imp) + max(Decimal('0'), cost_imp)) / 2)
        score = min(score, Decimal('100'))
        i = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_training_effectiveness(
                effectiveness_id,organization_id,entity_id,training_id,employee_id,period_id,department_id,
                baseline_output_per_hour,post_output_per_hour,output_improvement_pct,
                baseline_labour_cost_per_unit,post_labour_cost_per_unit,cost_improvement_pct,
                baseline_efficiency_pct,post_efficiency_pct,effectiveness_score,status,completed_date,created_by)
                VALUES(:i,:o,:e,:t,:emp,:p,:d,:bo,:po,:oi,:bc,:pc,:ci,:be,:pe,:s,'READY',:cd,:u)
                ON CONFLICT(organization_id,entity_id,training_id,employee_id,period_id) DO UPDATE SET
                baseline_output_per_hour=:bo,post_output_per_hour=:po,output_improvement_pct=:oi,
                baseline_labour_cost_per_unit=:bc,post_labour_cost_per_unit=:pc,cost_improvement_pct=:ci,
                baseline_efficiency_pct=:be,post_efficiency_pct=:pe,effectiveness_score=:s,status='READY',completed_date=:cd'''),
                {'i':i,'o':body['organization_id'],'e':body['entity_id'],'t':body['training_id'],'emp':body.get('employee_id'),
                 'p':body.get('period_id'),'d':body.get('department_id'),'bo':float(v['baseline_output_per_hour']),'po':float(v['post_output_per_hour']),
                 'oi':float(out_imp),'bc':float(v['baseline_labour_cost_per_unit']),'pc':float(v['post_labour_cost_per_unit']),
                 'ci':float(cost_imp),'be':float(v['baseline_efficiency_pct']),'pe':float(v['post_efficiency_pct']),
                 's':float(score),'cd':body.get('completed_date'),'u':str(u.user_id)})
        return {'effectiveness_id': i, 'output_improvement_pct': float(out_imp), 'cost_improvement_pct': float(cost_imp),
                'effectiveness_score': float(score), 'status': 'READY'}

    @app.post('/v90dw/workforce/certification-compliance/check')
    def compliance_check(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_compliance.check')
        for k in ('organization_id', 'entity_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        checked = body.get('checked_on') or date.today().isoformat()
        warning_days = int(body.get('warning_days') or 30)
        if warning_days < 0 or warning_days > 3650:
            raise HTTPException(400, 'warning_days must be between 0 and 3650')
        params={'o':body['organization_id'],'e':body['entity_id']}
        with engine.connect() as c:
            rows=c.execute(text('''SELECT certification_id,employee_id,certification_code,expiry_date,status
                FROM hr_employee_certification WHERE organization_id=:o AND entity_id=:e'''),params).mappings().all()
        counts={'COMPLIANT':0,'EXPIRING':0,'EXPIRED':0,'INACTIVE':0,'NO_EXPIRY':0}
        with engine.begin() as c:
            for r in rows:
                if str(r['status']).upper() != 'ACTIVE': status='INACTIVE'; days=None
                elif r['expiry_date'] is None: status='NO_EXPIRY'; days=None
                else:
                    days=(r['expiry_date']-date.fromisoformat(checked)).days
                    status='EXPIRED' if days < 0 else ('EXPIRING' if days <= warning_days else 'COMPLIANT')
                counts[status]+=1
                sid=str(uuid4())
                c.execute(text('''INSERT INTO hr_certification_compliance_snapshot(
                    snapshot_id,organization_id,entity_id,certification_id,employee_id,certification_code,expiry_date,days_to_expiry,compliance_status,checked_on,created_by)
                    VALUES(:i,:o,:e,:c,:emp,:code,:x,:d,:s,:on,:u)
                    ON CONFLICT(organization_id,entity_id,certification_id,checked_on) DO UPDATE SET
                    employee_id=:emp,certification_code=:code,expiry_date=:x,days_to_expiry=:d,compliance_status=:s,created_by=:u'''),
                    {'i':sid,'o':body['organization_id'],'e':body['entity_id'],'c':r['certification_id'],'emp':r['employee_id'],
                     'code':r['certification_code'],'x':r['expiry_date'],'d':days,'s':status,'on':checked,'u':str(u.user_id)})
        return {'checked_on':checked,'warning_days':warning_days,'certifications_checked':len(rows),**{k.lower():v for k,v in counts.items()}}

    @app.get('/v90dw/workforce/certification-compliance')
    def compliance(request: Request, organization_id: str, entity_id: str, checked_on: str | None = None):
        _perm(engine, request, 'workforce_compliance.view')
        where='organization_id=:o AND entity_id=:e'; params={'o':organization_id,'e':entity_id}
        if checked_on:
            where += ' AND checked_on=:d'; params['d']=checked_on
        with engine.connect() as c:
            r=c.execute(text(f'''SELECT compliance_status,COUNT(*) count FROM hr_certification_compliance_snapshot WHERE {where} GROUP BY compliance_status'''),params).mappings().all()
        return {str(x['compliance_status']).lower(): int(x['count']) for x in r}

    @app.get('/v90dw/workforce/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_id: str | None = None):
        _perm(engine, request, 'workforce_compliance.view')
        params={'o':organization_id,'e':entity_id}; where='organization_id=:o AND entity_id=:e'
        if period_id:
            where += ' AND period_id=:p'; params['p']=period_id
        with engine.connect() as c:
            t=c.execute(text(f'''SELECT COUNT(*) runs,COALESCE(AVG(effectiveness_score),0) score,
                COALESCE(AVG(output_improvement_pct),0) output_imp,COALESCE(AVG(cost_improvement_pct),0) cost_imp
                FROM hr_training_effectiveness WHERE {where}'''),params).mappings().first()
            q=c.execute(text(f'''SELECT compliance_status,COUNT(*) count FROM hr_certification_compliance_snapshot
                WHERE {where.replace(' AND period_id=:p','')} GROUP BY compliance_status'''),params).mappings().all()
        cert={str(x['compliance_status']).lower():int(x['count']) for x in q}
        return {'training_effectiveness_runs':int(t['runs'] or 0),'avg_effectiveness_score':float(_n(t['score'])),
                'avg_output_improvement_pct':float(_n(t['output_imp'])),'avg_cost_improvement_pct':float(_n(t['cost_imp'])),
                'certification_compliance':cert}

    @app.get('/ui/workforce-training-compliance')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'workforce-training-compliance.html')
