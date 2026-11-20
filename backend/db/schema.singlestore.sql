-- Snapback schema for SingleStore (generalcontext.md §8 + tweaks logged in NOTES.md).
-- {IMAGE_DIM} / {TEXT_DIM} are substituted from IMAGE_EMBED_DIM / TEXT_EMBED_DIM.

CREATE TABLE IF NOT EXISTS orders (
  order_id VARCHAR(64) PRIMARY KEY,
  store VARCHAR(64),
  item_name TEXT,
  sku VARCHAR(64),
  price DECIMAL(10,2),
  ordered_at DATETIME(6),
  delivered_at DATETIME(6),
  ship_zip VARCHAR(10),
  return_by DATE,
  status VARCHAR(32),                 -- active|returned|kept|claimed
  image_url TEXT,
  image_embedding VECTOR({IMAGE_DIM}),
  source_email_id VARCHAR(64),
  tracking_number VARCHAR(64),
  extraction JSON                     -- {fields, gaps, confidence, model}
);

CREATE TABLE IF NOT EXISTS catalog (
  sku VARCHAR(64) PRIMARY KEY,
  store VARCHAR(64),
  name TEXT,
  price DECIMAL(10,2),
  rating DECIMAL(3,2),
  in_stock BOOL,
  specs JSON,
  text_embedding VECTOR({TEXT_DIM})
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id VARCHAR(64) PRIMARY KEY,
  trigger_type VARCHAR(32),
  order_id VARCHAR(64),
  status VARCHAR(32),   -- detected|awaiting_user|planned|executing|verifying|awaiting_refund|done|expired|failed
  decision VARCHAR(32),
  idempotency_key VARCHAR(128),
  created_at DATETIME(6),
  updated_at DATETIME(6),
  authorized_by VARCHAR(64),
  details JSON                         -- options, savings math, RMA, label, new order id, ...
);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id VARCHAR(64) PRIMARY KEY,
  task_id VARCHAR(64),
  question TEXT,
  options JSON,
  recommended VARCHAR(32),
  choice VARCHAR(32),
  persona_inquiry_id VARCHAR(64),
  asked_at DATETIME(6),
  answered_at DATETIME(6)
);

CREATE TABLE IF NOT EXISTS audit_log (
  entry_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  seq BIGINT,                          -- chain order (AUTO_INCREMENT is not guaranteed sequential)
  task_id VARCHAR(64),
  step VARCHAR(64),
  inputs JSON,
  sources JSON,                        -- [{doc, section, url, retrieved_at, quote}]
  decision TEXT,
  rejected_options JSON,
  rules_checked JSON,                  -- [{rule, passed, evidence}]
  authorized_by VARCHAR(64),           -- mandate rule or approval_id
  model VARCHAR(64),
  cost_usd DECIMAL(10,5),
  latency_ms INT,
  verified BOOL,
  created_at DATETIME(6),
  prev_hash CHAR(64),
  entry_hash CHAR(64),
  KEY (seq)
);

CREATE TABLE IF NOT EXISTS mandates (
  user_id VARCHAR(64) PRIMARY KEY,
  rules JSON,
  verified_by VARCHAR(32),
  persona_inquiry_id VARCHAR(64),
  verified_at DATETIME(6)
);
