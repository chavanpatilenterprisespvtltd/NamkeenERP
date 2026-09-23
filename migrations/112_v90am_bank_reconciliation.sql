-- V90.am: Bank reconciliation and settlement controls for customer receipts.
CREATE TABLE IF NOT EXISTS bank_reconciliation_lines (
  bank_line_id text PRIMARY KEY,
  organization_id text NOT NULL,
  entity_id text NOT NULL,
  location_id text,
  bank_name text NOT NULL,
  statement_date date NOT NULL,
  statement_ref text NOT NULL,
  amount numeric(18,2) NOT NULL CHECK(amount > 0),
  transaction_type varchar(20) NOT NULL,
  bank_reference text,
  status varchar(20) NOT NULL DEFAULT 'UNMATCHED',
  matched_payment_id text,
  matched_by text,
  matched_at timestamptz,
  reconciled_by text,
  reconciled_at timestamptz,
  notes text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(entity_id, statement_ref)
);
CREATE TABLE IF NOT EXISTS bank_reconciliation_events (
  event_id text PRIMARY KEY,
  bank_line_id text NOT NULL,
  from_status varchar(20),
  to_status varchar(20) NOT NULL,
  event_type varchar(40) NOT NULL,
  payment_id text,
  notes text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_bank_recon_scope ON bank_reconciliation_lines(entity_id,statement_date,status);
CREATE INDEX IF NOT EXISTS ix_bank_recon_payment ON bank_reconciliation_lines(matched_payment_id,status);
CREATE INDEX IF NOT EXISTS ix_bank_recon_ref ON bank_reconciliation_lines(entity_id,statement_ref);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('bank_recon.view','View bank reconciliation') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('bank_recon.edit','Import and match bank lines') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('bank_recon.reconcile','Finalize bank reconciliation') ON CONFLICT(permission_id) DO NOTHING;
