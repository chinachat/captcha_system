"""系统设置（key-value，持久化到 SQLite settings 表）"""
from .db import get_db


def get_setting(key: str, default: str = "") -> str:
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_setting(key: str, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()


def get_bool_setting(key: str, default: bool = False) -> bool:
    return get_setting(key, "1" if default else "0") in ("1", "true", "yes")
