"""统计信息"""
from . import config
from .api_keys import list_api_keys
from .db import get_db
from .redis_client import get_redis
from .utils import now

def get_stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM captcha_logs").fetchone()[0]
    success = conn.execute("SELECT COUNT(*) FROM captcha_logs WHERE success = 1").fetchone()[0]
    slider = conn.execute("SELECT COUNT(*) FROM captcha_logs WHERE type = 'slider'").fetchone()[0]
    text = conn.execute("SELECT COUNT(*) FROM captcha_logs WHERE type = 'text'").fetchone()[0]
    click = conn.execute("SELECT COUNT(*) FROM captcha_logs WHERE type = 'click'").fetchone()[0]
    today = conn.execute(
        "SELECT COUNT(*) FROM captcha_logs WHERE created_at > ?", (now() - 86400,)
    ).fetchone()[0]
    recent = conn.execute(
        "SELECT * FROM captcha_logs ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    keys = list_api_keys()
    conn.close()
    return {
        "total": total,
        "success": success,
        "fail": total - success,
        "success_rate": round(success / total * 100, 1) if total else 0,
        "slider": slider,
        "text": text,
        "click": click,
        "today": today,
        "recent": [dict(r) for r in recent],
        "api_keys": keys,
        "rate_limit": {"generate_per_min": config.RATE_LIMIT_GENERATE, "window": config.RATE_LIMIT_WINDOW},
        "storage": "redis" if get_redis() else "sqlite",
    }

