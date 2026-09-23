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
        for pid,name in [('gst_compliance.view','View GST compliance'),('gst_compliance.manage','Manage GST compliance'),('gst_compliance.file','Mark GST filing status')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':pid,'n':name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_compliance_returns(
          return_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, return_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PREPARED',
          outward_tax NUMERIC NOT NULL DEFAULT 0, inward_tax NUMERIC NOT NULL DEFAULT 0, net_tax NUMERIC NOT NULL DEFAULT 0,
          amendment_count INTEGER NOT NULL DEFAULT 0, prepared_by TEXT NOT NULL, prepared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          filed_at TIMESTAMP, filing_reference TEXT, UNIQUE(filing_id,return_type))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS gst_compliance_documents(
          document_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, document_type TEXT NOT NULL, document_ref TEXT,
          taxable_value NUMERIC NOT NULL DEFAULT 0, tax_value NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'INCLUDED',
          created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

def register_v90ch_routes(app,engine):
    _ensure(engine)
    @app.get('/v90ch/gst/compliance')
    def summary(request:Request,filing_id:str):
        _perm(engine,request,'gst_compliance.view')
        with engine.connect() as c:
            f=c.execute(text('SELECT * FROM gst_filing_periods WHERE filing_id=:i'),{'i':filing_id}).mappings().first()
            if not f: raise HTTPException(404,'filing not found')
            rs=[dict(x) for x in c.execute(text('SELECT * FROM gst_compliance_returns WHERE filing_id=:i ORDER BY return_type'),{'i':filing_id}).mappings().all()]
            ds=[dict(x) for x in c.execute(text('SELECT * FROM gst_compliance_documents WHERE filing_id=:i ORDER BY created_at'),{'i':filing_id}).mappings().all()]
        return {'filing':dict(f),'returns':rs,'documents':ds}
    @app.post('/v90ch/gst/compliance/{filing_id}/prepare')
    def prepare(filing_id:str,request:Request,body:dict):
        u=_perm(engine,request,'gst_compliance.manage'); rtype=body.get('return_type','GST_RETURN')
        with engine.begin() as c:
            f=c.execute(text('SELECT * FROM gst_filing_periods WHERE filing_id=:i'),{'i':filing_id}).mappings().first()
            if not f: raise HTTPException(404,'filing not found')
            outward=_q(f['outward_tax']); inward=_q(f['inward_tax']); net=_q(f['net_tax']+f['adjustment_tax'])
            rid=str(uuid4())
            c.execute(text('''INSERT INTO gst_compliance_returns(return_id,filing_id,return_type,status,outward_tax,inward_tax,net_tax,prepared_by)
              VALUES(:r,:f,:t,'PREPARED',:o,:i,:n,:u) ON CONFLICT(filing_id,return_type) DO UPDATE SET status='PREPARED',outward_tax=:o,inward_tax=:i,net_tax=:n,prepared_by=:u,prepared_at=CURRENT_TIMESTAMP'''),{'r':rid,'f':filing_id,'t':rtype,'o':float(outward),'i':float(inward),'n':float(net),'u':str(u.user_id)})
            return {'filing_id':filing_id,'return_type':rtype,'status':'PREPARED','outward_tax':float(outward),'inward_tax':float(inward),'net_tax':float(net)}
    @app.post('/v90ch/gst/compliance/{filing_id}/document')
    def document(filing_id:str,request:Request,body:dict):
        u=_perm(engine,request,'gst_compliance.manage')
        with engine.begin() as c:
            if not c.execute(text('SELECT 1 FROM gst_filing_periods WHERE filing_id=:i'),{'i':filing_id}).first(): raise HTTPException(404,'filing not found')
            did=str(uuid4()); c.execute(text('INSERT INTO gst_compliance_documents(document_id,filing_id,document_type,document_ref,taxable_value,tax_value,created_by) VALUES(:d,:f,:t,:r,:v,:x,:u)'),{'d':did,'f':filing_id,'t':body.get('document_type','ADJUSTMENT'),'r':body.get('document_ref'),'v':float(_q(body.get('taxable_value'))),'x':float(_q(body.get('tax_value'))),'u':str(u.user_id)})
        return {'document_id':did,'filing_id':filing_id,'status':'INCLUDED'}
    @app.post('/v90ch/gst/compliance/{filing_id}/file')
    def mark_filed(filing_id:str,request:Request,body:dict):
        u=_perm(engine,request,'gst_compliance.file'); ref=body.get('filing_reference')
        if not ref: raise HTTPException(400,'filing_reference is required')
        with engine.begin() as c:
            r=c.execute(text("UPDATE gst_compliance_returns SET status='FILED',filed_at=CURRENT_TIMESTAMP,filing_reference=:r WHERE filing_id=:f AND status='PREPARED' RETURNING return_id"),{'r':ref,'f':filing_id}).first()
            if not r: raise HTTPException(409,'return must be PREPARED before filing')
            c.execute(text("UPDATE gst_filing_periods SET status='FILED' WHERE filing_id=:f AND status='LOCKED'"),{'f':filing_id})
        return {'filing_id':filing_id,'status':'FILED','filing_reference':ref,'filed_by':str(u.user_id)}
    @app.get('/v90ch/gst/compliance/{filing_id}/export')
    def export(filing_id:str,request:Request):
        _perm(engine,request,'gst_compliance.view')
        with engine.connect() as c:
            r=c.execute(text('SELECT * FROM gst_compliance_returns WHERE filing_id=:f ORDER BY return_type'),{'f':filing_id}).mappings().all()
            d=c.execute(text('SELECT document_type,document_ref,taxable_value,tax_value,status FROM gst_compliance_documents WHERE filing_id=:f ORDER BY created_at'),{'f':filing_id}).mappings().all()
        return {'format':'GST_COMPLIANCE_PACK_V1','filing_id':filing_id,'returns':[dict(x) for x in r],'documents':[dict(x) for x in d]}
    @app.get('/ui/gst-compliance')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'gst-compliance.html')
