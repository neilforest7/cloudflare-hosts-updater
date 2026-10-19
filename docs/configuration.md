# 部署与配置

这页列出 README 中折叠的高级设置、数据文件和常见限制。新安装请先按 [README 快速开始](../README.md#快速开始)运行。

## 远程访问

默认端口只绑定在宿主机的 `127.0.0.1:18080`。需要从局域网或反向代理访问时，先复制 `.env.example` 为 `.env` 并设置管理密码：

```dotenv
BIND_ADDRESS=0.0.0.0
WEB_USERNAME=admin
WEB_PASSWORD=换成强密码
```

然后运行 `docker compose up -d`。跨网络访问请使用 HTTPS 反向代理，并限制访问来源。应用挂载的 Docker Socket 可以控制宿主机上的容器；将挂载声明为只读不能限制 Docker API 的写操作。

## 高级配置

配置保存在 `/app/data/config.toml` 的 `[general]` 段。首次启动时可用表中配置名的大写形式设置初始值；已有配置后请在管理界面修改。

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `update_interval` | 自动更新间隔，支持 `s`、`m`、`h`、`d`，范围 1 秒至 365 天；纯数字按小时 | `12h` |
| `target_containers` | 目标容器名称，逗号或换行分隔；留空时只生成 hosts 文件 | 空 |
| `cf_domains` | 域名，逗号或换行分隔，不含协议、端口或路径 | 空 |
| `ip_count` | 每个域名使用的优选 IP 数量，1–20 | `1` |
| `preferred_ip` | 预设单个 IPv4 或 IPv6；设置后跳过测速，每个域名只生成一个 IP | 空 |
| `speed_test_args` | CloudflareSpeedTest 参数，支持引号；不可指定 `-o` | 空 |
| `speed_test_timeout` | 测速超时秒数，1–86400 | `1800` |
| `update_enabled` | 是否在启动时及按间隔自动更新；手动更新始终可用 | `true` |

多个优选 IP 会同时写入同一域名，最终使用哪个由目标程序的解析器决定。域名留空时不安排自动任务。

Compose 的 `.env` 支持以下变量：

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `BIND_ADDRESS` | 宿主机端口绑定地址 | `127.0.0.1` |
| `WEB_PORT` | 宿主机映射端口；容器内仍使用 `8080` | `18080` |
| `WEB_USERNAME` / `WEB_PASSWORD` | 管理界面登录；密码为空时不启用登录 | `admin` / 空 |
| `TZ` | 应用时区 | `Asia/Shanghai` |

Compose 固定将 `./data` 挂载到 `/app/data`。自行运行容器或程序时，还可设置 `DATA_DIR`（数据目录，默认 `/app/data`）、`WEB_HOST` / `WEB_PORT`（监听地址与端口，默认 `0.0.0.0:8080`）和 `CLOUDFLAREST_BIN`（测速程序路径，默认 `/app/CloudflareST`）。

### 不使用 Compose

```bash
docker build -t cloudflare-hosts-updater:local .
docker volume create cloudflare-hosts-data
docker run -d --name cloudflare-hosts-updater \
  --restart unless-stopped \
  -p 127.0.0.1:18080:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v cloudflare-hosts-data:/app/data \
  cloudflare-hosts-updater:local
```

## hosts 模板与文件

在数据目录创建 `template.hosts` 可自定义每条映射。模板必须为单行，只支持 `{ip}`、`{domain}` 和 `{speed}`，并以 IP 与域名开头：

```text
{ip} {domain} # 延迟:{speed}ms
```

`speed` 表示平均延迟毫秒；使用预设 IP 时显示 `0`，并非实测值。

| 文件 | 用途 |
| --- | --- |
| `config.toml` | 配置 |
| `hosts` | 最近生成的管理区块；不能证明每个容器都已写入 |
| `hosts.bak` | 上一次本地 hosts 产物 |
| `result.csv` | 最近一次有效测速结果；失败、超时或无输出不会覆盖 |
| `update_history.json` | 最近 50 次任务；损坏历史会保留 `.corrupt` 副本 |
| `updater.log` | 应用日志，最多 2 MiB，保留 3 个轮转文件 |

每个目标容器还会在写入前备份原文件到 `/etc/hosts.bak`。应以界面中的任务结果和容器实际 hosts 内容确认写入成功。旧版生成的 `hosts.bak.*` 和 `/etc/hosts.bak.*` 不会自动删除。

## 运行限制与排查

- 目标容器必须运行，并包含 `sh`、`cat`、`cp`、`mktemp`、`cmp`、`rm`。写入以容器 root 用户执行；Distroless 镜像或只读根文件系统可能无法使用。
- Docker 重建目标容器时会重建 `/etc/hosts`。重新执行一次更新，或等待下一次定时任务；当前版本不监听 Docker 生命周期事件。
- 域名应确实使用 Cloudflare CDN。优选 IP 不保证在所有网络环境下都可达。
- 如果旧 hosts 管理区块缺少结束标记，应用会停止写入并保留原内容。备份并修正标记后再执行。
- 测速受网络状况影响。排查配置或容器写入时，可暂时设置一个预设 IP。
- 更新器重启会使当前浏览器的页面凭证失效；刷新页面后重新登录。

```bash
docker compose ps
docker compose logs --tail=100
```

`GET /healthz` 只检查 Web 进程是否响应，不代表 Docker 或测速网络正常；任务记录会分别显示这些操作的结果。
