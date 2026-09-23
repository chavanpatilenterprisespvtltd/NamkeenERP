from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
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

def _q(v): return Decimal(str(v or 0)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)

def _ensure(engine):
    with engine.begin() as c:
        for pid,name in [('gst_filing.view','View GST filing'),('gst_filing.manage','Manage GST filing'),('gst_filing.export','Export GST filing pack')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':pid,'n':name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_filing_periods(
          filing_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT, period_key TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'DRAFT', outward_taxable NUMERIC NOT NULL DEFAULT 0, outward_tax NUMERIC NOT NULL DEFAULT 0,
          inward_taxable NUMERIC NOT NULL DEFAULT 0, inward_tax NUMERIC NOT NULL DEFAULT 0, net_tax NUMERIC NOT NULL DEFAULT 0,
          adjustment_tax NUMERIC NOT NULL DEFAULT 0, snapshot_json TEXT NOT NULL DEFAULT '{}',
          created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, locked_by TEXT, locked_at TIMESTAMP,
          UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_filing_adjustments(
          adjustment_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, adjustment_type TEXT NOT NULL,
          amount NUMERIC NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
          created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(filing_id) REFERENCES gst_filing_periods(filing_id))'''))

def register_v90cg_routes(app,engine):
    _ensure(engine)
    def totals(c,org,period,entity):
        p={'o':org,'p':period}; ef=''
        if entity: ef=' AND entity_id=:e';p['e']=entity
        rows=c.execute(text(f'''SELECT COALESCE(SUM(CASE WHEN COALESCE(supply_type,'OUTWARD')='OUTWARD' THEN taxable_value ELSE 0 END),0) outward_taxable,
          COALESCE(SUM(CASE WHEN COALESCE(supply_type,'OUTWARD')='OUTWARD' THEN total_tax ELSE 0 END),0) outward_tax,
          COALESCE(SUM(CASE WHEN COALESCE(supply_type,'OUTWARD')='INWARD' THEN taxable_value ELSE 0 END),0) inward_taxable,
          COALESCE(SUM(CASE WHEN COALESCE(supply_type,'OUTWARD')='INWARD' THEN total_tax ELSE 0 END),0) inward_tax
          FROM tax_transaction_lines WHERE organization_id=:o AND substr(created_at,1,7)=:p{ef}'''),p).mappings().one()
        return {k:_q(v) for k,v in rows.items()}
    @app.get('/v90cg/gst/filing')
    def filing(request:Request,organization_id:str,period_key:str,entity_id:str|None=None):
        _perm(engine,request,'gst_filing.view')
        with engine.connect() as c:
            r=c.execute(text('SELECT * FROM gst_filing_periods WHERE organization_id=:o AND period_key=:p AND (:e IS NULL AND entity_id IS NULL OR entity_id=:e)'),{'o':organization_id,'p':period_key,'e':entity_id}).mappings().first()
            return dict(r) if r else {'organization_id':organization_id,'entity_id':entity_id,'period_key':period_key,'status':'NOT_GENERATED'}
    @app.post('/v90cg/gst/filing/snapshot')
    def snapshot(request:Request,body:dict):
        u=_perm(engine,request,'gst_filing.manage'); org=body['organization_id'];period=body['period_key'];entity=body.get('entity_id')
        with engine.begin() as c:
            existing=c.execute(text('SELECT filing_id,status FROM gst_filing_periods WHERE organization_id=:o AND period_key=:p AND (:e IS NULL AND entity_id IS NULL OR entity_id=:e)'),{'o':org,'p':period,'e':entity}).mappings().first()
            if existing and existing['status']=='LOCKED': raise HTTPException(409,'filing period is locked')
            t=totals(c,org,period,entity); net=_q(t['outward_tax']-t['inward_tax'])
            fid=existing['filing_id'] if existing else str(uuid4())
            snap={k:float(v) for k,v in t.items()};snap['net_tax']=float(net)
            c.execute(text('''INSERT INTO gst_filing_periods(filing_id,organization_id,entity_id,period_key,status,outward_taxable,outward_tax,inward_taxable,inward_tax,net_tax,snapshot_json,created_by)
              VALUES(:i,:o,:e,:p,'SNAPSHOTTED',:otb,:ot,:itb,:it,:nt,:sj,:u)
              ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='SNAPSHOTTED',outward_taxable=:otb,outward_tax=:ot,inward_taxable=:itb,inward_tax=:it,net_tax=:nt,snapshot_json=:sj,created_by=:u'''),{'i':fid,'o':org,'e':entity,'p':period,'otb':float(t['outward_taxable']),'ot':float(t['outward_tax']),'itb':float(t['inward_taxable']),'it':float(t['inward_tax']),'nt':float(net),'sj':__import__('json').dumps(snap,sort_keys=True),'u':str(u.user_id)})
        return {'filing_id':fid,'status':'SNAPSHOTTED',**snap}
    @app.post('/v90cg/gst/filing/{filing_id}/adjustment')
    def adjustment(filing_id:str,request:Request,body:dict):
        u=_perm(engine,request,'gst_filing.manage'); amount=_q(body['amount'])
        if amount==0: raise HTTPException(400,'adjustment amount must be non-zero')
        with engine.begin() as c:
            r=c.execute(text('SELECT status FROM gst_filing_periods WHERE filing_id=:i'),{'i':filing_id}).mappings().first()
            if not r: raise HTTPException(404,'filing not found')
            if r['status']=='LOCKED': raise HTTPException(409,'filing period is locked')
            aid=str(uuid4());c.execute(text('INSERT INTO gst_filing_adjustments(adjustment_id,filing_id,adjustment_type,amount,reason,created_by) VALUES(:i,:f,:t,:a,:r,:u)'),{'i':aid,'f':filing_id,'t':body.get('adjustment_type','OTHER'),'a':float(amount),'r':body['reason'],'u':str(u.user_id)})
        return {'adjustment_id':aid,'filing_id':filing_id,'status':'DRAFT','amount':float(amount)}
    @app.post('/v90cg/gst/filing/{filing_id}/lock')
    def lock(filing_id:str,request:Request):
        u=_perm(engine,request,'gst_filing.manage')
        with engine.begin() as c:
            r=c.execute(text("UPDATE gst_filing_periods SET status='LOCKED',locked_by=:u,locked_at=CURRENT_TIMESTAMP WHERE filing_id=:i AND status<>'LOCKED' RETURNING filing_id"),{'u':str(u.user_id),'i':filing_id}).first()
            if not r: raise HTTPException(404,'filing not found or already locked')
        return {'filing_id':filing_id,'status':'LOCKED'}
    @app.get('/v90cg/gst/filing/{filing_id}/export')
    def export(filing_id:str,request:Request):
        _perm(engine,request,'gst_filing.export')
        with engine.connect() as c:
            f=c.execute(text('SELECT * FROM gst_filing_periods WHERE filing_id=:i'),{'i':filing_id}).mappings().first()
            if not f: raise HTTPException(404,'filing not found')
            ads=[dict(x) for x in c.execute(text('SELECT adjustment_type,amount,reason,status FROM gst_filing_adjustments WHERE filing_id=:i ORDER BY created_at'),{'i':filing_id}).mappings().all()]
            net=_q(f['net_tax']+sum((_q(x['amount']) for x in ads if x['status']!='VOID'),Decimal('0')))
            return {'format':'GST_FILING_PACK_V1','filing_id':filing_id,'organization_id':f['organization_id'],'entity_id':f['entity_id'],'period_key':f['period_key'],'status':f['status'],'outward_taxable':float(f['outward_taxable']),'outward_tax':float(f['outward_tax']),'inward_taxable':float(f['inward_taxable']),'inward_tax':float(f['inward_tax']),'adjustments':ads,'net_tax':float(net)}
    @app.get('/ui/gst-filing')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'gst-filing.html')
