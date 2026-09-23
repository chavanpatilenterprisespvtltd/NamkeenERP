-- V90.au: Distributor/Dealer management, territory assignment and salesperson portfolios.
CREATE TABLE IF NOT EXISTS sales_territories (
    territory_row_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NULL, territory_id TEXT NOT NULL, territory_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id, entity_id, territory_id)
);
CREATE TABLE IF NOT EXISTS customer_portfolio_assignments (
    assignment_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NULL, customer_id TEXT NOT NULL, customer_type TEXT NOT NULL,
    territory_id TEXT NOT NULL, salesperson_user_id TEXT NULL, effective_from TEXT NULL,
    effective_to TEXT NULL, reason TEXT NULL, active INTEGER NOT NULL DEFAULT 1,
    assigned_by TEXT NOT NULL, assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_customer_portfolio_active ON customer_portfolio_assignments(organization_id,entity_id,customer_id,active,assigned_at);
CREATE INDEX IF NOT EXISTS ix_customer_portfolio_salesperson ON customer_portfolio_assignments(organization_id,entity_id,salesperson_user_id,active);
CREATE TABLE IF NOT EXISTS customer_portfolio_audit (
    audit_id TEXT PRIMARY KEY, assignment_id TEXT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    customer_id TEXT NOT NULL, action TEXT NOT NULL, before_data TEXT NULL, after_data TEXT NULL,
    actor_user_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_portfolio_audit_customer ON customer_portfolio_audit(organization_id,entity_id,customer_id,created_at);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_portfolio.view','View distributor/dealer portfolios and territories') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_portfolio.edit','Manage distributor/dealer portfolios and territories') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_portfolio.assign','Assign/reassign customer portfolios') ON CONFLICT(permission_id) DO NOTHING;
