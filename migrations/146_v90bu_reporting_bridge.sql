-- V90.bu compatibility bridge: reporting release metadata.
CREATE TABLE IF NOT EXISTS v90_release_components (
    component_key TEXT PRIMARY KEY,
    release_version TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
