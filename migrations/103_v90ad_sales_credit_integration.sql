CREATE TABLE IF NOT EXISTS sales_order_control_reviews (
    control_review_id text PRIMARY KEY,
    sales_order_id text NOT NULL,
    organization_id text NOT NULL,
    entity_id text NOT NULL,
    location_id text NOT NULL,
    pricing_status varchar(20) NOT NULL,
    credit_status varchar(20) NOT NULL,
    stock_status varchar(20) NOT NULL,
    overall_status varchar(20) NOT NULL,
    reason text,
    checked_by text NOT NULL,
    checked_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_sales_order_control_reviews_order ON sales_order_control_reviews(sales_order_id, checked_at);
