FROM python:3.9-alpine

LABEL maintainer="YourName <your.email@example.com>"
LABEL description="CloudflareIP-Hosts更新器 - 自动选择最优Cloudflare IP并更新容器hosts"

# 安装必要的工具
RUN apk add --no-cache \
    curl \
    wget \
    unzip \
    docker-cli \
    && pip install --no-cache-dir \
    schedule==1.1.0

# 创建工作目录
WORKDIR /app

# 下载CloudflareSpeedTest
RUN wget -O /tmp/CloudflareST.zip https://github.com/XIU2/CloudflareSpeedTest/releases/latest/download/CloudflareST_linux_amd64.zip \
    && unzip -d /app /tmp/CloudflareST.zip \
    && chmod +x /app/CloudflareST \
    && rm /tmp/CloudflareST.zip

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