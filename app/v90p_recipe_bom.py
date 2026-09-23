from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def ensure_recipe_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS recipe (
            recipe_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            product_master_id TEXT NOT NULL, recipe_code TEXT NOT NULL, recipe_name TEXT NOT NULL,
            version_no INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
            effective_from TEXT NULL, effective_to TEXT NULL, yield_qty NUMERIC NOT NULL DEFAULT 100,
            yield_uom TEXT NOT NULL DEFAULT 'kg', expected_loss_pct NUMERIC NOT NULL DEFAULT 0,
            notes TEXT NULL, created_by TEXT NOT NULL, approved_by TEXT NULL,
            approved_at TEXT NULL, approval_reason TEXT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_recipe_code_version
           ON recipe(organization_id, entity_id, recipe_code, version_no)""",
        """CREATE TABLE IF NOT EXISTS recipe_line (
            recipe_line_id TEXT PRIMARY KEY, recipe_id TEXT NOT NULL, line_no INTEGER NOT NULL,
            material_master_id TEXT NOT NULL, material_type TEXT NOT NULL DEFAULT 'RAW_MATERIAL',
            qty NUMERIC NOT NULL, uom TEXT NOT NULL, scrap_pct NUMERIC NOT NULL DEFAULT 0,
            notes TEXT NULL, FOREIGN KEY(recipe_id) REFERENCES recipe(recipe_id)
        )""",
        """CREATE TABLE IF NOT EXISTS recipe_packaging_line (
            recipe_packaging_line_id TEXT PRIMARY KEY, recipe_id TEXT NOT NULL, line_no INTEGER NOT NULL,
            packaging_master_id TEXT NOT NULL, qty NUMERIC NOT NULL, uom TEXT NOT NULL,
            notes TEXT NULL, FOREIGN KEY(recipe_id) REFERENCES recipe(recipe_id)
        )""",
        """CREATE TABLE IF NOT EXISTS material_requirement_calc (
            calc_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, plan_line_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL, material_master_id TEXT NOT NULL, requirement_type TEXT NOT NULL,
            gross_qty NUMERIC NOT NULL, scrap_qty NUMERIC NOT NULL DEFAULT 0, required_qty NUMERIC NOT NULL,
            uom TEXT NOT NULL, available_qty NUMERIC NULL, shortage_qty NUMERIC NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))


class RecipeLineIn(BaseModel):
    material_master_id: UUID
    material_type: str = 'RAW_MATERIAL'
    qty: float = Field(gt=0)
    uom: str = Field(min_length=1)
    scrap_pct: float = Field(default=0, ge=0, lt=100)
    notes: str | None = None

class PackagingLineIn(BaseModel):
    packaging_master_id: UUID
    qty: float = Field(gt=0)
    uom: str = Field(min_length=1)
    notes: str | None = None

class RecipeIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    product_master_id: UUID
    recipe_code: str = Field(min_length=1)
    recipe_name: str = Field(min_length=1)
    version_no: int = Field(default=1, ge=1)
    yield_qty: float = Field(default=100, gt=0)
    yield_uom: str = 'kg'
    expected_loss_pct: float = Field(default=0, ge=0, lt=100)
    effective_from: str | None = None
    effective_to: str | None = None
    notes: str | None = None
    lines: list[RecipeLineIn] = Field(min_length=1)
    packaging: list[PackagingLineIn] = []

class DecisionIn(BaseModel):
    reason: str = ''


def _require(engine, request: Request, entity_id: UUID, location_id: UUID | None, write: bool, approve: bool=False):
    user = authenticate(request)
    perm = 'production.approve' if approve else ('production.edit' if write else 'production.view')
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    if location_id is not None:
        try:
            assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    return user


def _master_exists(engine, organization_id: UUID, entity_id: UUID, master_id: UUID, master_type: str | None = None):
    q = """SELECT master_id, entity_id, active, master_type FROM master_record
           WHERE replace(lower(organization_id),'-','')=replace(lower(:o),'-','')
             AND replace(lower(master_id),'-','')=replace(lower(:m),'-','')"""
    p={'o':str(organization_id),'m':str(master_id)}
    if master_type:
        q += ' AND master_type=:t'; p['t']=master_type
    with engine.connect() as conn:
        row=conn.execute(text(q),p).mappings().first()
    if not row or not row['active']:
        raise HTTPException(422, f'Referenced master not found: {master_id}')
    if row['entity_id'] not in (None, str(entity_id), str(entity_id).replace('-','')):
        raise HTTPException(422, 'Referenced master is outside entity scope')


