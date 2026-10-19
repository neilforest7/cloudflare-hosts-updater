# Cloudflare Hosts Updater

优选 Cloudflare IP，并为同一 Docker 环境中的指定容器更新 hosts。提供中文管理界面、后台任务、定时更新与执行记录。

![新版运行概览](docs/images/overview.png)

## 1.1 新版

- **更容易上手**：自动读取容器列表，勾选目标、填写域名后即可「保存并更新」；高级参数默认收起。
- **可靠更新**：只替换自身管理的 hosts 区块，保留 localhost、容器映射和用户条目；标记损坏时停止写入。
- **统一任务**：手动、启动和定时任务使用同一流程，同一时间只执行一个任务；前台无需等待测速请求完成。
- **准确反馈**：区分成功、部分成功和失败，显示每个目标容器的结果；支持 IPv4、IPv6 与多 IP 展示。
- **配置校验**：检查域名、容器名称、IP、更新间隔与测速参数；保存采用原子替换，空配置可正确保存。
- **可维护部署**：Python 3.13、Flask 3、Waitress；固定测速工具版本并校验 SHA-256，支持 amd64 / arm64 构建。
- **管理保护**：可选登录密码、CSRF 校验、日志轮转和健康检查；默认仅在宿主机本地开放端口。

## 从源码启动

```bash
git clone https://github.com/neilforest7/cloudflare-hosts-updater.git
cd cloudflare-hosts-updater
docker compose up -d --build
```

