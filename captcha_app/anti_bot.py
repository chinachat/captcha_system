"""抗自动化：轨迹/时序分析与失败锁定"""
import random
from collections import defaultdict

from . import config
from .utils import now

_fail_counter = defaultdict(int)
_fail_lock_until = {}


def _client_key(ip, api_key=""):
    return f"{ip}|{(api_key or '')[:16]}"


def _cleanup_expired():
    """清理已过期的锁定记录和计数器，防止内存无限增长。"""
    now_t = now()
    expired = [k for k, v in _fail_lock_until.items() if v < now_t]
    for k in expired:
        _fail_lock_until.pop(k, None)
        _fail_counter.pop(k, None)
    # 清理计数器为 0 且无锁定记录的孤立条目
    stale = [k for k, c in _fail_counter.items() if c == 0 and k not in _fail_lock_until]
    for k in stale:
        _fail_counter.pop(k, None)


def is_locked(ip, api_key="") -> tuple:
    """返回 (locked, remaining_seconds)"""
    now_t = now()
    # 概率触发全局过期清理（避免内存无限增长）
    if len(_fail_lock_until) > 500 and random.random() < 0.05:
        _cleanup_expired()

    k = _client_key(ip, api_key)
    until = _fail_lock_until.get(k, 0)
    if until > now_t:
        return True, int(until - now_t) + 1
    # 该 key 的锁定已过期，清理相关计数器
    if k in _fail_lock_until:
        _fail_lock_until.pop(k, None)
        _fail_counter.pop(k, None)
    return False, 0


def record_fail(ip, api_key=""):
    k = _client_key(ip, api_key)
    _fail_counter[k] += 1
    if _fail_counter[k] >= config.FAIL_LOCK_THRESHOLD:
        _fail_lock_until[k] = now() + config.FAIL_LOCK_SECONDS
        _fail_counter[k] = 0


def record_success(ip, api_key=""):
    k = _client_key(ip, api_key)
    _fail_counter[k] = 0
    _fail_lock_until.pop(k, None)


def analyze_slider_track(track, offset_x, duration_ms) -> tuple:
    """
    分析滑动轨迹是否像真人。
    track: [{"x": float, "t": float}, ...]  t 为相对毫秒
    返回 (ok: bool, reason: str)
    """
    if duration_ms is not None:
        try:
            duration_ms = float(duration_ms)
        except Exception:
            duration_ms = None
    if duration_ms is not None:
        if duration_ms < config.SLIDER_MIN_MS:
            return False, "slide_too_fast"
        if duration_ms > config.SLIDER_MAX_MS:
            return False, "slide_too_slow"

    if not track or not isinstance(track, list):
        # 无轨迹时：仅靠时间，若也没有时间则拒绝（强制前端上报）
        if duration_ms is None:
            return False, "missing_track"
        return True, "no_track_but_timing_ok"

    if len(track) < config.SLIDER_MIN_TRACK:
        return False, "track_too_short"

    xs, ts = [], []
    for p in track:
        try:
            xs.append(float(p.get("x", 0)))
            ts.append(float(p.get("t", 0)))
        except Exception:
            continue
    if len(xs) < config.SLIDER_MIN_TRACK:
        return False, "track_invalid"

    # 时间必须单调递增
    for i in range(1, len(ts)):
        if ts[i] + 1 < ts[i - 1]:
            return False, "time_not_monotonic"

    # 终点应接近提交的 offset
    if abs(xs[-1] - float(offset_x)) > 15:
        return False, "track_end_mismatch"

    # 线性度：拟合直线后的平均残差，完全直线像脚本
    n = len(xs)
    if n >= 6 and ts[-1] > ts[0]:
        t0, t1 = ts[0], ts[-1]
        x0, x1 = xs[0], xs[-1]
        if abs(t1 - t0) > 1e-6:
            residuals = []
            for i in range(n):
                ratio = (ts[i] - t0) / (t1 - t0)
                expected = x0 + ratio * (x1 - x0)
                residuals.append(abs(xs[i] - expected))
            avg_res = sum(residuals) / len(residuals)
            # 残差极小且采样点多 → 机器人匀速直线
            if avg_res < 0.35 and n >= 8 and duration_ms and duration_ms < 800:
                return False, "too_linear"

    # 速度突变检测：瞬间跳变过大
    for i in range(1, len(xs)):
        dt = max(ts[i] - ts[i - 1], 1)
        speed = abs(xs[i] - xs[i - 1]) / dt * 1000  # px/s
        if speed > 5000:  # 异常高速跳变
            return False, "speed_anomaly"

    return True, "ok"


def analyze_click_timing(timings, points) -> tuple:
    """
    timings: [t0, t1, ...] 相对毫秒，与 points 一一对应
    """
    if not timings or not isinstance(timings, list):
        return False, "missing_timing"
    if len(timings) != len(points):
        return False, "timing_count_mismatch"
    try:
        ts = [float(t) for t in timings]
    except Exception:
        return False, "timing_invalid"
    if ts[-1] < config.CLICK_MIN_TOTAL_MS:
        return False, "click_too_fast"
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] < config.CLICK_MIN_GAP_MS:
            return False, "click_gap_too_small"
        if ts[i] + 1 < ts[i - 1]:
            return False, "time_not_monotonic"
    return True, "ok"
