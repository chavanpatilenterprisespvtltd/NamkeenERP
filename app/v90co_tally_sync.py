from __future__ import annotations
from pathlib import Path
from uuid import uuid4
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
        perms=[('tally_sync.view','View Tally synchronization'),('tally_sync.manage','Manage Tally synchronization'),('tally_sync.retry','Retry Tally synchronization')]
        for p,n in perms: c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS tally_company_maps(map_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,tally_company TEXT NOT NULL,tally_company_guid TEXT,tally_host TEXT,tally_port INTEGER DEFAULT 9000,active INTEGER NOT NULL DEFAULT 1,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS tally_ledger_maps(map_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT,source_key TEXT NOT NULL,tally_ledger TEXT NOT NULL,tally_group TEXT,tax_type TEXT,active INTEGER NOT NULL DEFAULT 1,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,source_key,entity_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS tally_sync_queue(sync_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,posting_id TEXT NOT NULL,tally_company TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'QUEUED',attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,queued_by TEXT NOT NULL,queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,processed_at TIMESTAMP,UNIQUE(posting_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS tally_sync_events(event_id TEXT PRIMARY KEY,sync_id TEXT NOT NULL,event_type TEXT NOT NULL,status TEXT NOT NULL,message TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

def _queue(c, posting_id, user_id):
    p=c.execute(text('SELECT * FROM accounting_postings WHERE posting_id=:p'),{'p':posting_id}).mappings().first()
    if not p: raise HTTPException(404,'posting not found')
    company=c.execute(text('SELECT tally_company FROM tally_company_maps WHERE organization_id=:o AND entity_id=:e AND active=1'),{'o':p['organization_id'],'e':p['entity_id']}).scalar()
    if not company: raise HTTPException(400,'active Tally company mapping is required')
    doc=c.execute(text('SELECT payload FROM tally_export_documents WHERE posting_id=:p AND format=\'TALLY_XML\''),{'p':posting_id}).scalar()
    if not doc: raise HTTPException(400,'Tally XML export is not available for posting')
    existing=c.execute(text('SELECT sync_id,status FROM tally_sync_queue WHERE posting_id=:p'),{'p':posting_id}).mappings().first()
    if existing: return dict(existing)
    sid=str(uuid4()); c.execute(text('INSERT INTO tally_sync_queue(sync_id,organization_id,entity_id,posting_id,tally_company,payload,status,queued_by) VALUES(:s,:o,:e,:p,:c,:x,\'QUEUED\',:u)'),{'s':sid,'o':p['organization_id'],'e':p['entity_id'],'p':posting_id,'c':company,'x':doc,'u':str(user_id)})
    c.execute(text('INSERT INTO tally_sync_events(event_id,sync_id,event_type,status,message,created_by) VALUES(:i,:s,\'QUEUE\',\'QUEUED\',\'queued for Tally synchronization\',:u)'),{'i':str(uuid4()),'s':sid,'u':str(user_id)})
    return {'sync_id':sid,'status':'QUEUED'}

def register_v90co_routes(app,engine):
    _ensure(engine)
    @app.post('/v90co/tally/companies')
    def company(body:dict,request:Request):
        u=_perm(engine,request,'tally_sync.manage'); req=['organization_id','entity_id','tally_company']
        if any(not str(body.get(k) or '').strip() for k in req): raise HTTPException(400,'organization_id, entity_id and tally_company are required')
        with engine.begin() as c:
            c.execute(text('''INSERT INTO tally_company_maps(map_id,organization_id,entity_id,tally_company,tally_company_guid,tally_host,tally_port,created_by) VALUES(:i,:o,:e,:n,:g,:h,:p,:u) ON CONFLICT(organization_id,entity_id) DO UPDATE SET tally_company=:n,tally_company_guid=:g,tally_host=:h,tally_port=:p,active=1'''),{'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'n':body['tally_company'],'g':body.get('tally_company_guid'),'h':body.get('tally_host'),'p':int(body.get('tally_port') or 9000),'u':str(u.user_id)})
        return {'status':'MAPPED','tally_company':body['tally_company']}
    @app.post('/v90co/tally/ledger-maps')
    def ledger_map(body:dict,request:Request):
        u=_perm(engine,request,'tally_sync.manage')
        if not all(str(body.get(k) or '').strip() for k in ('organization_id','source_key','tally_ledger')): raise HTTPException(400,'organization_id, source_key and tally_ledger are required')
        with engine.begin() as c: c.execute(text('''INSERT INTO tally_ledger_maps(map_id,organization_id,entity_id,source_key,tally_ledger,tally_group,tax_type,created_by) VALUES(:i,:o,:e,:s,:l,:g,:t,:u) ON CONFLICT(organization_id,source_key,entity_id) DO UPDATE SET tally_ledger=:l,tally_group=:g,tax_type=:t,active=1'''),{'i':str(uuid4()),'o':body['organization_id'],'e':body.get('entity_id'),'s':body['source_key'],'l':body['tally_ledger'],'g':body.get('tally_group'),'t':body.get('tax_type'),'u':str(u.user_id)})
        return {'status':'MAPPED'}
    @app.post('/v90co/tally/queue/{posting_id}')
    def queue(posting_id:str,request:Request):
        u=_perm(engine,request,'tally_sync.manage')
        with engine.begin() as c: r=_queue(c,posting_id,u.user_id)
        return r
    @app.post('/v90co/tally/retry/{sync_id}')
    def retry(sync_id:str,request:Request):
        u=_perm(engine,request,'tally_sync.retry')
        with engine.begin() as c:
            r=c.execute(text('SELECT status FROM tally_sync_queue WHERE sync_id=:s'),{'s':sync_id}).scalar()
            if not r: raise HTTPException(404,'sync item not found')
            c.execute(text("UPDATE tally_sync_queue SET status='QUEUED',attempts=attempts+1,last_error=NULL WHERE sync_id=:s"),{'s':sync_id})
            c.execute(text("INSERT INTO tally_sync_events(event_id,sync_id,event_type,status,message,created_by) VALUES(:i,:s,'RETRY','QUEUED','retry requested',:u)"),{'i':str(uuid4()),'s':sync_id,'u':str(u.user_id)})
        return {'sync_id':sync_id,'status':'QUEUED'}
    @app.post('/v90co/tally/ack/{sync_id}')
    def ack(sync_id:str,body:dict,request:Request):
        u=_perm(engine,request,'tally_sync.manage'); status=str(body.get('status') or '').upper()
        if status not in ('ACKNOWLEDGED','FAILED'): raise HTTPException(400,'status must be ACKNOWLEDGED or FAILED')
        with engine.begin() as c:
            r=c.execute(text('SELECT 1 FROM tally_sync_queue WHERE sync_id=:s'),{'s':sync_id}).scalar()
            if not r: raise HTTPException(404,'sync item not found')
            c.execute(text('UPDATE tally_sync_queue SET status=:x,last_error=:e,processed_at=CURRENT_TIMESTAMP WHERE sync_id=:s'),{'x':status,'e':body.get('error'),'s':sync_id})
            c.execute(text('INSERT INTO tally_sync_events(event_id,sync_id,event_type,status,message,created_by) VALUES(:i,:s,\'ACK\',:x,:m,:u)'),{'i':str(uuid4()),'s':sync_id,'x':status,'m':body.get('message'),'u':str(u.user_id)})
        return {'sync_id':sync_id,'status':status}
    @app.get('/v90co/tally/sync')
    def sync(request:Request,organization_id:str,entity_id:str,status:str|None=None):
        _perm(engine,request,'tally_sync.view')
        with engine.connect() as c:
            q='SELECT * FROM tally_sync_queue WHERE organization_id=:o AND entity_id=:e'; params={'o':organization_id,'e':entity_id}
            if status: q+=' AND status=:s'; params['s']=status.upper()
            rows=c.execute(text(q+' ORDER BY queued_at DESC'),params).mappings().all()
        return {'items':[dict(x) for x in rows]}
    @app.get('/ui/tally-sync')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'tally-sync.html')
