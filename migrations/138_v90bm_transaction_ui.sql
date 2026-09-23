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
('v90bm_products','products','Product Master','/v90bm/products',1,1),
('v90bm_recipes','recipes','Recipe / BOM','/v90bm/recipes',1,1),
('v90bm_procurement','procurement','Procurement','/v90bm/procurement',1,1)
ON CONFLICT(screen_id) DO NOTHING;
