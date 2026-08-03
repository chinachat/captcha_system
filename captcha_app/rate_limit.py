"""IP 限流（Redis 或内存滑动窗口）"""
import threading
from collections import defaultdict, deque

from . import config
from .redis_client import get_redis
from .utils import now

_rate_memory = defaultdict(deque)
_rate_lock = threading.Lock()
_last_cleanup = [0.0]
_CLEANUP_INTERVAL = 60.0


def _sweep_memory():
    """定期清理已过期的限流条目，防止攻击者用随机 IP 撑爆内存。"""
    t = now()
    if t - _last_cleanup[0] < _CLEANUP_INTERVAL:
        return
    _last_cleanup[0] = t
    with _rate_lock:
        stale = [k for k, q in _rate_memory.items()
                 if q and q[0] < t - config.RATE_LIMIT_WINDOW - 10]
        for k in stale:
            del _rate_memory[k]


def check_rate_limit(ip: str, action: str = "generate") -> tuple:
    """返回 (allowed, remaining, reset_in)"""
    _sweep_memory()
    r = get_redis()
    key = f"rl:{action}:{ip}"
    limit = config.RATE_LIMIT_GENERATE
    window = config.RATE_LIMIT_WINDOW

    if r:
        try:
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            if count == 1 or ttl < 0:
                r.expire(key, window)
                ttl = window
            remaining = max(0, limit - count)
            if count > limit:
                return False, 0, max(ttl, 1)
            return True, remaining, max(ttl, 1)
        except Exception:
            pass

    with _rate_lock:
        q = _rate_memory[key]
        t = now()
        while q and q[0] < t - window:
            q.popleft()
        if len(q) >= limit:
            reset_in = int(q[0] + window - t) + 1
            return False, 0, max(reset_in, 1)
        q.append(t)
        remaining = limit - len(q)
        return True, remaining, window
