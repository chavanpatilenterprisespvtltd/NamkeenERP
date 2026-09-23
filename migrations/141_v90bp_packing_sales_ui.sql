CREATE TABLE IF NOT EXISTS ui_transaction_screen_registry (
    screen_id TEXT PRIMARY KEY,
    screen_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    api_path TEXT NOT NULL,
    mobile_supported INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO ui_transaction_screen_registry(screen_id,screen_key,title,api_path,mobile_supported,active)
VALUES
('v90bp_packing','packing','Packing / FG','/v90bp/packing/summary',1,1),
('v90bp_sales','sales','Sales / Customer Order Builder','/v90bp/sales/summary',1,1)
ON CONFLICT(screen_id) DO NOTHING;
