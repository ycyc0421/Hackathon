"""Create the local SQLite database from schema.sql."""
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "app.db"


def main() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    print(f"数据库已初始化：{DB_PATH}")


if __name__ == "__main__":
    main()
