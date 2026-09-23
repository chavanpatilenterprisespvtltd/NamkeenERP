CREATE TABLE IF NOT EXISTS ui_notification_reads (
    user_id TEXT NOT NULL,
    notification_id TEXT NOT NULL,
    read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, notification_id)
);
