"""HTTP 请求处理"""
import hmac
import json
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from . import config
import mimetypes
from .anti_bot import (
    analyze_click_timing,
    analyze_slider_track,
    is_locked,
    record_fail,
    record_success,
)
from .api_keys import (
    check_api_key,
    create_api_key,
    delete_api_key,
    list_api_keys,
    set_api_key_enabled,
)
from .captcha_gen import generate_click_captcha, generate_slider_captcha, generate_text_captcha
from .rate_limit import check_rate_limit
from .redis_client import get_redis
from .stats import get_stats
from .tokens import create_token, get_token, log_attempt, mark_used
from .utils import b64_image, create_jwt, decode_jwt, now


class CaptchaHandler(BaseHTTPRequestHandler):
    server_version = "CaptchaServer/2.0"

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def _send(self, code=200, body=None, content_type="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        elif body is None:
            body = b""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, msg, code=400):
        self._send(code, {"ok": False, "msg": msg})

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _client_ip(self):
        """获取客户端真实 IP。
        优先使用 X-Forwarded-For（反向代理场景），但仅在配置了 TRUSTED_PROXIES 时信任该头，
        防止客户端伪造 IP 绕过限流和失败锁定。
        """
        if config.TRUSTED_PROXIES:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def _ua(self):
        return self.headers.get("User-Agent", "")[:200]

    def _get_api_key(self):
        return self.headers.get("X-API-Key") or self.headers.get("Authorization", "").replace("Bearer ", "")

    def _require_api_key(self):
        key = self._get_api_key()
        if not check_api_key(key):
            self._json_error("无效或缺失 API Key（请在 Header 中携带 X-API-Key）", 401)
            return False
        return True

    def _require_admin(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            data = decode_jwt(auth[7:])
            if data and data.get("role") == "admin":
                return True
        cookie = self.headers.get("Cookie", "")
        m = re.search(r"admin_token=([^;]+)", cookie)
        if m:
            data = decode_jwt(m.group(1))
            if data and data.get("role") == "admin":
                return True
        self._json_error("未登录或登录已过期", 401)
        return False

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/", "/demo"):
            self._serve_demo()
        elif path in ("/admin", "/admin/"):
            self._serve_admin_page()
        elif path in ("/docs", "/api-docs"):
            self._serve_call_docs()
        elif path in ("/guide", "/readme"):
            self._serve_guide()
        elif path == "/api/v1/health":
            self._send(200, {
                "ok": True,
                "ts": now(),
                "storage": "redis" if get_redis() else "sqlite",
                "rate_limit": config.RATE_LIMIT_GENERATE,
            })
        elif path == "/api/v1/stats":
            if self._require_admin():
                self._send(200, {"ok": True, "data": get_stats()})
        elif path == "/api/v1/admin/keys":
            if self._require_admin():
                self._send(200, {"ok": True, "data": list_api_keys()})
        elif path == "/api/v1/docs":
            self._serve_api_docs()
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        else:
            self._json_error("Not Found", 404)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        routes = {
            "/api/v1/captcha/slider/generate": self._api_slider_generate,
            "/api/v1/captcha/slider/verify": self._api_slider_verify,
            "/api/v1/captcha/text/generate": self._api_text_generate,
            "/api/v1/captcha/text/verify": self._api_text_verify,
            "/api/v1/captcha/click/generate": self._api_click_generate,
            "/api/v1/captcha/click/verify": self._api_click_verify,
            "/api/v1/admin/login": self._api_admin_login,
            "/api/v1/admin/logout": lambda: self._send(200, {"ok": True}),
            "/api/v1/admin/keys": self._api_create_key,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._json_error("Not Found", 404)

    def do_PUT(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        # /api/v1/admin/keys/{key}/enable  or disable
        m = re.match(r"^/api/v1/admin/keys/([^/]+)/(enable|disable)$", path)
        if m:
            if not self._require_admin():
                return
            key, action = m.group(1), m.group(2)
            ok = set_api_key_enabled(key, action == "enable")
            self._send(200, {"ok": ok, "msg": "已更新" if ok else "Key 不存在"})
            return
        self._json_error("Not Found", 404)

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        m = re.match(r"^/api/v1/admin/keys/([^/]+)$", path)
        if m:
            if not self._require_admin():
                return
            key = m.group(1)
            if key == config.DEFAULT_API_KEY:
                self._json_error("不能删除默认 Key", 400)
                return
            ok = delete_api_key(key)
            self._send(200, {"ok": ok, "msg": "已删除" if ok else "Key 不存在"})
            return
        self._json_error("Not Found", 404)

    # ---------- 生成（带限流） ----------
    def _check_rl(self):
        ip = self._client_ip()
        api_key = self._get_api_key()
        locked, remain = is_locked(ip, api_key)
        if locked:
            self._send(429, {
                "ok": False,
                "msg": f"失败次数过多，请 {remain} 秒后再试",
                "retry_after": remain,
            }, headers={"Retry-After": str(remain)})
            return False
        allowed, remaining, reset_in = check_rate_limit(ip, "generate")
        if not allowed:
            self._send(429, {
                "ok": False,
                "msg": f"请求过于频繁，请 {reset_in} 秒后再试",
                "retry_after": reset_in,
            }, headers={"Retry-After": str(reset_in)})
            return False
        return True

    def _api_slider_generate(self):
        if not self._require_api_key() or not self._check_rl():
            return
        try:
            bg, piece, puzzle_x, puzzle_y = generate_slider_captcha()
            # 拼图块画布比缺口大一圈 pad=8，滑块 left / top 需对齐「块的左上角」
            # 对齐时：piece_left = puzzle_x - pad，piece_top = puzzle_y - pad
            pad = 8
            target_left = puzzle_x - pad
            target_top = puzzle_y - pad
            token = create_token(
                "slider", str(target_left),
                extra={"y": target_top, "pad": pad, "width": bg.width, "height": bg.height},
                ip=self._client_ip(), ua=self._ua()
            )
            self._send(200, {
                "ok": True,
                "data": {
                    "token": token,
                    "background": b64_image(bg),
                    "puzzle": b64_image(piece),
                    "puzzle_y": target_top,   # 前端直接用作 piece.style.top（原图像素）
                    "pad": pad,
                    "width": bg.width,
                    "height": bg.height,
                    "expires_in": config.CAPTCHA_EXPIRE_SECONDS,
                }
            })
        except Exception as e:
            self._json_error(f"生成失败: {e}", 500)

    def _api_slider_verify(self):
        if not self._require_api_key():
            return
        ip = self._client_ip()
        api_key = self._get_api_key()
        locked, remain = is_locked(ip, api_key)
        if locked:
            self._send(429, {"ok": False, "msg": f"失败次数过多，请 {remain} 秒后再试", "retry_after": remain})
            return

        body = self._read_json()
        token_id = body.get("token")
        offset_x = body.get("offset_x")
        track = body.get("track")          # [{x,t}, ...]
        duration_ms = body.get("duration_ms")
        if not token_id or offset_x is None:
            self._json_error("缺少 token 或 offset_x")
            return
        try:
            offset_x = float(offset_x)
        except Exception:
            self._json_error("offset_x 必须是数字")
            return

        row = get_token(token_id)
        if not row:
            self._json_error("验证码不存在或已失效", 400)
            return
        if row.get("used"):
            self._json_error("验证码已使用", 400)
            return
        if row.get("expires_at", 0) < now() and not get_redis():
            self._json_error("验证码已过期", 400)
            return
        if row["type"] != "slider":
            self._json_error("验证码类型不匹配", 400)
            return

        # 行为分析
        behavior_ok, reason = analyze_slider_track(track, offset_x, duration_ms)
        correct = float(row["secret"])
        pos_ok = abs(offset_x - correct) <= config.SLIDER_TOLERANCE
        success = bool(pos_ok and behavior_ok)

        mark_used(token_id)
        detail = f"offset={offset_x},correct={correct},pos={pos_ok},behavior={reason},dur={duration_ms}"
        log_attempt(token_id, "slider", success, detail, ip, self._ua())

        if success:
            record_success(ip, api_key)
            pass_token = create_jwt({"captcha": "passed", "type": "slider", "jti": token_id})
            self._send(200, {"ok": True, "msg": "验证通过", "pass_token": pass_token})
        else:
            record_fail(ip, api_key)
            msg = "验证失败，请重试"
            if not behavior_ok and reason in ("slide_too_fast", "too_linear", "missing_track", "track_too_short"):
                msg = "操作异常，请重新完成滑动"
            self._send(200, {"ok": False, "msg": msg})


    def _api_text_generate(self):
        """兼容旧接口：仍返回文字图+code，新业务请用 /click/"""
        if not self._require_api_key() or not self._check_rl():
            return
        try:
            img, code = generate_text_captcha()
            token = create_token("text", code.upper(), ip=self._client_ip(), ua=self._ua())
            self._send(200, {
                "ok": True,
                "data": {
                    "token": token,
                    "image": b64_image(img),
                    "expires_in": config.CAPTCHA_EXPIRE_SECONDS,
                }
            })
        except Exception as e:
            self._json_error(f"生成失败: {e}", 500)

    def _api_text_verify(self):
        if not self._require_api_key():
            return
        body = self._read_json()
        token_id = body.get("token")
        code = (body.get("code") or "").strip().upper()
        if not token_id or not code:
            self._json_error("缺少 token 或 code")
            return
        row = get_token(token_id)
        if not row:
            self._json_error("验证码不存在或已失效", 400)
            return
        if row.get("used"):
            self._json_error("验证码已使用", 400)
            return
        if row.get("expires_at", 0) < now() and not get_redis():
            self._json_error("验证码已过期", 400)
            return
        if row["type"] != "text":
            self._json_error("验证码类型不匹配", 400)
            return
        success = hmac.compare_digest(row["secret"].upper(), code)
        mark_used(token_id)
        log_attempt(token_id, "text", success, f"input={code}", self._client_ip(), self._ua())
        if success:
            pass_token = create_jwt({"captcha": "passed", "type": "text", "jti": token_id})
            self._send(200, {"ok": True, "msg": "验证通过", "pass_token": pass_token})
        else:
            self._send(200, {"ok": False, "msg": "验证码错误"})

    def _api_click_generate(self):
        if not self._require_api_key() or not self._check_rl():
            return
        try:
            img, targets = generate_click_captcha()
            # secret 存目标列表 JSON
            secret = json.dumps(targets, ensure_ascii=False)
            token = create_token(
                "click", secret,
                extra={"width": img.width, "height": img.height},
                ip=self._client_ip(), ua=self._ua()
            )
            prompt = "请依次点击：" + " → ".join(t["char"] for t in targets)
            self._send(200, {
                "ok": True,
                "data": {
                    "token": token,
                    "image": b64_image(img),
                    "prompt": prompt,
                    "chars": [t["char"] for t in targets],
                    "count": len(targets),
                    "width": img.width,
                    "height": img.height,
                    "expires_in": config.CAPTCHA_EXPIRE_SECONDS,
                }
            })
        except Exception as e:
            self._json_error(f"生成失败: {e}", 500)

    def _api_click_verify(self):
        if not self._require_api_key():
            return
        ip = self._client_ip()
        api_key = self._get_api_key()
        locked, remain = is_locked(ip, api_key)
        if locked:
            self._send(429, {"ok": False, "msg": f"失败次数过多，请 {remain} 秒后再试", "retry_after": remain})
            return

        body = self._read_json()
        token_id = body.get("token")
        points = body.get("points")
        timings = body.get("timings")  # 各次点击相对毫秒
        if not token_id or not isinstance(points, list):
            self._json_error("缺少 token 或 points")
            return

        row = get_token(token_id)
        if not row:
            self._json_error("验证码不存在或已失效", 400)
            return
        if row.get("used"):
            self._json_error("验证码已使用", 400)
            return
        if row.get("expires_at", 0) < now() and not get_redis():
            self._json_error("验证码已过期", 400)
            return
        if row["type"] != "click":
            self._json_error("验证码类型不匹配", 400)
            return

        try:
            targets = json.loads(row["secret"])
        except Exception:
            self._json_error("验证码数据损坏", 500)
            return

        if len(points) != len(targets):
            mark_used(token_id)
            record_fail(ip, api_key)
            log_attempt(token_id, "click", False,
                        f"count_mismatch points={len(points)} need={len(targets)}",
                        ip, self._ua())
            self._send(200, {"ok": False, "msg": "点击数量不正确"})
            return

        # 时序分析
        timing_ok, timing_reason = analyze_click_timing(timings, points)

        tol = 28
        pos_ok = True
        details = []
        for i, (pt, tg) in enumerate(zip(points, targets)):
            try:
                px = float(pt.get("x", -999))
                py = float(pt.get("y", -999))
            except Exception:
                pos_ok = False
                details.append(f"p{i}=invalid")
                break
            dist = ((px - tg["x"]) ** 2 + (py - tg["y"]) ** 2) ** 0.5
            details.append(f"p{i}={dist:.1f}")
            if dist > tol:
                pos_ok = False

        success = bool(pos_ok and timing_ok)
        mark_used(token_id)
        log_attempt(token_id, "click", success,
                    f"{';'.join(details)};timing={timing_reason}",
                    ip, self._ua())

        if success:
            record_success(ip, api_key)
            pass_token = create_jwt({"captcha": "passed", "type": "click", "jti": token_id})
            self._send(200, {"ok": True, "msg": "验证通过", "pass_token": pass_token})
        else:
            record_fail(ip, api_key)
            msg = "点击位置不正确，请重试"
            if not timing_ok:
                msg = "操作过快，请重新点选"
            self._send(200, {"ok": False, "msg": msg})


    def _api_admin_login(self):
        body = self._read_json()
        if body.get("username") == config.ADMIN_USER and body.get("password") == config.ADMIN_PASS:
            token = create_jwt({"role": "admin", "user": config.ADMIN_USER})
            self._send(200, {"ok": True, "token": token, "msg": "登录成功"},
                       headers={"Set-Cookie": f"admin_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={config.JWT_EXPIRE_HOURS*3600}"})
        else:
            self._json_error("用户名或密码错误", 401)

    def _api_create_key(self):
        if not self._require_admin():
            return
        body = self._read_json()
        name = (body.get("name") or "新 Key").strip()[:64]
        note = (body.get("note") or "").strip()[:200]
        key = create_api_key(name, note)
        self._send(200, {"ok": True, "data": {"key": key, "name": name, "note": note}})



    def _serve_guide(self):
        path = os.path.join(config.TEMPLATE_DIR, "guide.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self._send(200, content, "text/html; charset=utf-8")
        else:
            self._send(200, "<h1>guide.html missing</h1>", "text/html")

    def _serve_call_docs(self):
        path = os.path.join(config.TEMPLATE_DIR, "api-docs.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().replace("{{API_KEY}}", config.DEFAULT_API_KEY)
            self._send(200, content, "text/html; charset=utf-8")
        else:
            self._send(200, "<h1>api-docs.html missing</h1>", "text/html")

    def _serve_demo(self):
        path = os.path.join(config.TEMPLATE_DIR, "demo.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().replace("{{API_KEY}}", config.DEFAULT_API_KEY)
            self._send(200, content, "text/html; charset=utf-8")
        else:
            self._send(200, "<h1>demo.html missing</h1>", "text/html")

    def _serve_admin_page(self):
        path = os.path.join(config.TEMPLATE_DIR, "admin.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        else:
            self._send(200, "<h1>admin.html missing</h1>", "text/html")


    def _serve_static(self, rel):
        # 防止路径穿越
        rel = rel.replace("\\", "/").lstrip("/")
        if ".." in rel.split("/"):
            self._json_error("Forbidden", 403)
            return
        root = os.path.join(os.path.dirname(config.TEMPLATE_DIR), "static")
        fpath = os.path.normpath(os.path.join(root, rel))
        if not fpath.startswith(os.path.normpath(root)):
            self._json_error("Forbidden", 403)
            return
        if not os.path.isfile(fpath):
            self._json_error("Not Found", 404)
            return
        ctype, _ = mimetypes.guess_type(fpath)
        if not ctype:
            ctype = "application/octet-stream"
        if fpath.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        with open(fpath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def _serve_api_docs(self):
        self._send(200, {
            "title": "动态验证码 API 文档 v2",
            "auth": "Header: X-API-Key: <key>",
            "rate_limit": f"生成接口每 IP 每分钟最多 {config.RATE_LIMIT_GENERATE} 次",
            "storage": "redis" if get_redis() else "sqlite",
            "endpoints": [
                {"method": "POST", "path": "/api/v1/captcha/slider/generate", "desc": "生成滑动验证码"},
                {"method": "POST", "path": "/api/v1/captcha/slider/verify", "body": {"token": "", "offset_x": 0}},
                {"method": "POST", "path": "/api/v1/captcha/click/generate", "desc": "生成点选验证码"},
                {"method": "POST", "path": "/api/v1/captcha/click/verify", "body": {"token": "", "points": [{"x":0,"y":0}]}},
                {"method": "POST", "path": "/api/v1/admin/login", "body": {"username": "admin", "password": "<your-password>"}},
                {"method": "GET", "path": "/api/v1/stats", "desc": "统计（需管理员）"},
                {"method": "GET", "path": "/api/v1/admin/keys", "desc": "列出 API Key"},
                {"method": "POST", "path": "/api/v1/admin/keys", "body": {"name": "业务名", "note": "备注"}},
                {"method": "PUT", "path": "/api/v1/admin/keys/{key}/enable|disable"},
                {"method": "DELETE", "path": "/api/v1/admin/keys/{key}"},
            ],
            "default_api_key": config.DEFAULT_API_KEY,
            "admin": {"username": config.ADMIN_USER, "note": "生产环境请务必修改默认密码"},
        })
