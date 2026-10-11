# SQLite 数据层（第一版）

当前数据层按 `items[]` 结构组织，单品名是其中只有一个元素的特例。`schema.sql` 定义表结构，`init_db.py` 创建数据库，`seed_data.py` 将任务样例导入 SQLite。

## 运行

```powershell
python data/init_db.py
python data/seed_data.py
```

生成的 `data/app.db` 是本地运行文件，不提交到 Git。表结构和导入脚本才需要提交。

## 查看数据

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('SELECT task_id,status FROM tasks').fetchall()); print(c.execute(\"SELECT field_key,COUNT(*) FROM extracted_fields GROUP BY field_key\").fetchall())"
```

`normalized_value_json` 和 `bbox_json` 是 JSON 文本，读取后用 Python `json.loads()` 还原。

## 生成测试数据

```powershell
python data/generator.py
```

默认在 `data/generated/` 生成 16 组确定性 JSON 样例。每组包含商品目录、模拟的多份单证字段，以及 `expected.comparisons` 和 `expected.risks`，用于测试数据库、模型和比对规则。使用同一个 `--seed` 会得到相同结果。

`data/generated/` 是结构化的合成测试输入；它模拟 OCR/抽取完成后的统一 JSON，不是 PaddleOCR 的原始图片或 PDF。原始 OCR 测试素材放在本地的 `data/paddleocr_test/`，默认被 `.gitignore` 排除，避免把与跨境物流场景无关或许可不明确的文件提交到仓库。
