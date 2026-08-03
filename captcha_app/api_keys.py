"""API Key CRUD"""
import secrets

from . import config
from .db import get_db
from .utils import now

def check_api_key(key):
    if not key:
        return False
    conn = get_db()
    row = conn.execute("SELECT enabled FROM api_keys WHERE key = ?", (key,)).fetchone()
    return bool(row and row["enabled"])

def list_api_keys():
    conn = get_db()
    rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

def create_api_key(name, note=""):
    key = "ak-" + secrets.token_hex(16)
    conn = get_db()
    conn.execute(
        "INSERT INTO api_keys (key, name, created_at, enabled, note) VALUES (?, ?, ?, 1, ?)",
        (key, name or "未命名", now(), note or "")
    )
    conn.commit()
    return key

def set_api_key_enabled(key, enabled):
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM api_keys WHERE key = ?", (key,)).fetchone()
    if not exists:
        return False
    conn.execute("UPDATE api_keys SET enabled = ? WHERE key = ?", (1 if enabled else 0, key))
    conn.commit()
    return True

def delete_api_key(key):
    if key == config.DEFAULT_API_KEY:
        return False
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM api_keys WHERE key = ?", (key,)).fetchone()
    if not exists:
        return False
    conn.execute("DELETE FROM api_keys WHERE key = ?", (key,))
    conn.commit()
    return True

