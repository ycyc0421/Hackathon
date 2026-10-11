# CI/CD 工作流

## 设计原则

**分离验证和部署**：
- PR 阶段：只做验证（构建、测试、契约校验），不部署
- main 合并后：先运行 CI，成功后由独立部署工作流发布前后端

这样既保证代码质量，又避免未审查的代码直接上线。

## 在 Actions 中查看什么

| 工作流 | 运行标题 | 用途 |
|---|---|---|
| `CI` | `CI 验证（不部署）· 分支名` | 测试、契约校验和构建；成功不代表已上线 |
| `Deploy frontend and backend` | `前后端部署 · 提交 SHA` | 查看独立的后端、前端部署 job 及发布结果 |

查看 CI 中的「构建前端」job 只能确认构建状态。线上发布请到 **Actions → Deploy frontend and backend**，选择相同提交 SHA 的运行；CI 的 Summary 也提供该工作流入口。PR 不会发布服务，过期主分支提交会跳过部署。

## ci.yml

**触发条件**：`main`、`web/*` 分支的 push，以及针对 `main` 的 PR

**工作流程**：
1. **validate-contract**: 校验数据契约（`npm run validate`）
2. **build-frontend**: 前端逻辑回归并构建（`web/` 目录）
3. **backend-regression**: 后端语义回归、接口返回校验与挑战样例验证
4. 后端回归任务还验证数据层、部署回退单元测试和公网联调脚本语法，这些检查不操作线上服务器

**不包含部署**：PR 和 main 的 CI 都只做验证，不访问生产 secrets。只有 main 的 push CI 成功后，独立部署工作流才会继续检查是否应发布。

## deploy.yml

**触发条件**：
- `main` 的 push CI 成功后自动触发；PR 的 CI 不触发部署
- 支持手动触发（workflow_dispatch），仅允许 `main` 且对应提交已有成功的 push CI
- 发布前核对当前主分支提交；过期的 CI 结果不会把旧版本覆盖回线上
- 发布串行执行，不取消正在切换服务的部署

**三个 job 按依赖顺序执行**：

```text
确认通过 CI 的主分支版本
  → 部署后端与公网验证
    → 部署前端到 Cloudflare
```

| Job ID | Actions 显示名称 | 工作内容 |
|---|---|---|
| `revision` | 确认通过 CI 的主分支版本 | 检查最新 main 提交及其 CI 结果，跳过过期提交 |
| `deploy-backend` | 部署后端与公网验证 | 校验配置、预先构建前端、发布后端并验证公网接口及返回契约 |
| `deploy-frontend` | 部署前端到 Cloudflare | 后端 job 成功后，取回同一次运行的前端产物并发布 Worker |

后端 job 在切换服务之前，把 `VITE_API_BASE` 注入前端构建并保存 `frontend-production` 产物；构建或产物上传失败时不会开始发布后端。随后通过专用普通用户上传版本归档，使用指定的 Python 3.12 创建独立虚拟环境、安装依赖并运行后端自检。共享配置启用 OCR 时，还会安装 CPU 推理引擎并实跑 11 号 PNG 样例，全部文件和商品行通过后才切换用户服务。配置与数据保留，启动失败自动回退。

后端启动后，从部署服务器通过公开 HTTPS 域名验证跨域、样例上传和任务查询，将结果传回执行器校验契约；验证失败会回退后端，并阻止前端 job 执行。两个部署 job 检出同一提交，前端 job 使用已构建的产物。后端 job 成功仅代表后端通过验证，必须同时确认前端 job 成功，才能判断前后端均已发布。

单独重试部署 job 时会再次核对最新 main；如果主分支已更新，重试将失败并提示重新运行最新版本的完整部署，防止旧产物覆盖新版本。

当前采用浏览器直连 HTTPS 后端，Worker 继续托管静态资源。后端部署脚本见 [`deploy/backend.py`](../../deploy/backend.py)，公网验证脚本见 [`deploy/smoke.py`](../../deploy/smoke.py)。

公网验证复用后端版本中的 Python 与 HTTPX，无需在服务器安装 Node。这样可避免 GitHub 托管执行器被边缘人机挑战拦截；请求仍经过公开域名、TLS 和边缘代理。该检查验证部署服务器的出网路径，不能替代浏览器和其他网络的联调检查。

后端 API 地址在前端构建时固定。修改 GitHub 变量后需重新运行完整部署工作流；仅重试前端 job 会复用原构建产物，在 Cloudflare 后台设置同名运行时变量也不会改写已构建的页面。产物保留 7 天，过期后需重新运行完整部署。部署后通过 `?mock=0` 或顶栏切换到“真实后端”，填入 API 地址不会自动关闭示例模式。

**使用 Environment**：`production` environment 提供额外保护层

## 所需配置

### GitHub Environment Variables

在仓库的 **Settings → Environments → production → Environment variables** 添加：

| 名称 | 内容 |
|---|---|
| `VITE_API_BASE` | 后端完整 HTTPS API 前缀，以 `/api/v1` 结尾，不带尾斜杠，如 `https://backend.example.com/api/v1` |
| `FRONTEND_ORIGIN` | 实际前端站点的 HTTPS 源地址，用于验证该站点的跨域请求，如 `https://app.example.com` |

