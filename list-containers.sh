#!/bin/bash

# 列出当前环境中运行的容器，方便用户配置TARGET_CONTAINERS
echo "当前环境中运行的容器列表："
echo "----------------------------"
docker ps --format "{{.Names}}"
echo "----------------------------"
echo "请将需要更新hosts的容器名称添加到.env文件中的TARGET_CONTAINERS变量" 