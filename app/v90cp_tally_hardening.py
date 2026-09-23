from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET
from fastapi import HTTPException,Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
def _perm(e,r,p):
 u=authenticate(r); ps=permissions_for_user(e,u.user_id)
 if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
 return u
def _ensure(e):
 with e.begin() as c:
  for p,n in [('tally_hardening.view','View Tally integration hardening'),('tally_hardening.manage','Manage Tally integration hardening'),('tally_hardening.retry','Retry Tally integration')]: c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
  c.execute(text('CREATE TABLE IF NOT EXISTS tally_sync_validation(validation_id TEXT PRIMARY KEY,sync_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,validation_status TEXT NOT NULL,duplicate_flag INTEGER NOT NULL DEFAULT 0,mapping_status TEXT NOT NULL,xml_status TEXT NOT NULL,message TEXT,validated_by TEXT NOT NULL,validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'))
  c.execute(text('CREATE TABLE IF NOT EXISTS tally_sync_acknowledgements(acknowledgement_id TEXT PRIMARY KEY,sync_id TEXT NOT NULL,external_reference TEXT,tally_status TEXT NOT NULL,response_message TEXT,received_by TEXT NOT NULL,received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(sync_id,external_reference))'))
def _xml(x):
 try:
  root=ET.fromstring(x); return (root.tag.upper() in ('ENVELOPE','TALLYREQUEST','IMPORT'),'XML structure accepted')
 except Exception as ex:return False,f'invalid XML: {ex}'
def register_v90cp_routes(app,e):
 _ensure(e)
 @app.post('/v90cp/tally/validate/{sid}')
 def validate(sid:str,request:Request):
  u=_perm(e,request,'tally_hardening.manage')
  with e.begin() as c:
   r=c.execute(text('SELECT * FROM tally_sync_queue WHERE sync_id=:s'),{'s':sid}).mappings().first()
   if not r: raise HTTPException(404,'sync item not found')
   mapped=c.execute(text('SELECT 1 FROM tally_company_maps WHERE organization_id=:o AND entity_id=:e AND tally_company=:n AND active=1'),{'o':r['organization_id'],'e':r['entity_id'],'n':r['tally_company']}).scalar()
   ok,msg=_xml(r['payload']) if mapped else (False,'active Tally company mapping is missing')
   dup=c.execute(text("SELECT 1 FROM tally_sync_queue WHERE posting_id=:p AND sync_id<>:s AND status IN ('QUEUED','ACKNOWLEDGED')"),{'p':r['posting_id'],'s':sid}).scalar()
   st='EXCEPTION' if not mapped or not ok or dup else 'VALIDATED'; vid=str(uuid4())
   c.execute(text('INSERT INTO tally_sync_validation(validation_id,sync_id,organization_id,entity_id,validation_status,duplicate_flag,mapping_status,xml_status,message,validated_by) VALUES(:i,:s,:o,:e,:v,:d,:m,:x,:msg,:u)'),{'i':vid,'s':sid,'o':r['organization_id'],'e':r['entity_id'],'v':st,'d':int(bool(dup)),'m':'VALID' if mapped else 'INVALID','x':'VALID' if ok else 'INVALID','msg':'duplicate posting already queued or acknowledged' if dup else msg,'u':str(u.user_id)})
  return {'validation_id':vid,'sync_id':sid,'status':st,'duplicate_flag':bool(dup)}
 @app.post('/v90cp/tally/ack/{sid}')
 def ack(sid:str,body:dict,request:Request):
  u=_perm(e,request,'tally_hardening.manage'); st=str(body.get('tally_status') or '').upper()
  if st not in ('ACCEPTED','REJECTED','DUPLICATE'): raise HTTPException(400,'tally_status must be ACCEPTED, REJECTED or DUPLICATE')
  with e.begin() as c:
   if not c.execute(text('SELECT 1 FROM tally_sync_queue WHERE sync_id=:s'),{'s':sid}).scalar(): raise HTTPException(404,'sync item not found')
   ref=str(body.get('external_reference') or '').strip() or None
   if ref and c.execute(text('SELECT 1 FROM tally_sync_acknowledgements WHERE sync_id=:s AND external_reference=:r'),{'s':sid,'r':ref}).scalar(): raise HTTPException(409,'acknowledgement already recorded')
   aid=str(uuid4()); c.execute(text('INSERT INTO tally_sync_acknowledgements(acknowledgement_id,sync_id,external_reference,tally_status,response_message,received_by) VALUES(:i,:s,:r,:t,:m,:u)'),{'i':aid,'s':sid,'r':ref,'t':st,'m':body.get('message'),'u':str(u.user_id)})
   qs='ACKNOWLEDGED' if st=='ACCEPTED' else 'FAILED'; c.execute(text('UPDATE tally_sync_queue SET status=:st,last_error=:e,processed_at=CURRENT_TIMESTAMP WHERE sync_id=:s'),{'st':qs,'e':body.get('message') if qs=='FAILED' else None,'s':sid})
  return {'acknowledgement_id':aid,'sync_id':sid,'status':st}
 @app.get('/v90cp/tally/health')
 def health(request:Request,organization_id:str,entity_id:str):
  _perm(e,request,'tally_hardening.view')
  with e.connect() as c:
   m=c.execute(text('SELECT tally_company,tally_host,tally_port,active FROM tally_company_maps WHERE organization_id=:o AND entity_id=:e'),{'o':organization_id,'e':entity_id}).mappings().first()
   q={x:c.execute(text('SELECT COUNT(*) FROM tally_sync_queue WHERE organization_id=:o AND entity_id=:e AND status=:s'),{'o':organization_id,'e':entity_id,'s':x.upper()}).scalar() or 0 for x in ['queued','failed','acknowledged']}
  return {'mapping':dict(m) if m else None,'queue':q,'connector_boundary':'TALLY_HTTP_BOUNDARY_READY'}
 @app.get('/ui/tally-hardening')
 def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'tally-hardening.html')
