from __future__ import annotations
from uuid import uuid4
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(engine, request, permission):
    u=authenticate(request); p=permissions_for_user(engine,u.user_id)
    if permission not in p and 'admin.users' not in p: raise HTTPException(403,'permission denied')
    return u

def _ensure(engine):
    with engine.begin() as c:
        for pid,name in [('gst_close.view','View GST statutory close'),('gst_close.manage','Manage GST statutory close'),('gst_close.signoff','Sign off GST statutory close')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':pid,'n':name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_statutory_closes(
          close_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT,
          period_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', compliance_status TEXT NOT NULL DEFAULT 'PENDING',
          settlement_status TEXT NOT NULL DEFAULT 'PENDING', acknowledgement_status TEXT NOT NULL DEFAULT 'PENDING',
          exception_count INTEGER NOT NULL DEFAULT 0, locked_by TEXT, locked_at TIMESTAMP, reopened_by TEXT, reopened_at TIMESTAMP,
          remarks TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(filing_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_statutory_close_audit(
          audit_id TEXT PRIMARY KEY, close_id TEXT NOT NULL, action TEXT NOT NULL, from_status TEXT, to_status TEXT,
          reason TEXT, actor_id TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

def register_v90ck_routes(app,engine):
    _ensure(engine)
    def evaluate(c, filing_id):
        f=c.execute(text('SELECT * FROM gst_filing_periods WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
        if not f: raise HTTPException(404,'filing not found')
        s=c.execute(text('SELECT status FROM gst_settlement_runs WHERE filing_id=:f'),{'f':filing_id}).scalar()
        ss=c.execute(text('SELECT status FROM gst_settlement_signoffs WHERE settlement_id=(SELECT settlement_id FROM gst_settlement_runs WHERE filing_id=:f)'),{'f':filing_id}).scalar()
        ack=c.execute(text("SELECT COUNT(*) FROM gst_filing_acknowledgements WHERE filing_id=:f AND status='RECEIVED'"),{'f':filing_id}).scalar() or 0
        exceptions=(c.execute(text("SELECT COUNT(*) FROM gst_settlement_runs WHERE filing_id=:f AND status='EXCEPTION'"),{'f':filing_id}).scalar() or 0)
        compliance=(c.execute(text("SELECT COUNT(*) FROM gst_compliance_returns WHERE filing_id=:f AND status='FILED'"),{'f':filing_id}).scalar() or 0)
        return f, s or 'PENDING', ss or 'PENDING', 'RECEIVED' if ack else 'PENDING', int(exceptions), 'FILED' if compliance else 'PENDING'
    @app.post('/v90ck/gst/close/{filing_id}/evaluate')
    def evaluate_close(filing_id:str,request:Request):
        u=_perm(engine,request,'gst_close.manage')
        with engine.begin() as c:
            f,settlement,signoff,ack,exc,compliance=evaluate(c,filing_id)
            status='READY' if settlement=='MATCHED' and signoff=='SIGNED' and ack=='RECEIVED' and exc==0 and compliance=='FILED' else 'BLOCKED'
            cid=c.execute(text('SELECT close_id FROM gst_statutory_closes WHERE filing_id=:f'),{'f':filing_id}).scalar() or str(uuid4())
            c.execute(text('''INSERT INTO gst_statutory_closes(close_id,filing_id,organization_id,entity_id,period_key,status,compliance_status,settlement_status,acknowledgement_status,exception_count,remarks,created_by)
              VALUES(:i,:f,:o,:e,:p,:s,:cs,:ss,:as,:x,:r,:u)
              ON CONFLICT(filing_id) DO UPDATE SET status=:s,compliance_status=:cs,settlement_status=:ss,acknowledgement_status=:as,exception_count=:x,remarks=:r,updated_at=CURRENT_TIMESTAMP'''),
              {'i':cid,'f':filing_id,'o':f['organization_id'],'e':f['entity_id'],'p':f['period_key'],'s':status,'cs':compliance,'ss':settlement,'as':ack,'x':exc,'r':None if status=='READY' else 'One or more statutory close gates are incomplete','u':str(u.user_id)})
        return {'close_id':cid,'filing_id':filing_id,'status':status,'compliance_status':compliance,'settlement_status':settlement,'settlement_signoff':signoff,'acknowledgement_status':ack,'exception_count':exc}
    @app.post('/v90ck/gst/close/{filing_id}/finalize')
    def finalize(filing_id:str,request:Request,body:dict|None=None):
        u=_perm(engine,request,'gst_close.signoff')
        with engine.begin() as c:
            row=c.execute(text('SELECT * FROM gst_statutory_closes WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not row: raise HTTPException(404,'statutory close not evaluated')
            if row['status']!='READY': raise HTTPException(409,'statutory close gates are not satisfied')
            if row['status']=='LOCKED': raise HTTPException(409,'statutory period already locked')
            c.execute(text("UPDATE gst_statutory_closes SET status='LOCKED',locked_by=:u,locked_at=CURRENT_TIMESTAMP,remarks=:r,updated_at=CURRENT_TIMESTAMP WHERE filing_id=:f"),{'u':str(u.user_id),'r':(body or {}).get('remarks'),'f':filing_id})
            c.execute(text("UPDATE gst_filing_periods SET status='LOCKED',locked_by=:u,locked_at=CURRENT_TIMESTAMP WHERE filing_id=:f AND status<>'LOCKED'"),{'u':str(u.user_id),'f':filing_id})
            c.execute(text('INSERT INTO gst_statutory_close_audit(audit_id,close_id,action,from_status,to_status,reason,actor_id) VALUES(:i,:c,\'FINALIZE\',:fr,\'LOCKED\',:r,:u)'),{'i':str(uuid4()),'c':row['close_id'],'fr':row['status'],'r':(body or {}).get('remarks'),'u':str(u.user_id)})
        return {'filing_id':filing_id,'close_id':row['close_id'],'status':'LOCKED'}
    @app.post('/v90ck/gst/close/{filing_id}/reopen')
    def reopen(filing_id:str,request:Request,body:dict):
        u=_perm(engine,request,'gst_close.manage'); reason=str(body.get('reason') or '').strip()
        if not reason: raise HTTPException(400,'reason is required')
        with engine.begin() as c:
            row=c.execute(text('SELECT * FROM gst_statutory_closes WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not row: raise HTTPException(404,'statutory close not found')
            if row['status']!='LOCKED': raise HTTPException(409,'statutory period is not locked')
            c.execute(text("UPDATE gst_statutory_closes SET status='OPEN',reopened_by=:u,reopened_at=CURRENT_TIMESTAMP,remarks=:r,updated_at=CURRENT_TIMESTAMP WHERE filing_id=:f"),{'u':str(u.user_id),'r':reason,'f':filing_id})
            c.execute(text("UPDATE gst_filing_periods SET status='SNAPSHOTTED',locked_by=NULL,locked_at=NULL WHERE filing_id=:f"),{'f':filing_id})
            c.execute(text('INSERT INTO gst_statutory_close_audit(audit_id,close_id,action,from_status,to_status,reason,actor_id) VALUES(:i,:c,\'REOPEN\',\'LOCKED\',\'OPEN\',:r,:u)'),{'i':str(uuid4()),'c':row['close_id'],'r':reason,'u':str(u.user_id)})
        return {'filing_id':filing_id,'close_id':row['close_id'],'status':'OPEN'}
    @app.get('/v90ck/gst/close/{filing_id}')
    def summary(filing_id:str,request:Request):
        _perm(engine,request,'gst_close.view')
        with engine.connect() as c:
            r=c.execute(text('SELECT * FROM gst_statutory_closes WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not r: raise HTTPException(404,'statutory close not evaluated')
            audit=[dict(x) for x in c.execute(text('SELECT action,from_status,to_status,reason,actor_id,created_at FROM gst_statutory_close_audit WHERE close_id=:c ORDER BY created_at'),{'c':r['close_id']}).mappings().all()]
        return {'close':dict(r),'audit':audit}
    @app.get('/v90ck/gst/compliance-dashboard')
    def dashboard(request:Request,organization_id:str|None=None):
        _perm(engine,request,'gst_close.view')
        with engine.connect() as c:
            q='SELECT status,COUNT(*) count FROM gst_statutory_closes WHERE (:o IS NULL OR organization_id=:o) GROUP BY status ORDER BY status'
            rows=[dict(x) for x in c.execute(text(q),{'o':organization_id}).mappings().all()]
        return {'organization_id':organization_id,'statuses':rows}
    @app.get('/v90ck/gst/close/{filing_id}/export')
    def export(filing_id:str,request:Request):
        _perm(engine,request,'gst_close.view')
        with engine.connect() as c:
            r=c.execute(text('SELECT * FROM gst_statutory_closes WHERE filing_id=:f'),{'f':filing_id}).mappings().first()
            if not r: raise HTTPException(404,'statutory close not evaluated')
            audit=[dict(x) for x in c.execute(text('SELECT action,from_status,to_status,reason,actor_id,created_at FROM gst_statutory_close_audit WHERE close_id=:c ORDER BY created_at'),{'c':r['close_id']}).mappings().all()]
        return {'format':'GST_STATUTORY_CLOSE_PACK_V1','close':dict(r),'audit':audit}
    @app.get('/ui/gst-statutory-close')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'gst-statutory-close.html')
