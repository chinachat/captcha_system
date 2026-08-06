"""SQLite 初始化与连接"""
import sqlite3
import threading
import time

from . import config

_local = threading.local()


def get_db():
    conn = getattr(_local, "conn", None)
    if conn is None:
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
        _local.conn = conn
    return conn


def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()
    cur.executescript("""
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
        created_at    REAL NOT NULL,
        FOREIGN KEY (group_id) REFERENCES user_groups(id)
    );
    CREATE TABLE IF NOT EXISTS captcha_passes (
        jti         TEXT PRIMARY KEY,
        created_at  REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_tokens_expires ON captcha_tokens(expires_at);
    CREATE INDEX IF NOT EXISTS idx_logs_created ON captcha_logs(created_at);
    CREATE INDEX IF NOT EXISTS idx_logs_type ON captcha_logs(type);
    """)
    # 旧库迁移：先补列，再补索引（避免旧表缺列时建索引失败）
    log_cols = [r[1] for r in conn.execute("PRAGMA table_info(captcha_logs)")]
    if "api_key" not in log_cols:
        conn.execute("ALTER TABLE captcha_logs ADD COLUMN api_key TEXT")
    key_cols = [r[1] for r in conn.execute("PRAGMA table_info(api_keys)")]
    if "owner" not in key_cols:
        conn.execute("ALTER TABLE api_keys ADD COLUMN owner TEXT DEFAULT 'admin'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_api_key ON captcha_logs(api_key)")
    cur.execute("SELECT COUNT(*) FROM api_keys WHERE key = ?", (config.DEFAULT_API_KEY,))
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO api_keys (key, name, owner, created_at, enabled, note) VALUES (?, ?, 'admin', ?, 1, ?)",
            (config.DEFAULT_API_KEY, "默认演示 Key", time.time(), "系统自动创建")
        )
    conn.commit()
    conn.close()
