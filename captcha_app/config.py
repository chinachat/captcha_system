"""配置项（支持环境变量覆盖）"""
import os
import secrets

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-" + secrets.token_hex(8))
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
JWT_EXPIRE_HOURS = 24
CAPTCHA_EXPIRE_SECONDS = int(os.environ.get("CAPTCHA_EXPIRE", "120"))
SLIDER_TOLERANCE = 8
DB_PATH = os.environ.get("DB_PATH", "/tmp/captcha_system.db")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
DEFAULT_API_KEY = os.environ.get("DEFAULT_API_KEY", "demo-api-key-captcha-2026")

RATE_LIMIT_GENERATE = int(os.environ.get("RATE_LIMIT_GENERATE", "30"))
RATE_LIMIT_WINDOW = 60

SLIDER_MIN_MS = int(os.environ.get("SLIDER_MIN_MS", "280"))
SLIDER_MAX_MS = int(os.environ.get("SLIDER_MAX_MS", "30000"))
SLIDER_MIN_TRACK = int(os.environ.get("SLIDER_MIN_TRACK", "5"))
CLICK_MIN_TOTAL_MS = int(os.environ.get("CLICK_MIN_TOTAL_MS", "600"))
CLICK_MIN_GAP_MS = int(os.environ.get("CLICK_MIN_GAP_MS", "120"))
FAIL_LOCK_THRESHOLD = int(os.environ.get("FAIL_LOCK_THRESHOLD", "8"))
FAIL_LOCK_SECONDS = int(os.environ.get("FAIL_LOCK_SECONDS", "300"))

REDIS_URL = os.environ.get("REDIS_URL", "")
