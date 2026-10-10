# JSON Schema

[`数据契约.md`](../数据契约.md) 是可读形式的约定说明，本目录是同一份约定的**可机器校验**形式。两者内容必须一致，改动时同步修改。

| 文件 | 对应接口 |
|---|---|
| `check-task.schema.json` | `GET /api/v1/checks/{task_id}` 的返回体 |
| `evaluation.schema.json` | `GET /api/v1/evaluation/latest` 的返回体 |
| `validate.mjs` | 校验脚本 |

## 用途

可读形式的契约依赖人工比对。当 C 或 F 声明已按契约实现时，缺少验证手段，字段名不一致通常要到联调阶段才暴露。

schema 使这一验证可以自动完成：将真实返回交给校验脚本，即可判定是否符合契约。该脚本在首次运行时检出两处示例数据错误（`summary` 计数与数组长度不符、`Extraction` 含未定义字段）。

## 用法

```sh
npm install          # 依赖仅 ajv 一项
npm run validate     # 校验 docs/fixtures/ 下全部样例
```

校验内容分两个层面：

1. **结构**：字段名、类型、枚举取值、必填项
2. **自洽**：`summary` 中的计数必须等于对应数组的实际长度

## 跨字段约束

以下约束只能由 schema 表达，无法在可读文档中说明：

| 约束 | 位置 | 作用 |
|---|---|---|
| `canonical_value` 必须为 `null` | `Comparison` | 系统不判断哪份文件正确 |
| `CONFLICT` 时 `values` 至少 2 条，且 `severity` 不得为 `INFO` | `Comparison` | 防止将单文件数据误报为冲突 |
| `SINGLE_SOURCE` 时 `values` 至多 1 条 | `Comparison` | 同上 |
| `NOT_CHECKED` 时必须给出 `note` | `Comparison` | 强制说明未校验原因，不允许静默跳过 |
| `EXTRACTED` / `LOW_CONFIDENCE` 时 `normalized_value` 必须有值 | `Field` | 状态为已抽出则必须给出值 |
| `NOT_IN_DOC` / `MISSING_IN_DOC` / `UNRECOGNIZED` 时 `normalized_value` 必须为 `null` | `Field` | 防止以空字符串表示"未抽取到" |
| `metrics` 仅在 `status: DONE` 时非 `null` | `Evaluation` | 未跑分不得出现数字 |

## 两项有意采用的严格设定

### 一、`additionalProperties: false`

出现未定义的键即报错。这会在联调阶段暴露"后端自行增加字段"的情况，代价是后端增加字段前须先修改 schema。此为有意设定：契约变更需要先同步。

### 二、`_comment` 不属于契约

`docs/fixtures/` 下的示例文件顶层含 `"_comment"` 键，用于说明用途。校验脚本会自动剔除该键。**后端返回不应包含此键。**

## 尚未固定的两项

以下两项未确定，因此当前契约不能称为"已冻结"：

- `field_key` 的完整取值清单。`数据契约.md` 第六节给出了一套建议命名，需 C 确认与数据库字段一致
- 多品名场景下 `comparisons[]` 的结构。当前按单品名设计

对应 [`待确认问题.md`](../待确认问题.md) 中给 C 的 #3、#5。

## 校验后端返回

将后端返回保存为 JSON 文件后执行：

```sh
cd /home/ycyc/projects/Hackathon
node --input-type=module -e "
import Ajv2020 from 'ajv/dist/2020.js'
import { readFileSync } from 'node:fs'
const ajv = new Ajv2020({ allErrors: true, strict: false })
const schema = JSON.parse(readFileSync('docs/schema/check-task.schema.json', 'utf8'))
const validate = ajv.compile(schema)
const data = JSON.parse(readFileSync(process.argv[1], 'utf8'))
if (validate(data)) console.log('符合契约')
else console.log('不符合：', validate.errors)
" /path/to/response.json
```
