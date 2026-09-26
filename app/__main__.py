# FILE PATH: app/__main__.py
# ─── ERP Application Entry v1.1 (Session CS2 — startup safety gate, demo login dev-only, V90.gx routes) ─
#
# [Session CS2] FIX/FEATURE — STAGING/PRODUCTION COULD START WITH PUBLIC SECRETS, SQLITE AND DEMO LOGINS.
# Confirmed this session by reading login() (demo admin/manager fallback always active) and the
# startup sequence (no configuration validation before create_db_engine()).
#
# THE FIX:
#   - runtime_security.validate_runtime_configuration() runs before create_db_engine(); in
#     staging/production it raises when the token secret or DATABASE_URL(_FILE) is missing/unsafe.
#   - login(): unchanged code path, but auth.default_demo_users() now returns {} outside dev/test.
#   - uvicorn host/port read from APP_HOST / APP_PORT (defaults unchanged: 0.0.0.0:8000).
#   - registers the V90.gx modules (company profile & GST invoicing, intercompany X→Y settlement,
#     plant operations logs, notifications, lookups) — see the bottom of this file.
# NOT touched: any existing route, middleware, schema bootstrap order, or V90.i–V90.gw registrations.
#
# ─── v1.0 HEADER (preserved) ─────────────────────────────────────────────
# Cumulative V2–V90.gw application entry; no in-file changelog existed before Session CS2.
from fastapi import FastAPI, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from .auth import authenticate, default_demo_users, make_access_token, verify_password, hash_password, UserRecord, set_session_validator
from sqlalchemy.engine import Engine

