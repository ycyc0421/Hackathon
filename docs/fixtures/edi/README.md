# EDI 前端兼容验收样例

对应 [Issue #40](https://github.com/ycyc0421/Hackathon/issues/40)。核对基线为 `main@7f92e59a3ab3dcc3d79522ed25de7b619a0d93f4`，日期为 2026-10-12。

本目录提供合成上传文件，配套的 `../result/check-edi-*.json` 是**手工构造的前端返回夹具，不是真实接口输出**。原始文件、夹具中的 `input.notes` 均标明测试用途。它们不证明后端已支持 EDI，也不构成模型评测、法规结论或实际业务数据。

## 范围与接口

- 第一阶段前端接受 `.edi`，扩展名不区分大小写；`.txt` 暂不接受。C/F 尚需确认后端报文类型、版本、编码及多报文等边界。本包仅提供 `INVOIC:D:96A:UN` 的合成文本，不据此宣称覆盖所有 EDI。
- 复用 [CheckTask Schema](../../schema/check-task.schema.json) 中已有的 `file_type=EDI`、`parse_method=EDI_PARSE`、`items[]`、`item_id`、字段状态和任务错误，不新增公开字段或枚举。
- `POST /api/v1/checks` 使用 multipart 的 `files` 和 `destination_country`，随后轮询 `GET /api/v1/checks/{task_id}`。保留文件名和原始字节，不把解码后的文本重新编码后上传。
- 沿用最多 10 份、每份不超过 `20 × 1024 × 1024` 字节及现有同名歧义检查。文件选择、拖放、支持说明一致；PDF/图片继续使用原有路径。
- 当前基线后端将 `.edi` 识别为 `OTHER`，返回 `UNSUPPORTED` 和 `UNSUPPORTED_FILE_TYPE`；全不支持时任务为 `FAILED`。前端接受文件仅表示允许提交，真实模式须如实说明解析能力依赖后端。
- D 负责前端、契约与展示核验；C 负责 EDI 解析及金标，F 负责流水线接入与接口能力声明，B 参与集成验收。

## 上传文件

| 文件 | 用途 | 独立预期 |
|---|---|---|
| [invoice.edi](invoice.edi) | Issue 中的最小报文，ASCII/无 BOM UTF-8 | 1 个商品；`UNH` 到 `UNT` 共 26 段；见下表 |
| [invoice-truncated.edi](invoice-truncated.edi) | 从最小报文截断在 `MOA+203:48` | 没有完整尾段，不能当作完整解析成功 |
| [multi-item.edi](multi-item.edi) | 双商品、转义字符与 HTML 形似文本 | MUG350 / GLS300 数量为 2400 / 800，行号为 1 / 2；包装合计 120 箱 |
| [multi-item-missing.edi](multi-item-missing.edi) | 反转商品顺序，并去掉 GLS300 的 QTY 段 | GLS300 / MUG350 行号为 1 / 2；前者数量缺失，后者仍为 2400 |
| [synthetic-packing-list.pdf](synthetic-packing-list.pdf) | 一页合成装箱单 | MUG350 数量 2500 PCS、毛重 1080 KGS；没有金额 |
| [synthetic-packing-list.png](synthetic-packing-list.png) | 上述 PDF 的图片版 | 与 PDF 同一份合成内容，用于图片原文路径检查 |

PDF/PNG 仅是同一份合成内容的两种载体，不是两份独立业务证据。混合夹具让三种文件类型一起出现以检查界面兼容，不据来源票数判断哪个值正确。文件 SHA-256 见 [SHA256SUMS](SHA256SUMS)。

`invoice.edi` 的字段预期如下。单位沿用现有契约，报文中的单位代码保留在原文中；这些值是输入的创作预期，真实映射仍需 C/F 确认。

| 归属 | 字段或原文 | 预期 |
|---|---|---|
| 整票 | `invoice_no`，BGM | SYN-INVOIC-01 |
| 整票 | `shipment_date`，DTM+11 | 2026-10-14 |
| 整票 | `shipper` / `consignee`，NAD | SYNTHETIC SUPPLIER LTD / SYNTHETIC BUYER LTD |
| 整票 | `destination_country` / `currency` | US / USD |
| 整票 | `packages` | 100 CARTON；原文单位 CT |
| 整票 | `gross_weight` / `net_weight` | 1080 / 900 KGS；原文单位 KGM |
| 整票 | `volume` | 4.80 CBM；原文单位 MTQ |
| 整票 | `total_amount`，MOA+77 | 4800.00 USD |
| `item_mug` | `item_code` / `description` | MUG350 / CERAMIC MUG 350ML WHITE |
| `item_mug` | `hs_code` | 字符串 691110；只是合成输入，不代表正确归类 |
| `item_mug` | `quantity` / `unit_price` | 2400 PCS / 2.00 USD；数量原文单位 PCE |
| `item_mug` | `total_amount`，MOA+203 | 4800.00 USD，与票级金额分层 |
| `item_mug` | `packages` / `gross_weight` / `net_weight` | 100 CARTON / 1080 KGS / 900 KGS |
| 原件保留 | `RFF+ON:SYN-ORDER-01` | 订单引用；不擅自映射成 `contract_no`，本夹具不为它新增业务字段 |

本夹具仅输出商品行的 `quantity`，没有伪造票级 QTY。后端若提供票级数量合计，应明确标注“商品行求和”及来源，不能冒充报文中存在票级数量段。前端不做该项业务推导，也不把票级和行级金额、箱数、重量重复相加。

双商品报文的商品包装件数分别为 100、20，票级为 120；行金额分别为 4800、2400 USD，票级为 7200 USD。第二份报文虽保留金额和单价，GLS300 的缺失数量也不能由前端反推。

## 返回夹具

下列文件均可直接通过现有 `npm run validate` 的 CheckTask 结构及 summary 自洽检查。前端测试环境可加载它们；真实模式仍须消费真实接口返回。

| 返回文件 | 配套上传文件 | 必须观察到的状态 |
|---|---|---|
| [check-edi-only.json](../result/check-edi-only.json) | invoice.edi | `COMPLETED`；数量/金额 `SINGLE_SOURCE`、日期 `NOT_CHECKED`，0 冲突不等于全部通过 |
| [check-edi-mixed.json](../result/check-edi-mixed.json) | invoice.edi + synthetic-packing-list.pdf/.png | 数量 2400/2500/2500 为 `CONFLICT`，毛重为 `MATCH`；装箱单金额 `NOT_IN_DOC`，金额比对未完成 |
| [check-edi-multi-item.json](../result/check-edi-multi-item.json) | multi-item.edi + multi-item-missing.edi | MUG350 数量 `MATCH`，GLS300 为 `MISSING_IN_SOME`；第二份相应字段 `MISSING_IN_DOC` |
| [check-edi-partial.json](../result/check-edi-partial.json) | invoice.edi + invoice-truncated.edi | `PARTIAL`；有效文件仍有结果，失败文件、错误和不完整提示均保留 |
| [check-edi-unsupported.json](../result/check-edi-unsupported.json) | invoice.edi | 当前后端兼容形态：`OTHER` / `UNSUPPORTED`、任务 `FAILED`，没有抽取或比较结果 |
| [check-edi-failed.json](../result/check-edi-failed.json) | invoice-truncated.edi | 接入解析后的合成失败形态：文件和任务 `FAILED`，`DOC_PARSE_FAILED` 与 `ALL_DOCUMENTS_FAILED` |

部分夹具只选择与场景有关的字段，不是完整字段覆盖金标。截断夹具的错误码复用现有解析失败表达，最终错误粒度待 F 确认，不要求后端逐字返回本包错误文案。若后端已识别 EDI 但不支持其报文版本，`EDI / UNSUPPORTED` 也须正确展示，不能仅支持本包的 `OTHER / UNSUPPORTED`。

## 原文、来源和状态约束

- EDI 的 `page_count`、字段和比较值的 `page/bbox` 为 null，`bbox_unit` 为 null；本包全部置信度为 null。不得补第 1 页、OCR 框或默认置信度。
- 关联字段使用 `file_id + item_id + field_key`，同名票级字段的 `item_id=null`；原始 `line_no` 不是跨文件商品身份。`label` 来自返回体，不在前端建立字段中文名映射。
- 原文查看必须按纯文本处理，保留分隔符、release 字符、换行和原始顺序；原文件下载保留字节。展示解码后的业务值不等于改写原件。
- 双商品报文包含 `?+`、`?:`、`??`、`?'` 和 HTML 形似文本。原文显示编码串；夹具的商品描述值为 `CERAMIC MUG+SET:350ML?WHITE'S <b>TEST</b>`。`<b>`、`<script>` 都须作为文字显示，不能解释成 HTML。
- 只有浏览器内存中确有对应原始 File 时才提供原件操作；没有原件时明确不可用，不用 `raw_text` 拼造完整文件。全部失败时没有 comparison，仍应能从上传文件或文件状态列表查看/下载已保留的 EDI。
- `NOT_IN_DOC`、`MISSING_IN_DOC`、`UNRECOGNIZED`、`NORMALIZE_FAILED` 和文件处理失败按各自状态展示；缺值不用 0 补齐。后两种字段状态继续使用现有 [check-partial.json](../result/check-partial.json) 回归。
- `COMPLETED`、HTTP 200、空比较数组、0 冲突均不能单独推出校验通过；`NOT_CHECKED` 的 note 和任务错误不得隐藏。

## 验收矩阵

| 编号 | 操作 | 预期 |
|---|---|---|
| U1 | 选择、拖放 invoice.edi 及只改名的 INVOICE.EDI；对照同内容 .txt、PDF、PNG | 两条入口对扩展名行为一致；.txt 拒绝，其他按范围接受 |
| U2 | 10/11 份、恰好 20 MiB/多 1 字节、同名不同大小文件 | 保留现有限额和同名歧义拦截；原文不关联到另一份同名文件 |
| U3 | 真实模式提交并核对请求、服务端保存/接收内容 | multipart 的 files 保留文件名、字节哈希和 destination_country；轮询对应 task_id |
| S1 | 加载 EDI-only、混合夹具 | 状态、单位和原文来自返回；冲突不指定正确来源；无 EDI 页码 |
| S2 | 加载双商品夹具，展开数量和包装对照 | 商品乱序不串字段；缺失不被其他商品掩盖；票级 120 与行级 100/20 分开 |
| S3 | 加载部分失败、不支持和全部失败夹具 | 保留失败原因、不完整提示；不展示整体通过，失败原件仍可查看/下载 |
| S4 | 将不支持夹具的文件类型改为 EDI 后再加载 | 同样展示 UNSUPPORTED；不依赖 OTHER 的特判 |
| O1 | 打开双商品原件，检查转义串和 HTML 形似文本 | 内容为纯文本，窗口/页面不会执行其中脚本；下载哈希不变 |
| O2 | 切换 EDI/PDF/图片原件，随后移除文件或刷新 | PDF/图片原功能正常；无原始 File 时如实降级；没有白屏/控制台错误 |
| E1 | C/F 接入后，用真实模式重跑各类原件 | 保留上传→轮询→终态→原文证据和字段预期/实际对照，不能用 mock 代替 |

校验命令（仓库根目录）：

```sh
npm run validate
node --test tests/*.test.mjs
npm --prefix web run build
```

前端实现后还需 `npm --prefix web run dev` 走上述页面。构建与夹具校验通过仅说明本阶段材料或实现可验证，不证明 E1 已通过。当前 E1 尚未执行，#40 保持打开。

## 真实联调证据模板

| 项目 | 回填内容 |
|---|---|
| 执行信息 | 日期、前后端提交、环境、真实模式标识 |
| 输入 | 文件名、原始 SHA-256、目的国、请求参数 |
| 请求和任务 | 上传返回、task_id、轮询终态、完整 CheckTask 或错误返回 |
| 字段对照 | file_id、item_id、field_key、预期值/单位/状态、实际值/单位/状态、原文 |
| 原件操作 | 查看截图/录屏、下载 SHA-256、没有 page/bbox 时的降级 |
| 结论 | 通过/失败/未运行、未完成原因、后续负责角色 |

B 在 issue 中提到的 12 组、23 个 EDI 文件尚未包含在本包内。收到可共享材料后再扩充真实解析验收；逗号小数、多 UNH、错误 UNT 等能力边界由 C/F 明确，本包不替解析器声明支持。
