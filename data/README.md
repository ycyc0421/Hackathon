# SQLite 数据工具

当前目录提供独立 SQLite 初始化、样例导入和回归工具；后端任务存储已复用此处的表结构与导入器，运行库和样例库分离，见 [SQLite 接入说明](../SQLITE_INTEGRATION.md)。数据层按 `items[]` 组织，公开 API 的单品名票也可能使用空目录和票级字段。`schema.sql` 定义表结构，`init_db.py` 创建数据库，`seed_data.py` 将任务样例导入 SQLite。

## 运行

```powershell
python data/init_db.py
python data/seed_data.py
# 导入某一组生成样例
python data/seed_data.py --input data/generated/normal_multi.json
```

生成的 `data/app.db` 是本地运行文件，不提交到 Git。表结构和导入脚本才需要提交。

当前数据库结构版本为 1，以 SQLite 的 `user_version` 标记。同版本可重复初始化，已有记录会保留。旧开发库或其他版本会被明确拒绝；请先停止使用旧库，将其备份并移出 `data/app.db`，再执行以上命令重建并重新导入原始 JSON。初始化脚本不删除已有任务；同版本新增的商品字段和风险关系会按下述方式回填，未知结构版本仍明确拒绝。

导入器对同一 task_id 先删除旧任务再事务性重建，重复导入会替换该任务，不是跳过已有记录。生产备份与迁移必须单独审查，不要把初始化/种子命令当作线上升级流程。可用 `--db <本地数据库路径>` 隔离实验数据。

## 多商品关系与旧任务回填

商品行字段按文件编号与文件内行号关联到商品；重复行号、同一行重复归属、引用不存在的行及字段归属冲突会在写入前拒绝。尚未提供商品组的行保留未分组证据，不猜测归属；公开契约的平铺字段仍按原方式导入。风险关联的商品编号按首次出现顺序去重，原始任务快照不变。

后端启动和本地初始化时，会为尚未记录回填状态的任务补齐关系。存在完整任务快照时，仅重建该任务的抽取字段与风险商品关联，不删除任务、不修改快照或人工修正审计；没有快照时只保留并补齐已知的旧单商品风险关系，不猜测缺失的商品行。

整个回填批次在同一事务中提交，失败时关系与标记一起回滚。task_relation_state 记录逐任务状态，重复启动不重复写入；旧版本重写任务时标记随任务删除，再次升级可重新补齐。数据库结构版本保持为 1，这些新增表不阻止旧版本读取；本次不改变公开 API Schema。

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