from .db import create_db_engine, database_ping
from .release import load_release_info
from .identity import ensure_identity_schema, user_record, find_user, roles_for_user, permissions_for_user, create_user
from .org_structure import ensure_org_schema, create_entity, create_location, create_department, create_responsibility, assign_user
from .access_scope import ensure_access_scope_schema, create_warehouse, grant_entity_access, grant_location_access, grant_warehouse_access, accessible_scope, is_entity_allowed, is_location_allowed, is_warehouse_allowed
from .master_scope import ensure_master_scope_schema
from .v90i_master_api import register_v90i_routes
from .v90j_product_master import register_v90j_routes
from .v90k_operational_master import register_v90k_routes
from .v90l_procurement import register_v90l_routes
from .v90m_receiving_qc import register_v90m_routes
from .v90n_inventory_ops import register_v90n_routes
from .v90o_production_planning import register_v90o_routes
from .v90p_recipe_bom import register_v90p_routes
from .v90q_material_reservation import register_v90q_routes
from .v90r_production_execution import register_v90r_routes
from .v90s_process_logging import register_v90s_routes
from .v90t_process_controls_qc import register_v90t_routes
from .v90u_batch_output import register_v90u_routes
from .v90v_finished_goods import register_v90v_routes
from .v90w_packing import register_v90w_routes
from .v90x_packing_qc import register_v90x_routes
from .v90y_fg_fefo_dispatch import register_v90y_routes
from .v90z_sales_orders import register_v90z_routes
from .v90aa_price_margin import register_v90aa_routes
from .v90ab_incentives import register_v90ab_routes
from .v90ac_credit_payment import register_v90ac_routes
from .v90ad_sales_credit_integration import register_v90ad_routes
from .v90ae_sales_order_allocation import register_v90ae_routes
from .v90af_dispatch_pick import register_v90af_routes
from .v90ah_returns import register_v90ah_routes
from .v90ai_return_disposition import register_v90ai_routes
from .v90aj_return_accounting import register_v90aj_routes
from .v90ak_collections import register_v90ak_routes
from .v90al_receivables import register_v90al_routes
from .v90am_bank_reconciliation import register_v90am_routes
from .v90an_production_sales_integration import register_v90an_routes
from .v90ao_integration_uat import register_v90ao_routes
from .v90ap_supplier_payables import register_v90ap_routes
from .v90aq_cost_accounting import register_v90aq_routes
from .v90ar_variance_analysis import register_v90ar_routes
from .v90as_factory_mis import register_v90as_routes
from .v90at_sales_mis import register_v90at_routes
from .v90au_sales_portfolio import register_v90au_routes
from .v90av_scheme_settlement import register_v90av_routes
from .v90aw_returns_analytics import register_v90aw_routes
from .v90ax_dispatch_reconciliation import register_v90ax_routes
from .v90ay_inventory_valuation import register_v90ay_routes
from .v90az_trace_recall import register_v90az_routes
from .v90ba_barcode_scan import register_v90ba_routes
from .v90bb_offline_sync import register_v90bb_routes
from .v90bc_evidence import register_v90bc_routes
from .v90bd_notifications_approvals import register_v90bd_routes
from .v90be_audit_corrections import register_v90be_routes
from .v90bf_security_hardening import register_v90bf_routes, ensure_security_schema, create_session, login_is_throttled, record_login_attempt, validate_token_session
from .v90bg_backup_restore import register_v90bg_routes
from .v90bj_ui import register_v90bj_routes, ensure_ui_schema
from .v90bk_dashboards import register_v90bk_routes, ensure_dashboard_schema
from .v90bl_management_ui import register_v90bl_routes, ensure_management_ui_schema
from .v90bm_transaction_ui import register_v90bm_routes, ensure_transaction_ui_schema
from .v90bn_inventory_ui import register_v90bn_routes, ensure_inventory_ui_schema
from .v90bo_production_ui import register_v90bo_routes
from .v90bp_packing_sales_ui import register_v90bp_routes
from .v90bq_salesperson_ui import register_v90bq_routes
from .v90bs_dispatch_ui import register_v90bs_routes
from .v90bt_returns_ui import register_v90bt_routes
from .v90by_tax import register_v90by_routes
from .v90bz_accounting import register_v90bz_routes
from .v90ca_accounting_posting import register_v90ca_routes
from .v90cb_financial_controls import register_v90cb_routes
from .v90cc_assets_loans import register_v90cc_routes
from .v90cd_financial_integration import register_v90cd_routes
from .v90ce_statutory_reporting import register_v90ce_routes
from .v90cf_gst_reconciliation import register_v90cf_routes
from .v90cg_gst_filing import register_v90cg_routes
from .v90ch_gst_compliance import register_v90ch_routes
from .v90ci_gst_return_operations import register_v90ci_routes
from .v90cj_gst_settlement import register_v90cj_routes
from .v90ck_gst_final_close import register_v90ck_routes
from .v90cl_accounting_completion import register_v90cl_routes
from .v90cm_accounting_reconciliation import register_v90cm_routes
from .v90cn_year_end_close import register_v90cn_routes
from .v90cs_procurement_planning import register_v90cs_routes
from .v90co_tally_sync import register_v90co_routes
from .v90cp_tally_hardening import register_v90cp_routes
from .v90cq_mrp import register_v90cq_routes
from .v90cr_replenishment import register_v90cr_routes
from .v90ct_po_automation import register_v90ct_routes
from .v90cu_procurement_commercial import register_v90cu_routes
from .v90cv_procurement_analytics import register_v90cv_routes
from .v90cw_manufacturing_costing import register_v90cw_routes
from .v90cx_loss_yield import register_v90cx_routes
from .v90cy_variance import register_v90cy_routes
from .v90cz_scheduling import register_v90cz_routes
from .v90da_scheduling_optimization import register_v90da_routes
from .v90db_machine_oee import register_v90db_routes
from .v90dc_maintenance import register_v90dc_routes
from .v90dd_machine_iot import register_v90dd_routes
from .v90de_food_quality import register_v90de_routes
from .v90df_food_traceability import register_v90df_routes
from .v90dg_hr_workforce import register_v90dg_routes
from .v90dh_workforce_advanced import register_v90dh_routes
from .v90di_payroll import register_v90di_routes
from .v90dl_payroll_settlement import register_v90dl_routes
from .v90dm_payroll_accounting import register_v90dm_routes
from .v90dn_payroll_mis import register_v90dn_routes
from .v90do_labour_productivity import register_v90do_routes
from .v90dp_workforce_performance import register_v90dp_routes
from .v90dq_workforce_planning import register_v90dq_routes
from .v90dr_capacity_skills import register_v90dr_routes
from .v90ds_training_optimization import register_v90ds_routes
from .v90dt_workforce_forecasting import register_v90dt_routes
from .v90du_workforce_benchmarking import register_v90du_routes
from .v90dv_workforce_budgeting import register_v90dv_routes
from .v90dw_workforce_training_compliance import register_v90dw_routes
from .v90dx_workforce_cost_reconciliation import register_v90dx_routes
from .v90dy_workforce_productivity_kpi import register_v90dy_routes
from .v90dz_workforce_overtime_standards import register_v90dz_routes
from .v90ea_workforce_oee_integration import register_v90ea_routes
from .v90eb_workforce_bottleneck import register_v90eb_routes
from .v90ec_factory_bottleneck_optimization import register_v90ec_routes
from .v90ed_factory_bottleneck_scenarios import register_v90ed_routes
from .v90ee_factory_scenario_handoff import register_v90ee_routes
from .v90ef_scheduling_execution import register_v90ef_routes
from .v90eg_execution_reconciliation import register_v90eg_routes
from .v90eh_factory_benefit_realization import register_v90eh_routes
from .v90ei_maintenance_labour_costing import register_v90ei_routes
from .v90ej_maintenance_production_cost import register_v90ej_routes
from .v90ek_maintenance_reliability_cost import register_v90ek_routes
from .v90el_reliability_improvement import register_v90el_routes
from .v90em_maintenance_roi import register_v90em_routes
from .v90en_maintenance_strategy import register_v90en_routes
from .v90ep_predictive_maintenance import register_v90ep_routes
from .v90eq_maintenance_queue import register_v90eq_routes
from .v90er_maintenance_execution_feedback import register_v90er_routes
from .v90es_maintenance_outcome_optimization import register_v90es_routes
from .v90et_reliability_action_execution import register_v90et_routes
from .v90eu_reliability_governance import register_v90eu_routes
from .v90ev_reliability_change_implementation import register_v90ev_routes
from .v90ew_reliability_change_effectiveness import register_v90ew_routes
from .v90ex_reliability_governance_closure import register_v90ex_routes
from .v90ey_reliability_continuous_improvement import register_v90ey_routes
from .v90ez_reliability_knowledge_standardization import register_v90ez_routes
from .v90fa_reliability_standard_deployment import register_v90fa_routes
from .v90fb_enterprise_reliability_benchmarking import register_v90fb_routes
from .v90fc_reliability_capa import register_v90fc_routes
from .v90fd_reliability_audit_compliance import register_v90fd_routes
from .v90fe_reliability_executive_command import register_v90fe_routes
from .v90ff_reliability_executive_action import register_v90ff_routes
from .v90fg_reliability_executive_effectiveness import register_v90fg_routes
from .v90fh_reliability_executive_governance import register_v90fh_routes
from .v90fi_reliability_executive_governance_effectiveness import register_v90fi_routes
from .v90fj_reliability_governance_learning import register_v90fj_routes
from .v90fk_reliability_governance_learning_execution import register_v90fk_routes
from .v90fl_reliability_governance_learning_closure import register_v90fl_routes
from .v90fm_intercompany_execution import register_v90fm_routes
from .v90fn_security_rbac_scope_hardening import register_v90fn_routes
from .v90fo_audit_approval_evidence import register_v90fo_routes
from .v90fp_transaction_governance_integration import register_v90fp_routes
from .v90fq_governance_certification import register_v90fq_routes
from .v90fr_governance_coverage_remediation import register_v90fr_routes
from .v90fs_governance_remediation_uat import register_v90fs_routes
from .v90ft_uat_production_readiness import register_v90ft_routes
from .v90fv_deployment_cutover import register_v90fv_routes
from .v90fw_backup_dr import register_v90fw_routes
from .v90fx_observability import register_v90fx_routes
from .v90fy_performance_scalability import register_v90fy_routes
from .v90fz_performance_optimization import register_v90fz_routes
from .v90ga_performance_production_gate import register_v90ga_routes
from .v90gb_production_readiness_performance import register_v90gb_routes
from .v90gc_production_release_certification import register_v90gc_routes
from .v90gd_go_live_execution import register_v90gd_routes
from .v90ge_post_go_live_stabilization import register_v90ge_routes
from .v90gf_final_go_live_closure import register_v90gf_routes
from .v90gg_operational_handover_hypercare import register_v90gg_routes
from .v90gh_operations_sla import register_v90gh_routes
from .v90gi_incident_problem_escalation import register_v90gi_routes
from .v90gj_advanced_mis_dashboard import register_v90gj_routes
from .v90gk_costing_profitability import register_v90gk_routes
from .v90gl_working_capital import register_v90gl_routes
from .v90gn_advanced_sales_distribution import register_v90gn_routes
from .v90go_customer_distribution_execution import register_v90go_routes
from .v90gp_manufacturing_workforce_integration import register_v90gp_routes
from .v90gq_food_quality_traceability_command import register_v90gq_routes
from .v90gr_mobile_offline_execution import register_v90gr_routes
from .v90gs_mobile_transaction_integration import register_v90gs_routes
from .v90gt_mobile_inventory_dispatch_delivery import register_v90gt_routes
from .v90gu_mobile_remaining_transaction_execution import register_v90gu_routes
from .v90gv_mobile_exception_reconciliation import register_v90gv_routes
from .v90gw_completion_audit import register_v90gw_routes
from .v90ag_dispatch_execution import register_v90ag_routes

