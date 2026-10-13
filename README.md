# 跨境单证合规校验

上传同一票货物的发票、装箱单和提单，抽取字段，比较单证之间的差异，并保留原文供人工核对。系统提供目的国演示规则提示，不判断哪份单证正确，也不代替正式合规审查。

**在线入口：[hackathon.ychome.net](https://hackathon.ychome.net)** · **[真实后端模式](https://hackathon.ychome.net/?mock=0)** · **[接口文档](https://hackathon.ychome.net/docs)**

首次访问默认使用示例模式。顶栏切换到“真实后端”，或使用 `?mock=0`；`?mock=1` 返回示例模式。选择会在浏览器中保存。线上后端已部署，无需用户另行启动或填写 API 地址。

## 当前能力与边界

以下说明覆盖本分支实现；具体交付状态、待审功能和验证记录见[项目现状与计划](docs/项目现状与计划.md)。

| 能力 | 已实现 | 边界 |
|---|---|---|
| 文件读取 | 文本层 PDF、PaddleOCR-VL-1.6 图片及扫描 PDF | 原件基线与服务器记录见[主模型交付](docs/PADDLE_VL_DELIVERY.md)；不支持 EDI 解析 |
| 字段抽取 | 数量、件数、重量、金额、币种、HS 编码等字段及归一值 | 不伪造置信度和坐标；无法归一时明确标记 |
| 多文件比对 | 整票字段、多个商品行、行序变化、缺失与冲突 | 无法可靠对齐的商品不猜测对应关系 |
| OCR 证据 | 保留原始读数；有限 O/0 校正附警告 | 多表、缺少可核验列等情况显式失败 |
| 合规提示 | US/DE/NL/FR/GB 的演示规则提示 | 规则未经正式核实，不是法律或海关结论 |
| 用户界面 | 上传、差异、报告、评测四页；报告导出与人工修正接口已实现 | 修订界面的完整团队验收仍待完成；评测仍为 `NOT_RUN` |
| 存储 | 任务与结果持久化到 SQLite，旧 JSON 自动迁入并保留兼容导出 | 重启中断的任务标记为失败，需重新上传；不支持自动续跑 |
| 发布 | 同源整站自动部署、真实 OCR 探针、失败回退 | 样例通过不等于准确率评测或容量压测 |

`COMPLETED` 只表示处理完成，`MATCH` 只表示参与比对的值一致。解析失败、未识别、未校验和仅有单一来源，都不能展示为“合规通过”。

## 使用一遍真实流程

1. 打开真实后端模式，选择同一票货物的多份文件和目的国。
2. 上传后按逐文件状态观察解析过程；文件完成后已处理计数递增，最终在差异页查看商品、字段状态、来源文件和原始读数。
3. 在报告页核对冲突、缺失、未核验及演示规则警告。评测页尚无真实跑分。

演示使用仓库的合成单证，避免上传未经确认的真实业务资料。推荐输入、预期结果和失败案例见[演示与验证指南](docs/演示与验证.md)。

## 本地开发

以下命令均从仓库根目录执行。前端使用 Node.js 20（与 CI 一致）；后端及 OCR 使用 Python 3.12。

```sh
npm ci
npm run validate
npm --prefix web ci
npm --prefix web run dev
```

开发服务器通常为 `http://localhost:5173`，默认示例模式不需要后端。构建和逻辑回归：

```sh
node --test tests/*.test.mjs
npm --prefix web run build
```

真实后端的安装、环境变量和启动命令见[后端 README](backend/README.md)。后端监听本机 8000 端口后，在另一个终端启动前端：

```sh
# POSIX shell；开发服务器代理到本地后端
VITE_PROXY_API=http://127.0.0.1:8000 npm --prefix web run dev
```

PowerShell 使用 `$env:VITE_PROXY_API = 'http://127.0.0.1:8000'`，再运行相同 npm 命令。打开 `?mock=0` 才会请求真实 API。VITE_PROXY_API 只配置开发代理，地址不带 /api/v1；可选的 VITE_API_BASE 才是前端 API 基础地址，需含 /api/v1。生产两者均无需设置，使用当前站点同源路径。

## 当前架构

```text
浏览器 → Cloudflare 代理 / HTTPS → Nginx
                                  ├─ /           → current/web/dist
                                  └─ /api/v1/... → FastAPI（本机 18000）
                                                    ├─ 文本 PDF / PaddleOCR
                                                    ├─ 抽取、归一、行对齐、比对、规则提示
                                                    └─ 共享任务数据目录
```

前端静态产物和后端独立环境存放在同一个 release，`current` 指向当前版本。Cloudflare 负责代理入口，**当前部署不再使用 Worker 托管前端**。`worker/`、`wrangler.toml` 和旧前端部署命令仍保留在仓库中，不是现行发布入口。

PR 先通过 CI；main 的 push CI 成功后触发 `Deploy frontend and backend`。在“发布整站与公网验证”job 中确认实际部署结果，不能把 CI 绿色当成已经上线。GitHub 只需一个站点地址 `SITE_ORIGIN` 和 SSH 部署凭据；见[CI/CD 配置](.github/workflows/README.md)。

## 文档与目录

| 入口 | 内容 |
|---|---|
| [文档索引](docs/README.md) | 按使用、开发、运维和交付查找文档 |
| [项目现状与计划](docs/项目现状与计划.md) | 已完成、待合并、未实现和下一步 |
| [数据契约](docs/数据契约.md) / [Schema](docs/schema/README.md) | 对外数据与校验边界 |
| [后端](backend/README.md) / [前端](web/README.md) | 安装、联调、目录与限制 |
| [数据层](data/README.md) | 独立 SQLite 表、导入器和结构化样例 |
| [演示与验证](docs/演示与验证.md) | 可复现的输入、检查项及测试命令 |
| [部署工作流](.github/workflows/README.md) / [运维手册](docs/部署运维.md) | 发布、回退、共享数据及故障排查 |
| [待确认问题](docs/待确认问题.md) / [项目要求](docs/项目要求.md) | 尚未决策事项、外部要求与范围差异 |

`backend/samples/` 是原始合成 PDF/PNG；`docs/fixtures/` 是 API 格式示例；`data/generated/` 是结构化生成测试输入。三者用途不同，不能直接当作同一份正式评测集。

## 协作与变更

- 对外任务格式以 `docs/schema/check-task.schema.json` 为准，评测格式以 `evaluation.schema.json` 为准。字段、枚举及必填性变更先评审，再同步实现与文档。
- 前端网络访问集中在 `web/src/api/`；状态文案集中在 `labels.js`，字段中文名读取后端 `label`。
- PR 说明验证方式和能力边界；提交前运行契约校验及相应模块测试。构建产物、上传文件、数据库、凭据和个人资料不提交。
- 未合并 PR 不等于线上能力；演示规则不等于已核实规则；样例回归不等于正式评测。


## 候选工作流功能

本分支增加人工修正与审计重算、JSON/HTML 报告导出、项目结构化 JSON 输入及官方来源动态监测。标准 EDIFACT/X12 尚未支持；新功能仍待合并及生产验收。详见 [工作流说明](docs/workflow-and-rules.md)。
