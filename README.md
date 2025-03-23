# CloudflareIP-Hosts更新器

## 项目介绍

CloudflareIP-Hosts更新器是一个运行在Docker容器中的自动化工具，用于定期测试和选择最优的Cloudflare IP地址，并将这些IP地址更新到同一Docker环境中其他容器的hosts文件中。该工具利用[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)项目来测试Cloudflare的IP地址性能。

## 功能特点

- 定时执行CloudflareSpeedTest获取最优IP地址
- 支持使用预设的首选IP，无需测速（可选）
- 自动生成和维护hosts文件
- 将生成的hosts条目注入同一Docker环境中的其他容器
- 支持自定义测试周期和更新策略
- 轻量级设计，基于Alpine Linux
- 可配置的IP选择规则

## 技术架构

### 技术栈

- **基础镜像**: Alpine Linux
- **编程语言**: Python 3
- **核心组件**:
  - Python schedule库（定时任务）
  - Docker CLI（容器交互）
  - XIU2/CloudflareSpeedTest（IP测速）

### 系统架构

该系统采用以下架构工作：

1. **主程序容器**:
   - 运行Python脚本进行调度和控制
   - 调用CloudflareSpeedTest测试IP（或使用预设IP）
   - 生成hosts文件
   - 通过Docker命令更新其他容器的hosts文件

2. **数据流**:
   - CloudflareSpeedTest测试结果 → 解析处理 → hosts文件生成 → 注入其他容器

3. **容器交互**:
   - 通过挂载Docker socket实现容器间操作
   - 使用Docker exec命令在目标容器中执行hosts更新

## 安装与配置

### 前置条件

- Docker已安装并运行
- Docker Compose (推荐，但非必须)

### 快速开始

1. 克隆本仓库:
   ```bash
   git clone https://github.com/yourusername/cloudflare-hosts-updater.git
   cd cloudflare-hosts-updater
   ```

2. 配置环境变量（可选）:
   编辑`.env`文件设置自定义参数

3. 使用Docker Compose启动:
   ```bash
   docker-compose up -d
   ```

### Docker运行参数

```bash
docker run -d \
  --name cloudflare-hosts-updater \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/data:/app/data \
  -e UPDATE_INTERVAL=6h \
  -e TARGET_CONTAINERS=container1,container2 \
  -e CF_DOMAINS=www.example.com,example.com \
  -e PREFERRED_IP=104.18.182.64 \
  -e IP_COUNT=3 \
  yourusername/cloudflare-hosts-updater:latest
```

## 配置选项

| 环境变量 | 描述 | 默认值 |
|----------|------|--------|
| `UPDATE_INTERVAL` | CloudflareSpeedTest运行间隔 | `12h` |
| `TARGET_CONTAINERS` | 目标容器名称（逗号分隔） | - |
| `CF_DOMAINS` | 要更新的域名列表（逗号分隔） | - |
| `PREFERRED_IP` | 预设首选IP，如果设置则跳过测速 | - |
| `IP_COUNT` | 每个域名使用的IP数量 | `3` |
| `SPEED_TEST_ARGS` | CloudflareSpeedTest额外参数 | - |
| `HOSTS_MARKER` | hosts文件中的标记（用于定位更新位置） | `# CloudflareIP-Hosts更新器` |

## 进阶用法

### 使用预设IP

如果您已知道想要使用的Cloudflare IP地址，可以设置`PREFERRED_IP`环境变量：

```
PREFERRED_IP=104.18.182.64
```

设置此选项后，程序将不再执行测速，而是直接使用您指定的IP地址。

### 自定义hosts模板

您可以在`/app/data/template.hosts`中定义自定义的hosts模板，使用`{ip}`和`{domain}`作为占位符：

```
{ip} {domain} # 速度:{speed}ms
```

### 与其他容器集成

要在已有的Docker Compose环境中使用本工具，只需添加：

```yaml
services:
  # 您的其他服务...
  
  cloudflare-hosts-updater:
    image: yourusername/cloudflare-hosts-updater:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./updater-data:/app/data
    environment:
      - TARGET_CONTAINERS=web,api,db
      - CF_DOMAINS=example.com
      - PREFERRED_IP=104.18.182.64  # 可选，设置后将跳过测速
```

## 故障排除

### 常见问题

**问题**: 无法连接到Docker守护进程  
**解决方案**: 确保正确挂载了Docker socket并且容器有适当的权限

**问题**: CloudflareSpeedTest测试结果为空  
**解决方案**: 检查网络连接，可能需要调整测试参数，或考虑使用PREFERRED_IP参数

**问题**: 其他容器的hosts文件未更新  
**解决方案**: 确保目标容器名称正确，并且目标容器具有适当的文件系统权限

### 日志查看

```bash
docker logs cloudflare-hosts-updater
```

## 贡献指南

欢迎提交Pull Request或Issues来改进项目。请确保遵循以下准则：

1. 遵循现有的代码风格
2. 为新功能添加测试
3. 更新文档以反映更改

## 许可证

本项目采用MIT许可证 - 详见LICENSE文件 