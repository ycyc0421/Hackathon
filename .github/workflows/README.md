# CI/CD 工作流

## 设计原则

**分离验证和部署**：
- PR 阶段：只做验证（构建、测试、契约校验），不部署
- main 合并后：自动部署到生产环境

这样既保证代码质量，又避免未审查的代码直接上线。

## ci.yml

**触发条件**：所有分支的 push 和针对 main 的 PR

**工作流程**：
1. **validate-contract**: 校验数据契约（`npm run validate`）
2. **build-frontend**: 构建前端（`web/` 目录）

**不包含部署**：PR 只做验证，不访问生产 secrets，不部署到任何环境。

## deploy.yml

**触发条件**：
- 推送到 `main` 分支时自动触发
- 支持手动触发（workflow_dispatch）

**工作流程**：
1. 安装前端依赖并构建
2. 安装 Worker 依赖
3. 部署到 Cloudflare Worker

**使用 Environment**：`production` environment 提供额外保护层

## 所需配置

### GitHub Environment Secrets

在 https://github.com/ycyc0421/Hackathon/settings/environments/production 添加：

- `CLOUDFLARE_API_TOKEN`: Cloudflare API Token
- `CLOUDFLARE_ACCOUNT_ID`: `1dff901bbea91ab236726f6889839ff1`

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
- CI 失败不影响生产环境
