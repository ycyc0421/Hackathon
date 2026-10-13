# #38 后续修复与接口回归（2026-10-12）

本报告覆盖 #38 原审查、B 的根因补充与原件补齐，以及 D 最新的分工/验收回复。业务修复基于 `6a52698`，首轮修复提交为 `fc5f8347e9224b95383c882b4bfd31f280da570f`；后续主体拒绝守卫与测试调整见包含本报告的提交。本轮未修改生产、未合并 main。

## 已修复并验证

|问题|实现与本次证据|
|---|---|
|PDF 空 HS 后整行丢失|PyMuPDF 使用单元格坐标恢复有边框表格，保留空列；无法唯一定位仍保留保守路径。SHP-00017 HTTP 返回 HS `MISSING_IN_DOC`，数量 200、金额 454，不丢行。|
|HTML 空单元格左移|内部占位保留空列，展示原文去掉内部标记；空 HS 的数量/金额组件断言通过。|
|扫描主体交错映射|用带角色标签的结构化主体单元格提取公司，与普通 OCR 核验后映射。仅交错文本无法确定归属时 `UNRECOGNIZED`。B 的三张扫描 PNG 六个主体字段实际 HTTP 断言通过，反向公司阅读顺序组件测试通过。|
|REFERENCES CI 引用|独立识别 REFERENCES 中明确的 CI 引用；九票所有 PI/CI/PL 均返回各自 document_no 与共同 CI 引用，不比较自身编号相等。|
|PI 类型|明确 PROFORMA 标题使用现有 `OTHER`，避免被通用 invoice 文件名当作 CI，也修复 sample 文件名中 `pl` 的误匹配。没有添加公开枚举。|
|行字段页码|编排逐页解析并传实际页码；27 份文本 PDF 的有效行字段均 page=1。受控两页输入的 8 行分别保留 1/2 页。|
|扫描品名未核验|按货号附近区域寻找唯一一致的品名；单路布局恢复和两路不一致保留原文/归一值，比较为 `NOT_CHECKED`。没有把未完成 OCR 核验伪装成归一化失败或 MATCH。|
|T 恤扫描原件|三份均 EXTRACTED；自身编号 PI/CI/PL-20260830-08300186；真实公司、CT-2408、500 PCS、单价 2.80、金额 1400；PL 20 件、净重150、毛重170、1.680 CBM。PL 票/行金额均 NOT_IN_DOC，无 USD 500 或零补值。|

T 恤 CI/PL 的布局恢复仅支持验证过的严格单行表头/编号/数值/合计边界，不能推断为任意扫描模板均已支持。品名仍明确需要人工复核。结构化公司名目前核验常见公司后缀；不支持或不一致时保守返回无法识别。

## 新增覆盖能力（独立于回归修复）

- 单据内部毛重小于净重：`GROSS_BELOW_NET` WARNING，SHP-00016 第1行已命中。
- 数量×单价与行金额差异：`LINE_AMOUNT_MISMATCH` WARNING，仅已提取数值、币种一致且误差大于 0.01 时触发。SHP-00015 CI 第1行已命中；需要人工确认折扣/费用，不作为法规结论。
- 两项通过现有 errors[] 展示，未改变公开结构；未计入跨文件冲突数量。C/D 仍需按新增能力验收。
- 地址提取/比较尚未实现。应独立契约 PR 约定 `shipper_address` / `consignee_address`、可选性、来源、地址归一规则与差异含义，不能把本轮主体名称通过当作地址比较通过。

## 请求、输出与重现

请求均为 multipart `POST /api/v1/checks`，destination_country=US，其余参数未传；每票三份原件同传。结果通过 GET 任务接口与 GET 报告 format=json 保存。

[完整结果包](fixed-http-evidence.zip) / [SHA-256](fixed-http-evidence.sha256) 包含内部任务、公开 GET、完整报告、保存的两路 T 恤诊断输出、运行版本和文件哈希。

- `shirt/http-result.json`：三份 T 恤原始 PDF 实际 OCR/HTTP 输出。
- `followup-fixed/SHP-*.json`：九票 27 份文本 PDF；`SHP-00001-live-scan.json` 为三张 PNG 实际 OCR/HTTP。
- `followup-fixed/controlled-multipage.json`：复制 SHP-00019 CI 页得到的受控两页输入；这是合成来源定位测试，不是 B 所给多页原件。
- `followup-fixed/saved-ocr-replay.json`：B 保存输出的受控重放，无模型推理。
- T 恤原始两路文字为初次本地诊断保存，最终 HTTP 结果为修复后的最新重跑；详见 runtime.json。

公开 GET 与内部存储形状不同；报告现有 task 保存内部形状。12 个公开 GET 任务均通过公开 CheckTask Schema。对已有任务在隔离存储中补抓 GET 的过程没有额外模型推理。

输入包校验：B followup SHA-256 `1fd7cb0b1fcf972c2a9af9cd9c41792a3788a6cf1bcfa4b110ca319877b336ee`；T恤包 SHA-256 `06c33633b6285f20e99e626e2b94de2e84d389ad5ccba613d9e10f1285a68996`。T恤 PDF 原始字节保持不变。

```powershell
python -X utf8 backend/tools/test_review38.py
python -X utf8 backend/tools/test_paddle_adapter.py
python -X utf8 backend/tools/test_compare.py
python -X utf8 backend/tools/test_shirt_originals.py
# 先将 B 包安全解压到 backend/.out/followup
python -X utf8 backend/tools/run_followup_originals.py
```

本机为 Windows + 本地 PaddleOCR（普通 OCRv6 / PPStructureV3），oneDNN 使用默认配置；本轮原件运行成功，没有禁用 mkldnn，没有测试 PaddleOCR-VL-1.6，也不能据此评价 Linux 生产运行。

组件回归：review38 8 项中 7 通过、Windows 跳过旧 HTTP 项1项（另由本轮原件 HTTP 覆盖）；Paddle 适配5项、trade_json 5项/跳过1项、静态规则3项通过；compare 60项断言通过；review_regressions通过；npm validate四个契约示例通过。公开实际任务12份 schema通过。

## 明确未完成与交接

1. B 包只提供九票最小原件，100票的历史预测/评估不能当成本轮100票重跑。四行空HS原件未包含在此最小包，本轮不宣称已完成该原件验收。
2. C/D 需约定 PI 类型/必填与地址契约；现有 OTHER 是过渡行为，未新增 PROFORMA_INVOICE。单据内部两项警告需要单独业务验收。
3. C 确认原件金标，D 用同一输入核对实际前端显示；本报告只记录后端接口结果，不能替代 C/D 签字。
4. COMPLETED 仅处理终态；品名 NOT_CHECKED、规则未核实仍保留。没有宣称所有比较或法规检查通过。
