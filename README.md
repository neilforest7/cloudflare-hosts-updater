# CloudflareIP-Hosts更新器

一个轻量级工具，用于定期获取最优的Cloudflare IP地址，并自动更新Docker容器的hosts文件。

## 功能概览

- 自动测试并选择最佳的Cloudflare IP地址
- 更新指定Docker容器的hosts文件
- 支持预设IP，无需测速
- 支持Web界面实时配置
- 可自定义更新间隔和域名列表

## 快速开始

### Docker部署

```bash
docker run -d \
  --name cloudflare-hosts-updater \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/data:/app/data \
  -p 8080:8080 \
  -e UPDATE_INTERVAL=12h \
  -e TARGET_CONTAINERS=container1,container2 \
  -e CF_DOMAINS=example.com,example.org \
  -e IP_COUNT=1 \
  yourusername/cloudflare-hosts-updater:latest
```

### Docker Compose

```yaml
version: '3'
services:
  cloudflare-hosts-updater:
    image: yourusername/cloudflare-hosts-updater:latest
    container_name: cloudflare-hosts-updater
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./data:/app/data
    ports:
      - "8080:8080"
    environment:
      - UPDATE_INTERVAL=12h
      - TARGET_CONTAINERS=container1,container2
      - CF_DOMAINS=example.com,example.org
      - IP_COUNT=1
    restart: unless-stopped
```

## 配置选项

| 环境变量 | 描述 | 默认值 |
|----------|------|--------|
| `UPDATE_INTERVAL` | 更新间隔（如: 12h, 30m, 1d） | `12h` |
| `TARGET_CONTAINERS` | 目标容器名称（逗号分隔） | - |
| `CF_DOMAINS` | 域名列表（逗号分隔） | - |
| `IP_COUNT` | 每个域名使用的IP数量 | `1` |
| `PREFERRED_IP` | 预设IP（设置后跳过测速） | - |
| `SPEED_TEST_ARGS` | CloudflareST额外参数 | - |

## Web界面

访问 `http://your-docker-host:8080` 可进入Web管理界面：

- 查看当前配置
- 修改配置参数
- 手动触发测速和更新
- 查看运行日志

## 进阶用法

### 自定义hosts模板

在`/app/data/template.hosts`中创建模板：

```
{ip} {domain} # 速度:{speed}ms
```

### 使用预设IP

设置`PREFERRED_IP`环境变量或在Web界面中配置，将绕过测速直接使用该IP。

## 故障排除

- **容器无法访问Docker Socket**：确保正确挂载了`/var/run/docker.sock`
- **测速失败**：检查网络连接或考虑使用预设IP
- **hosts未更新**：确认容器名称正确且有文件系统权限

查看日志：

```bash
docker logs cloudflare-hosts-updater
```

## 致谢

本项目核心功能依赖于[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)项目，感谢其提供的高效Cloudflare IP测速工具。

## 许可证

本项目采用MIT许可证 