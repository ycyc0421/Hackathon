当前阻塞是否需要额外 LLM：独立判定
2026-10-12；固定后端 fca14f56910333c4bac8c72cfd6428ffe2fb6f2a

结论：已观察到的主线阻塞不以额外通用多模态 LLM 为必需依赖。旧字段映射、状态、空列、页码与比较问题可以由后端修复。残留存在文档模型的表格结构识别限制，以及后端尚未可靠完成的区域关联/核验；应先接通选定的 PaddleOCR-VL 并用原件对照，再决定额外模型是否有必要。

1. 独立证据

核对后端证据 ZIP SHA-256：399aa468d9352a96fc98b7a6e02b29e5a3ba7a09dcf1c31dcfd496c1ac3b104f。
逐字段核查保存的 T 恤 HTTP 返回：三份 EXTRACTED；CT-2408、500 PCS；两份发票单价 2.8/总金额 1400；PL 包装20、净重150、毛重170、体积1.68，PL 金额 NOT_IN_DOC 且值为 null；来源页为1。品名比较 NOT_CHECKED。

随后把同一份保存的普通 OCR 文本与 PPStructure Markdown，分别交给旧 6a52698 和新 fca14f5 的实际读取/适配代码。不重新调用模型，禁止多模态 API，使用三份原始 PDF 字节进行页图渲染。结果：旧版 PI/CI/PL 三份均读取失败；新版三份读取成功，字段/行解析的公司、数量、金额、重量等断言通过。新版 CI/PL 仍明确留 CT-2408 品名待核验。

这说明已观察到的读取改善可以由后端对相同模型输出的适配取得，不依赖更换模型或增加 LLM。此实验是保存输出重放，不是本次新跑 OCR/HTTP，也不能证明任意模板均支持。

2. 仍有 OCR/结构模型限制，不能全归为后端

普通 OCR 保存输出包含完整、正确的商品描述和关键数值；CI 的 I/l 有字符混淆，后端利用第二路明确编号一致进行窄范围校正。
PPStructure 保存的 CI 表头缺列/跨列，PL 网格把表头、数值和主体区组合错误，现有严格 HTML 解析拒绝。因此 CI/PL 依靠单行顺序布局恢复。该恢复分支主动把品名标为未完成核验；不是已经证实品名字符读错。
普通 OCR 本身有模型识别风险，但此组 NOT_CHECKED 的直接原因包括网格不可用与核验条件，而不能只凭 OCR_TEXT_DISAGREEMENT 错误名认定读字模型失败。
进一步后端工作：保留 rec_polys/rec_boxes 等区域关系，按 SKU 与实际行区拼接多行品名，验证数值列归属；布局歧义或字符不清继续显式未知。上述改进是待验证方向，不承诺已能自动解决全部模板。

3. 当前真正的接入缺口

fca14f5 的 paddle_reader.py 实际构造 PaddleOCR 与 PPStructureV3，没有调用 PaddleOCRVL。reader.py 的额外多模态 API 仍只做逐行转写，再交给同一字段/行解析；Paddle 路径失败后直接返回失败，不自动走 LLM。
因此“配置现有 LLM”本身不保证消除纯文本扁平化与正则限制。已选定的 PaddleOCR-VL 尚未进入业务链，是模型侧输出契约与后端适配的接入工作，不等于必须调用第二个通用模型。
地址比较、PI 类型/必填规则、EDI 解析契约、完整100票与四行空HS回归、前端/部署验收，也不能通过新增 LLM 自动完成。

4. 最小闭环与额外模型决策

模型侧提供固定 VL 版本、实际可调用入口、含页面/区域/表格的原始输出；后端适配结构和证据，确定性执行数值归一、内部算术、跨文件比较。
同一原件/金标对照现有管线与 VL：普通文本、三份 T 恤扫描、空列/多行表格。分别检查字段、数值、行完整性、证据、未完成比较、耗时和资源。
若存在稳定复现、无法及时通过布局适配或主模型解决的残留，再小范围评估额外多模态模型。不能在缺少效果对照时把第二个模型设为主线前置。

公开来源
https://github.com/ycyc0421/Hackathon/blob/fca14f56910333c4bac8c72cfd6428ffe2fb6f2a/backend/app/pipeline/paddle_reader.py
https://github.com/ycyc0421/Hackathon/blob/fca14f56910333c4bac8c72cfd6428ffe2fb6f2a/backend/app/pipeline/reader.py
https://github.com/ycyc0421/Hackathon/blob/fca14f56910333c4bac8c72cfd6428ffe2fb6f2a/docs/reviews/backend-followup-fixes-2026-10-12/README.md
https://github.com/ycyc0421/Hackathon/issues/45#issuecomment-6124499111

复现（两个源码 checkout 分别执行，安装已有后端依赖）
1. 从上述后端修复报告下载 fixed-http-evidence.zip，安全解压到 <evidence>，含 shirt/*-ocr.txt 与 *-structure.md。
2. 从下面原件材料下载并解压三份 PDF 至 <originals>：
https://github.com/ycyc0421/Hackathon/blob/1a9c117b7a064dccbe8a566833cf50558897fd2a/docs/reviews/shirt-originals-2026-10-12/README.md
3. 执行：
python replay_without_llm.py --repo <6a52698或fca14f5源码> --evidence <evidence> --originals <originals> --out <结果.json>
脚本 mock 预测为保存输出，禁止 LLM 调用；断言新版读取成功时的选定字段值。无需下载或加载权重。不用于估计新模型准确率。

本次未修改业务源码、生产或 LLM 配置。检查与重放后两个源码工作树仍干净。
