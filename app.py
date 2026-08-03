#!/usr/bin/env python3
"""动态验证码管理系统 - 入口"""
import threading
import time
from http.server import ThreadingHTTPServer

from captcha_app import config
from captcha_app.db import init_db
from captcha_app.handler import CaptchaHandler
from captcha_app.redis_client import get_redis
from captcha_app.tokens import cleanup_expired


class CaptchaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_cleanup_loop():
    while True:
        try:
            cleanup_expired()
        except Exception as e:
            print("cleanup error:", e)
        time.sleep(300)


def main():
    config.validate_config()
    init_db()
    get_redis()
    t = threading.Thread(target=run_cleanup_loop, daemon=True)
    t.start()
    server = CaptchaHTTPServer((config.HOST, config.PORT), CaptchaHandler)
    print("=" * 56)
    print("  动态验证码管理系统 v2.1（模块化）已启动")
    print(f"  演示页面:  http://127.0.0.1:{config.PORT}/")
    print(f"  管理后台:  http://127.0.0.1:{config.PORT}/admin")
    print(f"  API 文档:  http://127.0.0.1:{config.PORT}/api/v1/docs")
    print(f"  环境: {config.ENV}   管理员: {config.ADMIN_USER}（密码已隐藏）")
    print(f"  限流: 生成接口 {config.RATE_LIMIT_GENERATE} 次/分钟/IP")
    print(f"  存储: {'Redis' if get_redis() else 'SQLite'}")
    print("=" * 56)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == "__main__":
    main()
