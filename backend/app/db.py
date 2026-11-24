"""SQLite storage (stdlib sqlite3). Schema is created on startup."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  system_prompt TEXT
);
"""


def _path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    return url.replace("sqlite:///", "", 1)


@contextmanager
def connect():
    conn = sqlite3.connect(_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # commit on success, rollback on error
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    folder = os.path.dirname(_path())
    if folder:
        os.makedirs(folder, exist_ok=True)
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)


def ping() -> bool:
    try:
        with connect() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_history(session_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [
        {"role": r["role"], "content": r["content"],
         "metadata": json.loads(r["metadata"]) if r["metadata"] else None}
        for r in rows
    ]


def get_system_prompt(session_id: str) -> str | None:
    with connect() as c:
        row = c.execute("SELECT system_prompt FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    return row["system_prompt"] if row else None


def save_turn(session_id: str, user_msg: str, reply: str, metadata: dict,
              system_prompt: str | None) -> None:
    """Persist a successful exchange atomically (failed requests never reach this)."""
    with connect() as c:
        if system_prompt:
            c.execute(
                "INSERT INTO sessions(session_id, system_prompt) VALUES(?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET system_prompt=excluded.system_prompt",
                (session_id, system_prompt),
            )
        c.execute("INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
                  (session_id, "user", user_msg, None, _now()))
        c.execute("INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
                  (session_id, "assistant", reply, json.dumps(metadata), _now()))
