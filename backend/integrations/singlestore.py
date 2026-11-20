"""SingleStore repository with a SQLite fallback (chosen once at startup, never mid-run).

All SQL is written with %s placeholders; the SQLite backend rewrites them to '?'.
Vector columns are never selected in normal reads; use vector_search().
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.config import DATA_DIR, ROOT, mode, settings

log = logging.getLogger("snapback.db")

COLUMNS: Dict[str, List[str]] = {
    "orders": ["order_id", "store", "item_name", "sku", "price", "ordered_at", "delivered_at", "ship_zip",
               "return_by", "status", "image_url", "source_email_id", "tracking_number", "extraction"],
    "catalog": ["sku", "store", "name", "price", "rating", "in_stock", "specs"],
    "tasks": ["task_id", "trigger_type", "order_id", "status", "decision", "idempotency_key", "created_at",
              "updated_at", "authorized_by", "details"],
    "approvals": ["approval_id", "task_id", "question", "options", "recommended", "choice", "persona_inquiry_id",
                  "asked_at", "answered_at"],
    "audit_log": ["entry_id", "seq", "task_id", "step", "inputs", "sources", "decision", "rejected_options",
                  "rules_checked", "authorized_by", "model", "cost_usd", "latency_ms", "verified", "created_at",
                  "prev_hash", "entry_hash"],
    "mandates": ["user_id", "rules", "verified_by", "persona_inquiry_id", "verified_at"],
}
JSON_COLS = {"extraction", "specs", "details", "options", "inputs", "sources", "rejected_options", "rules_checked", "rules"}
VECTOR_COLS = {"orders": {"image_embedding": "image_embed_dim"}, "catalog": {"text_embedding": "text_embed_dim"}}
BOOL_COLS = {"in_stock", "verified"}


def _to_db(col: str, value: Any) -> Any:
    if value is None:
        return None
    if col in JSON_COLS or isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _from_db(col: str, value: Any) -> Any:
    if value is None:
        return None
    if col in JSON_COLS:
        if isinstance(value, (bytes, bytearray)):
            value = value.decode()
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value
    if col in BOOL_COLS:
        return bool(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _normalize(vec: Sequence[float]) -> List[float]:
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [float(v) / n for v in vec]


class Database:
    def __init__(self) -> None:
        self.backend = "singlestore" if mode("db") == "real" else "sqlite"
        import queue
        self._pool: "queue.LifoQueue" = queue.LifoQueue()   # shared connection pool (threads reuse connections)
        self._pool_lock = threading.Lock()
        self._pool_size = 0
        self._pool_max = 6
        self._db_ready = False
        self._sqlite_lock = threading.RLock()
        self._sqlite: Optional[sqlite3.Connection] = None
        if self.backend == "singlestore":
            import time
            last: Optional[Exception] = None
            for attempt in range(3):  # ride out brief network/DNS blips before falling back
                try:
                    self._release(self._acquire())
                    last = None
                    break
                except Exception as e:
                    last = e
                    time.sleep(1.5 * (attempt + 1))
            if last is not None:  # credential/network failure must never block the demo
                log.warning("SingleStore unavailable after retries (%s); falling back to SQLite", last)
                self.backend = "sqlite"
                self.fallback_reason = str(last)

    # ---------- connections ----------

    def _singlestore_params(self) -> Tuple[Dict[str, Any], str]:
        """Parse user:password@host:port/db by hand. The password is taken exactly as typed
        (no URL-encoding needed), so characters like @ / # ? ; > in it are safe."""
        raw = settings.singlestore_url.strip()
        if "://" in raw.split("@", 1)[0]:
            raw = raw.split("://", 1)[1]
        userinfo, _, hostpart = raw.rpartition("@")
        user, _, password = userinfo.partition(":")
        hostport, _, dbname = hostpart.partition("/")
        host, _, port = hostport.partition(":")
        dbname = dbname.split("?", 1)[0].strip() or "snapback"
        return dict(host=host, port=int(port) if port.isdigit() else 3306, user=user, password=password), dbname

    def _conn(self):
        """SQLite connection (the SingleStore path uses the pool via _acquire/_release)."""
        if self._sqlite is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._sqlite = sqlite3.connect(str(DATA_DIR / "snapback.db"), check_same_thread=False)
        return self._sqlite

    def _new_s2(self):
        import singlestoredb as s2
        params, dbname = self._singlestore_params()
        if not self._db_ready:
            conn = s2.connect(**params)
            cur = conn.cursor()
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{dbname}`")
            cur.execute(f"USE `{dbname}`")
            self._db_ready = True
            return conn
        return s2.connect(**params, database=dbname)

    def _acquire(self):
        import queue
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            pass
        with self._pool_lock:
            if self._pool_size < self._pool_max:
                self._pool_size += 1
                try:
                    return self._new_s2()
                except Exception:
                    self._pool_size -= 1
                    raise
        return self._pool.get(timeout=30)

    def _release(self, conn) -> None:
        self._pool.put(conn)

    def _discard(self, conn) -> None:
        try:
            conn.close()
        except Exception:
            pass
        with self._pool_lock:
            self._pool_size -= 1

    # ---------- raw SQL ----------

    def _sql(self, sql: str) -> str:
        return sql.replace("%s", "?") if self.backend == "sqlite" else sql

    def _s2(self, fn):
        """Run fn(conn) on a pooled SingleStore connection; if it dropped (e.g. the workspace
        auto-suspended and was resumed), replace it and retry once."""
        conn = self._acquire()
        try:
            out = fn(conn)
            self._release(conn)
            return out
        except Exception as e:
            msg = str(e)
            if not any(code in msg for code in ("2003", "2006", "2013", "Lost connection", "gone away", "closed")):
                self._release(conn)
                raise
            log.warning("SingleStore connection lost (%s); reconnecting", msg[:120])
            self._discard(conn)
            conn = self._acquire()
            try:
                out = fn(conn)
            finally:
                self._release(conn)
            return out

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        if self.backend == "sqlite":
            with self._sqlite_lock:
                conn = self._conn()
                cur = conn.execute(self._sql(sql), tuple(params))
                conn.commit()
                return cur.rowcount

        def run(conn):
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            conn.commit()
            return cur.rowcount
        return self._s2(run)

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        if self.backend == "sqlite":
            with self._sqlite_lock:
                cur = self._conn().execute(self._sql(sql), tuple(params))
                rows = cur.fetchall()
                desc = cur.description
        else:
            def run(conn):
                cur = conn.cursor()
                cur.execute(sql, tuple(params))
                return cur.fetchall(), cur.description
            rows, desc = self._s2(run)
        cols = [d[0] for d in desc] if desc else []
        return [{c: _from_db(c, v) for c, v in zip(cols, row)} for row in rows]

    # ---------- keepalive (workspace auto-suspends after ~20 min idle) ----------

    def start_keepalive(self, interval_s: int = 240) -> None:
        if self.backend != "singlestore" or getattr(self, "_keepalive", None):
            return

        def loop():
            import time
            while True:
                time.sleep(interval_s)
                try:
                    self.query("SELECT COUNT(*) AS n FROM orders")
                except Exception as e:
                    log.warning("SingleStore keepalive failed: %s", str(e)[:120])

        self._keepalive = threading.Thread(target=loop, daemon=True, name="singlestore-keepalive")
        self._keepalive.start()
        log.info("SingleStore keepalive every %ss", interval_s)

    # ---------- schema ----------

    def init_schema(self, drop: bool = False) -> None:
        if drop:
            for t in COLUMNS:
                self.execute(f"DROP TABLE IF EXISTS {t}")
        fname = "schema.singlestore.sql" if self.backend == "singlestore" else "schema.sqlite.sql"
        ddl = (ROOT / "backend" / "db" / fname).read_text()
        ddl = ddl.replace("{IMAGE_DIM}", str(settings.image_embed_dim)).replace("{TEXT_DIM}", str(settings.text_embed_dim))
        statements = [s.strip() for s in "\n".join(
            line for line in ddl.splitlines() if not line.strip().startswith("--")).split(";") if s.strip()]
        for stmt in statements:
            self.execute(stmt)

    # ---------- row helpers ----------

    def insert(self, table: str, row: Dict[str, Any], replace: bool = False) -> None:
        cols = list(row.keys())
        vals = []
        placeholders = []
        for c in cols:
            if c in VECTOR_COLS.get(table, {}):
                vec = _normalize(row[c]) if row[c] is not None else None
                vals.append(json.dumps(vec) if vec is not None else None)
                placeholders.append("%s")
            else:
                vals.append(_to_db(c, row[c]))
                placeholders.append("%s")
        verb = "REPLACE" if replace else "INSERT"
        self.execute(f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({', '.join(placeholders)})", vals)

    def insert_many(self, table: str, rows: List[Dict[str, Any]]) -> None:
        """One multi-row INSERT (one round trip to SingleStore instead of one per row)."""
        if not rows:
            return
        cols = list(rows[0].keys())
        vecs = VECTOR_COLS.get(table, {})
        params: List[Any] = []
        for r in rows:
            for c in cols:
                v = r.get(c)
                params.append(json.dumps(_normalize(v)) if (c in vecs and v is not None) else (None if c in vecs else _to_db(c, v)))
        one = "(" + ", ".join(["%s"] * len(cols)) + ")"
        self.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES " + ", ".join([one] * len(rows)), params)

    def upsert(self, table: str, row: Dict[str, Any]) -> None:
        self.insert(table, row, replace=True)

    def update(self, table: str, pk_col: str, pk: Any, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        sets = ", ".join(f"{c} = %s" for c in fields)
        self.execute(f"UPDATE {table} SET {sets} WHERE {pk_col} = %s", [_to_db(c, v) for c, v in fields.items()] + [pk])

    def select(self, table: str, where: Optional[Dict[str, Any]] = None, order_by: Optional[str] = None,
               limit: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = f"SELECT {', '.join(COLUMNS[table])} FROM {table}"
        params: List[Any] = []
        if where:
            sql += " WHERE " + " AND ".join(f"{c} = %s" for c in where)
            params = [_to_db(c, v) for c, v in where.items()]
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.query(sql, params)

    def get(self, table: str, pk_col: str, pk: Any) -> Optional[Dict[str, Any]]:
        rows = self.select(table, {pk_col: pk}, limit=1)
        return rows[0] if rows else None

    def count(self, table: str) -> int:
        return int(self.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])

    # ---------- vector search ----------

    def vector_search(self, table: str, column: str, id_col: str, vec: Sequence[float], k: int = 5,
                      where: Optional[Dict[str, Any]] = None) -> List[Tuple[str, float]]:
        q = _normalize(vec)
        if self.backend == "singlestore":
            dim = getattr(settings, VECTOR_COLS[table][column])
            sql = (f"SELECT {id_col} AS id, DOT_PRODUCT({column}, %s :> VECTOR({dim})) AS score FROM {table}"
                   f" WHERE {column} IS NOT NULL")
            params: List[Any] = [json.dumps(q)]
            for c, v in (where or {}).items():
                sql += f" AND {c} = %s"
                params.append(v)
            sql += f" ORDER BY score DESC LIMIT {int(k)}"
            return [(r["id"], float(r["score"])) for r in self.query(sql, params)]
        sql = f"SELECT {id_col} AS id, {column} AS vec FROM {table} WHERE {column} IS NOT NULL"
        params = []
        for c, v in (where or {}).items():
            sql += f" AND {c} = %s"
            params.append(v)
        scored = []
        for r in self.query(sql, params):
            other = json.loads(r["vec"]) if isinstance(r["vec"], str) else r["vec"]
            scored.append((r["id"], sum(a * b for a, b in zip(q, other))))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


_db: Optional[Database] = None


def db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
