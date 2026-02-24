from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parents[2] / "db" / "app.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_config ("
        "key TEXT PRIMARY KEY, "
        "value TEXT, "
        "updated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS connections ("
        "name TEXT PRIMARY KEY, "
        "type TEXT NOT NULL, "
        "host TEXT, "
        "port INTEGER, "
        "database TEXT, "
        "username TEXT, "
        "password TEXT, "
        "options_json TEXT, "
        "updated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    conn.commit()
    return conn


def get_config(key: str) -> Optional[str]:
    conn = get_connection()
    try:
        cur = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def set_config(key: str, value: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()