release = load_release_info()
# [Session CS2] FIX — see file header. Refuse to start staging/production with unsafe secrets/DB.
from .runtime_security import validate_runtime_configuration
runtime_config = validate_runtime_configuration()
engine: Engine = create_db_engine()
ensure_identity_schema(engine)
ensure_org_schema(engine)
ensure_access_scope_schema(engine)
ensure_master_scope_schema(engine)
app = FastAPI(title="Namkeen ERP", version=release.version)
security = HTTPBearer(auto_error=False)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    import uuid
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.path.startswith("/auth") or request.url.path.startswith("/v90bf"):
        response.headers["Cache-Control"] = "no-store"
    return response


register_v90i_routes(app, engine)
register_v90j_routes(app, engine)
register_v90k_routes(app, engine)
register_v90l_routes(app, engine)
register_v90m_routes(app, engine)
register_v90n_routes(app, engine)
register_v90o_routes(app, engine)
register_v90p_routes(app, engine)
register_v90q_routes(app, engine)
register_v90r_routes(app, engine)
register_v90s_routes(app, engine)
register_v90t_routes(app, engine)
register_v90u_routes(app, engine)
register_v90v_routes(app, engine)
register_v90w_routes(app, engine)
register_v90x_routes(app, engine)
register_v90y_routes(app, engine)
register_v90z_routes(app, engine)
register_v90aa_routes(app, engine)
register_v90ab_routes(app, engine)
register_v90ac_routes(app, engine)
register_v90ad_routes(app, engine)
register_v90ae_routes(app, engine)
register_v90af_routes(app, engine)
register_v90ah_routes(app, engine)
register_v90ai_routes(app, engine)
register_v90aj_routes(app, engine)
register_v90ag_routes(app, engine)
register_v90ak_routes(app, engine)
register_v90al_routes(app, engine)
register_v90am_routes(app, engine)
register_v90an_routes(app, engine)
register_v90ao_routes(app, engine)
register_v90ap_routes(app, engine)
register_v90aq_routes(app, engine)
register_v90ar_routes(app, engine)
register_v90as_routes(app, engine)
register_v90at_routes(app, engine)
register_v90au_routes(app, engine)
register_v90av_routes(app, engine)
register_v90aw_routes(app, engine)
register_v90ax_routes(app, engine)
register_v90ay_routes(app, engine)
register_v90az_routes(app, engine)
register_v90ba_routes(app, engine)
register_v90bb_routes(app, engine)
register_v90bc_routes(app, engine)
register_v90bd_routes(app, engine)
register_v90be_routes(app, engine)
register_v90bf_routes(app, engine)
register_v90bg_routes(app, engine)
register_v90bj_routes(app, engine)
register_v90bk_routes(app, engine)
register_v90bl_routes(app, engine)
register_v90bm_routes(app, engine)
register_v90bn_routes(app, engine)
register_v90bo_routes(app, engine)
register_v90bp_routes(app, engine)
register_v90bq_routes(app, engine)
register_v90bs_routes(app, engine)
register_v90bt_routes(app, engine)
register_v90by_routes(app, engine)
register_v90bz_routes(app, engine)
register_v90ca_routes(app, engine)
register_v90cb_routes(app, engine)
register_v90cc_routes(app, engine)
register_v90cd_routes(app, engine)
register_v90ce_routes(app, engine)
register_v90cf_routes(app, engine)
register_v90cg_routes(app, engine)
register_v90ch_routes(app, engine)
register_v90ci_routes(app, engine)
register_v90cj_routes(app, engine)
register_v90ck_routes(app, engine)
register_v90cl_routes(app, engine)
register_v90cm_routes(app, engine)
register_v90cn_routes(app, engine)
register_v90cs_routes(app, engine)
register_v90co_routes(app, engine)
register_v90cp_routes(app, engine)
register_v90cq_routes(app, engine)
register_v90cr_routes(app, engine)
register_v90ct_routes(app, engine)
register_v90cu_routes(app, engine)
register_v90cv_routes(app, engine)
register_v90cw_routes(app, engine)
register_v90cx_routes(app, engine)
register_v90cy_routes(app, engine)
register_v90cz_routes(app, engine)
register_v90da_routes(app, engine)
register_v90db_routes(app, engine)
register_v90dc_routes(app, engine)
register_v90dd_routes(app, engine)
register_v90de_routes(app, engine)
register_v90df_routes(app, engine)
register_v90dg_routes(app, engine)
register_v90dh_routes(app, engine)
register_v90di_routes(app, engine)
register_v90dl_routes(app, engine)
register_v90dm_routes(app, engine)
register_v90dn_routes(app, engine)
register_v90do_routes(app, engine)
register_v90dp_routes(app, engine)
register_v90dq_routes(app, engine)
register_v90dr_routes(app, engine)
register_v90ds_routes(app, engine)
register_v90dt_routes(app, engine)
register_v90du_routes(app, engine)
register_v90dv_routes(app, engine)
register_v90dw_routes(app, engine)
register_v90dx_routes(app, engine)
register_v90dy_routes(app, engine)
register_v90dz_routes(app, engine)
register_v90ea_routes(app, engine)
register_v90eb_routes(app, engine)
register_v90ec_routes(app, engine)
register_v90ed_routes(app, engine)
register_v90ee_routes(app, engine)
register_v90ef_routes(app, engine)
register_v90eg_routes(app, engine)
register_v90eh_routes(app, engine)
register_v90ei_routes(app, engine)
register_v90ej_routes(app, engine)
register_v90ek_routes(app, engine)
register_v90el_routes(app, engine)
register_v90em_routes(app, engine)
register_v90en_routes(app, engine)
register_v90ep_routes(app, engine)
register_v90eq_routes(app, engine)
register_v90er_routes(app, engine)
register_v90es_routes(app, engine)
register_v90et_routes(app, engine)
register_v90eu_routes(app, engine)
register_v90ev_routes(app, engine)
register_v90ew_routes(app, engine)
register_v90ex_routes(app, engine)
register_v90ey_routes(app, engine)
register_v90ez_routes(app, engine)
register_v90fa_routes(app, engine)
register_v90fb_routes(app, engine)
register_v90fc_routes(app, engine)
register_v90fd_routes(app, engine)
register_v90fe_routes(app, engine)
register_v90ff_routes(app, engine)
register_v90fg_routes(app, engine)
register_v90fh_routes(app, engine)
register_v90fi_routes(app, engine)
register_v90fj_routes(app, engine)
register_v90fk_routes(app, engine)
register_v90fl_routes(app, engine)
register_v90fm_routes(app, engine)
set_session_validator(lambda token: validate_token_session(engine, token))


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post('/auth/login')
def login(payload: LoginRequest, request: Request):
    ip = request.client.host if request.client else 'unknown'
    if login_is_throttled(engine, payload.username, ip):
        raise HTTPException(status_code=429, detail='too many failed login attempts; try again later')
    user = user_record(engine, payload.username, payload.password)
    if not user:
        # Backward-compatible demo credentials: development/test only ([Session CS2] — default_demo_users() is {} in staging/production).
        demo = default_demo_users().get(payload.username)
        if demo:
            demo_user, demo_password = demo
            if demo_user.active and payload.password == demo_password:
                user = demo_user
    if not user:
        record_login_attempt(engine, payload.username, ip, False)
        raise HTTPException(status_code=401, detail='invalid credentials')
    record_login_attempt(engine, payload.username, ip, True)
    token = make_access_token(user)
    session_id = create_session(engine, user, token, request)
    return {'access_token': token, 'token_type': 'bearer', 'expires_in': 8 * 60 * 60, 'session_id': session_id, 'user': user.__dict__, 'permissions': sorted(permissions_for_user(engine, user.user_id)) if find_user(engine, user.username) else []}


