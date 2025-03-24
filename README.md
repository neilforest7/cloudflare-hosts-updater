# 容器hosts自动修改器

![容器Hosts修改器界面](https://imgbed.neilforest.xyz/i/2025/03/24/67e0adaec6c12.png)

一个轻量级工具，用于定期获取最优的Cloudflare IP地址，并自动更新Docker容器的hosts文件。

## 功能概览

- 自动测试并选择最佳的Cloudflare IP地址
- 更新指定Docker容器的hosts文件（目标容器需要与此容器位于同一docker环境）
- 支持预设IP，无需测速
- 支持Web界面实时配置
- 可自定义更新间隔和域名列表

## 快速开始

无需预先配置任何文件，所有设置均可在Web界面完成。

首先创建一个data目录用于数据持久化：

```bash
# 创建data目录
mkdir -p your_dir/data
# 确保目录权限正确
chmod 777 your_dir/data
```

### Docker部署

```bash
docker run -d \
  --name cloudflare-hosts-updater \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v your_dir/data:/app/data \
  -p 18080:8080 \
  neilforest/cloudflare-hosts-updater:latest
```

### Docker Compose

```yaml
version: '3'
services:
  cloudflare-hosts-updater:
    image: neilforest/cloudflare-hosts-updater:latest
    container_name: cloudflare-hosts-updater
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./data:/app/data
    ports:
      - "18080:8080"
    restart: unless-stopped
```

部署后，访问 `http://your-docker-host:18080` 进入Web管理界面，在界面中完成所有配置。

## Web界面

- 配置更新间隔、目标容器和域名列表
- 设置IP数量和可选的预设IP
- 手动触发测速和更新
- 查看运行日志
- 保存所有配置（自动保存到容器中）

## 配置选项

以下配置均可在Web界面中设置：

| 配置项 | 描述 | 默认值 |
|----------|------|--------|
| 更新间隔 | 自动更新频率（如: 12h, 30m, 1d） | `12h` |
| 目标容器 | 需要更新hosts的容器名称（多个用逗号分隔） | - |
| 域名列表 | 需要解析的Cloudflare域名（多个用逗号分隔） | - |
| IP数量 | 每个域名使用的IP数量 | `1` |
| 预设IP | 可选的固定IP（设置后跳过测速） | - |
| 测速参数 | CloudflareST额外参数 | - |

## 进阶用法

### 自定义hosts模板

在挂载的`data`目录中创建`template.hosts`文件：

```
{ip} {domain} # 速度:{speed}ms
```

## 故障排除

- **容器无法访问Docker Socket**：确保正确挂载了`/var/run/docker.sock`
- **测速失败**：检查网络连接或考虑使用预设IP
- **hosts未更新**：确认容器名称正确且有文件系统权限
- **权限问题**：确保data目录有适当的权限（chmod 777 ./data）

查看日志：

```bash
docker logs cloudflare-hosts-updater
```

## 致谢

本项目核心功能依赖于[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)项目，感谢其提供的高效Cloudflare IP测速工具。

## 许可证

本项目采用MIT许可证 