在 Docker 宿主机访问 [http://127.0.0.1:18080](http://127.0.0.1:18080)。此命令从当前源码构建，Docker Hub 上旧的 `latest` 镜像不会自动包含这些改动。

首次使用无需编辑配置文件：

1. 页面自动进入「首次设置」，从列表中勾选目标容器。
2. 填写需要更新的域名，每行一个。粘贴完整网址时会自动提取域名。
3. 点击「保存并更新」，页面自动切换到总览，显示后台执行结果。

默认每 12 小时自动更新。固定 IP、多 IP 与测速参数位于「高级选项」；选择固定 IP 后会隐藏无关测速选项。日常可在总览点击「立即更新」，失败时直接查看对应容器的原因。

「仅保存」只保存规则；「保存并更新」同时启动任务。无法读取 Docker 时可以重试或手动填写名称。仅需导出 hosts 时，在「手动输入或仅导出 hosts」中勾选对应选项。

数据默认继续保存在 `./data:/app/data`，兼容旧版目录挂载。确保该目录可供容器写入即可，无需将目录权限设为 `777`。如果原来使用自定义路径，请保留原挂载路径。

### 从局域网或反向代理访问

复制 `.env.example` 为 `.env`，设置绑定地址和管理密码，再重建容器：

```dotenv
BIND_ADDRESS=0.0.0.0
WEB_USERNAME=admin
WEB_PASSWORD=替换为你自己的强密码
```

跨网络访问请使用 HTTPS 反向代理。Docker Socket 的访问权限能够控制宿主机 Docker；管理界面应仅开放给可信用户。将 Socket 挂载为只读不能限制 Docker API 的写操作。

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

## 从 1.0.x 升级

1. 备份旧 `data` 目录，停止旧更新器，避免两个版本同时写入目标容器。
2. 获取新版代码并重新构建镜像。
3. **沿用原来的数据挂载**。新版 Compose 默认仍为 `./data:/app/data`；如果旧部署使用自定义目录或命名卷，需保留对应挂载，避免创建全新的数据目录。
4. 启动新版，确认配置与历史记录，然后手动运行一次更新并检查容器实际内容。

新版兼容旧版 `[general]` 格式的 `config.toml`、`template.hosts`、`result.csv` 与历史记录，自动识别旧 hosts 管理标记。旧历史无法证明容器实际写入成功，因此显示为「旧版记录」。旧配置文件损坏或字段非法时会明确报错退出，避免恢复默认值后误操作；修复对应字段后重启即可。

行为变化：新安装不再预填特定容器或域名；「仅保存」不修改容器，执行更新需点击「保存并更新」或总览的「立即更新」。环境变量仅用于首次初始化，已有配置文件中的空值会被保留。配置更新不需要重启；直接编辑 TOML 文件后需重启服务。

## 配置

配置保存在 `/app/data/config.toml` 的 `[general]` 段。首次启动时也可用大写同名环境变量初始化。

| 配置键 | 说明 | 默认值 |
| --- | --- | --- |
| `update_interval` | 1 秒至 365 天，正整数加 `s`、`m`、`h`、`d`，纯数字按小时 | `12h` |
| `target_containers` | 目标容器名，逗号或换行分隔 | 空 |
| `cf_domains` | 域名，不含协议、端口或路径 | 空 |
| `ip_count` | 每个域名使用的优选 IP 数量，1–20 | `1` |
| `preferred_ip` | 单个预设 IPv4 / IPv6，设置后跳过测速 | 空 |
| `speed_test_args` | CloudflareSpeedTest 参数，支持引号，不支持自定义 `-o` | 空 |
| `speed_test_timeout` | 测速超时秒数，1–86400 | `1800` |
| `update_enabled` | 是否在启动时及按间隔自动更新；手动操作始终可用 | `true` |

容器列表留空时只生成本地 hosts；域名列表留空时不安排自动任务。预设 IP 模式始终为每个域名生成一个 IP。多个优选 IP 会同时写入每个域名，具体使用哪个由目标程序的解析器决定。

运行环境变量：`DATA_DIR`（默认 `/app/data`）、`WEB_HOST`（容器内默认 `0.0.0.0`）、`WEB_PORT`（容器内默认 `8080`）、`TZ`（默认 `Asia/Shanghai`）、`WEB_USERNAME`（默认 `admin`）、`WEB_PASSWORD`（默认不启用认证）、`CLOUDFLAREST_BIN`（默认 `/app/CloudflareST`）。Compose 的 `.env` 中 `WEB_PORT` 用于宿主机端口映射，容器内保持 `8080`。

### hosts 模板

可在数据目录创建 `template.hosts`，只支持一行，使用 `{ip}`、`{domain}`、`{speed}`：

```text
{ip} {domain} # 延迟:{speed}ms
```

`speed` 保留旧变量名，表示平均延迟毫秒；预设 IP 显示为 `0`，并非实际测量值。模板只允许一个 IP 和一个域名，附加说明必须在 `#` 之后。

### 数据与恢复

- `hosts`：最近生成的管理区块，**不代表每个容器都写入成功**；以任务结果和容器实际内容为准。
- `hosts.bak`：上一次本地 hosts 产物。
- `result.csv`：最近一次有效测速结果。失败、超时或没有输出时不会覆盖它，也不会将它当作新测速结果。
- `update_history.json`：最近 50 次任务；损坏历史保留一个 `.corrupt` 副本。
- `updater.log`：应用日志，每份最多 2 MiB，保留 3 个轮转文件。
- 每个目标容器的 `/etc/hosts.bak`：最近一次写入前的完整 hosts 备份；写入脚本检测到失败时尝试恢复。

不自动删除旧版产生的 `hosts.bak.*`、`/etc/hosts.bak.*` 文件，确认无需保留后可自行清理。

## 运行限制与排查

- 目标容器必须正在运行，且包含 `sh`、`cat`、`cp`、`mktemp`、`cmp`、`rm`。Distroless 镜像不适用该写入方式。
- 写入以容器 root 用户执行；只读根文件系统可能无法创建 `/etc/hosts.bak`，此时任务会报告失败。
- Docker 重建容器后会重建 `/etc/hosts`，需重新运行更新或等待下一次定时任务。当前版本不监听 Docker 生命周期事件。
- 域名应确实使用 Cloudflare CDN；优选 IP 不保证所有域名在目标网络下可达。
- 若旧管理区块缺少结束标记，任务会停止并保留原 hosts。先查看实际内容、备份并修正标记，再重新执行。
- 测速依赖目标网络条件；无法测速时可先用预设 IP 验证配置和容器写入。
- 更新器重启会使当前浏览器的页面凭证失效，刷新页面后重试即可。

```bash
docker compose logs --tail=100
docker compose ps
```

`GET /healthz` 仅检查 Web 进程是否可响应，不代表 Docker 或测速网络可用。任务结果会分别记录这些操作的错误。

## 本地开发与验证

需要 Python 3.11+。实际测速需下载 CloudflareSpeedTest 并设置 `CLOUDFLAREST_BIN`；容器写入需安装 Docker CLI 并能访问 Docker daemon。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
DATA_DIR=./data python -m app.main
```

```bash
ruff check .
ruff format --check .
pytest -q
# 仅在可创建临时容器的本地 Docker 环境运行：
RUN_DOCKER_TESTS=1 pytest -q tests/test_docker_integration.py
```

CI 检查 Python 3.11 / 3.13、代码风格、回归测试与 amd64 / arm64 镜像构建，不自动发布镜像。详细设计与后续方向见 [新版改进说明](docs/modernization.md)。

浏览器测试独立于应用运行，仅在开发时需要 Node 22+：

```bash
npm ci --prefix tests/browser
tests/browser/node_modules/.bin/playwright install --with-deps chromium
RUN_DOCKER_TESTS=1 npm test --prefix tests/browser
```

测试会启动临时本地服务，创建并清理自己的隔离容器，验证上手、更新、失败恢复及三种屏幕宽度下的可访问性。截图与报告位于 `.taste-skill/browser`。界面设计依据见 [上手流程与界面设计](docs/interface-design.md)。

## 致谢与许可证

测速依赖 [XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)，使用固定的 v2.3.5 发布包。应用使用 [MIT 许可证](LICENSE)；第三方软件适用各自许可证。
