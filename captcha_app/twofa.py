"""二次验证（TOTP）账号级存取：内置管理员存 settings 表，普通用户存 users 表。"""
from . import settings as settings_store
from .db import get_db
from . import totp

_ADMIN_TOTP_KEY = "admin_totp_secret"


def _is_admin_account(username: str) -> bool:
    # 内置管理员不在 users 表，用户名即 config.ADMIN_USER；普通用户必在 users 表
    from . import config
    return username == config.ADMIN_USER


def get_secret(account: str) -> str:
    if _is_admin_account(account):
        return settings_store.get_setting(_ADMIN_TOTP_KEY, "")
    row = get_db().execute("SELECT totp_secret FROM users WHERE username = ?", (account,)).fetchone()
    return row["totp_secret"] or "" if row else ""


def set_secret(account: str, secret: str):
    if _is_admin_account(account):
        settings_store.set_setting(_ADMIN_TOTP_KEY, secret)
        return
    conn = get_db()
    conn.execute("UPDATE users SET totp_secret = ? WHERE username = ?", (secret, account))
    conn.commit()


def clear_secret(account: str):
    set_secret(account, "")


def is_enabled(account: str) -> bool:
    return bool(get_secret(account))


def verify(account: str, code: str) -> bool:
    """校验账号的 TOTP 码；未启用时返回 False。"""
    secret = get_secret(account)
    if not secret:
        return False
    return totp.verify_code(secret, code)
