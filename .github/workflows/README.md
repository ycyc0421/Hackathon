# CI/CD 工作流

## 设计原则

**分离验证和部署**：
- PR 阶段：只做验证（构建、测试、契约校验），不部署
- main 合并后：自动部署到生产环境

这样既保证代码质量，又避免未审查的代码直接上线。

## ci.yml

**触发条件**：`main`、`web/*` 分支的 push，以及针对 `main` 的 PR

**工作流程**：
1. **validate-contract**: 校验数据契约（`npm run validate`）
2. **build-frontend**: 前端逻辑回归并构建（`web/` 目录）
3. **backend-regression**: 后端语义回归、接口返回校验与挑战样例验证
4. 后端回归任务还验证数据层、部署回退和公网联调脚本语法

**不包含部署**：PR 只做验证，不访问生产 secrets，不部署到任何环境。

## deploy.yml

**触发条件**：
- `main` 的 push CI 成功后自动触发；PR 的 CI 不触发部署
- 支持手动触发（workflow_dispatch），仅允许 `main` 且对应提交已有成功的 push CI
- 发布前核对当前主分支提交；过期的 CI 结果不会把旧版本覆盖回线上
- 发布串行执行，不取消正在切换服务的部署

**工作流程**：
1. 校验 `production` 的变量与部署密钥，检出本次通过 CI 的提交
2. 把 `VITE_API_BASE` 注入前端构建
3. 通过专用普通用户上传版本归档，在独立虚拟环境中安装依赖、运行后端自检
4. 保留共享配置和数据，切换代码目录并重启用户服务；启动失败自动回退
5. 从部署服务器通过公开 HTTPS 域名验证跨域、样例上传和任务查询，将结果传回 CI 校验契约；任一步失败则回退后端
6. 发布前端和 Worker 到 Cloudflare

当前采用浏览器直连 HTTPS 后端，Worker 继续托管静态资源。后端部署脚本见 [`deploy/backend.py`](../../deploy/backend.py)，公网验证脚本见 [`deploy/smoke.py`](../../deploy/smoke.py)。

公网验证复用后端版本中的 Python 与 HTTPX，无需在服务器安装 Node。这样可避免 GitHub 托管执行器被边缘人机挑战拦截；请求仍经过公开域名、TLS 和边缘代理。该检查验证部署服务器的出网路径，不能替代浏览器和其他网络的联调检查。

前端地址在构建时固定。修改 GitHub 变量后需重新运行工作流；在 Cloudflare 后台设置同名运行时变量不会改写已构建的页面。部署后通过 `?mock=0` 或顶栏切换到“真实后端”，填入 API 地址不会自动关闭示例模式。

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

- Python 3.12+、支持 `systemd --user` 的普通用户，启用该用户的 linger，使服务在退出 SSH 后及重启后继续运行。用户无需 sudo 或 Docker 权限。
- `~/app/current` 指向已有可用版本；`~/app/shared/backend.env` 保存运行配置，`~/app/shared/data` 保存任务结果。
- `~/app/venv/bin/python` 中已安装 pip，用于为新版本的 `.venv` 安装依赖；这个引导环境不随发布改动。
- 已有用户服务 `~/.config/systemd/user/hackathon-backend.service`，首次自动发布会更新为仓库中的[服务定义](../../deploy/hackathon-backend.service)。后端保持单 worker，监听本机 18000 端口。
- HTTPS 反向代理已连接本机 18000，允许前端跨域访问；TLS、域名和代理配置继续由管理员维护。

多模态服务配置仅保存在服务器的 `~/app/shared/backend.env`；未配置时图片和扫描件显式失败。工作流的上线验证使用文本层 PDF，不依赖模型密钥。

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

当前任务队列在进程内存中，部署重启可能中断处理中的任务，应在无进行中联调任务时发布；已完成的任务保留。自动部署不负责数据库迁移、OCR 模型配置或真实评测。

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
