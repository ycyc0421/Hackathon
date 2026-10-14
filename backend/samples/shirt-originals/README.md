# T 恤组扫描单证样本与人工金标

本目录包含同一票出口货物的三份扫描版 PDF 样本（形式发票、商业发票、装箱单）及人工核对金标 [`golden-fields.json`](golden-fields.json)，用于验证 `PaddleOCR-VL-1.6` 对内嵌图像 PDF 的版面识别与跨单证比对能力。

---

## 1. 样本文件与核心字段金标

| 单证类型 | 文件名 | 单据自身编号（`document_no`） | 商品数量 | 金额 / 包装与重量数据 |
|---|---|---|---|---|
| **形式发票（PI）** | [`exportdoc-proforma-invoice-sample.pdf`](exportdoc-proforma-invoice-sample.pdf) | `PI-20260830-08300186` | `500 PCS` | 总金额 `USD 1,400.00`；单价 `USD 2.80` |
| **商业发票（CI）** | [`exportdoc-commercial-invoice-sample.pdf`](exportdoc-commercial-invoice-sample.pdf) | `CI-20260830-08300186` | `500 PCS` | 总金额 `USD 1,400.00`；单价 `USD 2.80` |
| **装箱单（PL）** | [`exportdoc-packing-list-sample.pdf`](exportdoc-packing-list-sample.pdf) | `PL-20260830-08300186` | `500 PCS` | 包装 `20 PKGS`；净重 `150.00 KGS`；毛重 `170.00 KGS`；体积 `1.680 CBM`（无金额列） |

- **共同商品信息**：SKU `CT-2408`，品名 `100% Cotton T-shirt, unisex, assorted colors`，HS 编码 `6109.10`（PI/CI），卖方 `Ningbo Qihang Export Co., Ltd.`，买方 `Global Fashion Inc.`。
- **关键核验点**：
  1. 三份 PDF 均仅含页码文本层（`1 / 1`），正文全部为嵌入扫描图像，必须触发 OCR 通道完成抽取。
  2. 装箱单虽印有 `CURRENCY USD` 字样但无金额数值，系统须保持金额为 `NOT_IN_DOC`，不将数量 `500` 误拼为金额。
  3. 各单证自身的编号（`PI-...` / `CI-...` / `PL-...`）记录于 `document_no`，不作跨单证相等比较。

---

## 2. 运行验证命令

在已启用本地 `PaddleOCR-VL-1.6` 服务的环境下执行：

```sh
python backend/tools/test_shirt_originals.py
python backend/tools/accept_paddle_vl.py
```
