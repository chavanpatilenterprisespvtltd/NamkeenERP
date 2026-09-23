from __future__ import annotations
from datetime import date
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

def _ensure(e):
    with e.begin() as c:
        for p,n in [('po_control.view','View PO Controls'),('po_control.manage','Manage PO Controls'),('po_control.approve','Approve Purchase Orders')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_po_control(control_id TEXT PRIMARY KEY,po_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,approval_limit NUMERIC NOT NULL DEFAULT 0,order_value NUMERIC NOT NULL DEFAULT 0,price_variance_pct NUMERIC NOT NULL DEFAULT 0,landed_cost NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'PENDING',exception_code TEXT,created_by TEXT NOT NULL,approved_by TEXT,approved_at TIMESTAMP,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_price_history(price_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,supplier_id TEXT NOT NULL,item_master_id TEXT NOT NULL,unit_rate NUMERIC NOT NULL,landed_cost NUMERIC NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'INR',source_po_id TEXT,effective_date TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_supplier_rebate(rebate_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,supplier_id TEXT NOT NULL,item_master_id TEXT,threshold_qty NUMERIC NOT NULL DEFAULT 0,rebate_pct NUMERIC NOT NULL DEFAULT 0,credit_note_required INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL DEFAULT 'ACTIVE',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS procurement_commitment_snapshot(snapshot_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NOT NULL,supplier_id TEXT NOT NULL,committed_value NUMERIC NOT NULL DEFAULT 0,open_qty NUMERIC NOT NULL DEFAULT 0,as_of_date TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

def register_v90ct_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90ct/procurement/po/from-requisition')
    def from_req(body:dict,request:Request):
        u=_perm(e,request,'po_control.manage'); rid=body.get('requisition_id')
        with e.begin() as c:
            req=c.execute(text('SELECT * FROM procurement_requisition WHERE requisition_id=:i'),{'i':rid}).mappings().first()
            if not req: raise HTTPException(404,'requisition not found')
            if req['status'] not in ('DRAFT','APPROVED'): raise HTTPException(409,'requisition is not convertible')
            supplier=body.get('supplier_id'); quote=body.get('quote_id'); poid=str(uuid4()); pono=body.get('po_no') or ('PO-'+poid[:8].upper())
            c.execute(text('''INSERT INTO procurement_po(po_id,organization_id,entity_id,location_id,supplier_id,requisition_id,quote_id,po_no,po_date,expected_date,status,currency,payment_terms_days,delivery_terms,notes,requested_by) VALUES(:i,:o,:e,:l,:s,:r,:q,:n,:d,:ed,'PENDING_APPROVAL',:cur,:pt,:dt,:no,:by)'''),{'i':poid,'o':req['organization_id'],'e':req['entity_id'],'l':req['location_id'],'s':supplier or 'UNASSIGNED','r':rid,'q':quote,'n':pono,'d':date.today().isoformat(),'ed':body.get('expected_date'),'cur':body.get('currency','INR'),'pt':body.get('payment_terms_days'),'dt':body.get('delivery_terms'),'no':body.get('notes'),'by':str(u.user_id)})
            lines=c.execute(text('SELECT * FROM procurement_requisition_line WHERE requisition_id=:i ORDER BY line_no'),{'i':rid}).mappings().all()
            if not lines: raise HTTPException(409,'requisition has no lines')
            total=0
            for x in lines:
                rate=float(body.get('unit_rate',0)); total += float(x['qty'])*rate
                c.execute(text('''INSERT INTO procurement_po_line(line_id,po_id,line_no,item_master_id,description,qty,uom,unit_rate,discount,tax_rate,expected_date,notes) VALUES(:i,:p,:n,:m,:d,:q,:u,:r,0,0,:ed,:no)'''),{'i':str(uuid4()),'p':poid,'n':x['line_no'],'m':x['item_master_id'],'d':x.get('description'),'q':x['qty'],'u':x['uom'],'r':rate,'ed':x.get('required_date'),'no':x.get('notes')})
            c.execute(text("UPDATE procurement_requisition SET status='CONVERTED' WHERE requisition_id=:i"),{'i':rid})
            c.execute(text('''INSERT INTO procurement_po_control(control_id,po_id,organization_id,entity_id,approval_limit,order_value,price_variance_pct,landed_cost,status,created_by) VALUES(:i,:p,:o,:e,:lim,:v,:pv,:lc,'PENDING',:by)'''),{'i':str(uuid4()),'p':poid,'o':req['organization_id'],'e':req['entity_id'],'lim':float(body.get('approval_limit',0)),'v':total,'pv':float(body.get('price_variance_pct',0)),'lc':float(body.get('landed_cost',total)),'by':str(u.user_id)})
        return {'po_id':poid,'po_no':pono,'status':'PENDING_APPROVAL','order_value':total}
    @app.post('/v90ct/procurement/po/{po_id}/approve')
    def approve(po_id:str,request:Request):
        u=_perm(e,request,'po_control.approve')
        with e.begin() as c:
            row=c.execute(text("SELECT p.po_id,c.order_value,c.approval_limit FROM procurement_po p JOIN procurement_po_control c ON c.po_id=p.po_id WHERE p.po_id=:i AND p.status='PENDING_APPROVAL'"),{'i':po_id}).mappings().first()
            if not row: raise HTTPException(404,'pending PO not found')
            c.execute(text("UPDATE procurement_po SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE po_id=:i"),{'i':po_id,'u':str(u.user_id)})
            c.execute(text("UPDATE procurement_po_control SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE po_id=:i"),{'i':po_id,'u':str(u.user_id)})
        return {'po_id':po_id,'status':'APPROVED'}
    @app.post('/v90ct/procurement/price-history')
    def price(body:dict,request:Request):
        u=_perm(e,request,'po_control.manage')
        required=('organization_id','entity_id','supplier_id','item_master_id','unit_rate')
        if any(not str(body.get(k) or '').strip() for k in required): raise HTTPException(400,'required fields missing')
        pid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO procurement_price_history(price_id,organization_id,entity_id,supplier_id,item_master_id,unit_rate,landed_cost,currency,source_po_id,effective_date) VALUES(:i,:o,:e,:s,:m,:r,:l,:c,:p,:d)'''),{'i':pid,'o':body['organization_id'],'e':body['entity_id'],'s':body['supplier_id'],'m':body['item_master_id'],'r':float(body['unit_rate']),'l':float(body.get('landed_cost',body['unit_rate'])),'c':body.get('currency','INR'),'p':body.get('source_po_id'),'d':body.get('effective_date',date.today().isoformat())})
        return {'price_id':pid,'status':'RECORDED'}
    @app.get('/v90ct/procurement/commitments')
    def commitments(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'po_control.view')
        with e.connect() as c:
            rows=c.execute(text("SELECT supplier_id,COUNT(*) po_count,COALESCE(SUM((SELECT COALESCE(SUM(qty*unit_rate),0) FROM procurement_po_line l WHERE l.po_id=p.po_id)),0) committed_value FROM procurement_po p WHERE organization_id=:o AND entity_id=:e AND status IN ('PENDING_APPROVAL','APPROVED') GROUP BY supplier_id"),{'o':organization_id,'e':entity_id}).mappings().all()
        return {'organization_id':organization_id,'entity_id':entity_id,'commitments':[dict(x) for x in rows]}
    @app.get('/ui/procurement-controls')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'procurement-controls.html')
