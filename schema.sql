CREATE TABLE IF NOT EXISTS mandal_items (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, note TEXT NOT NULL,
 total_qty INTEGER NOT NULL CHECK(total_qty BETWEEN 1 AND 100000), photo BYTEA, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mandal_members (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, whatsapp TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1))
);
CREATE TABLE IF NOT EXISTS mandal_transactions (
 id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES mandal_items(id), member_id TEXT NOT NULL REFERENCES mandal_members(id),
 kind TEXT NOT NULL CHECK(kind IN('issue','return')), quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 100000),
 note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mandal_tx_item_member ON mandal_transactions(item_id,member_id);
CREATE INDEX IF NOT EXISTS mandal_tx_date ON mandal_transactions(created_at);
CREATE TABLE IF NOT EXISTS mandal_login_guard (id INTEGER PRIMARY KEY, failures INTEGER NOT NULL, blocked_until DOUBLE PRECISION NOT NULL);
