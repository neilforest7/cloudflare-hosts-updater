FROM python:3.9-alpine

ARG VERSION=1.0.6
LABEL version=$VERSION 
LABEL maintainer="neilforest <markeloffack@gmail.com>"
LABEL description="容器hosts自动修改器 - 自动选择最优Cloudflare IP并更新容器hosts"

# 安装必要的工具
RUN apk add --no-cache \
    curl \
    wget \
    unzip \
    docker-cli \
    && pip install --no-cache-dir \
    schedule==1.1.0 \
    werkzeug==2.0.1 \
    flask==2.0.1 \
    toml==0.10.2

# 创建工作目录
WORKDIR /app

# 下载CloudflareSpeedTest
RUN wget -O /tmp/CloudflareST.tar.gz https://github.com/XIU2/CloudflareSpeedTest/releases/latest/download/CloudflareST_linux_amd64.tar.gz \
    && tar -xzf /tmp/CloudflareST.tar.gz -C /app \
    && chmod +x /app/CloudflareST \
    && rm /tmp/CloudflareST.tar.gz

# 复制应用代码
COPY ./app /app
COPY ./data /app/data

# 创建数据目录
RUN mkdir -p /app/data \
    && chmod +x /app/main.py

# 设置卷
VOLUME ["/app/data"]

# 启动命令
CMD ["python", "/app/main.py"]