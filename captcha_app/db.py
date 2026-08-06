"""数据库层：SQLite（默认）/ PostgreSQL（设置 DATABASE_URL 时启用）

统一适配：调用方使用 `?` 占位符与 `conn.execute(...).fetchone()["col"]` 风格，
sqlite 原生支持；PostgreSQL 由适配层转换占位符并返回 dict 行。
autocommit 语义两端一致（SQLite isolation_level=None / psycopg autocommit=True），
异常后不遗留未提交事务。
"""
import sqlite3
import threading
import time

from . import config

_local = threading.local()
_backend = None  # "sqlite" | "postgres"


def backend():
    global _backend
    if _backend is None:
        _backend = "postgres" if config.DATABASE_URL else "sqlite"
    return _backend


def _connect():
    """建立原生连接（sqlite3 / psycopg），autocommit + dict 行。"""
    if backend() == "postgres":
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(config.DATABASE_URL, connect_timeout=5)
        conn.autocommit = True
        conn.row_factory = dict_row
        return conn
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # autocommit：语句级原子。防止异常（如 FK 违规）后遗留未提交事务，
    # 其连接被异常 traceback 引用、GC 前不释放写锁，导致全库写操作卡死
    conn.isolation_level = None
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _pg_translate(sql: str) -> str:
    """PostgreSQL：占位符 ? -> %s（现有 SQL 无字符串字面量 ?）。"""
    return sql.replace("?", "%s")


class _Cursor:
    """统一游标：fetchone/fetchall 返回 dict，暴露 rowcount/lastrowid。"""

    __slots__ = ("_cur",)

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        # PostgreSQL 无 lastrowid；相关调用已改用 INSERT ... RETURNING id
        try:
            return self._cur.lastrowid
        except Exception:
            return None


class _Conn:
    """统一连接：execute/executescript/commit/rollback/close。"""

    __slots__ = ("_c",)

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, args=()):
        if backend() == "postgres":
            sql = _pg_translate(sql)
        return _Cursor(self._c.execute(sql, args))

    def executescript(self, sql):
        if backend() == "postgres":
            # psycopg3 无参 execute 走 simple protocol，支持多语句
            self._c.execute(sql)
        else:
            self._c.executescript(sql)

    def commit(self):
        if backend() == "sqlite":
            self._c.commit()
        # postgres autocommit 模式下无需操作

    def rollback(self):
        if backend() == "sqlite":
            self._c.rollback()

    def close(self):
        self._c.close()


def get_db():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _Conn(_connect())
        _local.conn = conn
    return conn


def _table_columns(conn, table: str) -> list:
    """查询表列名（sqlite PRAGMA / postgres information_schema）。"""
    if backend() == "postgres":
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", (table,)
        ).fetchall()
        return [r["column_name"] for r in rows]
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r["name"] for r in rows]


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS captcha_tokens (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    secret      TEXT NOT NULL,
    extra       TEXT,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    used        INTEGER DEFAULT 0,
    ip          TEXT,
    user_agent  TEXT
);
CREATE TABLE IF NOT EXISTS captcha_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id    TEXT,
    type        TEXT,
    success     INTEGER,
    detail      TEXT,
    ip          TEXT,
    user_agent  TEXT,
    api_key     TEXT,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    key         TEXT PRIMARY KEY,
    name        TEXT,
    owner       TEXT DEFAULT 'admin',
    created_at  REAL,
    enabled     INTEGER DEFAULT 1,
    note        TEXT
);
CREATE TABLE IF NOT EXISTS user_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    key_quota   INTEGER NOT NULL DEFAULT 5,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    group_id      INTEGER,
    enabled       INTEGER DEFAULT 1,
    totp_secret   TEXT,
    created_at    REAL NOT NULL,
    FOREIGN KEY (group_id) REFERENCES user_groups(id)
);
CREATE TABLE IF NOT EXISTS captcha_passes (
    jti         TEXT PRIMARY KEY,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tokens_expires ON captcha_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_logs_created ON captcha_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_type ON captcha_logs(type);
CREATE INDEX IF NOT EXISTS idx_logs_api_key ON captcha_logs(api_key);
"""

_SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS captcha_tokens (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    secret      TEXT NOT NULL,
    extra       TEXT,
    created_at  DOUBLE PRECISION NOT NULL,
    expires_at  DOUBLE PRECISION NOT NULL,
    used        SMALLINT DEFAULT 0,
    ip          TEXT,
    user_agent  TEXT
);
CREATE TABLE IF NOT EXISTS captcha_logs (
    id          BIGSERIAL PRIMARY KEY,
    token_id    TEXT,
    type        TEXT,
    success     SMALLINT,
    detail      TEXT,
    ip          TEXT,
    user_agent  TEXT,
    api_key     TEXT,
    created_at  DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    key         TEXT PRIMARY KEY,
    name        TEXT,
    owner       TEXT DEFAULT 'admin',
    created_at  DOUBLE PRECISION,
    enabled     SMALLINT DEFAULT 1,
    note        TEXT
);
CREATE TABLE IF NOT EXISTS user_groups (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    key_quota   INTEGER NOT NULL DEFAULT 5,
    created_at  DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    group_id      INTEGER,
    enabled       SMALLINT DEFAULT 1,
    totp_secret   TEXT,
    created_at    DOUBLE PRECISION NOT NULL,
    FOREIGN KEY (group_id) REFERENCES user_groups(id)
);
CREATE TABLE IF NOT EXISTS captcha_passes (
    jti         TEXT PRIMARY KEY,
    created_at  DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tokens_expires ON captcha_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_logs_created ON captcha_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_type ON captcha_logs(type);
CREATE INDEX IF NOT EXISTS idx_logs_api_key ON captcha_logs(api_key);
"""


def init_db():
    conn = _Conn(_connect())
    try:
        conn.executescript(_SCHEMA_POSTGRES if backend() == "postgres" else _SCHEMA_SQLITE)
        # 旧库迁移：先补列，再补索引（避免旧表缺列时建索引失败）
        log_cols = _table_columns(conn, "captcha_logs")
        if "api_key" not in log_cols:
            conn.execute("ALTER TABLE captcha_logs ADD COLUMN api_key TEXT")
        key_cols = _table_columns(conn, "api_keys")
        if "owner" not in key_cols:
            conn.execute("ALTER TABLE api_keys ADD COLUMN owner TEXT DEFAULT 'admin'")
        user_cols = _table_columns(conn, "users")
        if "totp_secret" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_api_key ON captcha_logs(api_key)")
        row = conn.execute("SELECT COUNT(*) AS c FROM api_keys WHERE key = ?",
                           (config.DEFAULT_API_KEY,)).fetchone()
        if row and row["c"] == 0:
            conn.execute(
                "INSERT INTO api_keys (key, name, owner, created_at, enabled, note) "
                "VALUES (?, ?, 'admin', ?, 1, ?)",
                (config.DEFAULT_API_KEY, "默认演示 Key", time.time(), "系统自动创建")
            )
    finally:
        conn.close()
