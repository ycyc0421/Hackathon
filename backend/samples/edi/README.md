# 合成物流 EDI 回归素材 v1

本目录包含 **12 组、23 个 `.edi` 文件**，采用 UN/EDIFACT D.96A 的选定字段子集。
公司、地址、订单号、发票号、交易及商品数据全部为合成测试数据；不得用于申报或付款。

团队可获取的完整下载包及校验值见 [B 侧材料索引](../../../docs/fixtures/edi-full/README.md)。

`INVOIC` 表达商业发票，`DESADV` 表达发运通知及包装/商品明细。
**DESADV 不是正式提单或报关单，本包未生成提单、报关单或原产地证。**
当前应用的 EDI 上传和解析接入仍未实现。本次仅补充素材、生成器和素材检查器，
`validation-report.json` 的通过状态不代表应用解析通过、真实业务验收通过或完整标准认证。

## 与 #40 首批接入建议对齐

F 在 [#40 的 2026-10-12 回复](https://github.com/ycyc0421/Hackathon/issues/40#issuecomment-6123316495)
建议首批为 `INVOIC:D:96A:UN`、单文件单个 UNH、ASCII / 严格 UTF-8；C 尚需确认
解析契约。`.txt` 暂不启用，BOM 和坏字节行为仍需明确。本包 `.edi` 字节均为 ASCII，
属于无 BOM 的严格 UTF-8 子集，不包含非 ASCII 或坏编码验收素材。

**素材语法预期与首批 API 能力预期是两回事：**

| 素材类别 | 文件数 | 在首批建议范围中的位置 |
|---|---:|---|
| 单 UNH、INVOIC、语法完整 | 11 | C 确认建议后用于解析及字段回归；06 仍有业务字段缺席 |
| 单 UNH、INVOIC、错误 UNT 段数 | 1 | 无效报文负例，应显式拒绝，不发布貌似完整的字段 |
| 单 UNH、DESADV | 10 | 首批建议范围外；其中 12 还缺少尾段，错误优先级待 C/F 固定 |
| 一个 UNB 内多个 UNH | 1 | 首批建议范围外，不允许悄悄只处理第一条报文 |

逐文件信息见 `first-batch-matrix.json`。本包保留完整场景供后续扩展，但不要求 C/F
将 DESADV 或多 UNH 纳入首批。数量和重量跨 INVOIC/DESADV 的正确性预期只在两种
类型都被正式接入后执行；首批未支持 DESADV 时应检查 UNSUPPORTED/FAILED/PARTIAL
状态，不能要求它参与比较。金额和币种场景含两份 INVOIC，可先按支持范围验证。

#41 / #42 的六个 CheckTask 返回夹具属于 D 的合成界面材料；本目录则是 B 的完整
原始报文与独立字段/差异预期，两者互补，不把合成返回当作真实 API 结果。

## 文件与场景

| 目录 | EDI 文件数 | 内容和预期 |
|---|---:|---|
| `01_consistent` | 2 | 单商品数量、包装、净毛重、HS 相同；金额只由发票承担 |
| `02_quantity_conflict` | 2 | 商品数量 2400 / 2380 PCE，包装件数均为 100 CT |
| `03_net_gross_swapped` | 2 | 发运通知故意把净毛重交换；语法完整，业务值错误 |
| `04_amount_conflict` | 3 | 发票原件、副本和发运通知；单价 2.00 / 2.10，总金额 4800.00 / 5040.00 |
| `05_currency_conflict` | 3 | 发票原件、副本的金额数字相同，币种 USD / EUR 不同 |
| `06_missing_hs_currency` | 2 | 发票省略 HS、币种；缺席保持空值，不借用其他文件字段或默认 USD |
| `07_multiitem_reordered` | 2 | 三个商品，发票和发运通知行序不同，货号关系保持一致 |
| `08_release_characters` | 2 | 品名含 `+`、`:`、`?`、`'`，验证 release 字符转义 |
| `09_decimal_comma_compact` | 2 | UNA 指定逗号小数，报文不依赖行间换行 |
| `10_multi_message` | 1 | 同一 UNB/UNZ 内包含一份 INVOIC、一份 DESADV，UNZ 计数为 2 |
| `11_bad_unt_count` | 1 | **故意损坏的负例**：UNT 段数加一，预期拒绝 |
| `12_truncated` | 1 | **故意损坏的负例**：缺 UNT 和 UNZ，预期拒绝 |

每组用相同 `RFF+ON` 订单引用关联同票；DESADV 用 `RFF+IV` 引用对应发票号。
两个金额/币种场景用同发票号的原件和副本表达差异，不跨不同订单比较价格。
目的国来自 `NAD+CN` 的收货人国家；`NAD+CZ` 的发货人国家为 CN，不能误当目的国。

## 预期与证据

- `expected.json`：由合成数据的创作模型生成，独立于应用实际接口结果；包括每个报文的
  单证编号、关联引用、国家、日期、币种、票级字段、商品行和预期差异。
  数量、重量、金额、单位分别记录，金额使用精确十进制字符串。
- `manifest.json`：每个原始 EDI 文件的相对路径、字节数和 SHA-256。
- `validation-report.json`：本包素材检查结果；两个负例被识别为预期错误才算素材检查通过。

这些预期用于未来 EDI 解析器回归，不是当前接口返回，也未经人工业务金标验收。
`expected_discrepancies` 是按相同字段作用域、货号和金额币种计算的差异清单；
不要求未来接口逐字复用此结构，不包含正式目的国法规判定或正确 HS 归类结论。

字段缺席不自动等价于原件缺失或合规违规。例如 06 中 HS 未出现，只证明该发票没提供
该值；不据此编造法规要求。负例不应产生“完成、零冲突”的结果。

## 本包字段限定符

| 字段 | 本包表达 | 作用域与注意事项 |
|---|---|---|
| 发票/发运通知编号 | `BGM+380` / `BGM+351` 的编号 | 两类单证编号不要求相同 |
| 单证日期 / 发运日期 | `DTM+137` / `DTM+11`，格式 102 | 不能把签发日期当发运日期 |
| 商品货号 / HS | `LIN` 中 SA / `PIA` 中 HS | HS 为测试值，不宣称归类已核实 |
| 商品描述 | `IMD+F` 的自由文本 | 保留转义后的原始字节，解析时解码服务字符 |
| 发票数量 / 发运数量 | `QTY+47` / `QTY+12`，PCE | 包装件数不当作商品数量 |
| 包装件数 | `PAC`，类型 CT | INVOIC 有整票及商品 PAC；DESADV 每个 CPS 对应一个商品包装组 |
| 票级毛重 / 净重 | `MEA` 的 AAD / AAC，KGM | 与商品级重量区分 |
| 商品级毛重 / 净重 | `MEA` 的 AAE / AAL，KGM | AAE 为行级毛重，AAL 为净重；不把单件重当整行重 |
| 票级体积 | `MEA` 的 AAW，MTQ | 本包不在每个商品行重复整票体积 |
| 行金额 / 发票总金额 | `MOA+203` / 摘要中的 `MOA+77` | 与数量、单价分别解析 |
| 单价 | `PRI+AAA`，基数 1 PCE | 本包无税费和折扣，行金额为数量乘单价 |
| 发票币种 | `CUX+2:<币种>:4` | 06 故意省略，不能填默认值 |

**派生量明确区分：** 两类报文的票级商品数量由商品行求和；DESADV 的整票包装件数
由 CPS 包装组求和。`expected.json` 的 `quantity_source`、`packages_source` 标明这些
来源，不伪称原报文存在对应票级字段。当前语义单位为 PCE / KGM / CT / MTQ，
若映射项目的 PCS / KGS / CARTON / CBM，应记录单位映射。

## 本地复现

在仓库根目录执行，Python 标准库即可，不需要 OCR、模型或第三方库：

```powershell
# 仅检查已有文件，不重写 EDI 或预期
python backend/tools/make_edi_samples.py --check

# 在一个新目录重新生成，便于比较哈希
python backend/tools/make_edi_samples.py --output D:/hackson/tmp/edi-reproduction
```

不带参数的生成命令写入本目录；回归原件时使用 `--check`，避免意外重新生成。
素材检查器 `backend/tools/validate_edi_samples.py` 按独立读取逻辑检查 UNA、release 字符、
UNH/UNT 和 UNB/UNZ 控制引用及计数、所选字段子集的段序、商品数、解码字段与预期。
它是有边界的素材检查器，不是生产 EDI 解析器，也没有穷尽 D.96A 数据元素约束或任何
交易伙伴实施指南（MIG）。

## 参考来源

编写时查阅 UNECE 官方目录与段表，采用上述选定子集：

- [D.96A INVOIC 段表](https://service.unece.org/trade/untdid/d96a/trmd/invoic_s.htm)
- [D.96A DESADV 段表](https://service.unece.org/trade/untdid/d96a/trmd/desadv_s.htm)
- [D.96A 7143 商品编号类型：HS 与 SA](https://service.unece.org/trade/untdid/d96a/uncl/uncl7143.htm)
- [D.96A 6313 测量类型：票级与商品级净毛重](https://service.unece.org/trade/untdid/d96a/uncl/uncl6313.htm)

README 中的段语义描述用于本包复现与审阅；标准符合性仍需完整目录和目标交易伙伴
实施指南验证。本包没有将某次应用输出写成预期答案，也没有更改现有 PDF/图片原件。
