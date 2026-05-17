"""统一数据库 — 复用现有 investment.db"""
import sqlite3
from contextlib import contextmanager
from .config import config

class Database:
    def __init__(self): self.db_path = config.db_path
    @contextmanager
    def connect(self, rf=False):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA busy_timeout=5000")
            if rf: conn.row_factory = sqlite3.Row
            yield conn
        finally: conn.close()
    def query(self, sql, p=()):
        with self.connect(rf=True) as c: return [dict(r) for r in c.execute(sql, p).fetchall()]
    def query_one(self, sql, p=()):
        rows = self.query(sql, p); return rows[0] if rows else None
    def execute(self, sql, p=()):
        with self.connect() as c: c.execute(sql, p); c.commit()

db = Database()
