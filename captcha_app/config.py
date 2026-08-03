"""配置项（支持环境变量覆盖）"""
import os
import secrets
import sys

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-" + secrets.token_hex(8))
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
JWT_EXPIRE_HOURS = 24
CAPTCHA_EXPIRE_SECONDS = int(os.environ.get("CAPTCHA_EXPIRE", "120"))
# 业务 pass_token 独立短时效（秒）
PASS_TOKEN_EXPIRE_SECONDS = int(os.environ.get("PASS_TOKEN_EXPIRE", "60"))
SLIDER_TOLERANCE = 8
DB_PATH = os.environ.get("DB_PATH", "/tmp/captcha_system.db")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
DEFAULT_API_KEY = os.environ.get("DEFAULT_API_KEY", "demo-api-key-captcha-2026")

# 运行环境：development / production（production 下使用默认凭据将拒绝启动）
ENV = os.environ.get("ENV", "development").lower()
# 显式允许不安全默认值（仅建议本地开发调试用）
ALLOW_INSECURE_DEFAULTS = os.environ.get("ALLOW_INSECURE_DEFAULTS", "").lower() in ("1", "true", "yes")

# 请求体大小上限（字节），防内存耗尽 DoS
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", "65536"))
# 单连接请求读取超时（秒），防 slowloris
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "15"))

RATE_LIMIT_GENERATE = int(os.environ.get("RATE_LIMIT_GENERATE", "30"))
RATE_LIMIT_WINDOW = 60

SLIDER_MIN_MS = int(os.environ.get("SLIDER_MIN_MS", "280"))
SLIDER_MAX_MS = int(os.environ.get("SLIDER_MAX_MS", "30000"))
SLIDER_MIN_TRACK = int(os.environ.get("SLIDER_MIN_TRACK", "5"))
CLICK_MIN_TOTAL_MS = int(os.environ.get("CLICK_MIN_TOTAL_MS", "600"))
CLICK_MIN_GAP_MS = int(os.environ.get("CLICK_MIN_GAP_MS", "120"))
FAIL_LOCK_THRESHOLD = int(os.environ.get("FAIL_LOCK_THRESHOLD", "8"))
FAIL_LOCK_SECONDS = int(os.environ.get("FAIL_LOCK_SECONDS", "300"))

# 管理登录失败锁定（IP 维度）
LOGIN_LOCK_THRESHOLD = int(os.environ.get("LOGIN_LOCK_THRESHOLD", "5"))
LOGIN_LOCK_SECONDS = int(os.environ.get("LOGIN_LOCK_SECONDS", "300"))

REDIS_URL = os.environ.get("REDIS_URL", "")

# 可信代理 IP / CIDR 列表（逗号分隔），仅当请求真实来源 IP 命中该列表时才信任 X-Forwarded-For
# 例如: "192.168.1.0/24,10.0.0.1" 或 "127.0.0.1"
TRUSTED_PROXIES = os.environ.get("TRUSTED_PROXIES", "")

INSECURE_DEFAULTS = {
    "ADMIN_PASS": ADMIN_PASS == "admin123",
    "DEFAULT_API_KEY": DEFAULT_API_KEY == "demo-api-key-captcha-2026",
    "SECRET_KEY": SECRET_KEY.startswith("change-me-in-production-"),
}


def validate_config():
    """凭据校验：production 环境使用默认/占位凭据时拒绝启动（fail-fast）。"""
    insecure = [k for k, v in INSECURE_DEFAULTS.items() if v]
    if not insecure:
        return
    msg = ("检测到不安全默认配置: " + ", ".join(insecure) +
           "。请通过环境变量设置强随机值（SECRET_KEY 可用 `openssl rand -hex 32` 生成）。")
    if config_is_production() and not ALLOW_INSECURE_DEFAULTS:
        print("[FATAL] " + msg, file=sys.stderr)
        sys.exit(1)
    print("[WARN] " + msg + "（当前为开发环境，仅警告；生产环境将拒绝启动）")


def config_is_production():
    return ENV == "production"
