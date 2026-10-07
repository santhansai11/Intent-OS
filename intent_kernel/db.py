"""SQLite persistence for intents (storage/intents.db)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .paths import db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS intents (
    id            TEXT PRIMARY KEY,
    goal          TEXT NOT NULL,
    text          TEXT,
    intent_type   TEXT,
    priority      TEXT,
    deadline      TEXT,
    state         TEXT,
    created_at    REAL,
    started_at    REAL,
    completed_at  REAL,
    payload       TEXT
);
"""


class IntentDatabase:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------
    def upsert(self, intent) -> None:
        payload = json.dumps(intent.to_dict(include_log=True), default=str)
        self.conn.execute(
            """
            INSERT INTO intents (id, goal, text, intent_type, priority, deadline,
                                 state, created_at, started_at, completed_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state=excluded.state, started_at=excluded.started_at,
                completed_at=excluded.completed_at, payload=excluded.payload
            """,
            (
                intent.id,
                intent.goal,
                intent.text,
                intent.intent_type,
                intent.priority,
                intent.deadline.isoformat() if intent.deadline else None,
                intent.state,
                intent.created_at,
                intent.started_at,
                intent.completed_at,
                payload,
            ),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    def get(self, intent_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT payload FROM intents WHERE id = ?", (intent_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        if state:
            rows = self.conn.execute(
                "SELECT payload FROM intents WHERE state = ? ORDER BY created_at", (state,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT payload FROM intents ORDER BY created_at"
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
