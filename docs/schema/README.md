# JSON Schema 与验证

[数据契约](../数据契约.md) 描述业务语义，本目录的 JSON Schema 定义公开响应结构。修改结构时先改 Schema，再同步文档和样例；本轮文档修订不改变 Schema。

| 文件 | 用途 |
|---|---|
| [check-task.schema.json](check-task.schema.json) | 任务状态与最终结果 |
| [evaluation.schema.json](evaluation.schema.json) | 评测状态与结果 |
| [validate.mjs](validate.mjs) | 示例结构及 summary 计数检查 |

## 从仓库根目录运行

```sh
npm ci
npm run validate
# 先运行后端验证脚本生成输出，再校验真实返回目录
node backend/tools/validate_outputs.mjs backend/.out
```

输出目录以相应脚本实际写入位置为准，见[演示与验证](../演示与验证.md)。验证失败应使命令退出失败；不要用只打印错误却返回成功的临时脚本代替。

## 结构约束与业务约束

| 约束 | 当前检查边界 |
|---|---|
| canonical_value 必须为 null | Schema 强制；系统不判断哪份单证正确 |
| CONFLICT 至少两条 values，severity 为 WARNING 或 ERROR | Schema 强制；值是否真的不一致仍需业务回归 |
| SINGLE_SOURCE 恰好一条 value | Schema 的最小长度与条件最大长度共同限制 |
| NOT_CHECKED 解释未校验原因 | 后端应返回 note；当前 Schema 只约束存在时的 note，未强制该属性出现 |
| EXTRACTED / LOW_CONFIDENCE 的 normalized_value 非 null | Schema 强制 |
| NOT_IN_DOC / MISSING_IN_DOC / UNRECOGNIZED 的 normalized_value 为 null | Schema 强制 |
| 非 DONE 的评测 metrics 为 null | Schema 强制；DONE 仍允许 null，不代表已具备完整指标 |
| summary 计数与结果数组一致 | 校验脚本与后端语义验证，不是只靠 JSON Schema |

结构合法不能证明抽取准确、规则有效或商品对齐正确；还需对照原始文件和预期结果。

## 严格边界

- `additionalProperties: false` 拒绝未声明字段，增加公开字段前须同步契约。
- 示例顶层 `_comment` 由 fixture 校验脚本剔除，不属于 API 返回。
- 多品名已经支持：`items[]` 为商品目录，字段与比对通过 `item_id` 关联；单品名按票级处理时目录可为空。
- 内部 `line_items`、`alignment_status` 和 `summary.item_count` 不能直接进入公开响应。
- 字段清单和缺失语义见[数据契约](../数据契约.md)；新增业务字段还须同步抽取、归一、展示与数据层测试，不能仅改 Schema。

当前 items 的 Schema description 仍留有“第一版单品名”历史文字，但数组没有单元素约束；实际多品名能力由后端回归覆盖。本次不改 Schema JSON，后续契约维护应同步修正该注释。