Variables 只保存浏览器需要使用的公开地址。`VITE_API_BASE` 会进入前端构建产物；部署主机地址、维护账号和 SSH 凭据统一保存在下方的 Secrets，不写进仓库，也不放在 Variables 中。

### GitHub Environment Secrets

在仓库的 **Settings → Environments → production** 中添加：

- `CLOUDFLARE_API_TOKEN`: Cloudflare API Token
- `CLOUDFLARE_ACCOUNT_ID`: 部署目标的 Cloudflare 账户 ID
- `BACKEND_SSH_HOST`: 敏感的部署主机域名或 IPv4 地址，SSH 使用 22 端口
- `BACKEND_SSH_USER`: 已初始化的普通维护用户，不允许 `root`
- `BACKEND_SSH_KEY`: 仅用于部署的 SSH 私钥，对应公钥安装到普通维护用户；不使用共享登录密码
- `BACKEND_SSH_KNOWN_HOSTS`: 经可信连接核验的服务器 SSH 公钥记录；工作流严格校验，不临时接受未知主机

### 后端主机初始化

工作流只负责发布到已有服务。管理员首次准备：

- Python 3.12、支持 `systemd --user` 的普通用户，启用该用户的 linger，使服务在退出 SSH 后及重启后继续运行。用户无需 sudo 或 Docker 权限。
- `~/app/current` 指向已有可用版本；`~/app/shared/backend.env` 保存运行配置，`~/app/shared/data` 保存任务结果。
- `~/app/venv/bin/python` 中已安装 pip，用于为新版本的 `.venv` 安装依赖；这个引导环境不随发布改动。
- 已有用户服务 `~/.config/systemd/user/hackathon-backend.service`，首次自动发布会更新为仓库中的[服务定义](../../deploy/hackathon-backend.service)。后端保持单 worker，监听本机 18000 端口。
- HTTPS 反向代理已连接本机 18000，允许前端跨域访问；TLS、域名和代理配置继续由管理员维护。

发布默认使用维护用户的 `~/.local/bin/python3.12`；安装在其他位置时，在共享 `backend.env` 中用 `BACKEND_PYTHON` 指定解释器路径。路径支持 `~`，版本必须为 3.12。系统 `python3` 只执行发布脚本，不决定新虚拟环境的 Python 版本。

本地 OCR 由同一共享文件中的 `PADDLE_OCR_ENABLED` 控制，未配置或设为 `0` 时只安装普通依赖。设为 `1` 时，每个新版本独立安装 `requirements-ocr.txt`、兼容的 setuptools 和官方 CPU 渠道的 PaddlePaddle 3.2.0；服务器其他虚拟环境中手工安装的依赖不会被借用。发布脚本只读取这些配置，不写回文件。

开启 OCR 后，候选版本先运行真实模型图片探针，模型缓存保存在服务用户目录。切换后还会经公开 HTTPS 地址上传 11 号 PNG，以及由这些 PNG 生成的无文本层扫描 PDF；必须全部识别成功、保留 4 个商品行并检出颜色冲突，再校验返回契约。图片或扫描 PDF 检查失败会触发既有回退流程。未开启 OCR 时，日志明确说明只验证文本 PDF。整个后端 job 上限为 40 分钟，包含首次安装和模型下载。

用户服务的内存软、硬限制分别为 6 GiB 和 8 GiB，以容纳本地 OCR 模型和推理峰值；主机需提供相应资源。模型在固定线程中创建和复用，多个任务串行推理。多模态服务配置仍只保存在共享文件中，自动验证不使用模型 API 密钥。

### 发布与回退

每次发布保存到 `~/app/releases/<提交SHA>-<运行编号>-<重试编号>`，包括独立 `.venv`、依赖版本记录和上一个服务配置。版本目录不会自动删除，共享数据和配置不随代码替换。

普通维护用户可执行：

```sh
systemctl --user status hackathon-backend --no-pager
systemctl --user restart hackathon-backend
journalctl --user -u hackathon-backend -f
# 将下面的发布标识替换为 current 所指向的目录名
python3 ~/app/current/deploy/backend.py <发布标识> --rollback
```

启动或公网验证失败会恢复旧代码、旧服务配置和旧依赖，不回滚共享任务数据。若前端的 Cloudflare 发布失败，但后端已验证正常，保留该后端版本并将工作流标记为失败，修复后重新发布。

当前任务队列在进程内存中，部署重启可能中断处理中的任务，应在无进行中联调任务时发布；已完成的任务保留。自动部署不负责数据库迁移、共享配置的首次设置或真实评测。

### Token 权限要求

创建 API Token 时需要以下权限：

1. **Account Settings: Read** - 读取账户信息
2. **Workers Scripts: Edit** - 部署和更新 Worker
3. **Workers KV Storage: Edit** - Worker Sites 静态资源存储
4. **Workers Routes: Edit** - 配置自定义域名路由

### 为什么这样设计？

**安全性**：
- PR 不访问生产 secrets，防止恶意代码窃取
- 使用 GitHub Environment 增加审批层（可选配置 reviewers）
- Token 权限最小化，只给必需的 Workers 权限

**可靠性**：
- 代码经过审查后才部署
- main 分支保持可交付状态
- 支持手动触发部署和回滚

**效率**：
- PR 快速验证（无部署等待）
- 合并后自动部署
