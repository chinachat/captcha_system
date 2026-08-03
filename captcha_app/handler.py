"""HTTP 请求处理"""
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from . import config
from .anti_bot import (
    analyze_click_timing,
    analyze_slider_track,
    is_locked,
    login_locked,
    record_fail,
    record_login_fail,
    record_login_success,
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
    server_version = "CaptchaServer/2.1"
    timeout = config.REQUEST_TIMEOUT

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def _path(self):
        return urlparse(self.path).path.rstrip("/") or "/"

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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, msg, code=400):
        self._send(code, {"ok": False, "msg": msg})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        if length > config.MAX_BODY_BYTES:
            self._json_error("请求体过大", 413)
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _client_ip(self):
        """客户端真实 IP：仅当请求来自配置的可信代理时才信任 X-Forwarded-For，防止伪造绕过限流。"""
        peer = self.client_address[0]
        if config.TRUSTED_PROXIES:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded and self._peer_is_trusted(peer):
                return forwarded.split(",")[0].strip()
        return peer

    def _peer_is_trusted(self, peer):
        try:
            src = ipaddress.ip_address(peer)
        except ValueError:
            return False
        for item in config.TRUSTED_PROXIES.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                if "/" in item:
                    if src in ipaddress.ip_network(item, strict=False):
                        return True
                elif src == ipaddress.ip_address(item):
                    return True
            except ValueError:
                continue
        return False

    def _ua(self):
        return self.headers.get("User-Agent", "")[:200]

    def _get_api_key(self):
        auth = self.headers.get("Authorization", "")
        return self.headers.get("X-API-Key") or auth.replace("Bearer ", "")

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

    def _verify_token(self, token_id, ctype):
        row = get_token(token_id)
        if not row:
            self._json_error("验证码不存在或已失效", 400)
            return None
        if row.get("used"):
            self._json_error("验证码已使用", 400)
            return None
        if row.get("expires_at", 0) < now() and not get_redis():
            self._json_error("验证码已过期", 400)
            return None
        if row["type"] != ctype:
            self._json_error("验证码类型不匹配", 400)
            return None
        return row

    def _check_lock(self):
        ip = self._client_ip()
        key = self._get_api_key()
        locked, remain = is_locked(ip, key)
        if locked:
            self._send(429, {
                "ok": False,
                "msg": f"失败次数过多，请 {remain} 秒后再试",
                "retry_after": remain,
            }, headers={"Retry-After": str(remain)})
            return False
        return True

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        path = self._path()
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
                keys = list_api_keys()
                for k in keys:
                    k["connect"] = self._key_connect_info(k["key"])
                self._send(200, {"ok": True, "data": keys})
        elif path == "/api/v1/docs":
            self._serve_api_docs()
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        else:
            self._json_error("Not Found", 404)

    def do_POST(self):
        path = self._path()
        routes = {
            "/api/v1/captcha/slider/generate": self._api_slider_generate,
            "/api/v1/captcha/slider/verify": self._api_slider_verify,
            "/api/v1/captcha/text/generate": self._api_text_generate,
            "/api/v1/captcha/text/verify": self._api_text_verify,
            "/api/v1/captcha/click/generate": self._api_click_generate,
            "/api/v1/captcha/click/verify": self._api_click_verify,
            "/api/v1/captcha/test": self._api_captcha_test,
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
        path = self._path()
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
        path = self._path()
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

    def _check_rl(self):
        ip = self._client_ip()
        key = self._get_api_key()
        if not self._check_lock():
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
        except Exception as e:
            print("[ERROR] slider generate:", e)
            self._json_error("生成失败，请稍后重试", 500)
            return
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
                "puzzle_y": target_top,
                "pad": pad,
                "width": bg.width,
                "height": bg.height,
                "expires_in": config.CAPTCHA_EXPIRE_SECONDS,
            }
        })

    def _api_slider_verify(self):
        if not self._require_api_key():
            return
        ip = self._client_ip()
        api_key = self._get_api_key()
        if not self._check_lock():
            return

        body = self._read_json()
        if body is None:
            return
        token_id = body.get("token")
        offset_x = body.get("offset_x")
        track = body.get("track")
        duration_ms = body.get("duration_ms")
        if not token_id or offset_x is None:
            self._json_error("缺少 token 或 offset_x")
            return
        try:
            offset_x = float(offset_x)
        except Exception:
            self._json_error("offset_x 必须是数字")
            return

        row = self._verify_token(token_id, "slider")
        if row is None:
            return

        behavior_ok, reason = analyze_slider_track(track, offset_x, duration_ms)
        correct = float(row["secret"])
        pos_ok = abs(offset_x - correct) <= config.SLIDER_TOLERANCE
        success = bool(pos_ok and behavior_ok)

        mark_used(token_id)
        detail = f"offset={offset_x},correct={correct},pos={pos_ok},behavior={reason},dur={duration_ms}"
        log_attempt(token_id, "slider", success, detail, ip, self._ua(), api_key)

        if success:
            record_success(ip, api_key)
            pass_token = create_jwt({"captcha": "passed", "type": "slider", "jti": token_id},
                                    expires_seconds=config.PASS_TOKEN_EXPIRE_SECONDS,
                                    secret=config.PASS_TOKEN_SECRET)
            self._send(200, {"ok": True, "msg": "验证通过", "pass_token": pass_token})
        else:
            record_fail(ip, api_key)
            msg = "验证失败，请重试"
            if not behavior_ok and reason in ("slide_too_fast", "too_linear", "missing_track", "track_too_short"):
                msg = "操作异常，请重新完成滑动"
            self._send(200, {"ok": False, "msg": msg})

    def _api_captcha_test(self):
        """连接测试：校验 API Key 后，用服务端 PASS_TOKEN_SECRET 签发测试 pass_token。

        调用方（如 WordPress 插件）用自己配置的密钥反向验证该 token，
        即可确认两端密钥一致。需先升级服务端到 v2.2.0+。
        """
        if not self._require_api_key() or not self._check_rl():
            return
        try:
            test_token = create_jwt(
                {"captcha": "passed", "type": "test", "jti": f"test-{uuid.uuid4()}"},
                expires_seconds=60,
                secret=config.PASS_TOKEN_SECRET,
            )
        except Exception as e:
            print("[ERROR] captcha test:", e)
            self._json_error("测试令牌生成失败", 500)
            return
        self._send(200, {"ok": True, "data": {
            "pass_token": test_token,
            # 服务端是否显式配置了 PASS_TOKEN_SECRET（否则回退 SECRET_KEY）
            "server_secret_explicit": bool(os.environ.get("PASS_TOKEN_SECRET", "")),
            "ts": now(),
        }})

    def _api_text_generate(self):
        if not self._require_api_key() or not self._check_rl():
            return
        try:
            img, code = generate_text_captcha()
        except Exception as e:
            print("[ERROR] text generate:", e)
            self._json_error("生成失败，请稍后重试", 500)
            return
        token = create_token("text", code.upper(), ip=self._client_ip(), ua=self._ua())
        self._send(200, {
            "ok": True,
            "data": {
                "token": token,
                "image": b64_image(img),
                "expires_in": config.CAPTCHA_EXPIRE_SECONDS,
            }
        })

    def _api_text_verify(self):
        if not self._require_api_key():
            return
        api_key = self._get_api_key()
        body = self._read_json()
        if body is None:
            return
        token_id = body.get("token")
        code = (body.get("code") or "").strip().upper()
        if not token_id or not code:
            self._json_error("缺少 token 或 code")
            return
        row = self._verify_token(token_id, "text")
        if row is None:
            return
        success = hmac.compare_digest(row["secret"].upper(), code)
        mark_used(token_id)
        log_attempt(token_id, "text", success, f"input={code}", self._client_ip(), self._ua(), api_key)
        if success:
            pass_token = create_jwt({"captcha": "passed", "type": "text", "jti": token_id},
                                    expires_seconds=config.PASS_TOKEN_EXPIRE_SECONDS,
                                    secret=config.PASS_TOKEN_SECRET)
            self._send(200, {"ok": True, "msg": "验证通过", "pass_token": pass_token})
        else:
            self._send(200, {"ok": False, "msg": "验证码错误"})

    def _api_click_generate(self):
        if not self._require_api_key() or not self._check_rl():
            return
        try:
            img, targets = generate_click_captcha()
        except Exception as e:
            print("[ERROR] click generate:", e)
            self._json_error("生成失败，请稍后重试", 500)
            return
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

    def _api_click_verify(self):
        if not self._require_api_key():
            return
        ip = self._client_ip()
        api_key = self._get_api_key()
        if not self._check_lock():
            return

        body = self._read_json()
        if body is None:
            return
        token_id = body.get("token")
        points = body.get("points")
        timings = body.get("timings")
        if not token_id or not isinstance(points, list):
            self._json_error("缺少 token 或 points")
            return

        row = self._verify_token(token_id, "click")
        if row is None:
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
                        ip, self._ua(), api_key)
            self._send(200, {"ok": False, "msg": "点击数量不正确"})
            return

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
                    ip, self._ua(), api_key)

        if success:
            record_success(ip, api_key)
            pass_token = create_jwt({"captcha": "passed", "type": "click", "jti": token_id},
                                    expires_seconds=config.PASS_TOKEN_EXPIRE_SECONDS,
                                    secret=config.PASS_TOKEN_SECRET)
            self._send(200, {"ok": True, "msg": "验证通过", "pass_token": pass_token})
        else:
            record_fail(ip, api_key)
            msg = "点击位置不正确，请重试"
            if not timing_ok:
                msg = "操作过快，请重新点选"
            self._send(200, {"ok": False, "msg": msg})

    def _api_admin_login(self):
        body = self._read_json()
        if body is None:
            return
        ip = self._client_ip()
        locked, remain = login_locked(ip)
        if locked:
            self._send(429, {
                "ok": False,
                "msg": f"失败次数过多，请 {remain} 秒后再试",
                "retry_after": remain,
            }, headers={"Retry-After": str(remain)})
            return
        user_ok = hmac.compare_digest(
            str(body.get("username") or "").encode("utf-8"),
            config.ADMIN_USER.encode("utf-8"))
        pass_ok = hmac.compare_digest(
            str(body.get("password") or "").encode("utf-8"),
            config.ADMIN_PASS.encode("utf-8"))
        if user_ok and pass_ok:
            record_login_success(ip)
            token = create_jwt({"role": "admin", "user": config.ADMIN_USER})
            cookie = f"admin_token={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={config.JWT_EXPIRE_HOURS*3600}"
            if self.headers.get("X-Forwarded-Proto", "").lower() == "https":
                cookie += "; Secure"
            self._send(200, {"ok": True, "token": token, "msg": "登录成功"},
                       headers={"Set-Cookie": cookie})
        else:
            record_login_fail(ip)
            self._json_error("用户名或密码错误", 401)

    def _request_base_url(self):
        """根据请求推导插件可填写的 API 服务地址（尊重反向代理的 X-Forwarded-Proto）。"""
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",")[0].strip() or "http"
        host = self.headers.get("Host", "").strip()
        if not host:
            host = f"{self.client_address[0]}:{getattr(self.server, 'server_port', 8080)}"
        return f"{proto}://{host}"

    def _key_connect_info(self, key):
        """插件连接配置（仅管理员接口返回；含签名密钥，前端需提示妥善保管）。"""
        return {
            "base_url": self._request_base_url(),
            "api_key": key,
            "pass_token_secret": config.PASS_TOKEN_SECRET,
        }

    def _api_create_key(self):
        if not self._require_admin():
            return
        body = self._read_json()
        if body is None:
            return
        name = (body.get("name") or "新 Key").strip()[:64]
        note = (body.get("note") or "").strip()[:200]
        owner = (body.get("owner") or "admin").strip()[:64]
        key = create_api_key(name, note, owner)
        self._send(200, {"ok": True, "data": {
            "key": key, "name": name, "note": note, "owner": owner,
            "connect": self._key_connect_info(key),
        }})

    def _serve_template(self, filename, replace_key=False):
        path = os.path.join(config.TEMPLATE_DIR, filename)
        if not os.path.exists(path):
            self._send(200, f"<h1>{filename} missing</h1>", "text/html")
            return
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if replace_key:
            content = content.replace("{{API_KEY}}", config.DEFAULT_API_KEY)
        self._send(200, content, "text/html; charset=utf-8")

    def _serve_guide(self):
        self._serve_template("guide.html")

    def _serve_call_docs(self):
        self._serve_template("api-docs.html", replace_key=True)

    def _serve_demo(self):
        self._serve_template("demo.html", replace_key=True)

    def _serve_admin_page(self):
        self._serve_template("admin.html")

    def _serve_static(self, rel):
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
                {"method": "POST", "path": "/api/v1/captcha/test", "desc": "连接测试：校验 API Key 并返回测试 pass_token（v2.2.0+）"},
                {"method": "POST", "path": "/api/v1/admin/login", "body": {"username": "<admin>", "password": "<your-password>"}},
                {"method": "GET", "path": "/api/v1/stats", "desc": "统计（需管理员）"},
                {"method": "GET", "path": "/api/v1/admin/keys", "desc": "列出 API Key"},
                {"method": "POST", "path": "/api/v1/admin/keys", "body": {"name": "业务名", "note": "备注"}},
                {"method": "PUT", "path": "/api/v1/admin/keys/{key}/enable|disable"},
                {"method": "DELETE", "path": "/api/v1/admin/keys/{key}"},
            ],
        })
