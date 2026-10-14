# CI/CD 工作流

PR 只验证，main 的 push CI 成功后自动发布。前端静态资源与 Python 后端部署在同一服务器，当前生产统一使用 `https://hackathon.ychome.net`，前端同源请求 API。

文档修改也会触发 main CI 与部署，目前没有文档路径豁免。维护、备份、故障排查见[部署运维](../../docs/部署运维.md)。

## ci.yml

CI 验证数据契约、前端逻辑与构建、后端语义及接口、数据层、发布回退和公网探针。它不访问生产凭据，也不发布服务。

- 后端 job 用 Python 3.12 与根目录固定版本的测试工具执行 `python -m pytest`，自动发现 `backend/tests/`；接口回归同时校验合成样例结论、Schema、计数和引用。
- 数据层与部署回退分别作为独立矩阵任务运行，`fail-fast: false`；后端失败不会阻止它们执行。
- 每条 Python 用例最多 60 秒；后端 job 最多 15 分钟，支持任务最多 10 分钟。失败也上传 JUnit，后端另保留接口 JSON，均保留 7 天。
- 普通 CI 关闭真实模型，使用临时存储；真实 OCR 验收仍由专用工具和部署探针承担。具体本地命令见[后端验证说明](../../backend/README.md#验证与样例)。
- 同一 PR 的过期 CI 可取消；main 的 push CI 不取消，继续作为部署的前置检查。

## deploy.yml

两个 job 按顺序执行：

1. `revision`：确认提交仍为最新 main，且已有成功的 push CI。
2. `deploy-backend`（发布整站与公网验证）：构建前端、发布前后端、验证公网结果与返回契约。

支持手动触发，但仍须使用通过 push CI 的最新 main。发布串行执行，不取消正在切换服务的运行。SSH 每 20 秒发送保活，避免长时间模型推理无输出导致连接被断开。PR 不部署，过期提交不会覆盖线上。

### 发布流程

- 检查整站源地址。HTTP 仅允许直接访问 IP；域名地址使用 HTTPS。
- 前端直接使用默认同源 `/api/v1`，把 `web/dist` 与同一提交的代码打入一个版本归档。构建失败不会开始发布。
- 用专用普通用户上传归档，为每个版本创建 Python 3.12 独立虚拟环境并安装依赖。候选版本的测试使用临时数据，不写共享任务目录。
- 启用 OCR 时，安装 PaddlePaddle 3.2.0、PaddleOCR 3.7.0、PDF 渲染组件和兼容的 setuptools，切换前实跑 11 号 PNG 探针。模型缓存保存在维护用户目录。
- `current` 同时决定前端静态资源和后端代码。切换后验证首页、脚本及样式、API 跨域预检、上传轮询与返回契约；OCR 开启时额外验证图片和无文本层扫描 PDF，要求全部文件成功、4 个商品完整并检出颜色冲突。
- 启动或公网验证失败时，先停止新服务，再恢复前后端旧版本、旧依赖及旧服务配置；共享任务数据不回滚。后端 job 的时间上限为 40 分钟。

公网验证从部署服务器请求公开地址，经过 Nginx；结果传回 GitHub 执行器校验 Schema。该检查不能替代浏览器及其他网络的联调。前端默认仍使用示例模式，真实联调通过顶栏切换或 `?mock=0` 进入。

## GitHub production 环境配置

地址配置也保存在 production Secrets 中：

| 名称 | 示例 |
|---|---|
| `SITE_ORIGIN` | 整站源地址，如 `https://app.example.com` |

`SITE_ORIGIN` 只供部署验证使用，不注入前端构建。前端始终相对当前站点请求 `/api/v1`；公网探针由源地址推导 API 地址。无需设置 `VITE_API_BASE` 或 `FRONTEND_ORIGIN`，迁移时删除旧 Secrets。本地跨端口开发仍可使用前端的可选环境变量覆盖。

SSH 部署 Secrets：

- `BACKEND_SSH_HOST`：部署主机域名或 IPv4，SSH 使用 22 端口。
- `BACKEND_SSH_USER`：已初始化的普通维护用户，不允许 root。
- `BACKEND_SSH_KEY`：专用部署私钥，使用对应公钥登录，不使用共享密码。
- `BACKEND_SSH_KNOWN_HOSTS`：经可信连接核验的主机公钥记录。

当前整站流程不使用 Cloudflare Worker 发布凭据。域名可使用 Cloudflare 代理及源站证书；DNS、证书与源站访问限制由管理员维护。

## 服务器首次初始化

管理员需先准备：

- Python 3.12、普通维护用户与 `systemd --user`，为该用户启用 linger。发布用户无需 sudo 或 Docker 权限。
- `~/app/current` 指向一个已有可用版本，其中包含 `web/dist` 与后端独立 `.venv`，作为首次发布的回退目标。
- `~/app/shared/backend.env` 保存配置，`~/app/shared/data` 保存任务；权限仅授予维护用户。
- `~/app/venv/bin/python` 中安装支持 `--python` 的 pip，作为安装新环境的引导工具。
- 安装仓库中的 `deploy/hackathon-backend.service` 为用户服务，后端单 worker 监听 `127.0.0.1:18000`。
- Nginx 静态根目录指向维护用户的 `app/current/web/dist`，将 `/api/`、`/health`、`/docs` 和 `/openapi.json` 反向代理到本机 18000 端口。SPA 页面回退到 `index.html`，缺失的 `/assets/` 文件返回 404。
- 为 Nginx 提供维护用户 home、`app`、`releases` 目录的穿越权限；发布脚本仅额外开放版本目录的穿越和 `web/dist` 静态产物的读取权限。共享配置、数据及 SSH 私钥保持私有。
- 上传请求体上限需容纳最多 10 个、每个 20 MiB 的文件及 multipart 开销。

IP 访问可直接使用 HTTP 的同源页面与 API；若采用域名，管理员另行维护 TLS。修改 Nginx 前须验证配置，并保留已有站点配置。

### Python 与 OCR

发布默认使用维护用户的 `~/.local/bin/python3.12`，可通过共享文件中的 `BACKEND_PYTHON` 指定其他路径。系统 `python3` 只运行发布脚本，不决定新环境版本。

`PADDLE_OCR_ENABLED` 未配置或为 `0` 时只安装普通依赖，并明确记录仅验证文本 PDF。设为 `1` 时安装完整 OCR 依赖并运行真实模型及公网图片、扫描 PDF 探针。服务器其他虚拟环境中的手工依赖不会被借用。自动发布只读取共享配置。

服务的 `MemoryHigh` / `MemoryMax` 分别为 6 GiB / 8 GiB，CPU 配额为四核；模型固定在线程内创建和串行复用，推理线程数固定为 4，与 CPU 配额对齐，避免默认多线程争抢配额。主机还须为系统、其他服务，以及旧版本运行期间的新版本模型预检保留内存。

### 回退与数据

版本位于 `~/app/releases/<提交SHA>-<运行编号>-<重试编号>`，保存独立环境、依赖版本记录和上一版服务配置。版本目录不会自动删除。

```sh
systemctl --user status hackathon-backend --no-pager
journalctl --user -u hackathon-backend -f
# 使用 current 所指向的发布标识
python3 ~/app/current/deploy/backend.py <发布标识> --rollback
```

任务队列仍在进程内存中，重启可能中断进行中的任务，应在无进行中联调任务时发布；已完成任务保留。自动部署不负责数据库迁移或真实评测。
