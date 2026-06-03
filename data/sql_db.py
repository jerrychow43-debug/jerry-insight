# Jerry-Insight-Pro/data/sql_db.py
import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional


DB_PATH = "./data/jerry_pro.db"


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_runtime_tables():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS history (item TEXT, dec TEXT)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            intent TEXT,
            item_name TEXT,
            amount REAL,
            assistant_reply TEXT,
            audit_data TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            title TEXT,
            content TEXT,
            status TEXT,
            response TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def save_audit_log(item, decision):
    init_runtime_tables()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO history VALUES (?, ?)", (item, decision))
    conn.commit()
    conn.close()


def save_chat_history(
    query: str,
    intent: str,
    assistant_reply: str = "",
    item_name: Optional[str] = None,
    amount: Optional[float] = None,
    audit_data: Optional[Dict[str, Any]] = None,
):
    init_runtime_tables()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO chat_history
            (query, intent, item_name, amount, assistant_reply, audit_data, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            query,
            intent,
            item_name,
            amount,
            assistant_reply,
            json.dumps(audit_data or {}, ensure_ascii=False),
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        ),
    )
    conn.commit()
    conn.close()


def load_recent_chat_history(limit: Optional[int] = 100) -> List[Dict[str, Any]]:
    init_runtime_tables()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    sql = """
        SELECT query, intent, item_name, amount, assistant_reply, audit_data, created_at
        FROM chat_history
        ORDER BY id DESC
    """
    if limit is None:
        cursor.execute(sql)
    else:
        cursor.execute(f"{sql} LIMIT ?", (limit,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    for row in rows:
        try:
            row["audit_data"] = json.loads(row.get("audit_data") or "{}")
        except Exception:
            row["audit_data"] = {}
    return rows


def save_notification_log(channel: str, title: str, content: str, status: str, response: str):
    init_runtime_tables()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO notification_logs
            (channel, title, content, status, response, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            channel,
            title,
            content,
            status,
            response,
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        ),
    )
    conn.commit()
    conn.close()
