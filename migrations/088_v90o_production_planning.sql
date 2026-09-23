CREATE TABLE IF NOT EXISTS production_plan (
 plan_id text PRIMARY KEY, organization_id text NOT NULL, entity_id text NOT NULL, location_id text NOT NULL,
 plan_no text NOT NULL, period_start text NOT NULL, period_end text NOT NULL, status text NOT NULL DEFAULT 'DRAFT',
 source text, notes text, created_by text NOT NULL, approved_by text, approved_at timestamptz, approval_reason text,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS production_plan_line (
 plan_line_id text PRIMARY KEY, plan_id text NOT NULL, line_no integer NOT NULL, item_master_id text NOT NULL,
 uom text NOT NULL, planned_qty numeric NOT NULL, priority integer NOT NULL DEFAULT 1, due_date text, status text NOT NULL DEFAULT 'PLANNED', notes text
);
CREATE TABLE IF NOT EXISTS production_plan_requirement (
 requirement_id text PRIMARY KEY, plan_id text NOT NULL, plan_line_id text NOT NULL, requirement_type text NOT NULL,
 item_master_id text NOT NULL, required_qty numeric NOT NULL, uom text NOT NULL, status text NOT NULL DEFAULT 'OPEN', notes text
);

INSERT INTO erp_permissions(permission_id, permission_name) VALUES ('production.approve','Approve production') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_role_permissions(role_id, permission_id) SELECT 'super_admin','production.approve' WHERE NOT EXISTS (SELECT 1 FROM erp_role_permissions WHERE role_id='super_admin' AND permission_id='production.approve');
INSERT INTO erp_role_permissions(role_id, permission_id) SELECT 'manager','production.approve' WHERE NOT EXISTS (SELECT 1 FROM erp_role_permissions WHERE role_id='manager' AND permission_id='production.approve');
