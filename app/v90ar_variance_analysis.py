from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

MONEY = Decimal('0.01')

def _money(v) -> float:
    return float(Decimal(str(v or 0)).quantize(MONEY, rounding=ROUND_HALF_UP))

def _pct(actual: float, expected: float) -> float:
    return (actual - expected) * 100.0 / expected if expected else (100.0 if actual else 0.0)

def _require(engine, request: Request, entity_id: str, location_id: str | None, write: bool = False):
    user = authenticate(request)
    perm = 'costing.edit' if write else 'costing.view'
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    if location_id is not None:
        try:
            assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    return user

def ensure_v90ar_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS production_variance_report (
            variance_report_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, batch_id TEXT NOT NULL, production_order_id TEXT NOT NULL,
            product_master_id TEXT NOT NULL, planned_qty NUMERIC NOT NULL, actual_good_qty NUMERIC NOT NULL,
            expected_good_qty NUMERIC NOT NULL, actual_wastage_qty NUMERIC NOT NULL, expected_wastage_qty NUMERIC NOT NULL,
            yield_variance_qty NUMERIC NOT NULL, yield_variance_pct NUMERIC NOT NULL,
            wastage_variance_qty NUMERIC NOT NULL, wastage_variance_pct NUMERIC NOT NULL,
            material_variance_cost NUMERIC NOT NULL, packaging_variance_cost NUMERIC NOT NULL,
            total_variance_cost NUMERIC NOT NULL, status TEXT NOT NULL DEFAULT 'CALCULATED',
            calculated_by TEXT NOT NULL, calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(batch_id)
        )""",
        """CREATE TABLE IF NOT EXISTS production_variance_component (
            variance_component_id TEXT PRIMARY KEY, variance_report_id TEXT NOT NULL,
            component_type TEXT NOT NULL, item_master_id TEXT NOT NULL, uom TEXT NOT NULL,
            standard_qty NUMERIC NOT NULL, actual_qty NUMERIC NOT NULL, variance_qty NUMERIC NOT NULL,
            unit_rate NUMERIC NOT NULL, variance_cost NUMERIC NOT NULL, variance_pct NUMERIC NOT NULL,
            notes TEXT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(variance_report_id) REFERENCES production_variance_report(variance_report_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_prod_variance_scope ON production_variance_report(entity_id, location_id, calculated_at)",
        "CREATE INDEX IF NOT EXISTS ix_prod_variance_comp_report ON production_variance_component(variance_report_id, component_type)",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))

class VarianceCalculateIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID


