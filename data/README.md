# SQLite 数据工具

当前目录提供独立 SQLite 初始化、样例导入和回归工具；main 后端仍使用 JSON 任务存储，数据库接入尚待合并。数据层按 `items[]` 组织，公开 API 的单品名票也可能使用空目录和票级字段。`schema.sql` 定义表结构，`init_db.py` 创建数据库，`seed_data.py` 将任务样例导入 SQLite。

## 运行

```powershell
python data/init_db.py
python data/seed_data.py
# 导入某一组生成样例
python data/seed_data.py --input data/generated/normal_multi.json
```

生成的 `data/app.db` 是本地运行文件，不提交到 Git。表结构和导入脚本才需要提交。

当前数据库结构版本为 1，以 SQLite 的 `user_version` 标记。同版本可重复初始化，已有记录会保留。旧开发库或其他版本会被明确拒绝；请先停止使用旧库，将其备份并移出 `data/app.db`，再执行以上命令重建并重新导入原始 JSON。初始化脚本不会删除或自动迁移旧数据。

导入器对同一 task_id 先删除旧任务再事务性重建，重复导入会替换该任务，不是跳过已有记录。生产备份与迁移必须单独审查，不要把初始化/种子命令当作线上升级流程。可用 `--db <本地数据库路径>` 隔离实验数据。

## 查看数据

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('SELECT task_id,status FROM tasks').fetchall()); print(c.execute(\"SELECT field_key,COUNT(*) FROM extracted_fields GROUP BY field_key\").fetchall())"
```

运行数据层回归测试：

```powershell
python -m unittest discover -s data -p "test_*.py" -v
```

`normalized_value_json` 和 `bbox_json` 是 JSON 文本，读取后用 Python `json.loads()` 还原。

任务错误和告警完整保存到 `tasks.errors_json`，用 `json.loads()` 还原后保留原有顺序、错误码、消息、级别和任务内 `file_ids`。没有错误时保存 `[]`。文件抽取方式保存在 `documents.parse_method`，比对和风险的处理建议分别保存在对应表的 `suggested_action`；未提供的可选值为 SQL `NULL`。

`documents.file_id`、`comparisons.comparison_id`、`risks.risk_id` 在库中使用 `[task_id, 原始ID]` 的 JSON 文本隔离任务，读取时可用 `json.loads()` 取得原始 ID。`items.item_id` 和 `errors_json` 内的文件 ID 保持任务内原值。

## 生成测试数据

```powershell
python data/generator.py
```

默认在 `data/generated/` 生成 16 组确定性 JSON 样例。每组包含商品目录、模拟的多份单证字段，以及 `expected.comparisons` 和 `expected.risks`，用于测试数据库、模型和比对规则。使用同一个 `--seed` 会得到相同结果。

`data/generated/` 是结构化的合成测试输入；它模拟 OCR/抽取完成后的统一 JSON，不是 PaddleOCR 的原始图片或 PDF。仓库内可复现的原始 PDF/PNG 在 [backend/samples](../backend/samples/)，运行方法见[后端说明](../backend/README.md)。这些结构化输入不是 CheckTask API 响应，不能直接交给前端或公开 Schema 校验。
