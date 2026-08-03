# 基础镜像可通过 --build-arg BASE_IMAGE=... 或 build.sh 自动选择（国内/国际）
ARG BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
FROM ${BASE_IMAGE}

WORKDIR /app

# 自动探测网络环境：国内镜像源可达则 apt/pip 使用国内源，否则使用官方源
RUN python - <<'PY'
import urllib.request, socket
socket.setdefaulttimeout(3)
def reachable(url):
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except Exception:
        return False
if reachable("http://mirrors.aliyun.com/debian/"):
    open("/tmp/use_cn_mirror", "w").write("1")
    print("[mirror] 国内网络环境：apt/pip 使用国内镜像源")
else:
    print("[mirror] 国际网络环境：使用官方软件源")
PY

# apt：国内源可用时切换阿里云（兼容 Debian 12/13 的 deb822 格式与旧版 sources.list）
RUN if [ -f /tmp/use_cn_mirror ]; then \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g \
    fonts-dejavu-core \
    fonts-noto-cjk \
    fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY app.py .
COPY requirements.txt .
COPY captcha_app/ captcha_app/
COPY templates/ templates/
COPY static/ static/
COPY fonts/ fonts/

# pip：国内源可用时使用清华源
RUN if [ -f /tmp/use_cn_mirror ]; then \
      pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi

ENV HOST=0.0.0.0
ENV PORT=8080
ENV DB_PATH=/data/captcha.db
ENV ENV=production
ENV RATE_LIMIT_GENERATE=30
ENV PYTHONUNBUFFERED=1

# 以非 root 用户运行
RUN useradd -r -m -d /home/captcha captcha \
    && mkdir -p /data \
    && chown -R captcha:captcha /app /data
USER captcha

EXPOSE 8080
VOLUME /data

# 注意：SECRET_KEY / ADMIN_PASS / DEFAULT_API_KEY 必须通过环境变量传入，
# 否则容器会因 ENV=production 的 fail-fast 校验拒绝启动（防止默认凭据上线）。
CMD ["python3", "app.py"]
