# 后端 SQLite 接入

任务创建和状态更新立即提交到 SQLite，读接口直接读取数据库。复用 C 的版本 1 表结构与 `data/seed_data.py`，任务内文件/比对/风险 ID 保持原值，对应数据库 ID 继续按任务隔离。

运行库默认位于 `backend/.data/tasks.sqlite3`，在既有部署下随共享 `.data` 保留。可用 `TASK_DB_PATH` 指定绝对路径。正式运行库与 `data/app.db` 合成样例库分别使用；不要把生成样例库设为运行库。未知数据库版本明确拒绝，不自动删除或重建。

运行库额外创建 `api_task_payloads` 表保存完整任务 JSON，与关系表同一事务提交。这样保留 C 的关系表未覆盖的摘要、商品行组成员、对齐状态、比对 scope、OCR 原始证据及可选字段；API 契约不变。

启动时导入旧 `backend/.data/tasks/tsk_*.json`；已存在 ID 跳过，原文件保留。坏 JSON 或文件名/任务 ID 不一致会明确报错，应先修复或单独备份问题文件。逐任务原子导入，可重复执行。手动迁移：

```sh
python backend/tools/migrate_tasks.py --db /path/tasks.sqlite3 --legacy-dir /path/tasks
```

完成结果仍原子导出为旧格式 JSON，以便部署回退到旧版本时查回结果。SQLite 是主存储，JSON 是兼容导出。服务启动会将之前 PENDING/PROCESSING 的任务标记为 FAILED，附 `TASK_INTERRUPTED`；上传文件不能自动重跑，需重新上传。部署继续使用单 worker；迁移与重启时不要并行启动另一服务处理相同数据库。

验证：`python backend/tools/test_sqlite_store.py`，以及 C 的数据层回归、接口自检、文本 PDF 挑战集。此改动不实现评测，也不启用 OCR，不修改线上数据库或配置。
