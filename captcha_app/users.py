"""多用户：用户组与用户管理、密码哈希、API Key 配额"""
import hashlib
import hmac
import secrets

from .db import get_db
from .utils import now

DEFAULT_QUOTA = 5
PBKDF2_ITERATIONS = 200000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ITERATIONS)
    return f"{salt}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, hx = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ITERATIONS)
    return hmac.compare_digest(h.hex(), hx)


def authenticate_user(username: str, password: str):
    """普通用户认证（不含内置管理员）。返回 dict 或 None。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not row["enabled"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return dict(row)


# ---------- 用户组 ----------

def ensure_default_group() -> int:
    conn = get_db()
    row = conn.execute("SELECT id FROM user_groups ORDER BY id LIMIT 1").fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO user_groups (name, key_quota, created_at) VALUES (?, ?, ?) RETURNING id",
        ("默认组", DEFAULT_QUOTA, now()),
    )
    return cur.fetchone()["id"]


def list_groups():
    conn = get_db()
    rows = conn.execute("""
        SELECT g.*, (SELECT COUNT(*) FROM users u WHERE u.group_id = g.id) AS user_count
        FROM user_groups g ORDER BY g.id
    """).fetchall()
    return [dict(r) for r in rows]


def create_group(name: str, quota: int) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO user_groups (name, key_quota, created_at) VALUES (?, ?, ?) RETURNING id",
        (name, max(0, int(quota)), now()),
    )
    return cur.fetchone()["id"]


def update_group(gid, name: str, quota: int) -> bool:
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM user_groups WHERE id = ?", (gid,)).fetchone()
    if not exists:
        return False
    conn.execute(
        "UPDATE user_groups SET name = ?, key_quota = ? WHERE id = ?",
        (name, max(0, int(quota)), gid),
    )
    conn.commit()
    return True


def delete_group(gid) -> tuple:
    """返回 (ok, msg)。组内有用户时拒绝删除。"""
    conn = get_db()
    cnt = conn.execute("SELECT COUNT(*) AS c FROM users WHERE group_id = ?", (gid,)).fetchone()["c"]
    if cnt > 0:
        return False, "该组下仍有用户，请先调整用户所属组"
    conn.execute("DELETE FROM user_groups WHERE id = ?", (gid,))
    conn.commit()
    return True, ""


# ---------- 用户 ----------

def list_users():
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.username, u.group_id, u.enabled, u.created_at,
               g.name AS group_name, g.key_quota,
               (CASE WHEN u.totp_secret IS NULL OR u.totp_secret = '' THEN 0 ELSE 1 END) AS totp_enabled,
               (SELECT COUNT(*) FROM api_keys k WHERE k.owner = u.username) AS key_count
        FROM users u LEFT JOIN user_groups g ON g.id = u.group_id
        ORDER BY u.id
    """).fetchall()
    return [dict(r) for r in rows]


def create_user(username: str, password: str, group_id) -> tuple:
    """返回 (ok, msg, user)。"""
    username = (username or "").strip()[:32]
    if not username or not password:
        return False, "用户名与密码不能为空", None
    conn = get_db()
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return False, "用户名已存在", None
    if group_id is not None:
        g = conn.execute("SELECT 1 FROM user_groups WHERE id = ?", (group_id,)).fetchone()
        if not g:
            return False, "用户组不存在", None
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, group_id, enabled, created_at) "
        "VALUES (?, ?, ?, 1, ?) RETURNING id",
        (username, hash_password(password), group_id, now()),
    )
    return True, "", {"id": cur.fetchone()["id"], "username": username, "group_id": group_id, "enabled": 1}


def update_user(username: str, password: str = None, group_id=None, enabled=None) -> bool:
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    if not exists:
        return False
    sets, args = [], []
    if password is not None and password != "":
        sets.append("password_hash = ?")
        args.append(hash_password(password))
    if group_id is not None:
        sets.append("group_id = ?")
        args.append(group_id)
    if enabled is not None:
        sets.append("enabled = ?")
        args.append(1 if enabled else 0)
    if not sets:
        return True
    args.append(username)
    conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE username = ?", args)
    conn.commit()
    return True


def delete_user(username: str) -> bool:
    """删除用户并级联删除其 API Key。"""
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    if not exists:
        return False
    conn.execute("DELETE FROM api_keys WHERE owner = ?", (username,))
    conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    return True


def key_quota_for(username: str) -> int:
    conn = get_db()
    row = conn.execute("""
        SELECT g.key_quota FROM users u
        LEFT JOIN user_groups g ON g.id = u.group_id
        WHERE u.username = ?
    """, (username,)).fetchone()
    return row["key_quota"] if row and row["key_quota"] is not None else DEFAULT_QUOTA


def count_keys(owner: str) -> int:
    conn = get_db()
    return conn.execute("SELECT COUNT(*) AS c FROM api_keys WHERE owner = ?", (owner,)).fetchone()["c"]
