from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _perm(e, r, p):
    u = authenticate(r); ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403, 'permission denied')
    return u

def _valid(pk):
    try:
        y, m = map(int, pk.split('-'))
        if y < 2000 or not 1 <= m <= 12: raise ValueError
    except Exception as exc:
        raise HTTPException(400, 'period_key must be YYYY-MM') from exc

def ensure_v90ff_schema(e):
    with e.begin() as c:
        stmts = [
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_action(
            action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            exception_id TEXT, action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', title TEXT NOT NULL,
            decision_request TEXT NOT NULL, owner_user_id TEXT, due_date DATE, status TEXT NOT NULL DEFAULT 'PROPOSED',
            decision_note TEXT, evidence_note TEXT, decided_by TEXT, decided_at TIMESTAMP,
            completed_note TEXT, completed_by TEXT, completed_at TIMESTAMP, created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exception_id, action_type))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_action_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            action_count INTEGER NOT NULL DEFAULT 0, open_action_count INTEGER NOT NULL DEFAULT 0,
            completed_action_count INTEGER NOT NULL DEFAULT 0, closed_by TEXT NOT NULL, closure_note TEXT,
            closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_reliability_exec_action_scope ON maintenance_reliability_executive_action(organization_id,entity_id,period_key,status,priority)',
        'CREATE INDEX IF NOT EXISTS ix_reliability_exec_action_due ON maintenance_reliability_executive_action(organization_id,entity_id,status,due_date)',
        ]
        for s in stmts: c.execute(text(s))
        for p,n in [('maintenance_reliability_action.view','View Reliability Executive Actions'),('maintenance_reliability_action.manage','Manage Reliability Executive Actions'),('maintenance_reliability_action.close','Close Reliability Executive Action Period')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p':p,'n':n})

def register_v90ff_routes(app: FastAPI, e):
    ensure_v90ff_schema(e)
    @app.post('/v90ff/maintenance/reliability-actions/generate')
    def generate(body: dict, request: Request):
        u = _perm(e, request, 'maintenance_reliability_action.manage')
        o, ei, p = body.get('organization_id'), body.get('entity_id'), body.get('period_key')
        if not o or not ei or not p: raise HTTPException(400, 'organization_id, entity_id and period_key are required')
        _valid(p)
        with e.begin() as c:
            ex = c.execute(text("SELECT * FROM maintenance_reliability_executive_command_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN' ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END,created_at"), {'o':o,'e':ei,'p':p}).mappings().all()
            created=[]
            for x in ex:
                typ = 'ESCALATE_COMPLIANCE' if x['exception_type']=='AUDIT' else ('BENCHMARK_IMPROVEMENT' if x['exception_type']=='BENCHMARK' else 'MANAGEMENT_REVIEW')
                row = c.execute(text('''INSERT INTO maintenance_reliability_executive_action(action_id,organization_id,entity_id,period_key,exception_id,action_type,priority,title,decision_request,created_by)
                    SELECT :id,:o,:e,:p,:x,:t,:pr,:title,:req,:u WHERE NOT EXISTS(SELECT 1 FROM maintenance_reliability_executive_action WHERE exception_id=:x AND action_type=:t) RETURNING *'''),
                    {'id':str(uuid4()),'o':o,'e':ei,'p':p,'x':x['exception_id'],'t':typ,'pr':x['severity'],'title':x['title'],'req':x['required_action'],'u':str(u.user_id)}).mappings().first()
                if row: created.append(dict(row))
        return {'count':len(created),'actions':created,'automatic_operational_mutation':False}

    @app.get('/v90ff/maintenance/reliability-actions')
    def actions(organization_id:str, period_key:str, request:Request, entity_id:str|None=None, status:str|None=None):
        _perm(e, request, 'maintenance_reliability_action.view'); _valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_executive_action WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
            if status: q+=' AND status=:s'; par['s']=status.upper()
            rows=c.execute(text(q+' ORDER BY CASE priority WHEN \'CRITICAL\' THEN 1 WHEN \'HIGH\' THEN 2 WHEN \'MEDIUM\' THEN 3 ELSE 4 END,due_date NULLS LAST,created_at'),par).mappings().all()
        return {'count':len(rows),'actions':[dict(r) for r in rows]}

    @app.post('/v90ff/maintenance/reliability-actions/{action_id}/decide')
    def decide(action_id:str, body:dict, request:Request):
        u=_perm(e,request,'maintenance_reliability_action.manage')
        decision=str(body.get('decision') or '').upper()
        if decision not in {'APPROVE','REJECT','DEFER'}: raise HTTPException(400,'decision must be APPROVE, REJECT or DEFER')
        note=str(body.get('decision_note') or '').strip(); evidence=str(body.get('evidence_note') or '').strip()
        if not note or not evidence: raise HTTPException(400,'decision_note and evidence_note are required')
        status={'APPROVE':'APPROVED','REJECT':'REJECTED','DEFER':'DEFERRED'}[decision]
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_executive_action SET status=:s,decision_note=:n,evidence_note=:ev,decided_by=:u,decided_at=CURRENT_TIMESTAMP,owner_user_id=COALESCE(:owner,owner_user_id),due_date=COALESCE(:due,due_date) WHERE action_id=:i AND status='PROPOSED' RETURNING action_id"),{'s':status,'n':note,'ev':evidence,'u':str(u.user_id),'owner':body.get('owner_user_id'),'due':body.get('due_date'),'i':action_id}).first()
            if not r: raise HTTPException(404,'proposed executive action not found')
        return {'action_id':action_id,'status':status,'evidence_recorded':True,'automatic_operational_mutation':False}

    @app.post('/v90ff/maintenance/reliability-actions/{action_id}/complete')
    def complete(action_id:str, body:dict, request:Request):
        u=_perm(e,request,'maintenance_reliability_action.manage')
        note=str(body.get('completed_note') or '').strip(); evidence=str(body.get('evidence_note') or '').strip()
        if not note or not evidence: raise HTTPException(400,'completed_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_executive_action SET status='COMPLETED',completed_note=:n,evidence_note=:ev,completed_by=:u,completed_at=CURRENT_TIMESTAMP WHERE action_id=:i AND status='APPROVED' RETURNING action_id"),{'n':note,'ev':evidence,'u':str(u.user_id),'i':action_id}).first()
            if not r: raise HTTPException(409,'action must be APPROVED before completion')
        return {'action_id':action_id,'status':'COMPLETED','evidence_recorded':True,'automatic_operational_mutation':False}

    @app.post('/v90ff/maintenance/reliability-actions/{period_key}/close')
    def close(period_key:str, body:dict, request:Request):
        u=_perm(e,request,'maintenance_reliability_action.close'); _valid(period_key)
        o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            total=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_executive_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            open_count=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_executive_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('PROPOSED','APPROVED','DEFERRED')"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            done=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_executive_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='COMPLETED'"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            if open_count and not body.get('force'): raise HTTPException(409,f'{open_count} open executive action(s) remain; resolve, complete or force=true')
            c.execute(text('''INSERT INTO maintenance_reliability_executive_action_close(close_id,organization_id,entity_id,period_key,action_count,open_action_count,completed_action_count,closed_by,closure_note) VALUES(:i,:o,:e,:p,:t,:op,:d,:u,:n) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET action_count=:t,open_action_count=:op,completed_action_count=:d,closed_by=:u,closure_note=:n,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'t':int(total),'op':int(open_count),'d':int(done),'u':str(u.user_id),'n':body.get('closure_note')})
        return {'organization_id':o,'entity_id':ei,'period_key':period_key,'status':'CLOSED','action_count':int(total),'open_action_count':int(open_count),'completed_action_count':int(done),'forced':bool(body.get('force'))}

    @app.get('/ui/maintenance-reliability-actions')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-actions.html')
