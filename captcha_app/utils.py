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


def create_jwt(payload: dict) -> str:
    payload = payload.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRE_HOURS)
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str):
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None
