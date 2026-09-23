-- V90.az Batch traceability + recall / withdrawal capability
CREATE TABLE IF NOT EXISTS recall_cases (
  recall_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
  recall_no TEXT NOT NULL, title TEXT NOT NULL, reason TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'MEDIUM',
  status TEXT NOT NULL DEFAULT 'OPEN', source_type TEXT NOT NULL, source_id TEXT NOT NULL, initiated_by TEXT NOT NULL,
  initiated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, closed_at TEXT NULL,
  UNIQUE(organization_id,entity_id,recall_no)
);
CREATE TABLE IF NOT EXISTS recall_affected_lots (
  recall_lot_id TEXT PRIMARY KEY, recall_id TEXT NOT NULL, lot_type TEXT NOT NULL, lot_id TEXT NOT NULL,
  lot_code TEXT NULL, item_id TEXT NULL, original_qty NUMERIC NOT NULL DEFAULT 0, identified_qty NUMERIC NOT NULL DEFAULT 0,
  withdrawn_qty NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'IDENTIFIED',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(recall_id,lot_type,lot_id)
);
CREATE TABLE IF NOT EXISTS recall_withdrawals (
  withdrawal_id TEXT PRIMARY KEY, recall_id TEXT NOT NULL, lot_type TEXT NOT NULL, lot_id TEXT NOT NULL,
  quantity NUMERIC NOT NULL, reason TEXT NOT NULL, warehouse_id TEXT NULL, performed_by TEXT NOT NULL,
  performed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS recall_trace_events (
  trace_event_id TEXT PRIMARY KEY, recall_id TEXT NOT NULL, event_type TEXT NOT NULL, entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL, reference_id TEXT NULL, quantity NUMERIC NULL, customer_id TEXT NULL,
  event_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_recall_cases_scope ON recall_cases(entity_id,location_id,status,initiated_at);
CREATE INDEX IF NOT EXISTS ix_recall_affected_lot ON recall_affected_lots(lot_type,lot_id,status);
CREATE INDEX IF NOT EXISTS ix_recall_trace ON recall_trace_events(recall_id,event_type);
