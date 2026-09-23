from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _perm(engine, request, permission):
    u = authenticate(request)
    ps = permissions_for_user(engine, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _money(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def register_v90dn_routes(app: FastAPI, engine):
    with engine.begin() as c:
        perms = [
            ('payroll_mis.view', 'View Payroll MIS'),
            ('payroll_mis.manage', 'Manage Payroll Cost Allocation'),
            ('payroll_mis.post', 'Post Payroll Labour Allocation'),
            ('payroll_mis.close', 'Close Payroll MIS'),
        ]
        for p, n in perms:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_cost_rule(
            rule_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            rule_name TEXT NOT NULL, allocation_basis TEXT NOT NULL DEFAULT 'HOURS',
            department_id TEXT, production_only BOOLEAN NOT NULL DEFAULT FALSE,
            active BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,rule_name))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_cost_allocation(
            allocation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL, employee_id TEXT, department_id TEXT, production_batch_id TEXT,
            source_amount NUMERIC NOT NULL, allocated_amount NUMERIC NOT NULL,
            basis TEXT NOT NULL, basis_value NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ALLOCATED', created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id,employee_id,department_id,production_batch_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_labour_batch_summary(
            summary_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL, production_batch_id TEXT NOT NULL, labour_amount NUMERIC NOT NULL,
            labour_hours NUMERIC NOT NULL DEFAULT 0, employees_count INTEGER NOT NULL DEFAULT 0,
            cost_per_hour NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN',
            posted_journal_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id,production_batch_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_mis_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_id TEXT NOT NULL, run_id TEXT NOT NULL, gross_payroll NUMERIC NOT NULL,
            net_payroll NUMERIC NOT NULL, employer_cost NUMERIC NOT NULL, allocated_cost NUMERIC NOT NULL,
            production_labour NUMERIC NOT NULL, unallocated_cost NUMERIC NOT NULL,
            production_batches INTEGER NOT NULL DEFAULT 0, labour_hours NUMERIC NOT NULL DEFAULT 0,
            avg_labour_cost_per_hour NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN',
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_id,run_id))'''))

    def _run(c, run_id):
        r = c.execute(text('SELECT * FROM hr_payroll_run WHERE run_id=:r'), {'r': run_id}).mappings().first()
        if not r:
            raise HTTPException(404, 'payroll run not found')
        return r

    @app.post('/v90dn/payroll/cost-rules')
    def cost_rule(body: dict, request: Request):
        u = _perm(engine, request, 'payroll_mis.manage')
        for k in ('organization_id', 'entity_id', 'rule_name'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        basis = str(body.get('allocation_basis') or 'HOURS').upper()
        if basis not in {'HOURS', 'HEADCOUNT', 'FIXED', 'BATCH_HOURS'}:
            raise HTTPException(400, 'unsupported allocation_basis')
        i = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_payroll_cost_rule(rule_id,organization_id,entity_id,rule_name,allocation_basis,department_id,production_only,active,created_by)
                VALUES(:i,:o,:e,:n,:b,:d,:p,:a,:u)
                ON CONFLICT(organization_id,entity_id,rule_name) DO UPDATE SET allocation_basis=:b,department_id=:d,production_only=:p,active=:a'''),
                {'i': i, 'o': body['organization_id'], 'e': body['entity_id'], 'n': body['rule_name'], 'b': basis,
                 'd': body.get('department_id'), 'p': bool(body.get('production_only', False)), 'a': bool(body.get('active', True)), 'u': str(u.user_id)})
        return {'rule_id': i, 'status': 'SAVED', 'allocation_basis': basis}

    @app.post('/v90dn/payroll/runs/{run_id}/allocate')
    def allocate(run_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'payroll_mis.post')
        with engine.begin() as c:
            run = _run(c, run_id)
            if not run['approved']:
                raise HTTPException(409, 'payroll run must be approved')
            rows = c.execute(text('SELECT employee_id,department_id,batch_cost_allocated,basic,allowances,overtime_pay,employer_cost FROM hr_payroll_line WHERE run_id=:r'), {'r': run_id}).mappings().all()
            if not rows:
                raise HTTPException(409, 'payroll run has no payroll lines')
            c.execute(text('DELETE FROM hr_payroll_cost_allocation WHERE run_id=:r'), {'r': run_id})
            total_source = Decimal('0')
            total_alloc = Decimal('0')
            for x in rows:
                source = _money(x['basic']) + _money(x['allowances']) + _money(x['overtime_pay']) + _money(x['employer_cost'])
                explicit = _money(x['batch_cost_allocated'])
                amount = explicit if explicit > 0 else source
                dept = body.get('department_id') or x['department_id']
                batch = body.get('production_batch_id')
                basis_value = _money(body.get('basis_value', 1))
                if amount <= 0:
                    continue
                c.execute(text('''INSERT INTO hr_payroll_cost_allocation(allocation_id,run_id,organization_id,entity_id,employee_id,department_id,production_batch_id,source_amount,allocated_amount,basis,basis_value,created_by)
                    VALUES(:i,:r,:o,:e,:emp,:d,:b,:s,:a,:basis,:bv,:u)'''),
                    {'i': str(uuid4()), 'r': run_id, 'o': run['organization_id'], 'e': run['entity_id'], 'emp': x['employee_id'],
                     'd': dept, 'b': batch, 's': float(source), 'a': float(amount), 'basis': str(body.get('basis') or ('BATCH_HOURS' if batch else 'HOURS')).upper(),
                     'bv': float(basis_value), 'u': str(u.user_id)})
                total_source += source
                total_alloc += amount
            return {'run_id': run_id, 'source_amount': float(total_source), 'allocated_amount': float(total_alloc), 'unallocated_amount': float(max(total_source-total_alloc, Decimal('0'))), 'status': 'ALLOCATED'}

    @app.post('/v90dn/payroll/runs/{run_id}/production-labour/finalize')
    def finalize_labour(run_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'payroll_mis.post')
        batch = str(body.get('production_batch_id') or '').strip()
        if not batch:
            raise HTTPException(400, 'production_batch_id is required')
        with engine.begin() as c:
            run = _run(c, run_id)
            if not run['approved']:
                raise HTTPException(409, 'payroll run must be approved')
            amount = _money(c.execute(text('''SELECT COALESCE(SUM(allocated_amount),0) FROM hr_payroll_cost_allocation WHERE run_id=:r AND production_batch_id=:b'''), {'r': run_id, 'b': batch}).scalar())
            hours = _money(c.execute(text('''SELECT COALESCE(SUM(hours),0) FROM hr_payroll_batch_allocation WHERE run_id=:r AND batch_id=:b'''), {'r': run_id, 'b': batch}).scalar())
            employees = int(c.execute(text('SELECT COUNT(DISTINCT employee_id) FROM hr_payroll_cost_allocation WHERE run_id=:r AND production_batch_id=:b'), {'r': run_id, 'b': batch}).scalar() or 0)
            if amount <= 0:
                raise HTTPException(409, 'no payroll cost allocated to production batch')
            c.execute(text('''INSERT INTO hr_payroll_labour_batch_summary(summary_id,run_id,organization_id,entity_id,production_batch_id,labour_amount,labour_hours,employees_count,cost_per_hour,status)
                VALUES(:i,:r,:o,:e,:b,:a,:h,:ec,:cph,'FINALIZED')
                ON CONFLICT(run_id,production_batch_id) DO UPDATE SET labour_amount=:a,labour_hours=:h,employees_count=:ec,cost_per_hour=:cph,status='FINALIZED' '''),
                {'i': str(uuid4()), 'r': run_id, 'o': run['organization_id'], 'e': run['entity_id'], 'b': batch,
                 'a': float(amount), 'h': float(hours), 'ec': employees, 'cph': float(_money(amount / hours) if hours else 0)})
        return {'run_id': run_id, 'production_batch_id': batch, 'labour_amount': float(amount), 'labour_hours': float(hours), 'employees_count': employees, 'status': 'FINALIZED'}

    @app.post('/v90dn/payroll/runs/{run_id}/snapshot')
    def snapshot(run_id: str, request: Request):
        u = _perm(engine, request, 'payroll_mis.view')
        with engine.begin() as c:
            run = _run(c, run_id)
            allocated = _money(c.execute(text('SELECT COALESCE(SUM(allocated_amount),0) FROM hr_payroll_cost_allocation WHERE run_id=:r'), {'r': run_id}).scalar())
            production = _money(c.execute(text("SELECT COALESCE(SUM(labour_amount),0) FROM hr_payroll_labour_batch_summary WHERE run_id=:r AND status='FINALIZED'"), {'r': run_id}).scalar())
            batches = int(c.execute(text("SELECT COUNT(*) FROM hr_payroll_labour_batch_summary WHERE run_id=:r AND status='FINALIZED'"), {'r': run_id}).scalar() or 0)
            hours = _money(c.execute(text("SELECT COALESCE(SUM(labour_hours),0) FROM hr_payroll_labour_batch_summary WHERE run_id=:r AND status='FINALIZED'"), {'r': run_id}).scalar())
            unallocated = max(_money(run['employer_cost_total']) - allocated, Decimal('0'))
            avg = _money(production / hours) if hours else Decimal('0')
            sid = str(uuid4())
            c.execute(text('''INSERT INTO hr_payroll_mis_snapshot(snapshot_id,organization_id,entity_id,period_id,run_id,gross_payroll,net_payroll,employer_cost,allocated_cost,production_labour,unallocated_cost,production_batches,labour_hours,avg_labour_cost_per_hour,status)
                VALUES(:i,:o,:e,:p,:r,:g,:n,:ec,:a,:pl,:u,:b,:h,:avg,'READY')
                ON CONFLICT(organization_id,entity_id,period_id,run_id) DO UPDATE SET gross_payroll=:g,net_payroll=:n,employer_cost=:ec,allocated_cost=:a,production_labour=:pl,unallocated_cost=:u,production_batches=:b,labour_hours=:h,avg_labour_cost_per_hour=:avg,status='READY',generated_at=CURRENT_TIMESTAMP'''),
                {'i': sid, 'o': run['organization_id'], 'e': run['entity_id'], 'p': run['period_id'], 'r': run_id,
                 'g': float(run['gross_total']), 'n': float(run['net_total']), 'ec': float(run['employer_cost_total']), 'a': float(allocated),
                 'pl': float(production), 'u': float(unallocated), 'b': batches, 'h': float(hours), 'avg': float(avg)})
        return {'run_id': run_id, 'allocated_cost': float(allocated), 'production_labour': float(production), 'unallocated_cost': float(unallocated), 'status': 'READY'}

    @app.get('/v90dn/payroll/mis')
    def mis(request: Request, organization_id: str, entity_id: str, period_id: str | None = None):
        _perm(engine, request, 'payroll_mis.view')
        with engine.connect() as c:
            q = '''SELECT period_id,run_id,gross_payroll,net_payroll,employer_cost,allocated_cost,production_labour,unallocated_cost,production_batches,labour_hours,avg_labour_cost_per_hour,status,generated_at FROM hr_payroll_mis_snapshot WHERE organization_id=:o AND entity_id=:e'''
            params = {'o': organization_id, 'e': entity_id}
            if period_id:
                q += ' AND period_id=:p'; params['p'] = period_id
            q += ' ORDER BY generated_at DESC'
            rows = c.execute(text(q), params).mappings().all()
        return {'organization_id': organization_id, 'entity_id': entity_id, 'rows': [dict(x) for x in rows]}

    @app.post('/v90dn/payroll/runs/{run_id}/close')
    def close(run_id: str, request: Request):
        u = _perm(engine, request, 'payroll_mis.close')
        with engine.begin() as c:
            run = _run(c, run_id)
            snap = c.execute(text("SELECT status,unallocated_cost FROM hr_payroll_mis_snapshot WHERE run_id=:r"), {'r': run_id}).mappings().first()
            if not snap or snap['status'] != 'READY':
                raise HTTPException(409, 'MIS snapshot must be READY before payroll MIS close')
            if _money(snap['unallocated_cost']) > 0 and str(request.headers.get('x-allow-unallocated', '')).lower() != 'true':
                raise HTTPException(409, 'unallocated payroll cost remains; set x-allow-unallocated=true only with authorized review')
            c.execute(text("UPDATE hr_payroll_mis_snapshot SET status='CLOSED' WHERE run_id=:r"), {'r': run_id})
        return {'run_id': run_id, 'period_id': run['period_id'], 'status': 'CLOSED'}

    @app.get('/v90dn/payroll/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str):
        _perm(engine, request, 'payroll_mis.view')
        with engine.connect() as c:
            r = c.execute(text('''SELECT COUNT(*) runs,COALESCE(SUM(employer_cost),0) employer,COALESCE(SUM(allocated_cost),0) allocated,
                COALESCE(SUM(production_labour),0) production,COALESCE(SUM(unallocated_cost),0) unallocated,
                COALESCE(SUM(labour_hours),0) hours FROM hr_payroll_mis_snapshot WHERE organization_id=:o AND entity_id=:e'''), {'o': organization_id, 'e': entity_id}).mappings().first()
            batches = c.execute(text("SELECT COUNT(*) FROM hr_payroll_labour_batch_summary WHERE organization_id=:o AND entity_id=:e AND status='FINALIZED'"), {'o': organization_id, 'e': entity_id}).scalar()
        employer = _money(r['employer']); production = _money(r['production']); hours = _money(r['hours'])
        return {'payroll_runs': int(r['runs'] or 0), 'employer_cost': float(employer), 'allocated_cost': float(_money(r['allocated'])),
                'production_labour': float(production), 'unallocated_cost': float(_money(r['unallocated'])),
                'production_batches': int(batches or 0), 'labour_hours': float(hours),
                'avg_production_labour_per_hour': float(_money(production / hours) if hours else 0)}

    @app.get('/ui/payroll-mis')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'payroll-mis.html')
