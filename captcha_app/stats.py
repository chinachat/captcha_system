"""统计信息"""
from . import config
from .api_keys import list_api_keys
from .db import get_db
from .redis_client import get_redis
from .utils import now


def get_stats():
    conn = get_db()
    t = now()
    total = conn.execute("SELECT COUNT(*) FROM captcha_logs").fetchone()[0]
    success = conn.execute("SELECT COUNT(*) FROM captcha_logs WHERE success = 1").fetchone()[0]
    slider = conn.execute("SELECT COUNT(*) FROM captcha_logs WHERE type = 'slider'").fetchone()[0]
    text = conn.execute("SELECT COUNT(*) FROM captcha_logs WHERE type = 'text'").fetchone()[0]
    click = conn.execute("SELECT COUNT(*) FROM captcha_logs WHERE type = 'click'").fetchone()[0]
    today = conn.execute(
        "SELECT COUNT(*) FROM captcha_logs WHERE created_at > ?", (t - 86400,)
    ).fetchone()[0]
    today_ok = conn.execute(
        "SELECT COUNT(*) FROM captcha_logs WHERE success = 1 AND created_at > ?", (t - 86400,)
    ).fetchone()[0]
    recent = conn.execute(
        "SELECT * FROM captcha_logs ORDER BY created_at DESC LIMIT 50"
    ).fetchall()

    # 近 24 小时按小时聚合
    hourly = []
    for i in range(23, -1, -1):
        start = t - (i + 1) * 3600
        end = t - i * 3600
        row = conn.execute(
            "SELECT COUNT(*) AS c, SUM(success) AS s FROM captcha_logs "
            "WHERE created_at >= ? AND created_at < ?",
            (start, end),
        ).fetchone()
        c = row["c"] or 0
        s = int(row["s"] or 0)
        hourly.append({
            "hour": int(end),
            "label": __import__("datetime").datetime.fromtimestamp(end).strftime("%H:00"),
            "total": c,
            "success": s,
            "fail": c - s,
        })

    # 近 7 天按天
    daily = []
    for i in range(6, -1, -1):
        start = t - (i + 1) * 86400
        end = t - i * 86400
        row = conn.execute(
            "SELECT COUNT(*) AS c, SUM(success) AS s FROM captcha_logs "
            "WHERE created_at >= ? AND created_at < ?",
            (start, end),
        ).fetchone()
        c = row["c"] or 0
        s = int(row["s"] or 0)
        daily.append({
            "day": int(end),
            "label": __import__("datetime").datetime.fromtimestamp(end).strftime("%m-%d"),
            "total": c,
            "success": s,
            "fail": c - s,
        })

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
        "today_success": today_ok,
        "today_rate": round(today_ok / today * 100, 1) if today else 0,
        "recent": [dict(r) for r in recent],
        "hourly": hourly,
        "daily": daily,
        "api_keys": keys,
        "rate_limit": {
            "generate_per_min": config.RATE_LIMIT_GENERATE,
            "window": config.RATE_LIMIT_WINDOW,
        },
        "storage": "redis" if get_redis() else "sqlite",
    }
