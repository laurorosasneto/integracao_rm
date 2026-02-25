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
        "coligadas TEXT, "
        "created_at TEXT DEFAULT (datetime('now')), "
        "updated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    _ensure_column(conn, "platforms", "coligadas", "TEXT")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rm_config ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "host TEXT NOT NULL, "
        "database_name TEXT NOT NULL, "
        "username TEXT NOT NULL, "
        "password TEXT NOT NULL, "
        "updated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rm_queries ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "coligadas TEXT, "
        "periodos TEXT, "
        "cursos TEXT, "
        "turmas TEXT, "
        "salas TEXT, "
        "updated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    _ensure_column(conn, "rm_queries", "salas", "TEXT")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS routines ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "created_at TEXT NOT NULL, "
        "platform_id INTEGER NOT NULL, "
        "coligada TEXT, "
        "periodo TEXT, "
        "curso TEXT, "
        "turma TEXT, "
        "sala TEXT, "
        "professor TEXT, "
        "alunos TEXT, "
        "last_execution TEXT"
        ")"
    )
    _ensure_column(conn, "routines", "sala", "TEXT")

    # --- NOVO: Salas Modelo ---
    conn.execute(
        "CREATE TABLE IF NOT EXISTS salas_modelo ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "platform_id INTEGER NOT NULL, "
        "name TEXT NOT NULL, "
        "moodle_id TEXT NOT NULL, "
        "extra_filter TEXT, "
        "created_at TEXT DEFAULT (datetime('now')), "
        "updated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    _ensure_column(conn, "salas_modelo", "extra_filter", "TEXT")

    conn.commit()
    return conn


def list_platforms() -> list[tuple[int, str, str, str]]:
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, name, url, token, coligadas FROM platforms ORDER BY id DESC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def list_platforms_for_select() -> list[tuple[int, str]]:
    conn = get_connection()
    try:
        cur = conn.execute("SELECT id, name FROM platforms ORDER BY name ASC")
        return cur.fetchall()
    finally:
        conn.close()


def get_platform_coligadas(platform_id: int) -> str | None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT coligadas FROM platforms WHERE id = ?",
            (platform_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def create_platform(name: str, url: str, token: str, coligadas: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO platforms (name, url, token, coligadas, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (name, url, token, coligadas),
        )
        conn.commit()
    finally:
        conn.close()


def update_platform(platform_id: int, name: str, url: str, token: str, coligadas: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE platforms SET name = ?, url = ?, token = ?, coligadas = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (name, url, token, coligadas, platform_id),
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def delete_platform(platform_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM platforms WHERE id = ?", (platform_id,))
        conn.commit()
    finally:
        conn.close()


def list_routines() -> list[tuple]:
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT r.id, r.created_at, p.name, r.coligada, "
            "r.periodo, r.curso, r.turma, r.sala, "
            "r.professor, r.alunos, r.last_execution "
            "FROM routines r "
            "LEFT JOIN platforms p ON p.id = r.platform_id "
            "ORDER BY r.id DESC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def create_routine(data: dict) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO routines ("
            "created_at, platform_id, coligada, periodo, "
            "curso, turma, sala, professor, alunos, last_execution"
            ") VALUES ("
            "datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?"
            ")",
            (
                data["platform_id"],
                data.get("coligada", ""),
                data.get("periodo", ""),
                data.get("curso", ""),
                data.get("turma", ""),
                data.get("sala", ""),
                data.get("professor", ""),
                data.get("alunos", ""),
                data.get("last_execution", ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_routine(routine_id: int, data: dict) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE routines SET "
            "created_at = datetime('now'), "
            "platform_id = ?, coligada = ?, "
            "periodo = ?, curso = ?, turma = ?, sala = ?, professor = ?, "
            "alunos = ?, last_execution = ? "
            "WHERE id = ?",
            (
                data["platform_id"],
                data.get("coligada", ""),
                data.get("periodo", ""),
                data.get("curso", ""),
                data.get("turma", ""),
                data.get("sala", ""),
                data.get("professor", ""),
                data.get("alunos", ""),
                data.get("last_execution", ""),
                routine_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_routine(routine_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        conn.commit()
    finally:
        conn.close()


def get_rm_config() -> tuple[str, str, str, str] | None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT host, database_name, username, password FROM rm_config WHERE id = 1"
        )
        row = cur.fetchone()
        return (row[0], row[1], row[2], row[3]) if row else None
    finally:
        conn.close()


def set_rm_config(host: str, database_name: str, username: str, password: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO rm_config (id, host, database_name, username, password, updated_at) "
            "VALUES (1, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET "
            "host=excluded.host, database_name=excluded.database_name, "
            "username=excluded.username, password=excluded.password, "
            "updated_at=datetime('now')",
            (host, database_name, username, password),
        )
        conn.commit()
    finally:
        conn.close()


def get_rm_queries() -> dict[str, str] | None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT coligadas, periodos, cursos, turmas, salas FROM rm_queries WHERE id = 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        keys = [
            "coligadas",
            "periodos",
            "cursos",
            "turmas",
            "salas",
        ]
        return dict(zip(keys, row))
    finally:
        conn.close()


def set_rm_queries(values: dict[str, str]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO rm_queries ("
            "id, coligadas, periodos, cursos, turmas, salas, updated_at"
            ") VALUES ("
            "1, ?, ?, ?, ?, ?, datetime('now')"
            ") ON CONFLICT(id) DO UPDATE SET "
            "coligadas=excluded.coligadas, "
            "periodos=excluded.periodos, "
            "cursos=excluded.cursos, "
            "turmas=excluded.turmas, "
            "salas=excluded.salas, "
            "updated_at=datetime('now')",
            (
                values.get("coligadas", ""),
                values.get("periodos", ""),
                values.get("cursos", ""),
                values.get("turmas", ""),
                values.get("salas", ""),
            ),
        )
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


# -------------------------
# Salas Modelo (CRUD)
# -------------------------

def list_salas_modelo() -> list[tuple]:
    """Lista registros de Salas Modelo com JOIN da plataforma."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT s.id, s.created_at, s.platform_id, p.name, s.name, s.moodle_id, s.extra_filter, s.updated_at "
            "FROM salas_modelo s "
            "LEFT JOIN platforms p ON p.id = s.platform_id "
            "ORDER BY s.id DESC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def create_sala_modelo(platform_id: int, name: str, moodle_id: str, extra_filter: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO salas_modelo (platform_id, name, moodle_id, extra_filter, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (platform_id, name, moodle_id, extra_filter),
        )
        conn.commit()
    finally:
        conn.close()


def update_sala_modelo(sala_modelo_id: int, platform_id: int, name: str, moodle_id: str, extra_filter: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE salas_modelo SET platform_id = ?, name = ?, moodle_id = ?, extra_filter = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (platform_id, name, moodle_id, extra_filter, sala_modelo_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_sala_modelo(sala_modelo_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM salas_modelo WHERE id = ?", (sala_modelo_id,))
        conn.commit()
    finally:
        conn.close()