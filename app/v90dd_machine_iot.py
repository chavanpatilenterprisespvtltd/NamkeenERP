from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def register_v90dd_routes(app:FastAPI,e):
    with e.begin() as c:
        for p,n in [('machine_iot.view','View Machine IoT'),('machine_iot.manage','Manage Machine IoT'),('machine_iot.alert','Manage Machine Alerts')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS machine_iot_device(device_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT NOT NULL,device_code TEXT NOT NULL,device_type TEXT NOT NULL,protocol TEXT,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,device_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS machine_iot_telemetry(telemetry_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT NOT NULL,device_id TEXT NOT NULL,parameter_code TEXT NOT NULL,value NUMERIC NOT NULL,unit TEXT,event_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,quality TEXT NOT NULL DEFAULT 'GOOD',source TEXT NOT NULL DEFAULT 'MACHINE',created_by TEXT NOT NULL)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS machine_iot_state(state_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT NOT NULL,device_id TEXT NOT NULL,state_code TEXT NOT NULL,event_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,derived BOOLEAN NOT NULL DEFAULT FALSE,created_by TEXT NOT NULL)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS machine_iot_threshold(threshold_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,device_id TEXT NOT NULL,parameter_code TEXT NOT NULL,min_value NUMERIC,max_value NUMERIC,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,UNIQUE(organization_id,entity_id,device_id,parameter_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS machine_iot_alert(alert_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT NOT NULL,device_id TEXT NOT NULL,parameter_code TEXT NOT NULL,value NUMERIC NOT NULL,alert_type TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',telemetry_id TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_iot_telemetry_scope ON machine_iot_telemetry(organization_id,entity_id,work_center_id,device_id,event_at)'))
    @app.post('/v90dd/iot/devices')
    def device(b:dict,request:Request):
        u=_perm(e,request,'machine_iot.manage')
        for k in ('organization_id','entity_id','work_center_id','device_code','device_type'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO machine_iot_device(device_id,organization_id,entity_id,work_center_id,device_code,device_type,protocol,active,created_by) VALUES(:i,:o,:e,:w,:d,:t,:p,:a,:u) ON CONFLICT(organization_id,entity_id,device_code) DO UPDATE SET work_center_id=:w,device_type=:t,protocol=:p,active=:a'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'w':b['work_center_id'],'d':b['device_code'],'t':b['device_type'],'p':b.get('protocol'),'a':bool(b.get('active',True)),'u':str(u.user_id)})
        return {'device_id':i,'status':'ACTIVE'}
    @app.post('/v90dd/iot/telemetry')
    def telemetry(b:dict,request:Request):
        u=_perm(e,request,'machine_iot.manage')
        for k in ('organization_id','entity_id','work_center_id','device_id','parameter_code','value'):
            if b.get(k) is None or (isinstance(b.get(k),str) and not b[k].strip()): raise HTTPException(400,f'{k} is required')
        i=str(uuid4()); val=float(b['value'])
        with e.begin() as c:
            c.execute(text('''INSERT INTO machine_iot_telemetry(telemetry_id,organization_id,entity_id,work_center_id,device_id,parameter_code,value,unit,event_at,quality,source,created_by) VALUES(:i,:o,:e,:w,:d,:p,:v,:u,COALESCE(:at,CURRENT_TIMESTAMP),:q,:s,:c)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'w':b['work_center_id'],'d':b['device_id'],'p':b['parameter_code'],'v':val,'u':b.get('unit'),'at':b.get('event_at'),'q':b.get('quality','GOOD'),'s':b.get('source','MACHINE'),'c':str(u.user_id)})
            th=c.execute(text('SELECT min_value,max_value FROM machine_iot_threshold WHERE organization_id=:o AND entity_id=:e AND device_id=:d AND parameter_code=:p AND active=TRUE'),{'o':b['organization_id'],'e':b['entity_id'],'d':b['device_id'],'p':b['parameter_code']}).mappings().first()
            alert=None
            if th and ((th['min_value'] is not None and val<float(th['min_value'])) or (th['max_value'] is not None and val>float(th['max_value']))):
                typ='LOW' if th['min_value'] is not None and val<float(th['min_value']) else 'HIGH'; alert=str(uuid4())
                c.execute(text('''INSERT INTO machine_iot_alert(alert_id,organization_id,entity_id,work_center_id,device_id,parameter_code,value,alert_type,telemetry_id,created_by) VALUES(:a,:o,:e,:w,:d,:p,:v,:t,:i,:c)'''),{'a':alert,'o':b['organization_id'],'e':b['entity_id'],'w':b['work_center_id'],'d':b['device_id'],'p':b['parameter_code'],'v':val,'t':typ,'i':i,'c':str(u.user_id)})
        return {'telemetry_id':i,'alert_id':alert,'status':'RECORDED'}
    @app.post('/v90dd/iot/states')
    def state(b:dict,request:Request):
        u=_perm(e,request,'machine_iot.manage')
        for k in ('organization_id','entity_id','work_center_id','device_id','state_code'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO machine_iot_state(state_id,organization_id,entity_id,work_center_id,device_id,state_code,event_at,derived,created_by) VALUES(:i,:o,:e,:w,:d,:s,COALESCE(:at,CURRENT_TIMESTAMP),:v,:u)'),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'w':b['work_center_id'],'d':b['device_id'],'s':b['state_code'],'at':b.get('event_at'),'v':bool(b.get('derived',False)),'u':str(u.user_id)})
        return {'state_id':i,'status':'RECORDED'}
    @app.post('/v90dd/iot/thresholds')
    def threshold(b:dict,request:Request):
        u=_perm(e,request,'machine_iot.alert')
        for k in ('organization_id','entity_id','device_id','parameter_code'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO machine_iot_threshold(threshold_id,organization_id,entity_id,device_id,parameter_code,min_value,max_value,active,created_by) VALUES(:i,:o,:e,:d,:p,:mn,:mx,:a,:u) ON CONFLICT(organization_id,entity_id,device_id,parameter_code) DO UPDATE SET min_value=:mn,max_value=:mx,active=:a'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'d':b['device_id'],'p':b['parameter_code'],'mn':b.get('min_value'),'mx':b.get('max_value'),'a':bool(b.get('active',True)),'u':str(u.user_id)})
        return {'threshold_id':i,'status':'ACTIVE'}
    @app.get('/v90dd/iot/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'machine_iot.view')
        with e.connect() as c:
            d=c.execute(text('SELECT COUNT(*) FROM machine_iot_device WHERE organization_id=:o AND entity_id=:e AND active=TRUE'),{'o':organization_id,'e':entity_id}).scalar_one()
            t=c.execute(text('SELECT COUNT(*) FROM machine_iot_telemetry WHERE organization_id=:o AND entity_id=:e'),{'o':organization_id,'e':entity_id}).scalar_one()
            a=c.execute(text("SELECT COUNT(*) FROM machine_iot_alert WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),{'o':organization_id,'e':entity_id}).scalar_one()
        return {'active_devices':int(d),'telemetry_count':int(t),'open_alerts':int(a)}
    @app.get('/ui/machine-iot')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'machine-iot.html')
