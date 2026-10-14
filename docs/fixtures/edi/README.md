# EDI 前端兼容验收样例说明

本目录提供用于验证前端 EDI 报文上传、原件纯文本预览及多场景结果呈现的合成测试文件。配套的前端返回夹具位于 [`docs/fixtures/result/check-edi-*.json`](../result/)。

---

## 1. 功能定位与边界

- **前端兼容能力**：前端上传入口支持选择或拖放 `.edi` 文件（不区分大小写），并在上传列表、任务文件列表及差异页原件预览抽屉中提供**纯文本安全预览**与**原件字节下载**。
- **模式区分**：
  - 在**示例演示模式（`?mock=1`）**下，首页「EDI 报文」分组提供 6 个合成场景（单份报文、与 PDF/图片混合、双商品乱序与缺失、部分截断、后端不支持、整票解析失败），用于完整展示前端对各类 EDI 状态的渲染能力。
  - 在**真实后端模式（`?mock=0`）**下，上传页显式提示 EDI 解析取决于当前系统支持范围；后端若暂不支持该报文格式，任务将如实标记为 `UNSUPPORTED` / `FAILED`，绝不伪造通过结论。

---

## 2. 合成上传文件清单

| 文件 | 场景说明 | 核心内容预期 |
|---|---|---|
| [`invoice.edi`](invoice.edi) | 单商品标准 `INVOIC:D:96A:UN` 报文（ASCII / UTF-8） | 发票号 `SYN-INVOIC-01`，装运日期 `2026-10-14`，100 箱 / 2400 PCS 陶瓷杯，总金额 `4800.00 USD` |
| [`invoice-truncated.edi`](invoice-truncated.edi) | 截断在 `MOA+203:48` 处的损坏报文 | 缺少完整尾段（`UNT` / `UNZ`），用于验证解析失败提示与原件保留 |
| [`multi-item.edi`](multi-item.edi) | 双商品报文（含 EDIFACT 转义符与 `<script>` / `<b>` 形似文本） | 商品 `MUG350`（2400 PCS）与 `GLS300`（800 PCS），整票包装 120 箱 |
| [`multi-item-missing.edi`](multi-item-missing.edi) | 双商品逆序且缺失 `GLS300` 数量段 | 验证跨文件乱序按货号对齐，以及 `GLS300` 数量标记为 `MISSING_IN_DOC` |
| [`synthetic-packing-list.pdf`](synthetic-packing-list.pdf) / [`.png`](synthetic-packing-list.png) | 配套的一页合成装箱单（PDF 与图片版） | `MUG350` 数量为 `2500 PCS`（与 `invoice.edi` 的 `2400 PCS` 构成跨格式数量冲突） |

---

## 3. 配套契约返回夹具

下列夹具均通过 `npm run validate` 的 `CheckTask` Schema 与 `summary` 计数自洽性校验：

| 夹具文件 | 对应场景 | 预期呈现状态 |
|---|---|---|
| [`check-edi-only.json`](../result/check-edi-only.json) | 单份 `invoice.edi` | `COMPLETED`；数量/金额为 `SINGLE_SOURCE`（仅一份文件提供），日期为 `NOT_CHECKED`，不呈现为全部一致 |
| [`check-edi-mixed.json`](../result/check-edi-mixed.json) | `invoice.edi` + 装箱单 PDF/PNG | 数量 `2400 / 2500 / 2500` 判定为 `CONFLICT`；EDI 无页码（不显示页码标签），PDF/PNG 显示第 1 页 |
| [`check-edi-multi-item.json`](../result/check-edi-multi-item.json) | `multi-item.edi` + `multi-item-missing.edi` | 整票 120 箱与商品行 100/20 箱分层展示；`MUG350` 数量一致，`GLS300` 数量为 `MISSING_IN_SOME` |
| [`check-edi-partial.json`](../result/check-edi-partial.json) | 正常报文 + 截断报文 | `PARTIAL`；有效文件产出结果，截断文件保留错误原因与原件查看入口 |
| [`check-edi-unsupported.json`](../result/check-edi-unsupported.json) | 后端暂不支持 EDI 格式 | `FAILED` + `UNSUPPORTED`；零比对条目时不显示“通过”确认 |
| [`check-edi-failed.json`](../result/check-edi-failed.json) | 截断报文解析失败 | `FAILED` + `DOC_PARSE_FAILED`；保留错误记录与原件下载 |

---

## 4. 自动化回归命令

```sh
npm run validate
node --test tests/edi-mock-schema.test.mjs tests/edi-source.test.mjs
```
