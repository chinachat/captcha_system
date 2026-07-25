#!/usr/bin/env python3
"""动态验证码管理系统 - 入口"""
import threading
import time
from http.server import HTTPServer

from captcha_app import config
from captcha_app.db import init_db
from captcha_app.handler import CaptchaHandler
from captcha_app.redis_client import get_redis
from captcha_app.tokens import cleanup_expired


def run_cleanup_loop():
    while True:
        try:
            cleanup_expired()
        except Exception as e:
            print("cleanup error:", e)
        time.sleep(300)


def main():
    init_db()
    get_redis()
    t = threading.Thread(target=run_cleanup_loop, daemon=True)
    t.start()
    server = HTTPServer((config.HOST, config.PORT), CaptchaHandler)
    print("=" * 56)
    print("  动态验证码管理系统 v2.1（模块化）已启动")
    print(f"  演示页面:  http://127.0.0.1:{config.PORT}/")
    print(f"  管理后台:  http://127.0.0.1:{config.PORT}/admin")
    print(f"  API 文档:  http://127.0.0.1:{config.PORT}/api/v1/docs")
    print(f"  默认 API Key: {config.DEFAULT_API_KEY}")
    print(f"  管理员: {config.ADMIN_USER} / {config.ADMIN_PASS}")
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
