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
        (token_id, ctype, secret, json.dumps(extra or {}), now(), expires, ip, ua)
    )
    conn.commit()
    return token_id


def get_token(token_id):
    r = get_redis()
    if r:
        try:
            raw = r.get(f"captcha:{token_id}")
            if raw:
                data = json.loads(raw)
                # 过期时间由 Redis TTL 为准（setex 自动过期）
                ttl = r.ttl(f"captcha:{token_id}")
                expires_at = now() + max(int(ttl or 0), 0)
                return {
                    "id": token_id,
                    "type": data["type"],
                    "secret": data["secret"],
                    "extra": json.dumps(data.get("extra") or {}),
                    "used": data.get("used", 0),
                    "expires_at": expires_at,
                    "ip": data.get("ip", ""),
                }
            return None
        except Exception:
            pass

    conn = get_db()
    row = conn.execute("SELECT * FROM captcha_tokens WHERE id = ?", (token_id,)).fetchone()
    return dict(row) if row else None


def mark_used(token_id):
    r = get_redis()
    if r:
        try:
            lua = """
            local key = KEYS[1]
            local raw = redis.call('get', key)
            if not raw then return 0 end
            local ttl = redis.call('ttl', key)
            if ttl <= 0 then return 1 end
            local data = cjson.decode(raw)
            data['used'] = 1
            redis.call('setex', key, ttl, cjson.encode(data))
            return 1
            """
            result = r.eval(lua, 1, f"captcha:{token_id}")
            if result == 1:
                return
        except Exception:
            pass

    conn = get_db()
    try:
        conn.execute("UPDATE captcha_tokens SET used = 1 WHERE id = ?", (token_id,))
        conn.commit()
    except Exception as e:
        print("[WARN] mark_used failed:", e)


def log_attempt(token_id, ctype, success, detail, ip="", ua="", api_key=""):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO captcha_logs (token_id, type, success, detail, ip, user_agent, api_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (token_id, ctype, 1 if success else 0, detail, ip, ua, api_key, now())
        )
        conn.commit()
    except Exception as e:
        # 日志写入失败不阻断验证主流程
        print("[WARN] log_attempt failed:", e)


def consume_pass_jti(jti: str, ttl: int = 120) -> bool:
    """pass_token 一次性消费（原子）：返回 True 表示首次消费成功。

    Redis 模式用 SET NX EX；SQLite 用 INSERT OR IGNORE。
    """
    if not jti:
        return True
    r = get_redis()
    if r:
        try:
            key = f"pass:{jti}"
            if r.set(key, "1", nx=True, ex=ttl):
                return True
            return False
        except Exception:
            pass
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO captcha_passes (jti, created_at) VALUES (?, ?)",
            (jti, now()),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        print("[WARN] consume_pass_jti failed:", e)
        # 数据库异常时保守放行（不阻断业务），由签名与过期兜底
        return True


def cleanup_expired():
    t = now()
    conn = get_db()
    conn.execute("DELETE FROM captcha_tokens WHERE expires_at < ? OR used = 1", (t - 3600,))
    conn.execute("DELETE FROM captcha_logs WHERE created_at < ?", (t - 7 * 86400,))
    conn.execute("DELETE FROM captcha_passes WHERE created_at < ?", (t - 7 * 86400,))
    conn.commit()
