# SQLite 持久化架构与数据迁移说明

后端任务创建、逐文件进度更新、终态比对结果与人工修正审计均通过 SQLite 进行事务性持久化，读取接口直接从数据库查询。底层关系表结构复用 [`data/schema.sql`](data/schema.sql)（结构版本 `user_version = 1`）。

---

## 存储架构

1. **数据库位置**：
   - 默认运行库路径为 `backend/.data/tasks.sqlite3`（可通过环境变量 `TASK_DB_PATH` 指定绝对路径）。
   - 在生产部署中，`release/backend/.data` 软链接至跨版本共享的 `~/app/shared/data`，版本发布与回退不会丢失任务数据。
2. **双层存储模型**：
   - **规范化关系表**：写入 `tasks`、`items`、`documents`、`extracted_fields`、`comparisons`、`risks` 等表，支撑结构化查询与关联校验。
   - **完整载荷快照（`api_task_payloads`）**：在同一事务内保存完整任务快照（含商品行组成员、对齐状态、OCR 原始证据及修正审计链），确保对外 CheckTask 与 ReportContent 契约无损还原。
3. **JSON 兼容导出**：
   - 任务到达终态后，仍原子导出一份 `tsk_*.json` 快照，以便在极端情况下回退至早期版本时仍可读取结果。

---

## 历史数据自动迁入与中断恢复

- **启动自动迁移**：服务启动时自动扫描 `backend/.data/tasks/tsk_*.json`，将尚未入库的历史 JSON 任务逐条原子导入 SQLite；已存在的 `task_id` 自动跳过，原始 JSON 文件保留不变。
- **手动批量迁移**：
  ```sh
  python backend/tools/migrate_tasks.py --db /path/to/tasks.sqlite3 --legacy-dir /path/to/tasks
  ```
- **重启中断收尾**：服务启动时若发现处于 `PENDING` 或 `PROCESSING` 状态的未完成任务，会将其统一标记为 `FAILED`（附 `TASK_INTERRUPTED` 错误码），已持久化的原件文件保留可供下载；系统不做后台静默重跑，需由用户重新发起检查。

---

## 验证命令

```sh
python backend/tools/test_sqlite_store.py
python -m unittest discover -s data -p "test_*.py" -v
```
