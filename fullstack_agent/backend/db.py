import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "agent_history.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_message TEXT NOT NULL,
                assistant_reply TEXT NOT NULL,
                intent TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item TEXT NOT NULL,
                amount REAL NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                raw_query TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocked_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item TEXT NOT NULL,
                reason TEXT NOT NULL,
                raw_query TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO profile_state (key, value)
            VALUES ('current_surplus', '10000.0')
            """
        )
        conn.commit()


def insert_chat(user_message, assistant_reply, intent, latency_ms):
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO chat_history (user_message, assistant_reply, intent, latency_ms)
            VALUES (?, ?, ?, ?)
            """,
            (user_message, assistant_reply, intent, latency_ms),
        )
        conn.commit()
        return cur.lastrowid


def list_history(limit=50):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, user_message, assistant_reply, intent, latency_ms, created_at
            FROM chat_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def clear_history():
    with get_connection() as conn:
        conn.execute("DELETE FROM chat_history")
        conn.commit()


def get_current_surplus():
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM profile_state WHERE key = 'current_surplus'"
        ).fetchone()
        return round(float(row["value"]), 2) if row else 10000.0


def set_current_surplus(value):
    value = round(float(value), 2)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO profile_state (key, value)
            VALUES ('current_surplus', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(value),),
        )
        conn.commit()
    return value


def adjust_surplus(delta):
    current = get_current_surplus()
    return set_current_surplus(current + float(delta))


def insert_ledger_entry(item, amount, source, raw_query, status="active"):
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO ledger_entries (item, amount, source, status, raw_query)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item, amount, source, status, raw_query),
        )
        conn.commit()
        return cur.lastrowid


def undo_last_ledger_entry():
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, item, amount, source, status, raw_query, created_at
            FROM ledger_entries
            WHERE status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE ledger_entries SET status = 'cancelled' WHERE id = ?", (row["id"],))
        conn.commit()
        return dict(row)


def list_ledger(limit=50):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, item, amount, source, status, raw_query, created_at
            FROM ledger_entries
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def insert_blocked_item(item, reason, raw_query):
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO blocked_items (item, reason, raw_query)
            VALUES (?, ?, ?)
            """,
            (item, reason, raw_query),
        )
        conn.commit()
        return cur.lastrowid


def list_blocked_items(limit=50):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, item, reason, raw_query, created_at
            FROM blocked_items
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def find_memory_context(query, limit=5):
    chars = {c for c in query if c.strip()}
    candidates = []
    with get_connection() as conn:
        chat_rows = conn.execute(
            """
            SELECT user_message AS text, assistant_reply AS extra, created_at
            FROM chat_history
            ORDER BY id DESC
            LIMIT 80
            """
        ).fetchall()
        ledger_rows = conn.execute(
            """
            SELECT raw_query AS text, item || ' ' || amount || '元 ' || status AS extra, created_at
            FROM ledger_entries
            ORDER BY id DESC
            LIMIT 80
            """
        ).fetchall()

    for row in list(chat_rows) + list(ledger_rows):
        text = row["text"] or ""
        union = chars | {c for c in text if c.strip()}
        score = len(chars & {c for c in text if c.strip()}) / len(union) if union else 0.0
        if score > 0:
            candidates.append({
                "text": text,
                "extra": row["extra"] or "",
                "created_at": row["created_at"],
                "score": round(score, 4),
            })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:limit]