def register_v90ar_routes(app: FastAPI, engine) -> None:
    ensure_v90ar_schema(engine)

    @app.post('/v90ar/batches/{batch_id}/variance')
    def calculate_variance(batch_id: UUID, body: VarianceCalculateIn, request: Request):
        user = _require(engine, request, str(body.entity_id), str(body.location_id), write=True)
        with engine.connect() as conn:
            batch = conn.execute(text('SELECT * FROM production_batch WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            if not batch:
                raise HTTPException(404, 'production batch not found')
            if str(batch['organization_id']) != str(body.organization_id) or str(batch['entity_id']) != str(body.entity_id) or str(batch['location_id']) != str(body.location_id):
                raise HTTPException(422, 'batch scope mismatch')
            output = conn.execute(text('SELECT * FROM production_batch_output WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            if not output:
                raise HTTPException(409, 'batch output is required before variance analysis')
            order = conn.execute(text('SELECT * FROM production_order WHERE production_order_id=:o'), {'o': batch['production_order_id']}).mappings().first()
            if not order:
                raise HTTPException(409, 'production order not found')
            reqs = conn.execute(text('''SELECT material_master_id, requirement_type, required_qty, uom, recipe_id
                                        FROM material_requirement_calc WHERE plan_line_id=:pl
                                        ORDER BY requirement_type, material_master_id'''), {'pl': order['plan_line_id']}).mappings().all()
            recipe = None
            if reqs:
                recipe = conn.execute(text('SELECT expected_loss_pct, yield_qty, yield_uom FROM recipe WHERE recipe_id=:r'), {'r': reqs[0]['recipe_id']}).mappings().first()
            if not recipe:
                recipe = conn.execute(text('SELECT expected_loss_pct, yield_qty, yield_uom FROM recipe WHERE organization_id=:o AND entity_id=:e AND product_master_id=:p AND status=\'APPROVED\' ORDER BY version_no DESC LIMIT 1'), {'o': batch['organization_id'], 'e': batch['entity_id'], 'p': batch['product_master_id']}).mappings().first()
            if not recipe:
                raise HTTPException(409, 'approved recipe is required for variance analysis')
            issues = conn.execute(text('''SELECT material_master_id, uom, SUM(issued_qty) AS qty
                                          FROM production_material_issue WHERE production_order_id=:o AND status='POSTED'
                                          GROUP BY material_master_id, uom'''), {'o': batch['production_order_id']}).mappings().all()
            pack = conn.execute(text('''SELECT pmc.material_master_id, pmc.uom, SUM(pmc.quantity) AS qty
                                        FROM packing_material_consumption pmc
                                        JOIN packing_run pr ON pr.packing_run_id=pmc.packing_run_id
                                        JOIN finished_goods_lot fg ON fg.fg_lot_id=pr.source_fg_lot_id
                                        WHERE fg.batch_id=:b AND pr.status='COMPLETED'
                                        GROUP BY pmc.material_master_id, pmc.uom'''), {'b': str(batch_id)}).mappings().all()
            expected_map = {(str(r['material_master_id']), r['uom'], r['requirement_type']): float(r['required_qty']) for r in reqs}
            actual_issue = {(str(r['material_master_id']), r['uom']): float(r['qty']) for r in issues}
            actual_pack = {(str(r['material_master_id']), r['uom']): float(r['qty']) for r in pack}
            component_rows = []
            material_variance_cost = 0.0
            packaging_variance_cost = 0.0
            keys = set((k[0], k[1], k[2]) for k in expected_map) | set((k[0], k[1], 'RAW_MATERIAL') for k in actual_issue) | set((k[0], k[1], 'PACKAGING') for k in actual_pack)
            for item, uom, ctype in sorted(keys):
                standard = expected_map.get((item, uom, ctype), 0.0)
                actual = actual_pack.get((item, uom), 0.0) if ctype == 'PACKAGING' else actual_issue.get((item, uom), 0.0)
                variance = actual - standard
                rate = conn.execute(text('''SELECT unit_cost FROM product_cost_rate WHERE organization_id=:o AND entity_id=:e AND item_master_id=:i AND uom=:u AND active=1 ORDER BY effective_from DESC, created_at DESC LIMIT 1'''), {'o': batch['organization_id'], 'e': batch['entity_id'], 'i': item, 'u': uom}).scalar()
                rate = float(rate or 0)
                vc = variance * rate
                vp = (variance * 100.0 / standard) if standard else (100.0 if actual else 0.0)
                component_rows.append((ctype, item, uom, standard, actual, variance, rate, vc, vp))
                if ctype == 'PACKAGING': packaging_variance_cost += vc
                else: material_variance_cost += vc
            planned = float(batch['planned_qty'])
            expected_loss_pct = float(recipe['expected_loss_pct'] or 0)
            expected_good = planned * (1 - expected_loss_pct / 100.0)
            expected_waste = planned - expected_good
            actual_good = float(output['good_qty'])
            actual_waste = float(output['wastage_qty'])
            yield_var = actual_good - expected_good
            waste_var = actual_waste - expected_waste
            yield_var_pct = _pct(actual_good, expected_good)
            waste_var_pct = _pct(actual_waste, expected_waste)
            total_var = material_variance_cost + packaging_variance_cost
            existing = conn.execute(text('SELECT variance_report_id FROM production_variance_report WHERE batch_id=:b'), {'b': str(batch_id)}).scalar()
        if existing:
            raise HTTPException(409, 'variance report already calculated')
        report_id = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text('''INSERT INTO production_variance_report
                (variance_report_id,organization_id,entity_id,location_id,batch_id,production_order_id,product_master_id,planned_qty,actual_good_qty,expected_good_qty,actual_wastage_qty,expected_wastage_qty,yield_variance_qty,yield_variance_pct,wastage_variance_qty,wastage_variance_pct,material_variance_cost,packaging_variance_cost,total_variance_cost,status,calculated_by)
                VALUES(:id,:o,:e,:l,:b,:po,:p,:pl,:ag,:eg,:aw,:ew,:yv,:yvp,:wv,:wvp,:mv,:pv,:tv,'CALCULATED',:u)'''),
                {'id':report_id,'o':batch['organization_id'],'e':batch['entity_id'],'l':batch['location_id'],'b':str(batch_id),'po':batch['production_order_id'],'p':batch['product_master_id'],'pl':planned,'ag':actual_good,'eg':expected_good,'aw':actual_waste,'ew':expected_waste,'yv':yield_var,'yvp':yield_var_pct,'wv':waste_var,'wvp':waste_var_pct,'mv':material_variance_cost,'pv':packaging_variance_cost,'tv':total_var,'u':str(user.user_id)})
            for row in component_rows:
                conn.execute(text('''INSERT INTO production_variance_component
                    (variance_component_id,variance_report_id,component_type,item_master_id,uom,standard_qty,actual_qty,variance_qty,unit_rate,variance_cost,variance_pct)
                    VALUES(:id,:r,:t,:i,:u,:s,:a,:v,:rate,:c,:p)'''), {'id':str(uuid4()),'r':report_id,'t':row[0],'i':row[1],'u':row[2],'s':row[3],'a':row[4],'v':row[5],'rate':row[6],'c':row[7],'p':row[8]})
        return {'status':'CALCULATED','variance_report_id':report_id,'batch_id':str(batch_id),'yield_variance_qty':_money(yield_var),'yield_variance_pct':_money(yield_var_pct),'wastage_variance_qty':_money(waste_var),'wastage_variance_pct':_money(waste_var_pct),'material_variance_cost':_money(material_variance_cost),'packaging_variance_cost':_money(packaging_variance_cost),'total_variance_cost':_money(total_var),'components':len(component_rows)}

    @app.get('/v90ar/batches/{batch_id}/variance')
    def get_variance(batch_id: UUID, request: Request):
        with engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM production_variance_report WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            if not row:
                raise HTTPException(404, 'variance report not found')
            _require(engine, request, str(row['entity_id']), str(row['location_id']))
            comps = conn.execute(text('SELECT * FROM production_variance_component WHERE variance_report_id=:r ORDER BY component_type,item_master_id'), {'r': row['variance_report_id']}).mappings().all()
        result = dict(row)
        for k in ('planned_qty','actual_good_qty','expected_good_qty','actual_wastage_qty','expected_wastage_qty','yield_variance_qty','yield_variance_pct','wastage_variance_qty','wastage_variance_pct','material_variance_cost','packaging_variance_cost','total_variance_cost'):
            result[k] = _money(result[k])
        for c in comps:
            pass
        return {'report': result, 'components': [dict(x) for x in comps]}

    @app.get('/v90ar/variance-summary')
    def variance_summary(organization_id: UUID, entity_id: UUID, request: Request, location_id: UUID | None = None):
        _require(engine, request, str(entity_id), str(location_id) if location_id else None)
        q = '''SELECT COUNT(*) AS batches, COALESCE(SUM(material_variance_cost),0) AS material_variance_cost,
                       COALESCE(SUM(packaging_variance_cost),0) AS packaging_variance_cost,
                       COALESCE(SUM(total_variance_cost),0) AS total_variance_cost,
                       COALESCE(SUM(yield_variance_qty),0) AS yield_variance_qty,
                       COALESCE(SUM(wastage_variance_qty),0) AS wastage_variance_qty
                FROM production_variance_report WHERE organization_id=:o AND entity_id=:e'''
        params={'o':str(organization_id),'e':str(entity_id)}
        if location_id:
            q += ' AND location_id=:l'; params['l']=str(location_id)
        with engine.connect() as conn:
            r=conn.execute(text(q),params).mappings().first()
        return {k:_money(r[k]) if k != 'batches' else int(r[k]) for k in r}
