from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u
def valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception: raise HTTPException(400,'period_key must be YYYY-MM')

def register_v90es_routes(app: FastAPI,e):
    with e.begin() as c:
        for p,n in [('maintenance_outcome_optimization.view','View Maintenance Outcome Optimization'),('maintenance_outcome_optimization.manage','Calculate Maintenance Outcome Optimization'),('maintenance_outcome_optimization.approve','Approve Reliability Actions'),('maintenance_outcome_optimization.close','Close Maintenance Outcome Optimization')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_outcome_optimization_snapshot(optimization_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,work_center_id TEXT,pm_orders INTEGER NOT NULL DEFAULT 0,corrective_orders INTEGER NOT NULL DEFAULT 0,pm_interventions INTEGER NOT NULL DEFAULT 0,corrective_interventions INTEGER NOT NULL DEFAULT 0,pm_successes INTEGER NOT NULL DEFAULT 0,corrective_successes INTEGER NOT NULL DEFAULT 0,post_intervention_breakdowns INTEGER NOT NULL DEFAULT 0,repeat_failures INTEGER NOT NULL DEFAULT 0,pm_success_rate NUMERIC NOT NULL DEFAULT 0,corrective_success_rate NUMERIC NOT NULL DEFAULT 0,intervention_success_rate NUMERIC NOT NULL DEFAULT 0,spare_usage_events INTEGER NOT NULL DEFAULT 0,labour_charge_events INTEGER NOT NULL DEFAULT 0,recommended_pm_change TEXT NOT NULL DEFAULT 'REVIEW',recommended_readiness_action TEXT NOT NULL DEFAULT 'REVIEW',reliability_opportunity_score NUMERIC NOT NULL DEFAULT 0,recommendation TEXT NOT NULL DEFAULT 'REVIEW',confidence TEXT NOT NULL DEFAULT 'LOW',status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_outcome_optimization_key ON maintenance_outcome_optimization_snapshot(organization_id,entity_id,period_key,work_center_id)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_action(action_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,work_center_id TEXT,action_type TEXT NOT NULL,recommendation TEXT NOT NULL,rationale TEXT NOT NULL,confidence TEXT NOT NULL DEFAULT 'LOW',status TEXT NOT NULL DEFAULT 'PROPOSED',approved_by TEXT,approved_at TIMESTAMP,decision_note TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_outcome_optimization_close(close_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'CLOSED',closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))

    @app.post('/v90es/maintenance/outcome-optimization/snapshot')
    def snapshot(body:dict,request:Request):
        u=perm(e,request,'maintenance_outcome_optimization.manage')
        for k in ('organization_id','entity_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        o,ei,pk=body['organization_id'],body['entity_id'],body['period_key']; valid(pk); wc=body.get('work_center_id')
        with e.connect() as c:
            if c.execute(text('SELECT 1 FROM maintenance_outcome_optimization_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
            clause=' AND mo.work_center_id=:w' if wc else ''; params={'o':o,'e':ei,'p':pk+'%','w':wc}
            orders=c.execute(text(f'''SELECT mo.order_id,mo.work_center_id,UPPER(mo.order_type) order_type FROM maintenance_order mo WHERE mo.organization_id=:o AND mo.entity_id=:e AND CAST(mo.scheduled_date AS TEXT) LIKE :p{clause} ORDER BY mo.work_center_id,mo.order_id'''),params).mappings().all()
            centers=sorted({r['work_center_id'] for r in orders})
            # Include queue/risk work centers even when they had no maintenance order in the period.
            extra=c.execute(text('SELECT work_center_id FROM maintenance_execution_feedback_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'+(' AND work_center_id=:w' if wc else '')),{'o':o,'e':ei,'p':pk,'w':wc}).scalars().all()
            centers=sorted(set(centers)|set(extra))
            results=[]
            for w in centers:
                os=[r for r in orders if r['work_center_id']==w]
                pm=[r for r in os if r['order_type']=='PREVENTIVE']; corr=[r for r in os if r['order_type']!='PREVENTIVE']
                pi=ci=ps=cs=post=repeat=0
                for mo in os:
                    evs=c.execute(text('SELECT event_id,event_type,event_at FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND maintenance_order_id=:id ORDER BY event_at'),{'o':o,'e':ei,'id':mo['order_id']}).mappings().all()
                    ints=[x for x in evs if str(x['event_type']).upper()!='BREAKDOWN']
                    if not ints: continue
                    if mo['order_type']=='PREVENTIVE': pi+=1
                    else: ci+=1
                    first=str(ints[0]['event_at'])
                    brs=c.execute(text('''SELECT event_at FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND event_type='BREAKDOWN' AND CAST(event_at AS TEXT)>:at ORDER BY event_at LIMIT 2'''),{'o':o,'e':ei,'w':w,'at':first}).scalars().all()
                    if brs:
                        post+=len(brs); repeat+=max(0,len(brs)-1)
                    elif mo['order_type']=='PREVENTIVE': ps+=1
                    else: cs+=1
                spare=int(c.execute(text('SELECT COUNT(*) FROM maintenance_spare_usage WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND CAST(created_at AS TEXT) LIKE :p'),{'o':o,'e':ei,'w':w,'p':pk+'%'}).scalar() or 0)
                labour=int(c.execute(text('SELECT COUNT(*) FROM maintenance_labour_charge WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND CAST(charge_date AS TEXT) LIKE :p'),{'o':o,'e':ei,'w':w,'p':pk+'%'}).scalar() or 0)
                pmrate=d(Decimal(ps)/Decimal(pi)*100) if pi else d(0); crrate=d(Decimal(cs)/Decimal(ci)*100) if ci else d(0); total_i=pi+ci; success=d(Decimal(ps+cs)/Decimal(total_i)*100) if total_i else d(0)
                opportunity=d(min(100, Decimal(post)*20 + Decimal(repeat)*15 + (Decimal(100)-success)*Decimal('.45') + min(20,Decimal(spare+labour)*2)))
                if opportunity>=70: rec='PRIORITIZE_RELIABILITY_ACTION'
                elif opportunity>=40: rec='REVIEW_PM_AND_READINESS'
                else: rec='MONITOR'
                pmchange='SHORTEN_PM_INTERVAL' if post and pmrate<crrate else ('REVIEW_PM_INTERVAL' if pi else 'NO_PM_CHANGE')
                readiness='INCREASE_SPARE_AND_SKILL_READINESS' if spare+labour>=3 or post else 'STANDARD_READINESS'
                confidence='HIGH' if total_i>=5 else ('MEDIUM' if total_i>=2 else 'LOW')
                results.append((w,len(pm),len(corr),pi,ci,ps,cs,post,repeat,pmrate,crrate,success,spare,labour,pmchange,readiness,opportunity,rec,confidence))
        with e.begin() as c:
            for r in results:
                w,po,co,pi,ci,ps,cs,post,repeat,pmrate,crrate,success,spare,labour,pmchange,readiness,opp,rec,conf=r
                oid=str(uuid4())
                c.execute(text('''INSERT INTO maintenance_outcome_optimization_snapshot(optimization_id,organization_id,entity_id,period_key,work_center_id,pm_orders,corrective_orders,pm_interventions,corrective_interventions,pm_successes,corrective_successes,post_intervention_breakdowns,repeat_failures,pm_success_rate,corrective_success_rate,intervention_success_rate,spare_usage_events,labour_charge_events,recommended_pm_change,recommended_readiness_action,reliability_opportunity_score,recommendation,confidence,status,created_by) VALUES(:i,:o,:e,:p,:w,:po,:co,:pi,:ci,:ps,:cs,:pb,:rf,:pr,:cr,:sr,:su,:lc,:pc,:ra,:os,:rec,:cf,'OPEN',:u) ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET pm_orders=:po,corrective_orders=:co,pm_interventions=:pi,corrective_interventions=:ci,pm_successes=:ps,corrective_successes=:cs,post_intervention_breakdowns=:pb,repeat_failures=:rf,pm_success_rate=:pr,corrective_success_rate=:cr,intervention_success_rate=:sr,spare_usage_events=:su,labour_charge_events=:lc,recommended_pm_change=:pc,recommended_readiness_action=:ra,reliability_opportunity_score=:os,recommendation=:rec,confidence=:cf,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':oid,'o':o,'e':ei,'p':pk,'w':w,'po':po,'co':co,'pi':pi,'ci':ci,'ps':ps,'cs':cs,'pb':post,'rf':repeat,'pr':float(pmrate),'cr':float(crrate),'sr':float(success),'su':spare,'lc':labour,'pc':pmchange,'ra':readiness,'os':float(opp),'rec':rec,'cf':conf,'u':str(u.user_id)})
                # Refresh proposals for this work center; approvals remain explicit and separate.
                c.execute(text('DELETE FROM maintenance_reliability_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND work_center_id=:w AND status=:s'),{'o':o,'e':ei,'p':pk,'w':w,'s':'PROPOSED'})
                c.execute(text('''INSERT INTO maintenance_reliability_action(action_id,organization_id,entity_id,period_key,work_center_id,action_type,recommendation,rationale,confidence,created_by) VALUES(:i,:o,:e,:p,:w,'PM_STRATEGY',:r,:x,:c,:u),(:j,:o,:e,:p,:w,'READINESS',:rr,:rx,:c,:u)'''),{'i':str(uuid4()),'j':str(uuid4()),'o':o,'e':ei,'p':pk,'w':w,'r':pmchange,'x':f'PM success {pmrate}%; post-intervention breakdowns {post}.','rr':readiness,'rx':f'Spare usage events {spare}; labour charge events {labour}; repeat failures {repeat}.','c':conf,'u':str(u.user_id)})
        return {'period_key':pk,'count':len(results),'rows':[{'work_center_id':r[0],'pm_orders':r[1],'corrective_orders':r[2],'pm_success_rate':float(r[9]),'corrective_success_rate':float(r[10]),'intervention_success_rate':float(r[11]),'post_intervention_breakdowns':r[7],'repeat_failures':r[8],'recommended_pm_change':r[14],'recommended_readiness_action':r[15],'reliability_opportunity_score':float(r[16]),'recommendation':r[17],'confidence':r[18]} for r in results]}

    @app.get('/v90es/maintenance/outcome-optimization/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_outcome_optimization.view')
        with e.connect() as c: rows=c.execute(text('SELECT * FROM maintenance_outcome_optimization_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY reliability_opportunity_score DESC,work_center_id'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'opportunity_count':sum(float(r['reliability_opportunity_score'] or 0)>=40 for r in rows),'avg_intervention_success_rate':float(d(sum(Decimal(str(r['intervention_success_rate'] or 0)) for r in rows)/len(rows))) if rows else 0,'post_intervention_breakdowns':sum(int(r['post_intervention_breakdowns'] or 0) for r in rows),'repeat_failures':sum(int(r['repeat_failures'] or 0) for r in rows),'rows':[dict(r) for r in rows]}

    @app.get('/v90es/maintenance/outcome-optimization/actions')
    def actions(request:Request,organization_id:str,entity_id:str,period_key:str,status:str|None=None):
        perm(e,request,'maintenance_outcome_optimization.view'); clause=''; params={'o':organization_id,'e':entity_id,'p':period_key}
        if status: clause=' AND status=:s'; params['s']=status.upper()
        with e.connect() as c: rows=c.execute(text('SELECT * FROM maintenance_reliability_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p'+clause+' ORDER BY created_at DESC'),params).mappings().all()
        return {'count':len(rows),'actions':[dict(r) for r in rows]}

    @app.post('/v90es/maintenance/outcome-optimization/actions/{action_id}/approve')
    def approve(action_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_outcome_optimization.approve')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_action SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,decision_note=:n WHERE action_id=:i AND status='PROPOSED' RETURNING action_id"),{'u':str(u.user_id),'n':body.get('decision_note'),'i':action_id}).first()
            if not r: raise HTTPException(404,'proposed action not found')
        return {'action_id':action_id,'status':'APPROVED'}

    @app.post('/v90es/maintenance/outcome-optimization/actions/{action_id}/reject')
    def reject(action_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_outcome_optimization.approve')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_action SET status='REJECTED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,decision_note=:n WHERE action_id=:i AND status='PROPOSED' RETURNING action_id"),{'u':str(u.user_id),'n':body.get('decision_note'),'i':action_id}).first()
            if not r: raise HTTPException(404,'proposed action not found')
        return {'action_id':action_id,'status':'REJECTED'}

    @app.post('/v90es/maintenance/outcome-optimization/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_outcome_optimization.close'); valid(period_key)
        if not body.get('organization_id') or not body.get('entity_id'): raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_outcome_optimization_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'p':period_key,'u':str(u.user_id)})
            c.execute(text("UPDATE maintenance_outcome_optimization_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':body['organization_id'],'e':body['entity_id'],'p':period_key})
        return {'period_key':period_key,'status':'CLOSED'}

    @app.get('/ui/maintenance-outcome-optimization')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-outcome-optimization.html')
