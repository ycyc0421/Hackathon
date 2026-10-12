# B 侧完整 EDI 验证材料

对应 [Issue #40](https://github.com/ycyc0421/Hackathon/issues/40)，补齐此前仅在本地的
**12 组、23 个原始 `.edi` 文件及独立字段/差异预期**。与 D 在 #41/#42 提供的合成
CheckTask 返回夹具和前端 U1–E1 矩阵互补。

- [一次下载完整材料 ZIP](edi-synthetic-v1.zip)
- [ZIP SHA-256](edi-synthetic-v1.zip.sha256)
- [原始报文与场景说明](../../../backend/samples/edi/README.md)
- [独立字段及差异预期](../../../backend/samples/edi/expected.json)
- [逐文件 SHA-256](../../../backend/samples/edi/manifest.json)
- [首批建议支持范围矩阵](../../../backend/samples/edi/first-batch-matrix.json)
- [有边界的素材验证结果](../../../backend/samples/edi/validation-report.json)

ZIP SHA-256：`5502ee4c277fb16f71ced188886e09e10b707078c869017fe588e99350c5565c`。
解压后根目录保留 `backend/samples/edi`、两份 `backend/tools` 脚本和总 SHA-256 清单。
Python 标准库即可执行：

```sh
python backend/tools/make_edi_samples.py --check
```

12 组检查通过是素材封装、所选段序和创作预期一致；两个故意损坏的负例被正确拒绝
才算素材检查通过。不是完整 EDIFACT 标准认证，也不是当前应用实际接口验收。

## 首批范围与职责

F 的建议为 `INVOIC:D:96A:UN`、单文件单 UNH、ASCII / 严格 UTF-8，尚待 C 确认。
本包 11 个完整单报文 INVOIC 位于该建议范围；1 个 INVOIC 段数错误为拒绝负例。
10 个 DESADV 及 1 个多 UNH 文件在首批建议范围外，保留为不支持/后续扩展素材，
不要求当前接入将其当作成功结果。特定错误码、BOM 和坏字节策略待 C/F 固定。

- C：解析器、语法、版本与编码契约。
- F：接入流程、票级/商品级映射、字段原文/单位、错误/任务状态和真实 HTTP 回归。
- D：上传、原件查看/下载、字段与失败状态展示；全部失败时也保留原件入口。
- B：完整材料、独立预期、固定版本复验及最终联合联调。

本 PR 仅发布素材、复现检查和 CI 素材检查步骤，未实现 EDI 解析、未修改业务流水线、
未部署服务。#40 保持打开，关闭前需记录真实模式上传→轮询→结果→原件查看证据。
