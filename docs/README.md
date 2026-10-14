# 文档索引

本目录汇总项目的产品说明、接口契约、评测口径、架构设计与运维指南。

---

## 按主题导航

| 主题 | 阅读入口 | 内容说明 |
|---|---|---|
| **项目概览** | [根目录 README](../README.md) · [项目现状与路线图](项目现状与计划.md) | 系统定位、核心能力矩阵、在线入口与整体进展 |
| **使用与验收** | [演示与验证指南](演示与验证.md) · [工作流与修正验收](workflow-acceptance.md) | 推荐测试样例、预期核对结果、页面检查清单与回归命令 |
| **接口与数据契约** | [数据契约说明](数据契约.md) · [报告内容接口 v2](report-content-api.md) · [JSON Schema 目录](schema/README.md) | CheckTask、ReportContent 与 Evaluation 的字段定义与校验规则 |
| **系统评测** | [系统评测与持久化](评测运行.md) | 评测数据集范围、精确率/召回率/F1 计分口径、离线运行与持久化机制 |
| **模块开发文档** | [前端说明](../web/README.md) · [前端设计系统](../web/DESIGN.md) · [后端说明](../backend/README.md) · [数据层说明](../data/README.md) | 前后端与 SQLite 数据层的目录结构、开发联调与设计规范 |
| **工作流与规则监测** | [人工修正、报告与规则库](workflow-and-rules.md) · [官方规则来源动态监测](dynamic-rule-monitor.md) | 派生修正审计、结构化交换输入与官方来源定时抓取机制 |
| **部署与模型交付** | [部署运维手册](部署运维.md) · [CI/CD 工作流](../.github/workflows/README.md) · [OCR 主模型交付](PADDLE_VL_DELIVERY.md) · [SQLite 持久化接入](../SQLITE_INTEGRATION.md) | 同源整站发布、自动回退、PaddleOCR-VL-1.6 部署配置与数据备份 |
| **背景与专项材料** | [赛题要求说明](项目要求.md) · [待确认事项与边界](待确认问题.md) · [EDI 兼容样例](fixtures/edi/README.md) · [多表与金额修正记录](review38-fixes.md) | 赛题原始要求、能力边界与专项测试数据集说明 |

---

## 数据契约与测试材料边界

1. **唯一事实来源**：对外 JSON 结构以 [`schema/check-task.schema.json`](schema/check-task.schema.json)、[`schema/report-content.schema.json`](schema/report-content.schema.json) 和 [`schema/evaluation.schema.json`](schema/evaluation.schema.json) 为准；任何字段或枚举改动须先通过 `npm run validate` 校验。
2. **测试材料分工**：

| 目录 | 用途 | 适用边界 |
|---|---|---|
| [`fixtures/result/`](fixtures/result/) · [`fixtures/raw/`](fixtures/raw/) · [`fixtures/report/`](fixtures/report/) | API 响应与单文件抽取的契约校验夹具 | 用于校验 JSON Schema 与前端渲染，非原始上传单证 |
| [`fixtures/edi/`](fixtures/edi/) · [`backend/samples/edi/`](../backend/samples/edi/) | EDI 前端兼容测试与 EDIFACT 合成报文 | 供界面兼容验收与解析器预研，不代表生产后端已启用 EDI 解析 |
| [`backend/samples/`](../backend/samples/) | 01–11 合成单证、挑战集与真实版式回归样本 | 用于端到端上传、OCR 探针与比对逻辑回归 |
| [`data/generated/`](../data/generated/) | 字段级结构化合成测试数据 | 用于数据库与比对规则单元测试，非 CheckTask API 响应 |
