"""验证码 Token 存取与日志（SQLite / Redis）"""
import json
import uuid

from . import config
from .db import get_db
from .redis_client import get_redis
from .utils import now


def create_token(ctype, secret, extra=None, ip="", ua=""):
    token_id = str(uuid.uuid4())
    expires = now() + config.CAPTCHA_EXPIRE_SECONDS
    extra_json = json.dumps(extra or {})

    r = get_redis()
    if r:
        try:
            r.setex(
                f"captcha:{token_id}",
                config.CAPTCHA_EXPIRE_SECONDS,
                json.dumps({"type": ctype, "secret": secret, "extra": extra or {}, "used": 0, "ip": ip})
            )
            return token_id
        except Exception:
            pass

    conn = get_db()
    conn.execute(
        "INSERT INTO captcha_tokens (id, type, secret, extra, created_at, expires_at, ip, user_agent) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (token_id, ctype, secret, extra_json, now(), expires, ip, ua)
    )
    conn.commit()
    conn.close()
    return token_id


def get_token(token_id):
    r = get_redis()
    if r:
        try:
            raw = r.get(f"captcha:{token_id}")
            if raw:
                data = json.loads(raw)
                return {
                    "id": token_id,
                    "type": data["type"],
                    "secret": data["secret"],
                    "extra": json.dumps(data.get("extra") or {}),
                    "used": data.get("used", 0),
                    "expires_at": now() + 10,  # redis 已自动过期，这里给个宽松值
                    "ip": data.get("ip", ""),
                }
            return None
        except Exception:
            pass

    conn = get_db()
    row = conn.execute("SELECT * FROM captcha_tokens WHERE id = ?", (token_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_used(token_id):
    """原子标记 token 为已使用。Redis 场景下使用 Lua 脚本保证原子性。"""
    r = get_redis()
    if r:
        try:
            # Lua 脚本：原子获取 -> 替换 used 标志 -> 保持 TTL
            lua = """
            local key = KEYS[1]
            local raw = redis.call('get', key)
            if not raw then return 0 end
            local ttl = redis.call('ttl', key)
            if ttl <= 0 then ttl = 120 end
            local updated = string.gsub(raw, '"used"%s*:%s*0', '"used":1')
            redis.call('setex', key, ttl, updated)
            return 1
            """
            result = r.eval(lua, 1, f"captcha:{token_id}")
            if result == 1:
                return
        except Exception:
            pass

    conn = get_db()
    conn.execute("UPDATE captcha_tokens SET used = 1 WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()


def log_attempt(token_id, ctype, success, detail, ip="", ua=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO captcha_logs (token_id, type, success, detail, ip, user_agent, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (token_id, ctype, 1 if success else 0, detail, ip, ua, now())
    )
    conn.commit()
    conn.close()


def cleanup_expired():
    conn = get_db()
    conn.execute("DELETE FROM captcha_tokens WHERE expires_at < ? OR used = 1", (now() - 3600,))
    conn.execute("DELETE FROM captcha_logs WHERE created_at < ?", (now() - 7 * 86400,))
    conn.commit()
    conn.close()
