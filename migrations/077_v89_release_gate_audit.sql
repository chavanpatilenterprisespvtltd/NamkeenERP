CREATE TABLE IF NOT EXISTS release_gate_run (run_id uuid PRIMARY KEY, version_no integer NOT NULL, passed boolean NOT NULL, blockers jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
