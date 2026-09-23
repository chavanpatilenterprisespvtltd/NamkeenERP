-- V90.ab: Incentive rules and accrual foundation.
CREATE TABLE IF NOT EXISTS incentive_rules (
    incentive_rule_id VARCHAR(64) PRIMARY KEY,
    organization_id VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    rule_name VARCHAR(120) NOT NULL,
    rule_type VARCHAR(40) NOT NULL,
    rate NUMERIC(12,4) NOT NULL,
    min_margin_pct NUMERIC(8,4),
    min_net_price NUMERIC(14,4),
    fixed_amount NUMERIC(14,4),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS incentive_accruals (
    incentive_accrual_id VARCHAR(64) PRIMARY KEY,
    incentive_rule_id VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    location_id VARCHAR(64) NOT NULL,
    salesperson_user_id VARCHAR(64) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    sales_order_id VARCHAR(64),
    quantity NUMERIC(14,4) NOT NULL,
    unit_cost NUMERIC(14,4) NOT NULL,
    gross_net_sales NUMERIC(16,4) NOT NULL,
    net_sales NUMERIC(16,4) NOT NULL,
    margin_pct NUMERIC(10,4) NOT NULL,
    incentive_amount NUMERIC(16,4) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'ACCRUED',
    reason TEXT,
    created_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
