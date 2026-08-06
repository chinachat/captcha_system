"""统计信息"""
from datetime import datetime

from . import config
from .api_keys import list_api_keys
from .db import backend, get_db
from .redis_client import get_redis
from .utils import now


def get_stats(owner=None):
    """owner 为 None 时返回全量统计；否则仅统计该用户的 Key。"""
    conn = get_db()
    t = now()

    # 按归属过滤条件（普通用户只统计自己的 Key）
    owner_cond = ""
    owner_args = []
    if owner:
        owner_cond = "WHERE l.api_key IN (SELECT key FROM api_keys WHERE owner = ?)"
        owner_args.append(owner)

    agg = conn.execute(f"""
        SELECT
            COUNT(*)                                           AS total,
            COALESCE(SUM(success), 0)                          AS success,
            COALESCE(SUM(CASE WHEN type='slider' THEN 1 END), 0) AS slider,
            COALESCE(SUM(CASE WHEN type='text'   THEN 1 END), 0) AS text,
            COALESCE(SUM(CASE WHEN type='click'  THEN 1 END), 0) AS click,
            COALESCE(SUM(CASE WHEN created_at > ? THEN 1 END), 0) AS today,
            COALESCE(SUM(CASE WHEN success = 1 AND created_at > ? THEN 1 END), 0) AS today_success
        FROM captcha_logs l
        {owner_cond}
    """, [t - 86400, t - 86400] + owner_args).fetchone()

    total = agg["total"]
    success = agg["success"]
    slider = agg["slider"]
    text = agg["text"]
    click = agg["click"]
    today = agg["today"]
    today_ok = agg["today_success"]

    recent = conn.execute(
        f"SELECT * FROM captcha_logs l {owner_cond} ORDER BY created_at DESC LIMIT 50",
        owner_args
    ).fetchall()

    # 近 24 小时按小时聚合（单次 GROUP BY 查询）
    hour_cutoff = t - 24 * 3600
    hour_rows = conn.execute(f"""
        SELECT CAST(created_at / 3600 AS INTEGER) AS bucket,
               COUNT(*) AS c, COALESCE(SUM(success), 0) AS s
        FROM captcha_logs l
        {owner_cond + ' AND' if owner_cond else 'WHERE'} created_at >= ?
        GROUP BY bucket ORDER BY bucket
    """, owner_args + [hour_cutoff]).fetchall()

    hour_map = {}
    for r in hour_rows:
        hour_map[r["bucket"]] = (r["c"], int(r["s"]))

    hourly = []
    base = int(t) // 3600
    for i in range(23, -1, -1):
        bucket = base - (23 - i)
        end_ts = (bucket + 1) * 3600
        c, s = hour_map.get(bucket, (0, 0))
        hourly.append({
            "hour": end_ts,
            "label": datetime.fromtimestamp(end_ts).strftime("%H:00"),
            "total": c,
            "success": s,
            "fail": c - s,
        })

    # 近 7 天按天（单次 GROUP BY 查询）
    day_cutoff = t - 7 * 86400
    day_rows = conn.execute(f"""
        SELECT CAST(created_at / 86400 AS INTEGER) AS bucket,
               COUNT(*) AS c, COALESCE(SUM(success), 0) AS s
        FROM captcha_logs l
        {owner_cond + ' AND' if owner_cond else 'WHERE'} created_at >= ?
        GROUP BY bucket ORDER BY bucket
    """, owner_args + [day_cutoff]).fetchall()

    day_map = {}
    for r in day_rows:
        day_map[r["bucket"]] = (r["c"], int(r["s"]))

    daily = []
    day_base = int(t) // 86400
    for i in range(6, -1, -1):
        bucket = day_base - (6 - i)
        end_ts = (bucket + 1) * 86400
        c, s = day_map.get(bucket, (0, 0))
        daily.append({
            "day": end_ts,
            "label": datetime.fromtimestamp(end_ts).strftime("%m-%d"),
            "total": c,
            "success": s,
            "fail": c - s,
        })

    # 按 API Key 聚合（累计；自 v2.3.0 起日志记录 api_key，旧数据无归属）
    if owner:
        key_rows = conn.execute("""
            SELECT l.api_key AS key,
                   COALESCE(k.name, '未命名') AS name,
                   COUNT(*) AS total,
                   COALESCE(SUM(l.success), 0) AS success,
                   COALESCE(SUM(CASE WHEN l.created_at > ? THEN 1 ELSE 0 END), 0) AS today,
                   COALESCE(MAX(l.created_at), 0) AS last_active
            FROM captcha_logs l
            LEFT JOIN api_keys k ON k.key = l.api_key
            WHERE l.api_key IS NOT NULL AND k.owner = ?
            GROUP BY l.api_key, k.name
            ORDER BY total DESC
        """, (t - 86400, owner)).fetchall()
    else:
        key_rows = conn.execute("""
            SELECT l.api_key AS key,
                   COALESCE(k.name, '未命名') AS name,
                   COUNT(*) AS total,
                   COALESCE(SUM(l.success), 0) AS success,
                   COALESCE(SUM(CASE WHEN l.created_at > ? THEN 1 ELSE 0 END), 0) AS today,
                   COALESCE(MAX(l.created_at), 0) AS last_active
            FROM captcha_logs l
            LEFT JOIN api_keys k ON k.key = l.api_key
            WHERE l.api_key IS NOT NULL
            GROUP BY l.api_key, k.name
            ORDER BY total DESC
        """, (t - 86400,)).fetchall()

    if owner:
        keys = [k for k in list_api_keys() if k.get("owner") == owner]
    else:
        keys = list_api_keys()
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
        "by_key": [dict(r) for r in key_rows],
        "api_keys": keys,
        "rate_limit": {
            "generate_per_min": config.RATE_LIMIT_GENERATE,
            "window": config.RATE_LIMIT_WINDOW,
        },
        "storage": "postgres" if backend() == "postgres" else ("redis" if get_redis() else "sqlite"),
    }
