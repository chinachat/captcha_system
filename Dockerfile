FROM docker.m.daocloud.io/library/python:3.12-slim

WORKDIR /app

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
