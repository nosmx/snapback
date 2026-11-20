-- SQLite fallback mirroring schema.singlestore.sql. VECTOR and JSON columns are stored as JSON text;
-- vector search happens in Python (cosine over a few dozen rows).

CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY, store TEXT, item_name TEXT, sku TEXT, price NUMERIC,
  ordered_at TEXT, delivered_at TEXT, ship_zip TEXT, return_by TEXT, status TEXT,
  image_url TEXT, image_embedding TEXT, source_email_id TEXT, tracking_number TEXT, extraction TEXT
);

CREATE TABLE IF NOT EXISTS catalog (
  sku TEXT PRIMARY KEY, store TEXT, name TEXT, price NUMERIC, rating NUMERIC,
  in_stock INTEGER, specs TEXT, text_embedding TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY, trigger_type TEXT, order_id TEXT, status TEXT, decision TEXT,
  idempotency_key TEXT, created_at TEXT, updated_at TEXT, authorized_by TEXT, details TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY, task_id TEXT, question TEXT, options TEXT, recommended TEXT,
  choice TEXT, persona_inquiry_id TEXT, asked_at TEXT, answered_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  entry_id INTEGER PRIMARY KEY AUTOINCREMENT, seq INTEGER, task_id TEXT, step TEXT,
  inputs TEXT, sources TEXT, decision TEXT, rejected_options TEXT, rules_checked TEXT,
  authorized_by TEXT, model TEXT, cost_usd NUMERIC, latency_ms INTEGER, verified INTEGER,
  created_at TEXT, prev_hash TEXT, entry_hash TEXT
);
CREATE INDEX IF NOT EXISTS audit_seq ON audit_log(seq);

CREATE TABLE IF NOT EXISTS mandates (
  user_id TEXT PRIMARY KEY, rules TEXT, verified_by TEXT, persona_inquiry_id TEXT, verified_at TEXT
);
