# 数据层：SQLite 存储结构、样例导入与合成数据生成

本目录定义系统底层 SQLite 关系表结构（`schema.sql`）、数据库初始化工具（`init_db.py`）、任务数据导入器（`seed_data.py`）与结构化合成测试数据生成器（`generator.py`）。后端生产运行库直接复用此处的表结构与事务写入逻辑，详见 [SQLite 持久化接入说明](../SQLITE_INTEGRATION.md)。

---

## 快速使用

在仓库根目录执行：

```sh
# 1. 初始化本地示例数据库（生成 data/app.db）
python data/init_db.py

# 2. 导入默认任务样例
python data/seed_data.py

# 3. 导入指定结构化测试样例
python data/seed_data.py --input data/generated/normal_multi.json
```

> `data/app.db` 为本地运行生成的数据库文件，已被 Git 忽略；生产环境运行库默认位于 `backend/.data/tasks.sqlite3`，与本地示例库相互独立。可通过 `--db <路径>` 指定目标数据库文件。

---

## 表结构与版本管理

数据库结构版本通过 SQLite `PRAGMA user_version` 标识（当前版本为 `1`）：

| 表名 | 用途说明 |
|---|---|
| `tasks` | 检查任务主表（状态、目的国、汇总计数、错误列表 JSON、时间戳） |
| `items` | 任务内商品行目录（`item_id`、展示名、描述、文件内行号） |
| `documents` | 上传单证清单（`file_id`、文件名、单证类型、处理状态、解析方式、页数） |
| `extracted_fields` | 逐文件抽取的字段明细（原文、原始读数、归一值 JSON、单位、状态、页码与坐标） |
| `comparisons` | 跨文件比对结论（字段键、关联商品、比对状态、严重度、规则编号、核对建议） |
| `comparison_values` | 比对条目下各来源文件的取值与字段状态 |
| `risks` | 目的国合规与归类风险提示（风险类型、严重度、标题、详情、规则编号与来源） |
| `hs_dictionary` / `golden_cases` | HS 编码字典与金标参考用例表 |

- **幂等初始化与同版本升级**：对相同 `user_version` 重复运行 `init_db.py` 不会清空已有任务；若检测到未知版本则会显式拒绝，防止误覆盖。
- **任务级主键隔离**：`documents.file_id`、`comparisons.comparison_id` 与 `risks.risk_id` 在库内以 `[task_id, 原始ID]` 的 JSON 数组文本作为主键，确保不同任务之间的短 ID（如 `f1`、`cmp_1`）互不冲突。
- **多商品关联完整性**：写入商品级字段时校验文件与原始行号归属，拒绝重复行号或跨行归属冲突；历史任务的商品与风险关联在服务启动时于同一事务内自动回填。

---

## 数据查询与回归测试

查看本地库中的任务与字段统计：

```sh
python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('SELECT task_id,status FROM tasks').fetchall()); print(c.execute('SELECT field_key,COUNT(*) FROM extracted_fields GROUP BY field_key').fetchall())"
```

运行数据层单元测试：

```sh
python -m unittest discover -s data -p "test_*.py" -v
```

---

## 结构化测试数据生成

```sh
python data/generator.py
```

默认在 `data/generated/` 下生成 16 组确定性结构化 JSON 测试集（固定 `--seed` 可完全复现），涵盖单品名一致、数量/金额/重量冲突、多品名乱序对齐、字段缺失等场景。

> **说明**：`data/generated/` 模拟的是抽取完成后的结构化单证输入与预期结果（`expected.comparisons` / `expected.risks`），用于验证数据库与比对规则逻辑；供完整上传链路测试的原始 PDF/PNG 样例位于 [`backend/samples/`](../backend/samples/)。
