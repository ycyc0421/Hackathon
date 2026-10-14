# 人工修正、报告导出与规则库机制

本文档说明人工修正重算工作流、结构化报告与原件下载接口、结构化贸易 JSON 输入格式及目的国规则库设计。

---

## 1. 人工修正与派生重算

当单证扫描质量不佳或存在特殊书写习惯导致抽取值偏差时，业务人员可在报告页对已抽取字段提交人工修正：

- **修正范围**：仅允许修改已成功抽取文件（`EXTRACTED`）中已有的整票字段或商品行字段有效值；不允许凭空增删商品行，也不会篡改原始读数（`raw_value`）、原文片段（`raw_text`）或坐标证据。
- **派生任务机制**：每次修正会创建一个新的派生检查任务（`derived_task_id`），在保留原始证据的基础上重新运行单位归一化、多品名行对齐、跨文件比对与目的国规则匹配，无需重跑 OCR。原任务保持不变。
- **并发与幂等保护**：
  - `GET /api/v1/checks/{id}/corrections`：返回当前任务的结果指纹（`result_hash`）与历史修正审计链。
  - `POST /api/v1/checks/{id}/corrections`：请求体包含 `request_id`、`source_hash`、`reason`（必填）与 `changes[]`。若 `source_hash` 与服务端当前结果不一致则返回 `409 Conflict`；相同 `request_id` 与相同载荷的网络重试具备幂等性。

---

## 2. 报告导出与原件归档下载

1. **结构化报告与完整归档**：
   - `GET /api/v1/checks/{id}/report?format=json&view=content`：返回结构化报告内容（ReportContent v2），由前端生成自包含 HTML 报告（支持浏览器打印为 PDF）。
   - `GET /api/v1/checks/{id}/report?format=json&view=archive`：下载包含完整抽取结构与修正前后审计明细的 JSON 归档文件。
   - 详见 [结构化报告接口说明（v2）](report-content-api.md)。
2. **原始单证下载与能力探针**：
   - `GET /api/v1/checks/{task_id}/files/{file_id}`：以二进制附件形式（`application/octet-stream`，带 `nosniff`）下载任务保存的原始单证文件字节；派生修正任务会自动沿审计链追溯最初上传的原件。
   - `GET /api/v1/capabilities`：返回当前服务端实例支持的文件扩展名、上传大小/份数上限及扫描件 OCR 通道配置状态。

---

## 3. 结构化贸易 JSON 交换输入（`hackathon-trade-json-v1`）

除 PDF 与图片外，系统支持直接上传符合 `hackathon-trade-json-v1` 格式的 `.json` 单证文件（UTF-8 编码，上限 1 MiB、最多 200 个商品行）：

```json
{
  "format": "hackathon-trade-json-v1",
  "doc_type": "COMMERCIAL_INVOICE",
  "fields": {
    "invoice_no": "INV-001",
    "currency": "USD",
    "gross_weight": "120 KGS"
  },
  "line_items": [
    {
      "item_no": 1,
      "fields": {
        "item_code": "A1",
        "description": "CERAMIC MUG WHITE",
        "quantity": "100 PCS",
        "amount": "250.00"
      }
    }
  ]
}
```

- 字段键复用数据契约中的 `field_key`，原始值统一为字符串，度量值显式携带单位；重复键、重复行号或未知字段会显式报错拒绝。

---

## 4. 目的国规则与官方来源关联

系统内置美（US）、德（DE）、荷（NL）、法（FR）、英（GB）五国演示规则，分为两类触发逻辑：

1. **HS 归类复核（`hs_rules`）**：生成 `HS_CLASSIFICATION`（归类待复核）提示。
2. **随附支持资料提示（`certificate_rules`）**：基于目的国与 HS 编码前缀生成 `OTHER`（支持资料待人工核对）提示，并关联 `backend/app/rules/source_catalog.json` 中的官方法规来源（如欧盟食品接触材料法规、EUR-Lex 陶瓷指令、美国 FDA 陶瓷铅污染指引、英国 GOV.UK 食品包装概览）。

> **合规边界**：由于单凭 HS 编码无法断定商品具体用途（例如是否用于食品接触），且系统不对上传的附加证明文件做法律真伪鉴定，所有规则提示均标记为 `UNVERIFIED`（未经人工核实），仅作为业务复核线索，不构成强制申报指令或法律合规结论。官方法规来源的定时抓取机制见 [官方规则来源动态监测](dynamic-rule-monitor.md)。
