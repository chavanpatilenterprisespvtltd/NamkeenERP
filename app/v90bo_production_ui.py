from __future__ import annotations
import json
from uuid import UUID
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

HTML = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Production | Namkeen ERP</title><link rel="stylesheet" href="/web/assets/app.css"></head><body><main class="shell"><header><div><h1>Production Operations</h1><span class="muted">Planning, material issue, batches and production QC</span></div><a class="pill" href="/web">ERP Home</a></header><section class="card"><form id="f"><input id="o" placeholder="Organization ID" required><input id="e" placeholder="Entity ID" required><input id="l" placeholder="Location ID" required><button>Load Production</button></form><p id="err" class="error"></p></section><section id="kpi" class="metric-grid"></section><section class="grid"><article><h2>Plans</h2><div id="plans" class="list"></div></article><article><h2>Production Orders</h2><div id="orders" class="list"></div></article><article><h2>Production Batches</h2><div id="batches" class="list"></div></article><article><h2>Recent Process Logs / QC</h2><div id="qc" class="list"></div></article></section></main><script>const $=x=>document.getElementById(x),token=sessionStorage.getItem('erp_token')||localStorage.getItem('erp_token')||'';const esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]||c));async function get(path,p){const r=await fetch(path+'?'+p,{headers:{Authorization:`Bearer ${token}`}});const d=await r.json();if(!r.ok)throw Error(d.detail||'Load failed');return d}$("f").addEventListener('submit',async ev=>{ev.preventDefault();$("err").textContent='';try{const p=new URLSearchParams({organization_id:$("o").value,entity_id:$("e").value,location_id:$("l").value});const [s,pl,po,ba,qc]=await Promise.all([get('/v90bo/production/summary',p),get('/v90bo/plans',p),get('/v90bo/orders',p),get('/v90bo/batches',p),get('/v90bo/qc',p)]);$("kpi").innerHTML=Object.entries(s.counts).map(([k,v])=>`<div class="card metric"><div class="metric-label">${esc(k.replaceAll('_',' '))}</div><div class="metric-value">${esc(v)}</div></div>`).join('');$("plans").innerHTML=pl.items.map(x=>`<div class="list-item"><strong>${esc(x.plan_no)} · ${esc(x.status)}</strong><small>${esc(x.period_start)} → ${esc(x.period_end)}</small></div>`).join('')||'<div class="empty">No plans.</div>';$('orders').innerHTML=po.items.map(x=>`<div class="list-item"><strong>${esc(x.order_no)} · ${esc(x.status)}</strong><small>Product ${esc(x.product_master_id)} · ${esc(x.planned_qty)} ${esc(x.uom)}</small></div>`).join('')||'<div class="empty">No orders.</div>';$('batches').innerHTML=ba.items.map(x=>`<div class="list-item"><strong>${esc(x.batch_no)} · ${esc(x.status)}</strong><small>Product ${esc(x.product_master_id)} · ${esc(x.planned_qty)} ${esc(x.uom)}</small></div>`).join('')||'<div class="empty">No batches.</div>';$('qc').innerHTML=qc.items.map(x=>`<div class="list-item"><strong>${esc(x.stage)} · ${esc(x.status)}</strong><small>Batch ${esc(x.batch_id)} · ${esc(x.decision||'NO DECISION')}</small><small>${esc(x.created_at||'')}</small></div>`).join('')||'<div class="empty">No process/QC entries.</div>'}catch(e){$("err").textContent=e.message}});</script></body></html>'''

def _require(engine, request: Request, entity_id: UUID, location_id: UUID, write=False):
    user=authenticate(request); p=permissions_for_user(engine,user.user_id)
    need='production.edit' if write else 'production.view'
    if need not in p: raise HTTPException(403,'permission denied')
    try: assert_entity_location_allowed(engine,user.user_id,str(entity_id),str(location_id))
    except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
    return user

def _count(engine, table, where, params):
    try:
        with engine.connect() as c: return int(c.execute(text(f'SELECT COUNT(*) FROM {table} WHERE {where}'),params).scalar_one() or 0)
    except Exception: return 0

def ensure_production_ui_schema(engine):
    with engine.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS ui_production_preferences (preference_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,screen_key TEXT NOT NULL,filters TEXT NOT NULL DEFAULT '{}',columns TEXT NOT NULL DEFAULT '[]',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_ui_production_preferences ON ui_production_preferences(user_id,screen_key)'))
        c.execute(text("INSERT INTO erp_roles(role_id,role_name) VALUES ('production','Production') ON CONFLICT(role_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES ('production.view','View production') ON CONFLICT(permission_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES ('production.edit','Edit production') ON CONFLICT(permission_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES ('production','production.view') ON CONFLICT(role_id,permission_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES ('production','production.edit') ON CONFLICT(role_id,permission_id) DO NOTHING"))

def register_v90bo_routes(app: FastAPI, engine):
    ensure_production_ui_schema(engine)
    @app.get('/ui/production')
    def production_page(): return HTML
    @app.get('/v90bo/production/summary')
    def summary(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID):
        _require(engine,request,entity_id,location_id)
        p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        counts={'plans':_count(engine,'production_plan','organization_id=:o AND entity_id=:e AND location_id=:l',p),'pending_plan_approvals':_count(engine,'production_plan',"organization_id=:o AND entity_id=:e AND location_id=:l AND status='PENDING_APPROVAL'",p),'orders':_count(engine,'production_order','organization_id=:o AND entity_id=:e AND location_id=:l',p),'open_orders':_count(engine,'production_order',"organization_id=:o AND entity_id=:e AND location_id=:l AND status NOT IN ('COMPLETED','CLOSED')",p),'batches':_count(engine,'production_batch','organization_id=:o AND entity_id=:e AND location_id=:l',p),'running_batches':_count(engine,'production_batch',"organization_id=:o AND entity_id=:e AND location_id=:l AND status='RUNNING'",p),'material_issues':_count(engine,'production_material_issue','organization_id=:o AND entity_id=:e AND location_id=:l',p),'process_logs':_count(engine,'production_process_log','organization_id=:o AND entity_id=:e AND location_id=:l',p)}
        return {'counts':counts}
    @app.get('/v90bo/plans')
    def plans(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID,status:str|None=None,limit:int=100):
        _require(engine,request,entity_id,location_id); q='SELECT plan_id,plan_no,period_start,period_end,status,source,created_at FROM production_plan WHERE organization_id=:o AND entity_id=:e AND location_id=:l';p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if status:q+=' AND status=:s';p['s']=status.upper()
        q+=' ORDER BY created_at DESC LIMIT :lim';p['lim']=max(1,min(limit,200))
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(q),p).mappings().all()]
        return {'items':rows,'count':len(rows)}
    @app.get('/v90bo/orders')
    def orders(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID,status:str|None=None,limit:int=100):
        _require(engine,request,entity_id,location_id); q='SELECT production_order_id,order_no,product_master_id,planned_qty,uom,status,scheduled_start,scheduled_end,created_at FROM production_order WHERE organization_id=:o AND entity_id=:e AND location_id=:l';p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if status:q+=' AND status=:s';p['s']=status.upper()
        q+=' ORDER BY created_at DESC LIMIT :lim';p['lim']=max(1,min(limit,200))
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(q),p).mappings().all()]
        return {'items':rows,'count':len(rows)}
    @app.get('/v90bo/batches')
    def batches(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID,status:str|None=None,limit:int=100):
        _require(engine,request,entity_id,location_id); q='SELECT batch_id,batch_no,production_order_id,product_master_id,planned_qty,uom,status,start_at,end_at,operator_user_id,machine_id,created_at FROM production_batch WHERE organization_id=:o AND entity_id=:e AND location_id=:l';p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if status:q+=' AND status=:s';p['s']=status.upper()
        q+=' ORDER BY created_at DESC LIMIT :lim';p['lim']=max(1,min(limit,200))
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(q),p).mappings().all()]
        return {'items':rows,'count':len(rows)}
    @app.get('/v90bo/qc')
    def qc(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID,limit:int=100):
        _require(engine,request,entity_id,location_id); items=[]
        with engine.connect() as c:
            if _count(engine,'production_process_log','organization_id=:o AND entity_id=:e AND location_id=:l',{'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}):
                rows=c.execute(text('SELECT l.process_log_id,l.batch_id,l.stage,l.status,l.deviation_flag,l.created_at,d.decision,d.reason FROM production_process_log l LEFT JOIN production_process_qc_decision d ON d.process_log_id=l.process_log_id WHERE l.organization_id=:o AND l.entity_id=:e AND l.location_id=:l ORDER BY l.created_at DESC LIMIT :lim'),{'o':str(organization_id),'e':str(entity_id),'l':str(location_id),'lim':max(1,min(limit,200))}).mappings().all(); items=[dict(r) for r in rows]
        return {'items':items,'count':len(items)}
    @app.get('/v90bo/preferences/{screen_key}')
    def get_pref(screen_key:str,request:Request):
        u=authenticate(request)
        with engine.connect() as c: row=c.execute(text('SELECT filters,columns FROM ui_production_preferences WHERE user_id=:u AND screen_key=:s'),{'u':str(u.user_id),'s':screen_key}).mappings().first()
        return {'screen_key':screen_key,'filters':json.loads(row['filters']) if row else {},'columns':json.loads(row['columns']) if row else []}
    @app.put('/v90bo/preferences/{screen_key}')
    def set_pref(screen_key:str,payload:dict,request:Request):
        u=_require(engine,request,UUID(str(payload.get('entity_id'))) if payload.get('entity_id') else UUID(int=0),UUID(str(payload.get('location_id'))) if payload.get('location_id') else UUID(int=0),write=True) if payload.get('entity_id') and payload.get('location_id') else authenticate(request)
        filters=payload.get('filters',{}); columns=payload.get('columns',[])
        if not isinstance(filters,dict) or not isinstance(columns,list) or len(columns)>60: raise HTTPException(400,'invalid preference payload')
        if engine.dialect.name=='postgresql':
            sql='''INSERT INTO ui_production_preferences(preference_id,user_id,screen_key,filters,columns) VALUES(gen_random_uuid(),:u,:s,CAST(:f AS jsonb),CAST(:c AS jsonb)) ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=EXCLUDED.filters,columns=EXCLUDED.columns,updated_at=now()'''; params={'u':str(u.user_id),'s':screen_key,'f':json.dumps(filters),'c':json.dumps(columns)}
        else:
            from uuid import uuid4
            sql='''INSERT INTO ui_production_preferences(preference_id,user_id,screen_key,filters,columns) VALUES(:id,:u,:s,:f,:c) ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=excluded.filters,columns=excluded.columns,updated_at=CURRENT_TIMESTAMP''';params={'id':uuid4().hex,'u':str(u.user_id),'s':screen_key,'f':json.dumps(filters),'c':json.dumps(columns)}
        with engine.begin() as c:c.execute(text(sql),params)
        return {'screen_key':screen_key,'filters':filters,'columns':columns}
