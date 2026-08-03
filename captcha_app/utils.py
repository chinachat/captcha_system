"""通用工具"""
import io
import base64
import secrets
import time
from datetime import datetime, timedelta, timezone

from PIL import Image
import jwt

from . import config


def now():
    return time.time()


def b64_image(img: Image.Image, fmt="PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return "data:image/{};base64,{}".format(fmt.lower(), base64.b64encode(buf.getvalue()).decode())


def random_color(low=40, high=200):
    return tuple(secrets.randbelow(high - low) + low for _ in range(3))


def create_jwt(payload: dict, expires_seconds: int = None, secret: str = None) -> str:
    payload = payload.copy()
    now_utc = datetime.now(timezone.utc)
    payload["iat"] = now_utc
    expire_seconds = expires_seconds if expires_seconds is not None else config.JWT_EXPIRE_HOURS * 3600
    payload["exp"] = now_utc + timedelta(seconds=expire_seconds)
    return jwt.encode(payload, secret or config.SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str):
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None
