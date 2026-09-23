CREATE TABLE IF NOT EXISTS customer_credit_policies (
    credit_policy_id text PRIMARY KEY,
    organization_id text NOT NULL,
    entity_id text NOT NULL,
    customer_id text NOT NULL,
    credit_limit numeric(18,2) NOT NULL CHECK (credit_limit >= 0),
    credit_days integer NOT NULL DEFAULT 0 CHECK (credit_days >= 0),
    active boolean NOT NULL DEFAULT TRUE,
    notes text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS credit_reviews (
    credit_review_id text PRIMARY KEY,
    organization_id text NOT NULL,
    entity_id text NOT NULL,
    location_id text NOT NULL,
    customer_id text NOT NULL,
    proposed_order_total numeric(18,2) NOT NULL,
    current_outstanding numeric(18,2) NOT NULL,
    available_credit numeric(18,2) NOT NULL,
    overdue_amount numeric(18,2) NOT NULL,
    credit_limit numeric(18,2) NOT NULL,
    credit_days integer NOT NULL,
    status varchar(20) NOT NULL,
    reason text,
    sales_order_id text,
    reviewed_by text NOT NULL,
    reviewed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payment_transactions (
    payment_id text PRIMARY KEY,
    organization_id text NOT NULL,
    entity_id text NOT NULL,
    location_id text NOT NULL,
    customer_id text NOT NULL,
    sales_order_id text,
    amount numeric(18,2) NOT NULL CHECK (amount > 0),
    mode varchar(30) NOT NULL,
    reference_no varchar(120),
    cheque_no varchar(120),
    bank_name varchar(160),
    payment_date date NOT NULL,
    status varchar(30) NOT NULL,
    proof_file_id text,
    notes text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified_by text,
    verified_at timestamptz
);
CREATE INDEX IF NOT EXISTS ix_customer_credit_policy_scope ON customer_credit_policies(entity_id, customer_id, active);
CREATE INDEX IF NOT EXISTS ix_credit_reviews_scope ON credit_reviews(entity_id, customer_id, reviewed_at);
CREATE INDEX IF NOT EXISTS ix_payment_transactions_scope ON payment_transactions(entity_id, customer_id, status, payment_date);
