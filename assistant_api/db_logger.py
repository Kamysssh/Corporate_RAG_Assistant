"""
Логирование взаимодействий с корпоративным RAG-ассистентом в SQLite.

Записывает вопрос, ответ, роль ассистента, источник (консоль / Telegram),
признак попадания в кеш и время ответа — для аналитики и портфолио.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


class DatabaseLogger:
    """
    Запись диалогов в SQLite (отдельно от семантического кеша ответов).

    Поле role связывает запись с одной из трёх ролей: hr, post_sales, sales.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parent / "logs.db"
        self.db_path = Path(db_path)
        self._init_database()

    def _init_database(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id TEXT,
                username TEXT,
                source TEXT NOT NULL,
                role TEXT,
                query TEXT NOT NULL,
                response TEXT NOT NULL,
                from_cache INTEGER DEFAULT 0,
                response_time_ms INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON logs(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source ON logs(source)")
        cursor.execute("PRAGMA table_info(logs)")
        col_names = {row[1] for row in cursor.fetchall()}
        if "role" not in col_names:
            cursor.execute("ALTER TABLE logs ADD COLUMN role TEXT")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_role ON logs(role)")
        conn.commit()
        conn.close()

    def log_interaction(
        self,
        query: str,
        response: str,
        source: str = "console",
        role: Optional[str] = None,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        from_cache: bool = False,
        response_time_ms: Optional[int] = None,
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO logs (
                timestamp, user_id, username, source, role, query, response,
                from_cache, response_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                user_id,
                username,
                source,
                role,
                query,
                response,
                1 if from_cache else 0,
                response_time_ms,
            ),
        )
        conn.commit()
        conn.close()

    def get_logs(
        self,
        limit: Optional[int] = None,
        user_id: Optional[str] = None,
        source: Optional[str] = None,
        role: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        q = "SELECT * FROM logs WHERE 1=1"
        params: list = []
        if user_id:
            q += " AND user_id = ?"
            params.append(user_id)
        if source:
            q += " AND source = ?"
            params.append(source)
        if role:
            q += " AND role = ?"
            params.append(role)
        if start_date:
            q += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            q += " AND timestamp <= ?"
            params.append(end_date)
        q += " ORDER BY timestamp DESC"
        if limit:
            q += " LIMIT ?"
            params.append(limit)
        cursor.execute(q, params)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def export_to_csv(
        self,
        output_path: Optional[str] = None,
        user_id: Optional[str] = None,
        source: Optional[str] = None,
        role: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """Экспорт в CSV. Для записи в файл используется UTF-8 с BOM (utf-8-sig), чтобы Excel в Windows
        корректно показывал русский текст. Пустая строка, если записей нет.
        """
        logs = self.get_logs(
            user_id=user_id,
            source=source,
            role=role,
            start_date=start_date,
            end_date=end_date,
        )
        if not logs:
            return ""
        fieldnames = [
            "id",
            "timestamp",
            "user_id",
            "username",
            "source",
            "role",
            "query",
            "response",
            "from_cache",
            "response_time_ms",
            "created_at",
        ]
        if output_path:
            # utf-8-sig: BOM в начале файла — Excel в Windows открывает как UTF-8, а не «кракозябры»
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(logs)
            return output_path
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(logs)
        return buf.getvalue()

    def get_stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM logs")
        total_requests = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM logs WHERE from_cache = 1")
        cached_requests = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(DISTINCT user_id) FROM logs WHERE user_id IS NOT NULL"
        )
        unique_users = cursor.fetchone()[0]
        cursor.execute("SELECT source, COUNT(*) FROM logs GROUP BY source")
        by_source = dict(cursor.fetchall())
        cursor.execute(
            "SELECT role, COUNT(*) FROM logs WHERE role IS NOT NULL GROUP BY role"
        )
        by_role = dict(cursor.fetchall())
        cursor.execute(
            "SELECT AVG(response_time_ms) FROM logs WHERE response_time_ms IS NOT NULL"
        )
        row = cursor.fetchone()
        avg_response_time = row[0] if row else None
        conn.close()
        return {
            "total_requests": total_requests,
            "cached_requests": cached_requests,
            "unique_users": unique_users,
            "by_source": by_source,
            "by_role": by_role,
            "avg_response_time_ms": avg_response_time if avg_response_time else 0.0,
        }