def register_v90p_routes(app: FastAPI, engine) -> None:
    ensure_recipe_schema(engine)

    @app.post('/v90p/recipes')
    def create_recipe(body: RecipeIn, request: Request):
        user=_require(engine,request,body.entity_id,None,True)
        if body.effective_to and body.effective_from and body.effective_to < body.effective_from:
            raise HTTPException(422,'effective_to must be on/after effective_from')
        _master_exists(engine,body.organization_id,body.entity_id,body.product_master_id,'PRODUCT')
        for l in body.lines: _master_exists(engine,body.organization_id,body.entity_id,l.material_master_id)
        for l in body.packaging: _master_exists(engine,body.organization_id,body.entity_id,l.packaging_master_id)
        with engine.connect() as conn:
            exists=conn.execute(text('SELECT 1 FROM recipe WHERE organization_id=:o AND entity_id=:e AND recipe_code=:c AND version_no=:v'),{'o':str(body.organization_id),'e':str(body.entity_id),'c':body.recipe_code,'v':body.version_no}).first()
        if exists: raise HTTPException(409,'recipe code/version already exists')
        rid=uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO recipe(recipe_id,organization_id,entity_id,product_master_id,recipe_code,recipe_name,version_no,status,effective_from,effective_to,yield_qty,yield_uom,expected_loss_pct,notes,created_by)
                VALUES(:id,:o,:e,:p,:c,:n,:v,'DRAFT',:ef,:et,:y,:yu,:lp,:notes,:u)"""),{
                'id':str(rid),'o':str(body.organization_id),'e':str(body.entity_id),'p':str(body.product_master_id),'c':body.recipe_code,'n':body.recipe_name,'v':body.version_no,'ef':body.effective_from,'et':body.effective_to,'y':body.yield_qty,'yu':body.yield_uom,'lp':body.expected_loss_pct,'notes':body.notes,'u':str(user.user_id)})
            for i,l in enumerate(body.lines,1):
                conn.execute(text("""INSERT INTO recipe_line(recipe_line_id,recipe_id,line_no,material_master_id,material_type,qty,uom,scrap_pct,notes)
                    VALUES(:id,:r,:n,:m,:t,:q,:u,:s,:notes)"""),{'id':str(uuid4()),'r':str(rid),'n':i,'m':str(l.material_master_id),'t':l.material_type,'q':l.qty,'u':l.uom,'s':l.scrap_pct,'notes':l.notes})
            for i,l in enumerate(body.packaging,1):
                conn.execute(text("""INSERT INTO recipe_packaging_line(recipe_packaging_line_id,recipe_id,line_no,packaging_master_id,qty,uom,notes)
                    VALUES(:id,:r,:n,:m,:q,:u,:notes)"""),{'id':str(uuid4()),'r':str(rid),'n':i,'m':str(l.packaging_master_id),'q':l.qty,'u':l.uom,'notes':l.notes})
        return {'recipe_id':str(rid),'status':'DRAFT','version_no':body.version_no}

    @app.get('/v90p/recipes/{recipe_id}')
    def get_recipe(recipe_id: UUID, request: Request):
        user=authenticate(request)
        if 'production.view' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.connect() as conn:
            r=conn.execute(text('SELECT * FROM recipe WHERE recipe_id=:id'),{'id':str(recipe_id)}).mappings().first()
            if not r: raise HTTPException(404,'recipe not found')
            lines=conn.execute(text('SELECT * FROM recipe_line WHERE recipe_id=:id ORDER BY line_no'),{'id':str(recipe_id)}).mappings().all()
            packaging=conn.execute(text('SELECT * FROM recipe_packaging_line WHERE recipe_id=:id ORDER BY line_no'),{'id':str(recipe_id)}).mappings().all()
        return {'recipe':dict(r),'lines':[dict(x) for x in lines],'packaging':[dict(x) for x in packaging]}

    @app.post('/v90p/recipes/{recipe_id}/submit')
    def submit(recipe_id: UUID, body: DecisionIn, request: Request):
        user=authenticate(request)
        if 'production.edit' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row=conn.execute(text('SELECT status FROM recipe WHERE recipe_id=:id'),{'id':str(recipe_id)}).mappings().first()
            if not row: raise HTTPException(404,'recipe not found')
            if row['status']!='DRAFT': raise HTTPException(409,'only draft recipe can be submitted')
            conn.execute(text("UPDATE recipe SET status='PENDING_APPROVAL' WHERE recipe_id=:id"),{'id':str(recipe_id)})
        return {'recipe_id':str(recipe_id),'status':'PENDING_APPROVAL'}

    @app.post('/v90p/recipes/{recipe_id}/approve')
    def approve(recipe_id: UUID, body: DecisionIn, request: Request):
        user=authenticate(request)
        if 'production.approve' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row=conn.execute(text('SELECT status,created_by FROM recipe WHERE recipe_id=:id'),{'id':str(recipe_id)}).mappings().first()
            if not row: raise HTTPException(404,'recipe not found')
            if row['status']!='PENDING_APPROVAL': raise HTTPException(409,'only pending recipe can be approved')
            if str(row['created_by'])==str(user.user_id): raise HTTPException(409,'self-approval is not allowed')
            conn.execute(text("UPDATE recipe SET status='APPROVED', approved_by=:u, approved_at=CURRENT_TIMESTAMP, approval_reason=:r WHERE recipe_id=:id"),{'u':str(user.user_id),'r':body.reason,'id':str(recipe_id)})
        return {'recipe_id':str(recipe_id),'status':'APPROVED'}

    @app.post('/v90p/material-requirements/calculate')
    def calc(body: dict, request: Request):
        user=authenticate(request)
        if 'production.edit' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        plan_id=body.get('plan_id'); plan_line_id=body.get('plan_line_id'); qty=float(body.get('planned_qty',0))
        if not plan_id or not plan_line_id or qty<=0: raise HTTPException(422,'plan_id, plan_line_id and planned_qty are required')
        with engine.connect() as conn:
            plan=conn.execute(text('SELECT organization_id,entity_id,location_id FROM production_plan WHERE plan_id=:p'),{'p':plan_id}).mappings().first()
            line=conn.execute(text('SELECT item_master_id FROM production_plan_line WHERE plan_line_id=:pl AND plan_id=:p'),{'pl':plan_line_id,'p':plan_id}).mappings().first()
            if not plan or not line: raise HTTPException(404,'production plan/line not found')
            rec=conn.execute(text("""SELECT * FROM recipe WHERE organization_id=:o AND entity_id=:e AND product_master_id=:m AND status='APPROVED'
                     ORDER BY version_no DESC LIMIT 1"""),{'o':plan['organization_id'],'e':plan['entity_id'],'m':line['item_master_id']}).mappings().first()
            if not rec: raise HTTPException(409,'no approved recipe found for planned product')
            lines=conn.execute(text('SELECT * FROM recipe_line WHERE recipe_id=:r ORDER BY line_no'),{'r':rec['recipe_id']}).mappings().all()
            pack=conn.execute(text('SELECT * FROM recipe_packaging_line WHERE recipe_id=:r ORDER BY line_no'),{'r':rec['recipe_id']}).mappings().all()
        try: assert_entity_location_allowed(engine,user.user_id,str(plan['entity_id']),str(plan['location_id']))
        except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
        factor=qty/float(rec['yield_qty'])
        out=[]
        with engine.begin() as conn:
            conn.execute(text('DELETE FROM material_requirement_calc WHERE plan_id=:p AND plan_line_id=:pl'),{'p':plan_id,'pl':plan_line_id})
            for l in lines:
                gross=float(l['qty'])*factor; scrap=gross*float(l['scrap_pct'])/100; req=gross+scrap
                cid=uuid4(); conn.execute(text("""INSERT INTO material_requirement_calc(calc_id,plan_id,plan_line_id,recipe_id,material_master_id,requirement_type,gross_qty,scrap_qty,required_qty,uom)
                    VALUES(:id,:p,:pl,:r,:m,'RAW_MATERIAL',:g,:s,:q,:u)"""),{'id':str(cid),'p':plan_id,'pl':plan_line_id,'r':rec['recipe_id'],'m':l['material_master_id'],'g':gross,'s':scrap,'q':req,'u':l['uom']})
                out.append({'calc_id':str(cid),'material_master_id':l['material_master_id'],'requirement_type':'RAW_MATERIAL','required_qty':req,'uom':l['uom']})
            for l in pack:
                req=float(l['qty'])*factor; cid=uuid4(); conn.execute(text("""INSERT INTO material_requirement_calc(calc_id,plan_id,plan_line_id,recipe_id,material_master_id,requirement_type,gross_qty,scrap_qty,required_qty,uom)
                    VALUES(:id,:p,:pl,:r,:m,'PACKAGING',:g,0,:q,:u)"""),{'id':str(cid),'p':plan_id,'pl':plan_line_id,'r':rec['recipe_id'],'m':l['packaging_master_id'],'g':req,'q':req,'u':l['uom']})
                out.append({'calc_id':str(cid),'material_master_id':l['packaging_master_id'],'requirement_type':'PACKAGING','required_qty':req,'uom':l['uom']})
        return {'plan_id':plan_id,'plan_line_id':plan_line_id,'recipe_id':rec['recipe_id'],'recipe_version':rec['version_no'],'planned_qty':qty,'requirements':out}
