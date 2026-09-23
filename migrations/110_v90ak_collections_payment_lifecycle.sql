-- V90.ak: Collections and payment lifecycle.
CREATE TABLE IF NOT EXISTS payment_allocations (
  allocation_id text PRIMARY KEY,
  payment_id text NOT NULL,
  invoice_id text NOT NULL,
  customer_id text NOT NULL,
  organization_id text NOT NULL,
  entity_id text NOT NULL,
  amount numeric(18,2) NOT NULL CHECK(amount > 0),
  status varchar(20) NOT NULL DEFAULT 'POSTED',
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(payment_id, invoice_id)
);
CREATE TABLE IF NOT EXISTS cash_collection_events (
  collection_event_id text PRIMARY KEY,
  payment_id text NOT NULL UNIQUE,
  status varchar(30) NOT NULL,
  evidence_file_id text,
  handover_at timestamptz,
  deposited_at timestamptz,
  deposit_ref varchar(120),
  deposit_date date,
  verified_by text,
  verified_at timestamptz,
  reason text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payment_lifecycle_events (
  lifecycle_event_id text PRIMARY KEY,
  payment_id text NOT NULL,
  from_status varchar(40),
  to_status varchar(40) NOT NULL,
  event_type varchar(40) NOT NULL,
  reference_no varchar(160),
  notes text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_payment_allocations_payment ON payment_allocations(payment_id,status);
CREATE INDEX IF NOT EXISTS ix_payment_allocations_invoice ON payment_allocations(invoice_id,status);
CREATE INDEX IF NOT EXISTS ix_payment_lifecycle_payment ON payment_lifecycle_events(payment_id,created_at);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('collections.view','View collection lifecycle') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('collections.edit','Record collection lifecycle') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('collections.verify','Verify deposits and cheque clearance') ON CONFLICT(permission_id) DO NOTHING;
