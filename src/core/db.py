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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS platforms ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT NOT NULL, "
        "url TEXT NOT NULL, "
        "token TEXT NOT NULL, "
        "created_at TEXT DEFAULT (datetime('now')), "
        "updated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    conn.commit()
    return conn


def list_platforms() -> list[tuple[int, str, str, str]]:
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, name, url, token FROM platforms ORDER BY id DESC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def create_platform(name: str, url: str, token: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO platforms (name, url, token, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (name, url, token),
        )
        conn.commit()
    finally:
        conn.close()


def update_platform(platform_id: int, name: str, url: str, token: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE platforms SET name = ?, url = ?, token = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (name, url, token, platform_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_platform(platform_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM platforms WHERE id = ?", (platform_id,))
        conn.commit()
    finally:
        conn.close()


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
