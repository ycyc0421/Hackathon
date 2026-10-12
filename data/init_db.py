"""Create the local SQLite database from schema.sql."""
from contextlib import closing
from pathlib import Path
import sqlite3
from seed_data import backfill_task_relations

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "app.db"
SCHEMA_VERSION = 1


def main() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        has_tables = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
        ).fetchone() is not None
        if version != SCHEMA_VERSION and (version != 0 or has_tables):
            raise SystemExit(
                f"数据库结构版本不兼容：{version}（当前支持 {SCHEMA_VERSION}）。"
                f"请先备份并移走 {DB_PATH}，再重新初始化；原数据库保持不变。"
            )
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
        backfill_task_relations(conn)
    print(f"数据库已初始化：{DB_PATH}")


if __name__ == "__main__":
    main()
