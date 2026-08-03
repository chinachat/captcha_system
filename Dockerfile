FROM docker.m.daocloud.io/library/python:3.12-slim

WORKDIR /app

# 国内云服务器：将 Debian 软件源切换为阿里云镜像（Debian 12 为 deb822 格式，
# 兼容旧版 sources.list），避免 apt-get update / fonts-noto-cjk 下载卡死
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
      /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
      /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
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

RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

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
