"""API Key CRUD（check 带内存缓存，减少每请求 DB 查询）"""
import secrets
import time

from . import config
from .db import get_db
from .utils import now

DEMO_PREFIX = "cg-demo-"

# Key 状态缓存：key -> (enabled, expires_at)。启停/删除时立即失效；TTL 兜底防多实例不一致
_API_KEY_CACHE = {}
_API_KEY_CACHE_TTL = 30


def _invalidate_api_key(key):
    _API_KEY_CACHE.pop(key, None)


def _cache_clear():
    _API_KEY_CACHE.clear()


def ensure_demo_key() -> str:
    """演示页专用 Key：每次启动轮换（删除旧演示 Key 并生成新的）。

    与业务 Key 隔离：页面不展示、独立全局限流、后台可禁用。
    """
    conn = get_db()
    rows = conn.execute("SELECT key FROM api_keys WHERE key LIKE ?", (DEMO_PREFIX + "%",)).fetchall()
    for r in rows:
        conn.execute("DELETE FROM api_keys WHERE key = ?", (r["key"],))
        _invalidate_api_key(r["key"])
    key = DEMO_PREFIX + secrets.token_hex(8)
    conn.execute(
        "INSERT INTO api_keys (key, name, owner, created_at, enabled, note) "
        "VALUES (?, ?, 'demo', ?, 1, ?)",
        (key, "演示页 Key（自动轮换）", now(), "仅供演示页使用，受限流保护"),
    )
    conn.commit()
    return key


def get_demo_key() -> str:
    """获取当前演示 Key；不存在（被删除）时重新生成。"""
    conn = get_db()
    row = conn.execute(
        "SELECT key FROM api_keys WHERE key LIKE ? ORDER BY created_at DESC LIMIT 1",
        (DEMO_PREFIX + "%",),
    ).fetchone()
    if row:
        return row["key"]
    return ensure_demo_key()

def check_api_key(key):
    if not key:
        return False
    now_t = now()
    hit = _API_KEY_CACHE.get(key)
    if hit and hit[1] > now_t:
        return hit[0]
    conn = get_db()
    row = conn.execute("SELECT enabled FROM api_keys WHERE key = ?", (key,)).fetchone()
    enabled = bool(row and row["enabled"])
    _API_KEY_CACHE[key] = (enabled, now_t + _API_KEY_CACHE_TTL)
    return enabled

def list_api_keys():
    conn = get_db()
    rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

def create_api_key(name, note="", owner="admin"):
    key = "ak-" + secrets.token_hex(16)
    conn = get_db()
    conn.execute(
        "INSERT INTO api_keys (key, name, owner, created_at, enabled, note) VALUES (?, ?, ?, ?, 1, ?)",
        (key, name or "未命名", owner or "admin", now(), note or "")
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
    _invalidate_api_key(key)
    return True

def update_api_key(key, name, note):
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM api_keys WHERE key = ?", (key,)).fetchone()
    if not exists:
        return False
    conn.execute(
        "UPDATE api_keys SET name = ?, note = ? WHERE key = ?",
        (name, note, key)
    )
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
    _invalidate_api_key(key)
    return True

