"""TOTP 二次验证（RFC 6238，纯标准库实现，零第三方依赖）

- HMAC-SHA1 / 30 秒步长 / 6 位数字
- 校验允许 ±1 个时间步的时钟漂移
- secret 为 Base32 字符串（Authenticator 应用手动添加用）
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1  # 时钟漂移容差（时间步）


def generate_secret() -> str:
    """生成 20 字节随机密钥，Base32 编码（无填充）。"""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _normalize_secret(secret: str) -> bytes:
    s = str(secret).strip().replace(" ", "").upper()
    if not s:
        raise ValueError("empty secret")
    s += "=" * ((8 - len(s) % 8) % 8)
    return base64.b32decode(s)


def _code_for_counter(secret: bytes, counter: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(code).zfill(DIGITS)


def totp_code(secret: str, at: float = None) -> str:
    """生成指定时刻（默认当前时间）的 TOTP 码，用于测试。"""
    counter = int((time.time() if at is None else at) // STEP)
    return _code_for_counter(_normalize_secret(secret), counter)


def verify_code(secret: str, code: str, window: int = WINDOW) -> bool:
    """校验 TOTP 码（常量时间比较 + 前后 window 步容差）。"""
    if not code or not secret:
        return False
    code = str(code).strip()
    counter = int(time.time() // STEP)
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_code_for_counter(_normalize_secret(secret), counter + delta), code):
            return True
    return False


def otpauth_uri(secret: str, account: str, issuer: str = "captcha_system") -> str:
    """otpauth:// URI，供 Authenticator 类应用手动添加。"""
    label = quote(f"{issuer}:{account}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def qr_png_base64(secret: str, account: str, issuer: str = "captcha_system") -> str:
    """生成 otpauth URI 的二维码 PNG（base64，Authenticator 直接扫描绑定）。"""
    from .utils import b64_image
    try:
        import qrcode
    except ImportError:
        return ""
    uri = otpauth_uri(secret, account, issuer)
    img = qrcode.make(uri, box_size=4, border=2)
    return b64_image(img)
