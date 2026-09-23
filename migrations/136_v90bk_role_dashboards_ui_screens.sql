CREATE TABLE IF NOT EXISTS ui_screen_catalog (
    screen_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    route TEXT NOT NULL,
    role_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ui_dashboard_preferences (
    preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    dashboard_key TEXT NOT NULL,
    widgets JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, dashboard_key)
);
