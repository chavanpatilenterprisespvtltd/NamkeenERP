-- FILE PATH: migrations/278_v90gx_notifications.sql
-- V90.gx (Session CS2): Notification outbox (SMS/WhatsApp via webhook, e-mail via SMTP).
-- Same DDL as the runtime ensure_* function in the matching app/v90gx_*.py module (idempotent).
CREATE TABLE IF NOT EXISTS notification_outbox(notification_id TEXT PRIMARY KEY,organization_id TEXT NULL,channel TEXT NOT NULL,recipient TEXT NOT NULL,subject TEXT NULL,body TEXT NOT NULL, template_code TEXT NOT NULL,reference TEXT NULL,dedupe_key TEXT NULL UNIQUE,status TEXT NOT NULL DEFAULT 'QUEUED',attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at TEXT NULL, last_error TEXT NULL,provider TEXT NULL,provider_message_id TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,sent_at TIMESTAMP NULL);
CREATE INDEX IF NOT EXISTS ix_notification_outbox_status ON notification_outbox(status,next_attempt_at);
