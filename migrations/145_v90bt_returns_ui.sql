-- V90.bt: returns operational UI preference schema.
CREATE TABLE IF NOT EXISTS ui_returns_preferences (
    preference_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    screen_key TEXT NOT NULL,
    filters TEXT NOT NULL DEFAULT '{}',
    columns TEXT NOT NULL DEFAULT '[]',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, screen_key)
);
