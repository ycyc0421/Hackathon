# 文档索引

项目包含前端、后端、OCR、独立数据层和整站发布流程。本目录不再只是前端提出的接口草案。

## 按任务阅读

| 想做什么 | 阅读入口 |
|---|---|
| 了解项目并打开线上应用 | [根 README](../README.md) |
| 确认哪些能力已交付 | [项目现状与计划](项目现状与计划.md) |
| 走一遍演示、复现回归 | [演示与验证](演示与验证.md) |
| 验收 EDI 前端兼容 | [EDI 合成输入、返回夹具与验收矩阵](fixtures/edi/README.md) |
| 启动后端或配置 OCR | [后端 README](../backend/README.md) |
| 开发页面或切换数据源 | [前端 README](../web/README.md)、[设计系统](../web/DESIGN.md) |
| 对接接口、排查字段语义 | [数据契约](数据契约.md)、[Schema 使用说明](schema/README.md) |
| 跑评测、看分数口径与范围 | [系统评测与持久化](评测运行.md) |
| 初始化独立 SQLite 测试库 | [数据层 README](../data/README.md) |
| 配置 GitHub 自动部署 | [CI/CD 工作流](../.github/workflows/README.md) |
| 查线上版本、回退、排障 | [部署运维](部署运维.md) |
| 确认未决事项与交付要求 | [待确认问题](待确认问题.md)、[项目要求](项目要求.md) |

## 事实来源与更新规则

1. **对外数据结构**以 [CheckTask Schema](schema/check-task.schema.json) 和 [Evaluation Schema](schema/evaluation.schema.json) 为准。[数据契约](数据契约.md)解释其语义，不另造一套字段。
2. **实际行为**核对当前分支代码；后端内部模型、数据库表和对外 JSON 不是一一相同的对象。
3. **线上状态**看对应提交的部署运行及公网验证，不以 PR 描述、CI 构建产物或本地修改推断已上线。
4. **状态快照**集中在[项目现状与计划](项目现状与计划.md)，标明日期与基线。功能合并后同时更新限制和待办，避免到处复制易过期的测试数量。
5. **环境值和凭据**不写入公开文档；配置表使用占位示例。文档不引用本地私人资料路径。

新增或变更契约时，先改 Schema、校验 fixtures，再同步可读文档、前后端与数据层；破坏性变更须先在 Issue 协调。仅纠正文档与已存在 Schema 的差异，不需要改写 Schema。

## 验证材料

| 目录 | 用途 | 不代表什么 |
|---|---|---|
| [fixtures/result](fixtures/result/)、[fixtures/raw](fixtures/raw/) | API 返回和单文件抽取结构示例 | 不是原始上传文件 |
| [fixtures/edi](fixtures/edi/) | EDI 兼容测试的合成上传文件与验收说明 | 不是后端已支持 EDI 的证据或实际业务金标 |
| [backend/samples](../backend/samples/) | 合成单证、挑战样例及预期结果 | 不是实际业务准确率评测 |
| [data/generated](../data/generated/) | 字段级结构化测试输入 | 不是原始 OCR 图片，也不一定可直接提交 API |

多品名 `items[]` 与 `item_id + field_key` 已在当前接口实现。评测的计分口径与运行范围见[系统评测](评测运行.md)；仍待决策的是正式适用规则及新增业务范围，不应再把多品名结构写成未确定。
