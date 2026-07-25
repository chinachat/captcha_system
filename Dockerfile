FROM docker.m.daocloud.io/library/python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g \
    fonts-dejavu-core \
    fonts-noto-cjk \
    fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    pillow PyJWT redis

COPY app.py .
COPY captcha_app/ captcha_app/
COPY templates/ templates/
COPY fonts/ fonts/

ENV HOST=0.0.0.0
ENV PORT=8080
ENV DB_PATH=/data/captcha.db
ENV SECRET_KEY=please-change-me-in-production
ENV ADMIN_USER=admin
ENV ADMIN_PASS=admin123
ENV DEFAULT_API_KEY=demo-api-key-captcha-2026
ENV RATE_LIMIT_GENERATE=30

EXPOSE 8080
VOLUME /data

CMD ["python3", "app.py"]
