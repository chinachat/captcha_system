"""可选 Redis 连接"""
from . import config

_redis = None


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
        print("[INFO] Redis 已连接:", config.REDIS_URL)
        return _redis
    except Exception as e:
        print("[WARN] Redis 连接失败，回退到 SQLite/内存:", e)
        _redis = False
        return None
