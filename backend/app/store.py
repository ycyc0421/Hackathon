"""Task storage facade; writes are durable in SQLite."""
from .sqlite_store import TaskStore

store = TaskStore()
