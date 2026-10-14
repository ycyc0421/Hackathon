# CI/CD 自动验证与整站发布工作流

仓库采用两阶段流水线：Pull Request 触发全套自动化验证（`ci.yml`）；合并至 `main` 并通过验证后，自动触发同源整站发布与公网端到端探针（`deploy.yml`）。前端静态资源与 Python 后端部署于同一生产节点（`https://hackathon.ychome.net`），通过 Nginx 同源对外提供服务。

日常巡检、备份与故障排查见 [部署与运维手册](../../docs/部署运维.md)。

---

## 1. 持续集成（`ci.yml`）

在每次 PR 更新与 `main` 推送时执行，不访问生产环境凭据：

- **数据契约与前端构建**：执行 `npm run validate` 校验全部 JSON Schema 与示例夹具，运行 `node --test tests/*.test.mjs`（119 项前端与报告生成单测），并执行 `vite build` 产出 `web-dist` 构建产物。
- **后端单元与接口回归**：使用 Python 3.12 运行 `python -m pytest`，自动发现 `backend/tests/` 下的全部用例；每个测试自动隔离临时 SQLite 数据库与上传目录，并对接口输出执行 Ajv Schema 与计数自洽性校验。
- **数据层与部署脚本回归**：在独立矩阵任务中运行 `data/` 与 `deploy/` 下的单元测试（`fail-fast: false`），验证数据库迁移、环境指纹复用与自动回退逻辑。

---

## 2. 整站自动发布（`deploy.yml`）

由 `revision` 与 `deploy-backend` 两个串行作业组成，仅允许已通过 `main` CI 的最新提交发布上线：

### 发布与预检步骤

1. **产物复用**：直接下载同一提交在 `ci.yml` 中构建通过的 `web-dist` 静态产物，与后端代码打包为版本归档上传至服务器 `~/app/releases/<发布标识>`。
2. **Python 环境指纹缓存**：根据 Python 版本、平台及依赖声明文件计算指纹，在 `~/app/shared/python-envs/<指纹>` 下创建或复用虚拟环境，并在发布目录记录 `requirements.lock`。
3. **上线前预检**：在隔离临时目录运行后端回归测试；若启用 OCR，则校验固定模型权重与引擎哈希，并实跑本地 OCR 探针。
4. **原子切换与公网探针**：更新 `~/app/current` 软链接并重启 `systemd --user` 服务，随后从公网源地址依次验证：
   - 首页与静态资源可达性；
   - API 健康检查与文本层 PDF 上传、轮询及返回 Schema；
   - 启用 OCR 时的多品名图片与无文本层扫描 PDF 端到端核验。
5. **失败自动回退**：任一预检或公网探针失败时，立即停止新服务，将 `~/app/current`、依赖环境与 systemd 配置恢复至上一可用版本；跨版本共享的任务与评测数据（`~/app/shared/data`）保持不变。

---

## 3. GitHub Production 环境配置

在仓库 `production` 环境的 Secrets 中配置以下项：

| Secret 名称 | 说明 |
|---|---|
| `SITE_ORIGIN` | 生产站点源地址（如 `https://hackathon.ychome.net`），供公网探针使用 |
| `BACKEND_SSH_HOST` | 部署服务器域名或 IPv4 地址 |
| `BACKEND_SSH_USER` | 服务器普通维护用户名（非 `root`） |
| `BACKEND_SSH_KEY` | 专用部署 SSH 私钥 |
| `BACKEND_SSH_KNOWN_HOSTS` | 预先核验的服务器主机公钥记录 |

---

## 4. 服务器基础环境要求

首次接入自动部署前，服务器需具备以下基础条件：

- **运行账户与服务管理**：普通维护用户已启用 `loginctl enable-linger`，可通过 `systemd --user` 管理 `hackathon-backend.service`（监听 `127.0.0.1:18000`）及 OCR 模型服务（监听 `127.0.0.1:18082` / `18083`）。三个服务同属 `hackathon.slice`（总内存上限 8 GiB，CPU 配额 4 核）。
- **目录布局**：
  - `~/app/current`：指向当前生效的发布版本目录；
  - `~/app/shared/backend.env`：保存服务端运行环境变量；
  - `~/app/shared/data`：保存跨版本持久化的 SQLite 数据库、上传原件与 `evaluation/` 评测结果；
  - `~/app/venv/bin/python`：提供支持 `--python` 参数的 `pip` 引导工具。
- **Nginx 反向代理**：静态根目录指向 `~/app/current/web/dist`（SPA 路由回退至 `index.html`），并将 `/api/`、`/health`、`/docs`、`/openapi.json` 代理至 `http://127.0.0.1:18000`，请求体上限支持单次最多 10 份 × 20 MiB 文件上传。

---

## 5. 手动巡检与版本回退

在服务器维护用户下查看服务状态或执行回退：

```sh
systemctl --user status hackathon-backend --no-pager
journalctl --user -u hackathon-backend -f

# 将当前版本回退至其记录的上一可用版本
python3 ~/app/current/deploy/backend.py <当前发布标识> --rollback
```
