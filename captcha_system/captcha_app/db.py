"""SQLite 初始化与连接"""
import sqlite3
import time

from . import config


def get_db():
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
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
        created_at  REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS api_keys (
        key         TEXT PRIMARY KEY,
        name        TEXT,
        created_at  REAL,
        enabled     INTEGER DEFAULT 1,
        note        TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_tokens_expires ON captcha_tokens(expires_at);
    CREATE INDEX IF NOT EXISTS idx_logs_created ON captcha_logs(created_at);
    """)
    cur.execute("SELECT COUNT(*) FROM api_keys WHERE key = ?", (config.DEFAULT_API_KEY,))
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO api_keys (key, name, created_at, enabled, note) VALUES (?, ?, ?, 1, ?)",
            (config.DEFAULT_API_KEY, "默认演示 Key", time.time(), "系统自动创建")
        )
    conn.commit()
    conn.close()
