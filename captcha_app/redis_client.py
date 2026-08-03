"""可选 Redis 连接"""
from urllib.parse import urlparse

from . import config

_redis = None


def _safe_redis_desc(url):
    """脱敏 Redis URL：不打印密码。"""
    try:
        p = urlparse(url)
        host = p.hostname or ""
        port = p.port or 6379
        db = (p.path or "/0").lstrip("/") or "0"
        return f"redis://{host}:{port}/{db}"
    except Exception:
        return "redis://<redacted>"


def get_redis():
    global _redis
    if _redis is not None:
        return _redis if _redis is not False else None
    if not config.REDIS_URL:
        return None
    try:
        import redis
        _redis = redis.from_url(config.REDIS_URL, decode_responses=True)
        _redis.ping()
        print("[INFO] Redis 已连接:", _safe_redis_desc(config.REDIS_URL))
        return _redis
    except Exception as e:
        print("[WARN] Redis 连接失败，回退到 SQLite/内存:", e)
        _redis = False
        return None
