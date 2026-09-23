-- V90.bo: production planning/execution UI preferences
-- Schema objects are created idempotently by the runtime module for SQLite/PostgreSQL compatibility.
CREATE TABLE IF NOT EXISTS ui_production_preferences (
    preference_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    screen_key TEXT NOT NULL,
    filters TEXT NOT NULL DEFAULT '{}',
    columns TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ui_production_preferences ON ui_production_preferences(user_id, screen_key);
