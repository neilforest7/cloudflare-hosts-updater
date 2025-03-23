#!/bin/bash

# CloudflareIP-Hosts更新器启动脚本

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo "错误：未安装Docker，请先安装Docker"
    exit 1
fi

# 检查Docker Compose是否安装
if ! command -v docker-compose &> /dev/null && ! command -v docker compose &> /dev/null; then
    echo "警告：未安装Docker Compose，将使用Docker命令运行"
    USE_COMPOSE=false
else
    USE_COMPOSE=true
fi

# 检查环境文件
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "未找到.env文件，将从.env.example复制创建"
        cp .env.example .env
        echo "请编辑.env文件配置参数后重新运行此脚本"
        exit 0
    else
        echo "错误：未找到.env或.env.example文件"
        exit 1
    fi
fi

# 创建数据目录
mkdir -p data

# 使用Docker Compose或Docker运行
if [ "$USE_COMPOSE" = true ]; then
    if command -v docker-compose &> /dev/null; then
        echo "使用docker-compose启动..."
        docker-compose up -d
    else
        echo "使用docker compose启动..."
        docker compose up -d
    fi
else
    echo "使用docker命令启动..."
    
    # 加载环境变量
    source .env
    
    # 构建镜像
    docker build -t cloudflare-hosts-updater .
    
    # 运行容器
    docker run -d \
        --name cloudflare-hosts-updater \
        --restart unless-stopped \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v "$(pwd)/data:/app/data" \
        -e UPDATE_INTERVAL="${UPDATE_INTERVAL:-6h}" \
        -e TARGET_CONTAINERS="${TARGET_CONTAINERS}" \
        -e CF_DOMAINS="${CF_DOMAINS}" \
        -e IP_COUNT="${IP_COUNT:-3}" \
        -e SPEED_TEST_ARGS="${SPEED_TEST_ARGS}" \
        -e HOSTS_MARKER="${HOSTS_MARKER:-# CloudflareIP-Hosts更新器}" \
        cloudflare-hosts-updater
fi

echo "CloudflareIP-Hosts更新器已启动"
echo "查看日志: docker logs cloudflare-hosts-updater" 