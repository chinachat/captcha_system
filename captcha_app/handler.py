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
from . import settings
from . import totp
from . import twofa
from . import users
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
    get_demo_key,
    list_api_keys,
    set_api_key_enabled,
    update_api_key,
)
from .captcha_gen import generate_click_captcha, generate_slider_captcha, generate_text_captcha
from .db import get_db
from .rate_limit import check_rate_limit
from .redis_client import get_redis
from .stats import get_stats
from .tokens import consume_pass_jti, create_token, get_token, log_attempt, mark_used
from .users import (
    authenticate_user,
    count_keys,
    create_group,
    create_user,
    delete_group,
    delete_user,
    ensure_default_group,
    key_quota_for,
    list_groups,
    list_users,
    update_group,
    update_user,
)
from .utils import b64_image, create_jwt, decode_jwt, now

# 模板内容缓存：path -> (mtime, content)，开发时改模板即失效
_TEMPLATE_CACHE = {}


class CaptchaHandler(BaseHTTPRequestHandler):
    server_version = "CaptchaServer/2.1"
    timeout = config.REQUEST_TIMEOUT
    # HTTP/1.1 keep-alive：复用连接，减少握手与线程创建开销（空闲由 timeout 兜底断开）
    protocol_version = "HTTP/1.1"
    # 单连接最大请求数：防长连接长期占满并发槽位
    _MAX_REQUESTS_PER_CONN = 100

    def handle_one_request(self):
        self._req_count = getattr(self, "_req_count", 0) + 1
        if self._req_count > self._MAX_REQUESTS_PER_CONN:
            self.close_connection = True
        super().handle_one_request()

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

    def _internal_error(self, e):
        """handler 未捕获异常的统一兜底：记录并返回 500 JSON，避免连接无响应断开。"""
        print(f"[ERROR] {type(e).__name__}: {e}")
        try:
            self._send(500, {"ok": False, "msg": "服务器内部错误，请稍后重试"})
        except Exception:
            pass

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

    def _storage_label(self):
        """存储标识：postgres / redis / sqlite。"""
        from .db import backend
        if backend() == "postgres":
            return "postgres"
        return "redis" if get_redis() else "sqlite"

    def _require_api_key(self):
        key = self._get_api_key()
        if not check_api_key(key):
            self._json_error("无效或缺失 API Key（请在 Header 中携带 X-API-Key）", 401)
            return False
        return True

    def _require_admin(self):
        data = self._auth_data()
        if data and data.get("role") == "admin":
            return True
        self._json_error("需要管理员权限", 401)
        return False

    def _require_auth(self):
        """任意已登录用户（管理员或普通用户）。"""
        data = self._auth_data()
        if data:
            return data
        self._json_error("未登录或登录已过期", 401)
        return None

    def _auth_data(self):
        """解析当前登录用户（JWT 或 Cookie），返回 payload 或 None。"""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            data = decode_jwt(auth[7:])
            if data:
                return data
        cookie = self.headers.get("Cookie", "")
        m = re.search(r"admin_token=([^;]+)", cookie)
        if m:
            return decode_jwt(m.group(1))
        return None

    def _current_user(self):
        """当前登录用户名（默认 admin）。"""
        data = self._auth_data()
        return data.get("user", config.ADMIN_USER) if data else config.ADMIN_USER

    def _is_admin_request(self):
        data = self._auth_data()
        return bool(data and data.get("role") == "admin")

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
        try:
            self._handle_get()
        except Exception as e:
            self._internal_error(e)

    def _handle_get(self):
        path = self._path()
        if path == "/":
            self._serve_landing()
        elif path == "/demo":
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
                "storage": self._storage_label(),
                "rate_limit": config.RATE_LIMIT_GENERATE,
            })
        elif path == "/api/v1/stats":
            auth = self._require_auth()
            if auth:
                owner = None if auth.get("role") == "admin" else auth.get("user")
                data = get_stats(owner=owner)
                # 页面 Key 卡片数据源是 stats，需同步附加插件连接配置
                for k in data.get("api_keys", []):
                    k["connect"] = self._key_connect_info(k["key"], include_secret=auth.get("role") == "admin")
                # 当前登录账号的二次验证状态（安全设置卡片数据源）
                data["twofa_enabled"] = twofa.is_enabled(auth.get("user", config.ADMIN_USER))
                self._send(200, {"ok": True, "data": data})
        elif path == "/api/v1/admin/keys":
            if self._require_auth():
                keys = list_api_keys()
                if not self._is_admin_request():
                    # 普通用户仅可见自己的 Key
                    me = self._current_user()
                    keys = [k for k in keys if k.get("owner") == me]
                for k in keys:
                    k["connect"] = self._key_connect_info(k["key"], include_secret=self._is_admin_request())
                self._send(200, {"ok": True, "data": keys})
        elif path == "/api/v1/admin/users":
            if self._require_admin():
                self._send(200, {"ok": True, "data": list_users()})
        elif path == "/api/v1/admin/groups":
            if self._require_admin():
                self._send(200, {"ok": True, "data": list_groups()})
        elif path == "/api/v1/admin/settings":
            if self._require_admin():
                self._send(200, {"ok": True, "data": {
                    "registration_enabled": settings.get_bool_setting("registration_enabled", False),
                }})
        elif path == "/api/v1/docs":
            self._serve_api_docs()
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        else:
            self._json_error("Not Found", 404)

    def do_POST(self):
        try:
            self._handle_post()
        except Exception as e:
            self._internal_error(e)

    def _handle_post(self):
        path = self._path()
        routes = {
            "/api/v1/register": self._api_register,
            "/api/v1/captcha/slider/generate": self._api_slider_generate,
            "/api/v1/captcha/slider/verify": self._api_slider_verify,
            "/api/v1/captcha/text/generate": self._api_text_generate,
            "/api/v1/captcha/text/verify": self._api_text_verify,
            "/api/v1/captcha/click/generate": self._api_click_generate,
            "/api/v1/captcha/click/verify": self._api_click_verify,
            "/api/v1/captcha/test": self._api_captcha_test,
            "/api/v1/captcha/validate": self._api_captcha_validate,
            "/api/v1/admin/login": self._api_admin_login,
            "/api/v1/admin/login/2fa": self._api_login_2fa,
            "/api/v1/admin/2fa/setup": self._api_2fa_setup,
            "/api/v1/admin/2fa/confirm": self._api_2fa_confirm,
            "/api/v1/admin/logout": lambda: self._send(200, {"ok": True}),
            "/api/v1/admin/captcha/generate": self._api_login_captcha_generate,
            "/api/v1/admin/keys": self._api_create_key,
            "/api/v1/admin/users": self._api_create_user,
            "/api/v1/admin/groups": self._api_create_group,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._json_error("Not Found", 404)

    def _can_manage_key(self, key_value):
        """当前用户是否有权管理该 Key（管理员任意；普通用户仅自己的）。"""
        me = self._current_user()
        if self._is_admin_request():
            return True
        conn_owner = get_db()
        row = conn_owner.execute("SELECT owner FROM api_keys WHERE key = ?", (key_value,)).fetchone()
        return bool(row and row["owner"] == me)

    def do_PUT(self):
        try:
            self._handle_put()
        except Exception as e:
            self._internal_error(e)

    def _handle_put(self):
        path = self._path()
        # 系统设置（管理员）
        if path == "/api/v1/admin/settings":
            if not self._require_admin():
                return
            body = self._read_json()
            if body is None:
                return
            settings.set_setting("registration_enabled",
                                 "1" if body.get("registration_enabled") else "0")
            self._send(200, {"ok": True, "msg": "已更新"})
            return
        m = re.match(r"^/api/v1/admin/keys/([^/]+)/(enable|disable)$", path)
        if m:
            if not self._require_auth():
                return
            key, action = m.group(1), m.group(2)
            if not self._can_manage_key(key):
                self._json_error("无权操作该 Key", 403)
                return
            ok = set_api_key_enabled(key, action == "enable")
            self._send(200, {"ok": ok, "msg": "已更新" if ok else "Key 不存在"})
            return
        # 编辑 Key（名称/备注）
        m = re.match(r"^/api/v1/admin/keys/([^/]+)$", path)
        if m:
            if not self._require_auth():
                return
            key = m.group(1)
            if not self._can_manage_key(key):
                self._json_error("无权操作该 Key", 403)
                return
            body = self._read_json()
            if body is None:
                return
            name = (body.get("name") or "").strip()[:64]
            note = (body.get("note") or "").strip()[:200]
            ok = update_api_key(key, name, note)
            self._send(200, {"ok": ok, "msg": "已更新" if ok else "Key 不存在"})
            return
        # 编辑用户（管理员）
        m = re.match(r"^/api/v1/admin/users/([^/]+)$", path)
        if m:
            if not self._require_admin():
                return
            username = m.group(1)
            body = self._read_json()
            if body is None:
                return
            password = (body.get("password") or "").strip()
            group_id = body.get("group_id")
            enabled = body.get("enabled")
            ok = update_user(
                username,
                password=password if password else None,
                group_id=group_id if group_id is not None else None,
                enabled=enabled if enabled is not None else None,
            )
            self._send(200, {"ok": ok, "msg": "已更新" if ok else "用户不存在"})
            return
        # 编辑用户组（管理员）
        m = re.match(r"^/api/v1/admin/groups/(\d+)$", path)
        if m:
            if not self._require_admin():
                return
            gid = int(m.group(1))
            body = self._read_json()
            if body is None:
                return
            name = (body.get("name") or "").strip()[:32]
            quota = int(body.get("key_quota") or 0)
            ok = update_group(gid, name, quota)
            self._send(200, {"ok": ok, "msg": "已更新" if ok else "组不存在"})
            return
        self._json_error("Not Found", 404)

    def do_DELETE(self):
        try:
            self._handle_delete()
        except Exception as e:
            self._internal_error(e)

    def _handle_delete(self):
        path = self._path()
        # 解绑当前账号二次验证（需当前 TOTP 码，防会话劫持后直接关闭）
        if path == "/api/v1/admin/2fa":
            self._api_2fa_disable()
            return
        # 管理员重置指定用户的二次验证
        m = re.match(r"^/api/v1/admin/users/([^/]+)/2fa$", path)
        if m:
            if not self._require_admin():
                return
            username = m.group(1)
            if username == config.ADMIN_USER:
                self._json_error("内置管理员请在自身安全设置中操作", 400)
                return
            twofa.clear_secret(username)
            self._send(200, {"ok": True, "msg": "已重置该用户的二次验证"})
            return
        m = re.match(r"^/api/v1/admin/keys/([^/]+)$", path)
        if m:
            if not self._require_auth():
                return
            key = m.group(1)
            if not self._can_manage_key(key):
                self._json_error("无权操作该 Key", 403)
                return
            if key == config.DEFAULT_API_KEY:
                self._json_error("不能删除默认 Key", 400)
                return
            ok = delete_api_key(key)
            self._send(200, {"ok": ok, "msg": "已删除" if ok else "Key 不存在"})
            return
        # 删除用户（管理员）
        m = re.match(r"^/api/v1/admin/users/([^/]+)$", path)
        if m:
            if not self._require_admin():
                return
            username = m.group(1)
            ok = delete_user(username)
            self._send(200, {"ok": ok, "msg": "已删除" if ok else "用户不存在"})
            return
        # 删除用户组（管理员）
        m = re.match(r"^/api/v1/admin/groups/(\d+)$", path)
        if m:
            if not self._require_admin():
                return
            ok, msg = delete_group(int(m.group(1)))
            self._send(200, {"ok": ok, "msg": msg or "已删除"})
            return
        self._json_error("Not Found", 404)

    def _check_rl(self):
        ip = self._client_ip()
        key = self._get_api_key()
        if not self._check_lock():
            return False
        # 演示 Key 使用独立全局限流（防恶意调用），其余走常规 IP 限流
        if key and key.startswith("cg-demo-"):
            allowed, remaining, reset_in = check_rate_limit(ip, "generate_demo", scope_key=key)
        else:
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

    def _api_captcha_validate(self):
        """在线校验 pass_token（服务端验签 + 一次性消费）。

        供未配置 PASS_TOKEN_SECRET 的接入方（如 WordPress 插件普通用户）使用：
        调用方只需携带自己的 API Key 与 pass_token。
        """
        if not self._require_api_key() or not self._check_rl():
            return
        body = self._read_json()
        if body is None:
            return
        token = body.get("pass_token") or body.get("token")
        if not token or not isinstance(token, str):
            self._json_error("缺少 pass_token")
            return
        payload = decode_jwt(token, secret=config.PASS_TOKEN_SECRET)
        if not payload or payload.get("captcha") != "passed":
            self._send(200, {"ok": False, "msg": "验证未通过"})
            return
        jti = str(payload.get("jti") or "")
        if not consume_pass_jti(jti):
            self._send(200, {"ok": False, "msg": "验证码已使用"})
            return
        self._send(200, {"ok": True, "msg": "验证通过"})

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

    def _api_login_captcha_generate(self):
        """登录表单验证码（无需 API Key；按 IP 限流防滥用）。"""
        ip = self._client_ip()
        allowed, _, reset_in = check_rate_limit(ip, "login_captcha")
        if not allowed:
            self._send(429, {
                "ok": False,
                "msg": f"验证码获取过于频繁，请 {reset_in} 秒后再试",
                "retry_after": reset_in,
            }, headers={"Retry-After": str(reset_in)})
            return
        try:
            img, code = generate_text_captcha()
            token = create_token("text", code.upper(), ip=ip, ua=self._ua())
            self._send(200, {
                "ok": True,
                "data": {
                    "token": token,
                    "image": b64_image(img),
                    "expires_in": config.CAPTCHA_EXPIRE_SECONDS,
                }
            })
        except Exception as e:
            print("[ERROR] login captcha generate:", e)
            self._json_error("生成失败，请稍后重试", 500)

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

        # 登录验证码（默认开启，LOGIN_CAPTCHA=0 关闭）
        if config.LOGIN_CAPTCHA:
            captcha_ok = self._check_login_captcha(body)
            if captcha_ok is not True:
                self._send(captcha_ok or 400, {"ok": False, "msg": "验证码错误或已过期"})
                return

        username = str(body.get("username") or "")
        password = str(body.get("password") or "")

        account, role, user = None, "", None
        # 内置管理员
        if hmac.compare_digest(username.encode("utf-8"), config.ADMIN_USER.encode("utf-8")) and \
           hmac.compare_digest(password.encode("utf-8"), config.ADMIN_PASS.encode("utf-8")):
            account, role = config.ADMIN_USER, "admin"
        else:
            # 普通用户（用户组体系）
            user = users.authenticate_user(username, password)
            if user:
                account, role = user["username"], "user"

        if account is None:
            record_login_fail(ip)
            self._json_error("用户名或密码错误", 401)
            return

        # 二次验证（TOTP）：已启用则先发短期 pre_token，验证通过后再发正式 JWT
        if twofa.is_enabled(account):
            claims = {"role": role, "user": account, "step": "2fa", "jti": str(uuid.uuid4())}
            if user and user.get("group_id") is not None:
                claims["group_id"] = user["group_id"]
            pre_token = create_jwt(claims, expires_seconds=300)
            self._send(200, {"ok": False, "need_2fa": True, "pre_token": pre_token,
                             "msg": "请输入二次验证码"})
            return

        record_login_success(ip)
        claims = {"role": role, "user": account}
        if user and user.get("group_id") is not None:
            claims["group_id"] = user["group_id"]
        token = create_jwt(claims)
        self._send_login_ok(token, account, role)

    def _api_login_2fa(self):
        """二次验证第二步：pre_token + TOTP 码 → 正式 JWT。"""
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
        pre_token = body.get("pre_token")
        code = (body.get("code") or "").strip()
        payload = decode_jwt(pre_token) if pre_token else None
        if not payload or payload.get("step") != "2fa":
            self._json_error("会话已失效，请重新登录", 401)
            return
        # pre_token 一次性消费：仅在 TOTP 校验通过后消费，输错动态码可重试不失效
        account = payload.get("user")
        if twofa.verify(account, code):
            jti = str(payload.get("jti") or "")
            if jti and not consume_pass_jti(jti, ttl=300):
                self._json_error("会话已使用，请重新登录", 401)
                return
            record_login_success(ip)
            claims = {"role": payload.get("role", "user"), "user": account}
            if payload.get("group_id") is not None:
                claims["group_id"] = payload["group_id"]
            token = create_jwt(claims)
            self._send_login_ok(token, account, claims["role"])
        else:
            record_login_fail(ip)
            self._send(200, {"ok": False, "msg": "二次验证码不正确，请重试"})

    def _api_register(self):
        """用户注册：管理面板开关控制；需验证码 + IP 限流防滥用。"""
        if not settings.get_bool_setting("registration_enabled", False):
            self._json_error("注册未开放", 403)
            return
        ip = self._client_ip()
        allowed, _, reset_in = check_rate_limit(ip, "register")
        if not allowed:
            self._send(429, {
                "ok": False,
                "msg": f"注册过于频繁，请 {reset_in} 秒后再试",
                "retry_after": reset_in,
            }, headers={"Retry-After": str(reset_in)})
            return
        body = self._read_json()
        if body is None:
            return
        # 注册验证码（复用登录验证码机制，防脚本批量注册）
        if config.LOGIN_CAPTCHA:
            captcha_ok = self._check_login_captcha(body)
            if captcha_ok is not True:
                self._send(captcha_ok or 400, {"ok": False, "msg": "验证码错误或已过期"})
                return
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        # 用户名不能与内置管理员冲突
        if hmac.compare_digest(username.encode("utf-8"), config.ADMIN_USER.encode("utf-8")):
            self._json_error("用户名不可用", 400)
            return
        ok, msg, _ = create_user(username, password, ensure_default_group())
        if not ok:
            self._json_error(msg, 400)
            return
        self._send(200, {"ok": True, "msg": "注册成功，请登录"})

    def _api_2fa_setup(self):
        """生成 TOTP 密钥（不落库，确认后才启用）；附带二维码 PNG 供 Authenticator 扫描。"""
        auth = self._require_auth()
        if not auth:
            return
        account = auth.get("user", config.ADMIN_USER)
        secret = totp.generate_secret()
        self._send(200, {"ok": True, "data": {
            "account": account,
            "secret": secret,
            "uri": totp.otpauth_uri(secret, account),
            "qr": totp.qr_png_base64(secret, account),
        }})

    def _api_2fa_confirm(self):
        """确认启用：用提交的密钥校验当前 TOTP 码，通过后写入持久化。"""
        auth = self._require_auth()
        if not auth:
            return
        body = self._read_json()
        if body is None:
            return
        account = auth.get("user", config.ADMIN_USER)
        secret = (body.get("secret") or "").strip()
        code = (body.get("code") or "").strip()
        if not secret or not code:
            self._json_error("缺少密钥或验证码")
            return
        if twofa.is_enabled(account):
            self._json_error("已启用二次验证，请先解绑再重新绑定", 400)
            return
        if not totp.verify_code(secret, code):
            self._json_error("验证码不正确，请重试", 400)
            return
        twofa.set_secret(account, secret)
        self._send(200, {"ok": True, "msg": "二次验证已启用"})

    def _api_2fa_disable(self):
        """解绑当前账号二次验证（需当前 TOTP 码，防会话劫持后直接关闭）。"""
        auth = self._require_auth()
        if not auth:
            return
        body = self._read_json()
        if body is None:
            return
        account = auth.get("user", config.ADMIN_USER)
        code = (body.get("code") or "").strip()
        if not twofa.is_enabled(account):
            self._json_error("未启用二次验证", 400)
            return
        if not twofa.verify(account, code):
            self._json_error("验证码不正确", 400)
            return
        twofa.clear_secret(account)
        self._send(200, {"ok": True, "msg": "二次验证已关闭"})

    def _check_login_captcha(self, body):
        """校验登录验证码：返回 True 或 HTTP 状态码。"""
        token_id = body.get("captcha_token")
        code = (body.get("captcha_code") or "").strip().upper()
        if not token_id or not code:
            return 400
        row = get_token(token_id)
        if not row or row.get("used") or row.get("type") != "text":
            return 400
        if row.get("expires_at", 0) < now() and not get_redis():
            return 400
        ok = hmac.compare_digest(row["secret"].upper(), code)
        mark_used(token_id)
        return True if ok else 400

    def _send_login_ok(self, token, user, role):
        cookie = f"admin_token={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={config.JWT_EXPIRE_HOURS*3600}"
        if self.headers.get("X-Forwarded-Proto", "").lower() == "https":
            cookie += "; Secure"
        self._send(200, {
            "ok": True,
            "token": token,
            "user": user,
            "role": role,
            "msg": "登录成功",
        }, headers={"Set-Cookie": cookie})

    def _request_base_url(self):
        """根据请求推导插件可填写的 API 服务地址（尊重反向代理的 X-Forwarded-Proto）。"""
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",")[0].strip() or "http"
        host = self.headers.get("Host", "").strip()
        if not host:
            host = f"{self.client_address[0]}:{getattr(self.server, 'server_port', 8080)}"
        return f"{proto}://{host}"

    def _key_connect_info(self, key, include_secret=True):
        """插件连接配置（仅管理员接口返回；含签名密钥，前端需提示妥善保管）。

        普通用户不返回 pass_token_secret——该密钥可签发伪造 pass_token，
        多用户场景下仅管理员可见。
        """
        info = {
            "base_url": self._request_base_url(),
            "api_key": key,
        }
        if include_secret:
            info["pass_token_secret"] = config.PASS_TOKEN_SECRET
        return info

    def _api_create_key(self):
        if not self._require_auth():
            return
        body = self._read_json()
        if body is None:
            return
        name = (body.get("name") or "新 Key").strip()[:64]
        note = (body.get("note") or "").strip()[:200]

        if self._is_admin_request():
            # 管理员：可指定归属用户，默认自己，不限制数量
            owner = (body.get("owner") or self._current_user()).strip()[:64]
        else:
            # 普通用户：只能为自己创建，受所在组配额限制
            owner = self._current_user()
            if count_keys(owner) >= key_quota_for(owner):
                self._send(403, {"ok": False,
                                 "msg": f"已达到 API Key 数量上限（{key_quota_for(owner)} 个），请联系管理员"})
                return

        key = create_api_key(name, note, owner)
        self._send(200, {"ok": True, "data": {
            "key": key, "name": name, "note": note, "owner": owner,
            "connect": self._key_connect_info(key, include_secret=self._is_admin_request()),
        }})

    def _api_create_user(self):
        if not self._require_admin():
            return
        body = self._read_json()
        if body is None:
            return
        username = (body.get("username") or "").strip()[:32]
        password = (body.get("password") or "").strip()
        group_id = body.get("group_id") or ensure_default_group()
        ok, msg, user = create_user(username, password, group_id)
        if not ok:
            self._json_error(msg, 400)
            return
        self._send(200, {"ok": True, "data": user, "msg": "用户已创建"})

    def _api_create_group(self):
        if not self._require_admin():
            return
        body = self._read_json()
        if body is None:
            return
        name = (body.get("name") or "").strip()[:32]
        quota = int(body.get("key_quota") or 5)
        if not name:
            self._json_error("组名称不能为空", 400)
            return
        gid = create_group(name, quota)
        self._send(200, {"ok": True, "data": {"id": gid, "name": name, "key_quota": max(0, quota)}})

    def _serve_template(self, filename, replace_key=False):
        path = os.path.join(config.TEMPLATE_DIR, filename)
        if not os.path.exists(path):
            self._send(200, f"<h1>{filename} missing</h1>", "text/html")
            return
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        hit = _TEMPLATE_CACHE.get(path)
        if hit and hit[0] == mtime:
            content = hit[1]
        else:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            _TEMPLATE_CACHE[path] = (mtime, content)
        if replace_key:
            # 页面注入受限的演示 Key（与业务 Key 隔离；页面源码可见但不展示）
            content = content.replace("{{API_KEY}}", get_demo_key())
            content = content.replace("{{DEMO_KEY}}", get_demo_key())
        self._send(200, content, "text/html; charset=utf-8")

    def _serve_guide(self):
        self._serve_template("guide.html")

    def _serve_call_docs(self):
        self._serve_template("api-docs.html", replace_key=True)

    def _serve_landing(self):
        """项目首页（科技感落地页，双主题，内置登录/注册）。"""
        self._serve_template("landing.html")

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
            "storage": self._storage_label(),
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