@app.get('/auth/me')
def me(request: Request):
    return authenticate(request).__dict__


@app.get('/auth/permissions')
def auth_permissions(request: Request):
    user = authenticate(request)
    return {'user_id': user.user_id, 'roles': roles_for_user(engine, user.user_id), 'permissions': sorted(permissions_for_user(engine, user.user_id))}

@app.post('/admin/users')
def admin_create_user(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    create_user(engine, payload['user_id'], payload['username'], payload['password'], payload.get('display_name', payload['username']), payload.get('role_id','operator'))
    return {'status':'created','user_id':payload['user_id'],'username':payload['username']}



@app.post('/admin/entities')
def admin_create_entity(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    create_entity(engine, payload['entity_id'], payload['entity_code'], payload['entity_name'], payload.get('entity_type','legal_entity'))
    return {'status':'created','entity_id':payload['entity_id']}

@app.post('/admin/locations')
def admin_create_location(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    create_location(engine, payload['location_id'], payload['entity_id'], payload['location_code'], payload['location_name'], payload.get('location_type','site'))
    return {'status':'created','location_id':payload['location_id']}

@app.post('/admin/departments')
def admin_create_department(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    create_department(engine, payload['department_id'], payload['entity_id'], payload['department_code'], payload['department_name'])
    return {'status':'created','department_id':payload['department_id']}

@app.post('/admin/responsibilities')
def admin_create_responsibility(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    create_responsibility(engine, payload['responsibility_id'], payload['entity_id'], payload['responsibility_code'], payload['responsibility_name'], payload['module_name'], payload.get('department_id'), payload.get('primary_user_id'), payload.get('backup_user_id'), payload.get('approval_user_id'))
    return {'status':'created','responsibility_id':payload['responsibility_id']}


@app.post('/admin/warehouses')
def admin_create_warehouse(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    create_warehouse(engine, payload['warehouse_id'], payload['entity_id'], payload['location_id'], payload['warehouse_code'], payload['warehouse_name'], payload.get('warehouse_type','general'))
    return {'status':'created','warehouse_id':payload['warehouse_id']}

@app.post('/admin/access/entity')
def admin_grant_entity_access(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    grant_entity_access(engine, payload['user_id'], payload['entity_id'])
    return {'status':'granted','scope':'entity'}

@app.post('/admin/access/location')
def admin_grant_location_access(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    grant_location_access(engine, payload['user_id'], payload['location_id'])
    return {'status':'granted','scope':'location'}

@app.post('/admin/access/warehouse')
def admin_grant_warehouse_access(payload: dict, request: Request):
    user = authenticate(request)
    if 'admin.users' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    grant_warehouse_access(engine, payload['user_id'], payload['warehouse_id'])
    return {'status':'granted','scope':'warehouse'}

@app.get('/auth/scope')
def auth_scope(request: Request):
    user = authenticate(request)
    return {'user_id': user.user_id, **accessible_scope(engine, user.user_id)}

@app.get('/access/check/{scope_type}/{scope_id}')
def access_check(scope_type: str, scope_id: str, request: Request):
    user = authenticate(request)
    checks = {'entity': is_entity_allowed, 'location': is_location_allowed, 'warehouse': is_warehouse_allowed}
    fn = checks.get(scope_type)
    if not fn:
        raise HTTPException(status_code=400, detail='unsupported scope type')
    return {'allowed': bool(fn(engine, user.user_id, scope_id)), 'scope': scope_type, 'scope_id': scope_id}


@app.get('/masters/access-check')
def masters_access_check(request: Request, entity_id: str | None = None, location_id: str | None = None):
    from .v90h import require_master_access
    user = require_master_access(engine, request, entity_id, location_id, write=False)
    return {'allowed': True, 'user_id': user.user_id, 'entity_id': entity_id, 'location_id': location_id, 'operation': 'read'}

@app.post('/masters/access-check')
def masters_write_access_check(payload: dict, request: Request):
    from .v90h import require_master_access
    user = require_master_access(engine, request, payload.get('entity_id'), payload.get('location_id'), write=True)
    return {'allowed': True, 'user_id': user.user_id, 'entity_id': payload.get('entity_id'), 'location_id': payload.get('location_id'), 'operation': 'write'}

@app.get('/health')
def health():
    return {'status': 'ok', 'version': release.version}


@app.get('/ready')
def ready():
    ok, detail = database_ping(engine)
    return {
        'status': 'ready' if ok else 'not_ready',
        'version': release.version,
        'database': detail,
    }


@app.get('/build')
def build():
    return {'release': release.version, 'maintenance_stage': release.version, 'security_foundation': 'authentication_session_api', 'transaction_governance': 'erp_wide_policy_driven_audit_and_approval_integration', 'governance_certification': 'critical_action_coverage_certification_exception_and_period_close', 'org_structure': 'entity_location_department_responsibility', 'access_scope': 'entity_location_warehouse', 'master_scoping': 'entity_location', 'master_api': 'crud_approval_scoped', 'product_master': 'product_sku_pack_uom_workflows', 'operational_master': 'customer_supplier_warehouse_bin_workflows', 'procurement': 'requisition_quote_po_grn_preparation', 'receiving_qc_inventory': 'grn_incoming_qc_lot_release_stock_ledger', 'inventory_ops': 'reservation_fefo_transfer', 'production_planning': 'production_plan_lines_requirements_approval', 'recipe_bom': 'recipe_versioned_material_packaging_requirements', 'material_reservation': 'material_reservation_production_order', 'production_execution': 'material_issue_batch_start_complete', 'production_process_logging': 'stage_operator_machine_measurements_deviations', 'process_controls_qc': 'control_limits_evaluation_hold_release', 'batch_output': 'good_rework_wastage_yield_qc_gate', 'finished_goods': 'batch_output_to_fg_lot_inventory', 'packing': 'fg_bulk_to_sku_packing_packaging_consumption', 'fg_fefo_dispatch': 'expiry_fefo_allocation_dispatch_readiness', 'sales_orders': 'customer_order_pricing_stock_approval', 'incentives': 'approved_incentive_rules_accrual_calculation', 'credit_payment': 'customer_credit_outstanding_payment_verification', 'sales_credit_control': 'sales_order_pricing_credit_stock_gate', 'sales_order_allocation': 'approved_order_fg_fefo_allocation_release', 'dispatch_pick': 'pick_list_warehouse_pick_dispatch_readiness', 'dispatch_execution': 'shipment_posting_stock_depletion_invoice_linkage', 'returns': 'return_request_receipt_qc_hold', 'return_disposition': 'saleable_repack_rework_damage_expired_dispose', 'return_accounting': 'credit_note_customer_credit_incentive_reversal', 'bank_reconciliation': 'statement_import_payment_match_reconciliation', 'supplier_payables': 'supplier_invoice_payment_allocation_aging_followup', 'cost_accounting': 'product_cost_rates_batch_cost_rollup_material_packaging_wastage_costs', 'sales_mis': 'sales_kpis_distributor_dealer_territory_sales_reporting', 'scheme_settlement': 'commercial_scheme_discount_settlement_incentive_settlement', 'returns_analytics_rework': 'return_damage_expiry_mis_repack_rework_cost_accounting', 'dispatch_reconciliation': 'dispatch_reconciliation_transporter_pod_partial_dispatch_backorder', 'batch_traceability_recall': 'batch_traceability_forward_recall_withdrawal', 'evidence': 'attachment_document_management_photo_gps_evidence', 'backup_restore': 'verified_postgres_backup_restore_migration_validation', 'observability': 'health_readiness_alerting_incident_escalation_operational_sla_evidence', 'performance_scalability': 'performance_baselines_load_stress_evidence_database_hotspots_capacity_regression_readiness', 'performance_optimization': 'performance_optimization_execution_capacity_remediation_post_change_validation_scalability_certification', 'ui_integration': 'web_ui_android_build_pipeline', 'ui_role_dashboards': 'screen_by_screen_web_mobile_role_specific_dashboards', 'management_ui': 'management_dashboard_approval_inbox_notifications_center', 'production_ui': 'production_planning_material_issue_batch_execution_production_qc', 'packing_sales_ui': 'packing_fg_qc_sales_customer_order_builder', 'returns_ui': 'returns_return_qc_disposition_accounting_ui', 'statutory_reporting': 'gst_hsn_sac_summary_validation_period_close', 'gst_filing': 'gst_filing_snapshot_adjustment_lock_export', 'gst_final_close': 'gst_final_statutory_close_reopen_audit_compliance_dashboard', 'accounting_completion': 'chart_of_accounts_journal_vouchers_general_ledger_opening_balances_financial_period_close', 'accounting_reconciliation': 'sales_receivables_purchase_payables_inventory_bank_gst_intercompany_reconciliation_signoff', 'year_end_close': 'year_end_p_and_l_close_retained_earnings_opening_balance_carryforward_reopen', 'tally_hardening': 'company_ledger_mapping_validation_duplicate_control_acknowledgement_retry_connector_boundary', 'advanced_mrp': 'demand_driven_production_planning_multilevel_bom_material_shortage_reorder_procurement_suggestions_exception_dashboard', 'replenishment': 'min_max_reorder_point_safety_stock_lead_time_supplier_planning_open_po_netting_mrp_shortage_replenishment_suggestions', 'advanced_procurement': 'supplier_sourcing_rules_supplier_performance_rfq_quotation_comparison_landed_cost_replenishment_to_purchase_requisition', 'po_automation': 'pr_to_po_conversion_approval_price_history_landed_cost_supplier_rebate_open_commitment_controls', 'manufacturing_costing': 'batch_actual_cost_standard_vs_actual_material_packaging_labor_overhead_rework_wastage_byproduct_yield_cost_variance', 'manufacturing_loss_yield': 'ingredient_consumption_variance_process_loss_norms_wastage_cost_rework_byproduct_valuation_yield_benchmarking_manufacturing_variance_approval', 'manufacturing_variance': 'batch_material_labour_overhead_yield_wastage_rework_byproduct_variance_shift_operator_machine_performance_corrective_actions', 'manufacturing_scheduling': 'work_center_capacity_shift_calendar_production_scheduling_finite_capacity_bottleneck_conflict_rescheduling', 'manufacturing_scheduling_optimization': 'routing_operations_setup_changeover_product_work_center_compatibility_finite_capacity_priority_due_date_schedule_optimization', 'manufacturing_scenario_execution': 'approved_factory_scenario_handoff_scheduling_proposal_approval_execution_overtime_audit', 'manufacturing_execution_reconciliation': 'scenario_execution_planned_vs_actual_schedule_variance_overtime_reconciliation_close', 'machine_oee': 'machine_status_runtime_downtime_availability_performance_quality_oee_dashboard', 'preventive_maintenance': 'maintenance_plans_work_orders_breakdowns_spares_cost_reliability_due_alerts', 'machine_iot': 'device_registry_telemetry_machine_state_threshold_alert_oee_feed_maintenance_trigger', 'food_quality': 'raw_fg_qc_specs_sampling_inspection_coa_batch_release_hold_nc_capa_allergen_traceability_dashboard', 'hr_workforce': 'employee_master_shift_calendar_attendance_labour_allocation_labour_cost_dashboard', 'hr_workforce_advanced': 'user_employee_mapping_shift_roster_attendance_exceptions_overtime_labour_variance_productivity_payroll_integration_boundary', 'payroll': 'payroll_period_compensation_attendance_overtime_calculation_employer_cost_batch_labour_allocation_journal_boundary', 'payroll_settlement': 'employee_bank_mapping_payment_batch_payslip_statutory_settlement_payment_status_payroll_bank_gl_reconciliation', 'workforce_optimization': 'skill_gap_training_certification_workforce_optimization_capacity_savings', 'maintenance_labour_costing': 'maintenance_order_labour_hours_overtime_rates_burden_cost_period_close_dashboard', 'maintenance_reliability_cost': 'preventive_vs_breakdown_maintenance_cost_oee_downtime_production_cost_reliability_dashboard', 'maintenance_reliability_action_execution': 'approved_reliability_action_execution_owner_due_date_before_after_benefit_realization_effectiveness_dashboard', 'maintenance_reliability_change_implementation': 'controlled_reliability_change_request_status_plan_revision_benefit_rollback', 'maintenance_reliability_change_effectiveness': 'target_vs_actual_effectiveness_failure_detection_repeat_failure_feedback_governance_handoff', 'maintenance_reliability_continuous_improvement': 'cross_period_reliability_learning_trend_recurring_failure_feedback_governance_control', 'maintenance_reliability_knowledge_standardization': 'reliability_knowledge_lessons_best_practices_controlled_standard_recommendations_approval', 'maintenance_reliability_standard_deployment': 'approved_standard_deployment_adoption_acknowledgement_exceptions_version_control', 'maintenance_reliability_benchmarking': 'enterprise_reliability_benchmarking_normalized_kpis_peer_ranking_exceptions', 'maintenance_reliability_capa': 'recurring_failure_to_capa_root_cause_corrective_action_effectiveness_overdue_evidence_closure', 'maintenance_reliability_audit': 'reliability_audit_evidence_completeness_approval_compliance_unauthorized_change_detection_audit_exceptions', 'maintenance_reliability_command': 'executive_reliability_health_cost_oee_effectiveness_adoption_capa_benchmark_audit_exceptions', 'maintenance_reliability_executive_effectiveness': 'executive_action_completion_benefit_review_effectiveness_score_period_close', 'maintenance_reliability_executive_governance': 'executive_action_governance_escalation_evidence_resolution_period_close', 'maintenance_reliability_governance_effectiveness': 'executive_governance_resolution_effectiveness_evidence_review_score_period_close', 'maintenance_reliability_executive_actions': 'executive_exception_to_management_action_decision_owner_due_date_evidence_completion_period_close'}


@app.get('/version')
def version():
    return {
        'version': release.version,
        'schema_target': release.schema_target,
        'migration_policy': release.migration_policy,
    }


if __name__ == '__main__':
    import uvicorn
    import os
    uvicorn.run(app, host=os.getenv('APP_HOST', '0.0.0.0'), port=int(os.getenv('APP_PORT', '8000')))  # [Session CS2]

register_v90fn_routes(app, engine)
register_v90fo_routes(app, engine)
register_v90fp_routes(app, engine)
register_v90fq_routes(app, engine)
register_v90fr_routes(app, engine)
register_v90fs_routes(app, engine)
register_v90ft_routes(app, engine)
register_v90fv_routes(app, engine)

register_v90fw_routes(app, engine)
register_v90fx_routes(app, engine)
register_v90fy_routes(app, engine)
register_v90fz_routes(app, engine)
register_v90ga_routes(app, engine)
register_v90gb_routes(app, engine)
register_v90gc_routes(app, engine)
register_v90gd_routes(app, engine)
register_v90ge_routes(app, engine)
register_v90gf_routes(app, engine)
register_v90gg_routes(app, engine)
register_v90gh_routes(app, engine)
register_v90gi_routes(app, engine)
register_v90gj_routes(app, engine)
register_v90gk_routes(app, engine)
register_v90gl_routes(app, engine)
register_v90gn_routes(app, engine)
register_v90gp_routes(app, engine)
register_v90go_routes(app, engine)
register_v90gq_routes(app, engine)
register_v90gr_routes(app, engine)
register_v90gs_routes(app, engine)
register_v90gt_routes(app, engine)
register_v90gu_routes(app, engine)
register_v90gv_routes(app, engine)
register_v90gw_routes(app, engine)

# [Session CS2] FEATURE — V90.gx modules (see file header).
from .v90gx_company_gst_invoicing import register_v90gx_company_routes
register_v90gx_company_routes(app, engine)
from .v90gx_intercompany_settlement import register_v90gx_intercompany_routes
register_v90gx_intercompany_routes(app, engine)
from .v90gx_plant_operations import register_v90gx_plant_routes
register_v90gx_plant_routes(app, engine)
from .v90gx_notifications import register_v90gx_notification_routes
register_v90gx_notification_routes(app, engine)
from .v90gx_ui_support import register_v90gx_ui_routes
register_v90gx_ui_routes(app, engine)
